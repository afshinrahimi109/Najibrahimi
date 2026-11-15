"""Small pieces that need no running agent."""
import base64
import contextlib
import io
import os
import shutil
import struct
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

    def test_hashtag_limits(self):
        self.assertEqual((ia.GOOD_HASHTAGS, ia.MAX_HASHTAGS), (5, 30))      # advised by Instagram / accepted by the API
        self.assertEqual(ia.limit_tags("متن #a #b #c #d #e #f #g"), "متن #a #b #c #d #e")
        self.assertEqual(ia.limit_tags("متن #a #b\n\nخط دوم"), "متن #a #b\n\nخط دوم")

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


    def test_a_refusal_about_hashtags_is_named(self):
        for err in (ia.GraphError("The caption contains too many hashtags", 100, 0, 400),
                    ia.GraphError("Too many hashtags in the caption", 36004, 2207010, 400),
                    ia.GraphError("Caption has too many Hashtags", 2500, 0, 400)):
            self.assertIn("این تعداد هشتگ را نپذیرفت", err.fa, err.kind)
        self.assertNotIn("تعداد هشتگ", ia.GraphError("The caption was too long", 36004, 2207010, 400).fa)
        self.assertNotIn("تعداد هشتگ", ia.GraphError("hashtag", 190).fa)    # other kinds keep their own explanation


class StudioHelperTests(unittest.TestCase):
    def test_shorten_cuts_at_a_word(self):
        self.assertEqual(ia.shorten("  سلام   دنیا  ", 40), "سلام دنیا")
        self.assertEqual(ia.shorten("تخفیف بیست درصدی لاتهٔ پاییزی تا آخر هفته", 24), "تخفیف بیست درصدی لاتهٔ…")
        self.assertEqual(ia.shorten("abcdefghijklmnop", 8), "abcdefgh…")
        self.assertEqual(ia.shorten(None, 8), "")

    def test_loose_json_finds_the_object_in_an_answer(self):
        self.assertEqual(ia.loose_json('حتماً!\n```json\n{"a": 1, "b": {"c": [2]}}\n```\nموفق باشید'), {"a": 1, "b": {"c": [2]}})
        for bad in ("", "no braces", "{not json}", "[1, 2]", '{"a": 1', None):
            self.assertIsNone(ia.loose_json(bad), bad)

    def test_picture_descriptions_ask_for_no_writing(self):
        cases = {
            'A hand holding a sign that reads "20% OFF" beside a latte, cozy café interior.': "A hand holding a sign beside a latte, cozy cafe interior",
            'An inviting café sign with the word "کافه" illuminated, warm lighting': "An inviting cafe sign, warm lighting",
            "a display board with the text '20% off this week', customers in the background": "a display board, customers in the background",
            "A banner saying Welcome; warm light. A cup labeled SALE, on a table": "A banner; warm light. A cup, on a table",
            "fresh carrot cake on a wooden table, top-down shot": "fresh carrot cake on a wooden table, top-down shot",
        }
        for asked, want in cases.items():
            self.assertEqual(ia.no_writing(asked), want)
        self.assertEqual(ia.no_writing(None), "")
        self.assertEqual(ia.no_writing("کیک هویج خانگی"), "")           # nothing an English-only service could read

    def test_a_service_that_says_not_now(self):
        said = ('{"status":402,"success":false,"error":{"code":"FREE_LIMIT","message":"Free limit reached: 1 image every 45 seconds per IP. '
                'Retry after 41s, or get unlimited images with a pollen key"}}')
        self.assertEqual(ia.Studio.refusal({}, said.encode())[1], 41)
        plain = "Free limit reached: 1 reply every 45 seconds per IP. Please wait 39 seconds or get unlimited replies, then try again."
        self.assertEqual(ia.Studio.refusal({}, plain.encode())[1], 39)
        self.assertEqual(ia.Studio.refusal({"retry-after": "10"}, b'{"error":{"code":"SERVICE_UNAVAILABLE","message":"at its limit"}}')[1], 10)
        self.assertEqual(ia.Studio.refusal({}, b"<html>Bad Gateway</html>")[1], 0)

    def test_what_counts_as_a_picture(self):
        self.assertTrue(ia.Studio.is_picture(ia.fake_picture("x", 200, 300)))
        self.assertTrue(ia.Studio.is_picture(jpeg()))
        self.assertTrue(ia.Studio.is_picture(b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 40))
        for raw in (b"", b"GIF89a" + b"\x00" * 40, mp4(), b'{"error": "x"}', b"<html>"):
            self.assertFalse(ia.Studio.is_picture(raw), raw[:12])

    def test_the_stand_in_picture_depends_on_the_request(self):
        a, b = ia.fake_picture("latte 1", 300, 400), ia.fake_picture("bicycle 2", 300, 400)
        self.assertEqual(a[:8], b"\x89PNG\r\n\x1a\n")
        self.assertNotEqual(a, b)
        self.assertEqual(a, ia.fake_picture("latte 1", 300, 400))
        self.assertEqual(struct.unpack(">II", a[16:24]), (300, 400))
        self.assertEqual(struct.unpack(">II", ia.fake_picture("x", 5000, 5000)[16:24]), (640, 1136))     # never huge

    def test_the_embedded_typeface_is_a_woff2_file(self):
        raw = base64.b64decode(ia.FONT_WOFF2)
        self.assertEqual(raw[:4], b"wOF2")
        self.assertEqual(struct.unpack(">I", raw[8:12])[0], len(raw))      # the length the file states about itself


class FileTests(unittest.TestCase):
    def test_webm_and_webp(self):
        self.assertEqual(ia.sniff(b"\x1a\x45\xdf\xa3" + b"\x00" * 60), ("video", "webm", "video/webm"))
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cases = {"lossy": b"RIFF\x00\x00\x00\x00WEBPVP8 \x00\x00\x00\x00\x00\x00\x00\x9d\x01\x2a\x01\x02\x81\x02",        # 513x641
                 "lossless": b"RIFF\x00\x00\x00\x00WEBPVP8L\x00\x00\x00\x00\x2f\x00\x02\xa0\x00" + b"\x00" * 6,                # 513x641
                 "extended": b"RIFF\x00\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x10\x00\x00\x00\x00\x02\x00\x80\x02\x00"}       # 513x641
        for name, head in cases.items():
            path = os.path.join(tmp, name + ".webp")
            with open(path, "wb") as fh:
                fh.write(head + b"\x00" * 8)
            self.assertEqual(ia.image_size(path), (513, 641), name)

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
