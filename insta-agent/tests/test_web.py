"""The panel's HTTP side: login, write protection, uploads, media links, and what must never leak."""
import http.client
import json
import os
import shutil
import tempfile
import unittest

from harness import Rig, ia, jpeg, mp4, png


class OpenPanelTests(unittest.TestCase):
    """Panel without login (loopback only) – the plumbing."""

    @classmethod
    def setUpClass(cls):
        cls.rig = Rig()

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()

    def test_page_is_served_with_a_strict_policy(self):
        status, body, headers = self.rig.get("/")
        html = body.decode("utf-8")
        self.assertEqual(status, 200)
        csp = headers["Content-Security-Policy"]
        nonce = csp.split("script-src 'nonce-")[1].split("'")[0]
        self.assertIn('<script nonce="%s">' % nonce, html)
        self.assertNotIn("__NONCE__", html)
        self.assertNotIn("unsafe-inline", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(self.rig.app.web.key, html)
        self.assertNotIn(ia.SIM_TOKEN, html)
        other = self.rig.get("/")[2]["Content-Security-Policy"]
        self.assertNotEqual(csp, other)                                   # a fresh nonce every time

    def test_page_never_contains_outside_resources(self):
        html = self.rig.get("/")[1].decode("utf-8")
        for needle in ("<script src", "//fonts.", "cdn.", "<link rel=\"stylesheet\""):
            self.assertNotIn(needle, html)

    def test_status_shape_and_no_secrets(self):
        st = self.rig.ok("GET", "/api/status")
        self.assertTrue(st["connected"])
        self.assertEqual(st["account"]["username"], "demo.cafe")
        for key in ("open_comments", "open_dms", "scheduled", "drafts", "unseen"):
            self.assertIn(key, st["counts"])
        self.rig.ok("POST", "/api/settings", {"ai": {"key": "sk-very-secret-1"}, "telegram": {"token": "999:very-secret-2", "chat_id": "5"}})
        for path in ("/api/status", "/api/settings", "/api/log", "/api/rules", "/api/posts"):
            raw = json.dumps(self.rig.ok("GET", path))
            for secret in (ia.SIM_TOKEN, "sk-very-secret-1", "999:very-secret-2", self.rig.app.web.key, self.rig.app.web.secret):
                self.assertNotIn(secret, raw, path)
        self.assertTrue(self.rig.ok("GET", "/api/settings")["telegram"]["token_set"])

    def test_writes_need_the_custom_header(self):
        status, body, _ = self.rig.post("/api/settings", {"autopilot": False}, headers={"X-IA": None})
        self.assertEqual(status, 403)
        self.assertTrue(self.rig.ok("GET", "/api/settings")["autopilot"])
        status, _, _ = self.rig.req("DELETE", "/api/rules/1", headers={"X-IA": None})
        self.assertEqual(status, 403)

    def test_foreign_origin_is_refused(self):
        status, _, _ = self.rig.post("/api/settings", {"autopilot": False}, headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertTrue(self.rig.ok("GET", "/api/settings")["autopilot"])
        host = self.rig.base.split("//")[1]
        status, _, _ = self.rig.post("/api/settings", {"brand": {"tone": "گرم"}}, headers={"Origin": "http://" + host})
        self.assertEqual(status, 200)

    def test_foreign_host_name_is_refused(self):
        # DNS rebinding: a web page that points its own name at 127.0.0.1 must not reach the panel.
        for path in ("/", "/api/status", "/_sim/ig/me"):
            status, _, _ = self.rig.get(path, headers={"Host": "evil.example:8787"})
            self.assertEqual(status, 403, path)
        self.assertEqual(self.rig.get("/api/status", headers={"Host": "localhost:1"})[0], 200)

    def test_bad_requests_are_answered_cleanly(self):
        self.assertEqual(self.rig.get("/api/nope")[0], 404)
        self.assertEqual(self.rig.get("/nope")[0], 404)
        self.assertEqual(self.rig.get("/api/posts/999999")[0], 404)
        status, body, _ = self.rig.req("POST", "/api/settings", raw=b"[1,2", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        conn = http.client.HTTPConnection("127.0.0.1", self.rig.app.port, timeout=10)   # announces 3 MB of JSON
        conn.putrequest("POST", "/api/settings")
        for k, v in (("X-IA", "1"), ("Content-Type", "application/json"), ("Content-Length", str(3 * 1024 * 1024))):
            conn.putheader(k, v)
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)                  # refused before a single byte is read
        conn.close()
        status, body, _ = self.rig.post("/api/posts", {"kind": "image", "media": [], "action": "schedule", "scheduled_at": "soon"})
        self.assertEqual(status, 400)
        status, body, _ = self.rig.post("/api/settings", {"limits": {"quiet_from": "99:99", "quiet_to": "07:00"}})
        self.assertEqual(status, 400)
        self.assertTrue(body["error"])
        self.assertEqual(self.rig.get("/api/status")[0], 200)             # still alive after all of that

    def test_upload_and_private_preview(self):
        data = jpeg(1080, 1350, pad=3000)
        f = self.rig.upload(data, "عکس من.jpg")
        self.assertEqual((f["type"], f["width"], f["height"], f["size"]), ("image", 1080, 1350, len(data)))
        self.assertRegex(f["id"], r"^[0-9a-f]{24}$")
        status, body, headers = self.rig.get(f["preview"])
        self.assertEqual((status, body, headers["Content-Type"]), (200, data, "image/jpeg"))
        v = self.rig.upload(mp4(5000), "clip.mp4")
        self.assertEqual(v["type"], "video")

    def test_upload_refuses_what_instagram_would_refuse(self):
        before = set(os.listdir(self.rig.agent.store.dir))
        for blob in (b"<html><script>alert(1)</script></html>", png(), b"GIF89a" + b"\x00" * 50, b"MZ\x90\x00" + b"\x00" * 60):
            status, body, _ = self.rig.req("POST", "/api/upload?name=x.jpg", raw=blob)
            self.assertEqual(status, 400)
            self.assertTrue(body["error"])
        status, _, _ = self.rig.req("POST", "/api/upload?name=x.jpg", raw=b"")
        self.assertEqual(status, 400)
        self.assertEqual(set(os.listdir(self.rig.agent.store.dir)), before)   # nothing left behind

    def test_media_link_for_instagram(self):
        data = mp4(200000)
        f = self.rig.upload(data, "clip.mp4")
        name = "/m/%s.mp4" % f["id"]
        for base in (self.rig.base, self.rig.media_base):
            status, body, headers = self.rig.get(name, base=base, headers={"X-IA": None})
            self.assertEqual((status, len(body), headers["Content-Type"]), (200, len(data), "video/mp4"))
            self.assertEqual(headers["Accept-Ranges"], "bytes")
        # Instagram's fetcher reaches the media port through the tunnel, under the tunnel's own host name
        status, body, _ = self.rig.get(name, base=self.rig.media_base, headers={"Host": "abc.trycloudflare.com"})
        self.assertEqual((status, body), (200, data))
        status, body, headers = self.rig.get(name, headers={"Range": "bytes=10-19"})
        self.assertEqual((status, body, headers["Content-Range"]), (206, data[10:20], "bytes 10-19/200000"))
        status, body, headers = self.rig.get(name, headers={"Range": "bytes=199990-"})
        self.assertEqual((status, body), (206, data[199990:]))
        status, body, headers = self.rig.get(name, headers={"Range": "bytes=-5"})
        self.assertEqual((status, body), (206, data[-5:]))
        self.assertEqual(self.rig.get(name, headers={"Range": "bytes=500000-"})[0], 416)
        status, body, headers = self.rig.req("HEAD", name)
        self.assertEqual((status, body, headers["Content-Length"]), (200, b"", "200000"))

    def test_media_link_cannot_reach_anything_else(self):
        f = self.rig.upload(jpeg())
        for path in ("/m/%s.mp4" % f["id"], "/m/%s" % f["id"], "/m/../agent.db", "/m/..%2Fagent.db", "/m/%2e%2e/key.txt",
                     "/m/" + "0" * 24 + ".jpg", "/m/%s.jpg/../../key.txt" % f["id"]):
            for base in (self.rig.base, self.rig.media_base):
                self.assertEqual(self.rig.get(path, base=base)[0], 404, path)

    def test_media_port_serves_only_media(self):
        base = self.rig.media_base
        self.assertEqual(self.rig.get("/healthz", base=base)[:2], (200, b"ok"))
        for path in ("/", "/api/status", "/api/settings", "/_sim/ig/me", "/manifest.webmanifest", "/icon.svg"):
            self.assertEqual(self.rig.get(path, base=base)[0], 404, path)
        self.assertEqual(self.rig.post("/api/connect", {"token": ia.SIM_TOKEN}, base=base)[0], 404)
        self.assertEqual(self.rig.app.media_httpd.server_address[0], "127.0.0.1")

    def test_app_icons_and_manifest(self):
        status, body, headers = self.rig.get("/manifest.webmanifest")
        self.assertEqual(status, 200)
        self.assertEqual(body["display"], "standalone")
        for size in (192, 512):
            status, body, headers = self.rig.get("/icon-%d.png" % size)
            self.assertEqual(status, 200)
            self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(ia.sniff(body[:64])[1], "png")
            self.assertEqual(int.from_bytes(body[16:20], "big"), size)
        self.assertEqual(self.rig.get("/icon.svg")[2]["Content-Type"], "image/svg+xml")

    def test_connection_survives_an_unread_body(self):
        # refused writes do not read their body; the next request must still be understood
        for _ in range(3):
            self.assertEqual(self.rig.post("/api/settings", {"x": "y" * 5000}, headers={"X-IA": None})[0], 403)
            self.assertEqual(self.rig.get("/api/status")[0], 200)


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(auth=True)
        self.key = self.rig.app.web.key

    def tearDown(self):
        self.rig.close()

    def login(self, key):
        status, body, headers = self.rig.post("/api/login", {"key": key})
        if status == 200:
            self.rig.cookie = headers["Set-Cookie"].split(";")[0]
        return status, body, headers

    def test_everything_is_closed_without_login(self):
        for path in ("/api/status", "/api/settings", "/api/posts", "/api/log", "/api/comments", "/api/dm", "/api/rules"):
            status, body, _ = self.rig.get(path)
            self.assertEqual((status, body["code"]), (401, "auth"), path)
        self.assertEqual(self.rig.post("/api/connect", {"token": ia.SIM_TOKEN})[0], 401)
        self.assertEqual(self.rig.req("POST", "/api/upload?name=a.jpg", raw=jpeg())[0], 401)
        self.assertEqual(self.rig.req("DELETE", "/api/rules/1")[0], 401)
        f = self.rig.agent.store.add(self._tmp_upload(), "a.jpg")
        self.assertEqual(self.rig.get("/api/file/" + f["id"])[0], 401)
        self.assertEqual(self.rig.get("/")[0], 200)                       # the page itself (the login form) is public
        self.assertEqual(self.rig.get("/healthz")[0], 200)

    def _tmp_upload(self):
        path = os.path.join(self.rig.agent.store.dir, "up-test.part")
        with open(path, "wb") as fh:
            fh.write(jpeg())
        return path

    def test_login_logout(self):
        status, body, _ = self.login("AAAAA-AAAAA")
        self.assertEqual(status, 401)
        self.assertNotEqual(body.get("code"), "auth")                     # "wrong key" is not "session lost"
        status, _, headers = self.login(self.key)
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn(self.key, cookie)
        self.assertEqual(self.rig.get("/api/status")[0], 200)
        status, _, headers = self.rig.post("/api/logout")
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.rig.cookie = "ia_session=deadbeef"
        self.assertEqual(self.rig.get("/api/status")[0], 401)

    def test_key_typed_loosely_is_accepted(self):
        loose = " " + self.key.lower().replace("-", " ") + " "
        self.assertEqual(self.login(loose)[0], 200)

    def test_link_from_the_terminal_logs_in(self):
        status, _, headers = self.rig.get("/?k=wrong-key")
        self.assertEqual((status, headers["Location"], headers.get("Set-Cookie")), (303, "/", None))
        status, _, headers = self.rig.get("/?k=" + self.key)
        self.assertEqual((status, headers["Location"]), (303, "/"))       # the key leaves the address bar
        self.rig.cookie = headers["Set-Cookie"].split(";")[0]
        self.assertEqual(self.rig.get("/api/status")[0], 200)

    def test_guessing_is_locked_out(self):
        for _ in range(8):
            self.assertEqual(self.login("ZZZZZ-ZZZZZ")[0], 401)
        self.assertEqual(self.login("ZZZZZ-ZZZZZ")[0], 429)
        self.assertEqual(self.login(self.key)[0], 429)                    # even the right key waits now
        self.assertEqual(self.rig.get("/?k=" + self.key)[2].get("Set-Cookie"), None)
        self.rig.app.web.fails.clear()
        self.assertEqual(self.login(self.key)[0], 200)

    def test_session_survives_a_restart_and_dies_with_the_key(self):
        self.login(self.key)
        cookie = self.rig.cookie
        web2 = ia.Web(self.rig.app.cfg, self.rig.agent)                   # what a restart would build
        self.assertEqual((web2.key, "ia_session=" + web2.session()), (self.key, cookie))
        os.remove(os.path.join(self.rig.app.cfg.data_dir, "key.txt"))     # the owner asks for a new key
        web3 = ia.Web(self.rig.app.cfg, self.rig.agent)
        self.assertNotEqual(web3.key, self.key)
        self.assertNotEqual("ia_session=" + web3.session(), cookie)

    def test_files_holding_secrets_are_private(self):
        d = self.rig.app.cfg.data_dir
        self.assertEqual(os.stat(d).st_mode & 0o077, 0)
        for name in ("key.txt", "secret.txt"):
            self.assertEqual(os.stat(os.path.join(d, name)).st_mode & 0o077, 0, name)


class StartupTests(unittest.TestCase):
    def test_own_password_from_the_environment(self):
        rig = Rig(auth=True, env={"AGENT_PASSWORD": "رمز خودم 123"})
        try:
            self.assertEqual(rig.post("/api/login", {"key": "رمز خودم 124"})[0], 401)
            self.assertEqual(rig.post("/api/login", {"key": "رمز خودم 123"})[0], 200)
        finally:
            rig.close()

    def test_second_copy_on_the_same_data_is_refused(self):
        rig = Rig()
        try:
            twin = ia.App(["--port", "0", "--no-browser", "--no-auth", "--data", rig.app.cfg.data_dir],
                          {"AGENT_QUIET": "1", "HOME": rig.tmp, "AGENT_SIM": "1", "AGENT_NO_LOOP": "1"})
            with self.assertRaises(ia.UserError):
                twin.start()
            twin.agent.db.close()
        finally:
            rig.close()

    def test_a_real_run_has_no_simulator(self):
        tmp = tempfile.mkdtemp(prefix="ia-real-")
        app = ia.App(["--port", "0", "--no-browser", "--no-auth", "--data", os.path.join(tmp, "d")],
                     {"AGENT_QUIET": "1", "HOME": tmp, "AGENT_NO_LOOP": "1"})
        app.start()
        try:
            self.assertIsNone(app.agent.sim)
            self.assertTrue(app.cfg.ig_graph.startswith("https://graph.instagram.com"))
            rig = Rig.__new__(Rig)
            rig.base, rig.cookie = "http://127.0.0.1:%d" % app.port, ""
            self.assertEqual(rig.get("/_sim/ig/me")[0], 404)
            st = rig.ok("GET", "/api/status")
            self.assertEqual((st["connected"], st["demo"]), (False, False))
            self.assertEqual(rig.post("/api/posts", {"kind": "image", "media": [], "action": "now"})[0], 400)
            self.assertEqual(rig.post("/api/comments/sync")[0], 409)
            status, body, _ = rig.post("/api/connect", {"token": "short"})
            self.assertEqual(status, 400)
        finally:
            app.stop()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_demo_starts_connected_and_alive(self):
        rig = Rig(demo=True)
        try:
            st = rig.ok("GET", "/api/status")
            self.assertTrue(st["demo"] and st["connected"])
            self.assertEqual(st["account"]["username"], "demo.cafe")
            self.assertTrue(st["auto"]["comment_reply"] and st["auto"]["dm_reply"] and st["auto"]["spam_hide"])
            rig.tick()
            self.assertGreater(rig.ok("GET", "/api/status")["counts"]["open_comments"], 0)
            self.assertNotIn("frame-ancestors", rig.get("/")[2]["Content-Security-Policy"])   # the demo may be embedded
            # nothing that was already on the fake page is answered automatically
            self.assertEqual(rig.ok("GET", "/api/status")["counts"]["auto_today"], 0)
            cid = rig.sim.add_comment("قیمت این چنده؟", "tester")
            rig.tick(2)
            self.assertGreaterEqual(rig.ok("GET", "/api/status")["counts"]["auto_today"], 1)
            answers = [c for c in rig.sim.comments.values() if c["parent_id"] == cid]
            self.assertEqual(len(answers), 1)
            self.assertIn("@tester", answers[0]["text"])
        finally:
            rig.close()


if __name__ == "__main__":
    unittest.main()
