"""Small pieces that need no running agent."""
import contextlib
import io
import os
import tempfile
import unittest

from harness import ia, jpeg, mp4, png


class TextTests(unittest.TestCase):
    def test_parse_ts_understands_graph_formats(self):
        self.assertEqual(ia.parse_ts("2026-11-11T10:20:30+0000"), 1794392430.0)
        self.assertEqual(ia.parse_ts("2026-11-11T10:20:30Z"), 1794392430.0)
        self.assertEqual(ia.parse_ts("2026-11-11T13:50:30+03:30"), 1794392430.0)
        self.assertEqual(ia.parse_ts("2026-11-11T10:20:30.123+0000"), 1794392430.0)
        self.assertEqual(ia.parse_ts(1794392430), 1794392430.0)
        self.assertEqual(ia.parse_ts("1794392430000"), 1794392430.0)
        self.assertEqual(ia.parse_ts(""), 0.0)
        self.assertEqual(ia.parse_ts("nonsense"), 0.0)
        self.assertEqual(ia.parse_ts(ia.iso(1794392430)), 1794392430.0)

    def test_norm_unifies_persian_and_arabic_spelling(self):
        self.assertEqual(ia.norm("قيمت"), ia.norm("قیمت"))                # Arabic ي
        self.assertEqual(ia.norm("كتاب"), ia.norm("کتاب"))                # Arabic ك
        self.assertEqual(ia.norm("می‌خوام"), ia.norm("میخوام"))            # half-space
        self.assertEqual(ia.norm("PRICE?!  "), "price")
        self.assertEqual(ia.norm("۱۲۳"), "123")
        self.assertEqual(ia.norm("آدرس"), ia.norm("ادرس"))

    def test_rule_matching_modes(self):
        rule = {"mode": "any", "keywords": ["قیمت", "چنده"]}
        self.assertTrue(ia.rule_matches(rule, "سلام قيمت این چنده؟"))
        self.assertTrue(ia.rule_matches(rule, "قیمت‌ها رو می‌گید؟"))
        self.assertFalse(ia.rule_matches(rule, "چه قشنگ"))
        self.assertFalse(ia.rule_matches(rule, ""))
        both = {"mode": "all", "keywords": ["ارسال", "تهران"]}
        self.assertTrue(ia.rule_matches(both, "ارسال به تهران دارید؟"))
        self.assertFalse(ia.rule_matches(both, "ارسال دارید؟"))
        exact = {"mode": "exact", "keywords": ["سلام"]}
        self.assertTrue(ia.rule_matches(exact, " سلام! "))
        self.assertFalse(ia.rule_matches(exact, "سلام خوبی"))
        self.assertTrue(ia.rule_matches({"mode": "every", "keywords": []}, "هر چیزی"))
        short = {"mode": "any", "keywords": ["hi"]}                        # short words must be whole words
        self.assertTrue(ia.rule_matches(short, "Hi there"))
        self.assertFalse(ia.rule_matches(short, "this is nice"))

    def test_spam_detection(self):
        for text in ("فالوور ارزان و واقعی فقط با ما", "check my bio 😍", "www.win-money.xyz", "t.me/somechannel",
                     "خرید فالوور با تخفیف", "visit cheap-shop.com now"):
            self.assertTrue(ia.looks_spam(text), text)
        for text in ("قیمت لاته چنده؟", "چه قشنگ شده 😍", "ساعت ۲۳.۳۰ بازید؟", "سلام. خوبید؟ ممنون"):
            self.assertFalse(ia.looks_spam(text), text)

    def test_tokens_are_redacted_everywhere(self):
        token = "IGAAabcdefghijklmnopqrstuvwxyz0123456789"
        self.assertNotIn(token, ia.redact("GET /me?access_token=%s&x=1" % token))
        self.assertNotIn(token, ia.redact("bad token %s here" % token))
        self.assertNotIn("123456:ABCdef_ghiJKL", ia.redact("https://api.telegram.org/bot123456:ABCdef_ghiJKL/sendMessage"))
        err = ia.GraphError("Invalid token access_token=%s" % token, 190)
        self.assertNotIn(token, str(err) + err.fa + err.message)

    def test_caption_counters(self):
        self.assertEqual(ia.count_tags("سلام #یک #دو@x و @page.name"), (2, 1))
        self.assertEqual(ia.count_tags("a@b.com نیست منشن"), (0, 0))

    def test_persian_numbers(self):
        self.assertEqual(ia.fa(1840), "۱٬۸۴۰")
        self.assertEqual(ia.fa(7), "۷")

    def test_rule_render(self):
        self.assertEqual(ia.Rules.render("سلام {username} 🌹", "sara"), "سلام @sara 🌹")
        self.assertEqual(ia.Rules.render("سلام {username} 🌹", ""), "سلام 🌹")


class ErrorTests(unittest.TestCase):
    def test_instagram_errors_are_classified(self):
        table = [((190, 463), "auth"), ((10, 0), "permission"), ((200, 0), "permission"), ((4, 0), "throttle"),
                 ((613, 0), "throttle"), ((80002, 0), "throttle"), ((100, 0), "param"), ((2, 0), "transient"),
                 ((9007, 2207027), "not_ready"), ((24, 2207008), "expired"), ((9, 2207042), "quota"),
                 ((4, 2207051), "blocked"), ((25, 2207050), "blocked"), ((368, 0), "blocked"), ((9004, 2207052), "fetch"),
                 ((36001, 2207005), "media"), ((36003, 2207009), "media"), ((10, 2534022), "window"), ((2500, 0), "other")]
        for (code, sub), kind in table:
            self.assertEqual(ia.GraphError("x", code, sub, 400).kind, kind, (code, sub))
        self.assertEqual(ia.GraphError("x", status=503).kind, "transient")
        self.assertEqual(ia.GraphError("x", status=429).kind, "throttle")
        self.assertTrue(ia.GraphError("x", kind="network").transient)
        self.assertFalse(ia.GraphError("x", 36001, 2207005).transient)
        for e in (ia.GraphError("x", 190, 460), ia.GraphError("x", 36003, 2207009), ia.GraphError("x", kind="network")):
            self.assertTrue(any("\u0600" <= ch <= "\u06ff" for ch in e.fa))   # always explained in Persian


class FileTests(unittest.TestCase):
    def test_sniff_knows_what_instagram_accepts(self):
        self.assertEqual(ia.sniff(jpeg()[:64]), ("image", "jpg", "image/jpeg"))
        self.assertEqual(ia.sniff(png()[:64])[1], "png")
        self.assertEqual(ia.sniff(mp4()[:64]), ("video", "mp4", "video/mp4"))
        self.assertEqual(ia.sniff(b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00")[1], "mov")
        self.assertEqual(ia.sniff(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00")[1], "heic")
        self.assertIsNone(ia.sniff(b"<html><script>alert(1)</script>"))
        self.assertIsNone(ia.sniff(b""))

    def test_image_size(self):
        with tempfile.TemporaryDirectory() as d:
            for name, data, want in (("a.jpg", jpeg(1080, 1350), (1080, 1350)), ("b.jpg", jpeg(640, 480, pad=40), (640, 480)),
                                     ("c.png", png(), (10, 10)), ("d.bin", b"junk", (0, 0)), ("e.jpg", b"\xff\xd8\xff", (0, 0))):
                path = os.path.join(d, name)
                with open(path, "wb") as fh:
                    fh.write(data)
                self.assertEqual(ia.image_size(path), want, name)


class ConfigTests(unittest.TestCase):
    def test_port_zero_and_defaults(self):
        cfg = ia.Config(["--port", "0"], {"HOME": "/tmp/x"})
        self.assertEqual(cfg.port, 0)
        self.assertEqual(ia.Config([], {"HOME": "/tmp/x"}).port, ia.DEFAULT_PORT)
        self.assertEqual(ia.Config([], {"HOME": "/tmp/x", "PORT": "9001"}).port, 9001)
        self.assertEqual(ia.Config(["--port", "7000"], {"HOME": "/tmp/x", "PORT": "9001"}).port, 7000)

    def test_demo_uses_its_own_folder(self):
        live = ia.Config([], {"HOME": "/tmp/x"})
        demo = ia.Config(["--demo"], {"HOME": "/tmp/x"})
        self.assertNotEqual(live.data_dir, demo.data_dir)
        self.assertTrue(demo.sim and demo.embed_ok and not live.sim and not live.embed_ok)

    def test_no_auth_is_refused_on_a_public_address(self):
        said = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(said):
            ia.Config(["--host", "0.0.0.0", "--no-auth"], {"HOME": "/tmp/x", "AGENT_QUIET": "1"})
        self.assertIn("--no-auth", said.getvalue())
        self.assertTrue(ia.Config(["--no-auth"], {"HOME": "/tmp/x"}).no_auth)
        self.assertTrue(ia.Config(["--host", "0.0.0.0", "--no-auth", "--demo"], {"HOME": "/tmp/x"}).no_auth)

    def test_env_file_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# comment\nIG_ACCESS_TOKEN = 'abc'\nexport AGENT_PORT=9000\nbroken line\nEMPTY=\n")
            self.assertEqual(ia.read_env_file(path), {"IG_ACCESS_TOKEN": "abc", "AGENT_PORT": "9000", "EMPTY": ""})
        self.assertEqual(ia.read_env_file("/nonexistent/.env"), {})


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = ia.DB(os.path.join(self.dir.name, "t.db"))
        self.s = ia.Settings(self.db)

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_defaults_and_unknown_keys(self):
        self.assertTrue(self.s.get("autopilot"))
        self.assertFalse(self.s.get("auto.comment_reply"))
        self.s.patch({"nonsense": 1, "auto": {"nope": True}, "limits": {"per_hour": "12"}, "since": {"comment_reply": 5}})
        got = self.s.all()
        self.assertNotIn("nonsense", got)
        self.assertNotIn("nope", got["auto"])
        self.assertEqual(got["limits"]["per_hour"], 12)
        self.assertEqual(got["since"]["comment_reply"], 0)               # cannot be set from outside

    def test_numbers_are_clamped_and_types_kept(self):
        self.s.patch({"limits": {"per_hour": 99999, "cooldown_min": -5, "daily_posts": 0}, "autopilot": "yes"})
        got = self.s.all()
        self.assertEqual((got["limits"]["per_hour"], got["limits"]["cooldown_min"], got["limits"]["daily_posts"]), (200, 0, 1))
        self.assertIs(got["autopilot"], True)                            # a string is not a switch

    def test_switching_on_stamps_the_moment(self):
        self.assertEqual(self.s.get("since.comment_reply"), 0)
        self.s.patch({"auto": {"comment_reply": True}})
        first = self.s.get("since.comment_reply")
        self.assertGreater(first, 0)
        self.s.patch({"auto": {"comment_reply": True}})                  # already on: the stamp stays
        self.assertEqual(self.s.get("since.comment_reply"), first)
        self.assertEqual(self.s.get("since.dm_reply"), 0)

    def test_secrets_are_masked_and_kept_on_empty(self):
        self.s.patch({"ai": {"key": "sk-secret"}, "telegram": {"token": "123:abc", "chat_id": "7"}})
        pub = self.s.public()
        self.assertEqual((pub["ai"]["key"], pub["ai"]["key_set"], pub["telegram"]["token"], pub["telegram"]["token_set"]), ("", True, "", True))
        self.s.patch({"ai": {"key": "", "model": "m"}})                  # saving the form with an empty key keeps it
        self.assertEqual(self.s.all()["ai"]["key"], "sk-secret")
        self.s.patch({"ai": {"key_clear": True}})
        self.assertEqual(self.s.all()["ai"]["key"], "")

    def test_bad_values_are_explained(self):
        for patch in ({"limits": {"quiet_from": "25:00", "quiet_to": "07:00"}}, {"limits": {"quiet_from": "23:00"}},
                      {"network": {"proxy": "socks5://1.2.3.4:1080"}}, {"media": {"public_url": "ftp://x"}}, {"ai": {"url": "not a url"}}):
            with self.assertRaises(ia.UserError, msg=str(patch)):
                self.s.patch(patch)
        self.s.patch({"network": {"proxy": "127.0.0.1:10809"}, "limits": {"quiet_from": "۲۳:۰۰", "quiet_to": "07:30"}})
        self.assertEqual(self.s.get("network.proxy"), "http://127.0.0.1:10809")
        self.assertEqual(self.s.get("limits.quiet_from"), "23:00")
        self.assertEqual(ia.Settings(self.db).get("limits.quiet_to"), "07:30")   # really stored

    def test_rules_validation(self):
        rules = ia.Rules(self.db)
        with self.assertRaises(ia.UserError):
            rules.save({"scope": "comment", "keywords": "", "replies": ["x"]})
        with self.assertRaises(ia.UserError):
            rules.save({"scope": "comment", "keywords": "a", "replies": []})
        with self.assertRaises(ia.UserError):
            rules.save({"scope": "dm", "keywords": "a", "replies": ["ب" * 600]})   # over 1000 bytes
        with self.assertRaises(ia.UserError):
            rules.save({"scope": "story", "keywords": "a", "replies": ["x"]})
        r = rules.save({"scope": "comment", "keywords": "قیمت، چنده\nهزینه", "replies": "سلام", "hide": True})
        self.assertEqual((r["keywords"], r["replies"], r["hide"], r["name"]), (["قیمت", "چنده", "هزینه"], ["سلام"], True, "قیمت"))
        self.assertEqual(rules.match("comment", "هزینه‌اش چقدره؟")["id"], r["id"])
        self.assertIsNone(rules.match("dm", "هزینه؟"))
        rules.save(dict(r, enabled=False), r["id"])
        self.assertIsNone(rules.match("comment", "هزینه؟"))


if __name__ == "__main__":
    unittest.main()
