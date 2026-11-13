"""Connecting a page, keeping the token alive, numbers, the writing assistant, alerts, restarts."""
import contextlib
import http.server
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

from harness import ROOT, FakeAI, Rig, ia, jpeg


class Base(unittest.TestCase):
    connect, env = True, None

    def setUp(self):
        self.rig = Rig(connect=self.connect, env=self.env)
        self.sim, self.agent = self.rig.sim, self.rig.agent

    def tearDown(self):
        self.rig.close()

    def calls(self, pattern, method=None):
        return [c for c in self.sim.calls if (method is None or c[0] == method) and re.search(pattern, c[1])]

    def notes(self, level=None):
        return [n["text"] for n in self.rig.ok("GET", "/api/log")["items"] if level in (None, n["level"])]


class ConnectTests(Base):
    connect = False

    def test_things_that_are_not_tokens(self):
        for bad in ("", "short", "سلام این توکن من است " * 3, "IGAA with spaces inside " * 3 + "!", None, 12345):
            status, body, _ = self.rig.post("/api/connect", {"token": bad})
            self.assertEqual(status, 400, bad)
            self.assertTrue(body["error"])
        self.assertEqual(self.sim.calls, [])                              # Instagram was never bothered

    def test_wrong_token(self):
        status, body, _ = self.rig.post("/api/connect", {"token": "IGAA" + "x" * 40})
        self.assertEqual((status, body["kind"]), (502, "auth"))
        self.assertIn("توکن", body["error"])
        st = self.rig.ok("GET", "/api/status")
        self.assertFalse(st["connected"])
        self.assertIsNone(self.agent.db.get("secret.token"))
        self.assertFalse(self.agent.ig.acct.get("invalid"))               # nothing was connected, so nothing "broke"

    def test_connect(self):
        pasted = '  "%s\n%s"  ' % (ia.SIM_TOKEN[:20], ia.SIM_TOKEN[20:])   # copied with quotes and a line break
        st = self.rig.ok("POST", "/api/connect", {"token": pasted})
        self.assertTrue(st["connected"])
        a = st["account"]
        self.assertEqual((a["username"], a["name"], a["followers"], a["follows"], a["media_count"], a["login"]),
                         ("demo.cafe", "کافه دمو", 1840, 312, 10, "ig"))
        self.assertEqual(self.agent.db.get("secret.token"), ia.SIM_TOKEN)
        self.assertIn("پیج @demo.cafe وصل شد", self.notes()[0])
        if os.name == "posix":                                            # nobody else on the device can read it
            self.assertEqual(os.stat(os.path.join(self.rig.app.cfg.data_dir, "agent.db")).st_mode & 0o077, 0)
        series = self.rig.ok("GET", "/api/insights")["followers"]["series"]
        self.assertEqual([s["followers"] for s in series], [1840])        # today's follower count is on record

    def test_nothing_works_before_connecting(self):
        for path in ("/api/media", "/api/insights", "/api/insights/audience"):
            self.assertEqual(self.rig.get(path)[0], 409, path)
        for path in ("/api/comments/sync", "/api/dm/sync", "/api/token/refresh"):
            self.assertEqual(self.rig.post(path)[0], 409, path)
        f = self.rig.upload(jpeg())
        status, body, _ = self.rig.post("/api/posts", {"kind": "image", "media": [{"file": f["id"]}], "action": "now"})
        self.assertEqual(status, 400)
        self.assertEqual(self.rig.ok("POST", "/api/posts", {"kind": "image", "media": [{"file": f["id"]}], "action": "draft"})["status"], "draft")
        self.rig.tick(3)
        self.assertEqual(self.sim.calls, [])

    def test_older_api_version_is_found(self):
        self.sim.bad_versions = {"v27.0"}
        self.rig.ok("POST", "/api/connect", {"token": ia.SIM_TOKEN})
        self.assertEqual((self.agent.ig.acct["version"], self.agent.graph.version), ("v26.0", "v26.0"))
        self.rig.tick()
        self.assertEqual(self.rig.ok("GET", "/api/status")["counts"]["open_comments"], 5)
        self.assertEqual(self.notes("warn") + self.notes("alert"), [])

    def test_no_version_number_as_a_last_resort(self):
        self.sim.bad_versions = {"v27.0", "v26.0", "v25.0"}
        self.rig.ok("POST", "/api/connect", {"token": ia.SIM_TOKEN})
        self.assertEqual(self.agent.graph.version, "")
        self.assertEqual(len(self.rig.ok("GET", "/api/media")["items"]), 10)

    def test_profile_with_fewer_readable_fields(self):
        self.sim.unknown_fields = {"biography", "followers_count"}
        st = self.rig.ok("POST", "/api/connect", {"token": ia.SIM_TOKEN})
        self.assertEqual((st["account"]["username"], st["account"]["followers"], st["account"]["media_count"]), ("demo.cafe", None, 10))
        self.rig.tick()                                                   # later profile refreshes use what worked
        self.assertEqual(self.notes("warn") + self.notes("alert"), [])
        self.assertEqual(self.rig.get("/api/insights")[0], 200)

    def test_facebook_login_token(self):
        st = self.rig.ok("POST", "/api/connect", {"token": ia.SIM_FB_TOKEN})
        a = self.agent.ig.acct
        self.assertEqual((st["account"]["login"], a["page_id"], a["ig_id"]), ("fb", "100200300400500", "17841400000000001"))
        self.assertEqual(self.agent.db.get("secret.token"), ia.SIM_PAGE_TOKEN)   # the page's token, not the person's
        self.assertTrue(self.agent.ig.base().endswith("/_sim/fb"))
        self.rig.tick()
        counts = self.rig.ok("GET", "/api/status")["counts"]
        self.assertEqual((counts["open_comments"], counts["open_dms"]), (5, 2))
        conv = next(c for c in self.sim.convs.values() if c["username"] == "elham.gh")
        self.rig.ok("POST", "/api/dm/%s/send" % conv["id"], {"text": "سلام 🌹"})
        self.assertEqual(self.calls(r"/messages$", "POST")[0][1], "100200300400500/messages")
        self.assertEqual(self.calls(r"/conversations$", "GET")[0][1], "100200300400500/conversations")
        p = self.rig.new_post()
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        status, body, _ = self.rig.post("/api/token/refresh")
        self.assertEqual(status, 400)
        self.agent.ig.save_acct(token_next=0)
        self.rig.tick()
        self.assertEqual(self.calls(r"refresh_access_token"), [])

    def test_facebook_token_without_a_linked_page(self):
        real = self.sim.route

        def route(method, host, parts, *a):
            if parts == ["me", "accounts"]:
                return 200, {"data": [{"id": "1", "name": "A page without Instagram", "access_token": ia.SIM_PAGE_TOKEN}]}
            return real(method, host, parts, *a)

        self.sim.route = route
        status, body, _ = self.rig.post("/api/connect", {"token": ia.SIM_FB_TOKEN})
        self.assertEqual(status, 400)
        self.assertIn("IGAA", body["error"])

    def test_token_from_the_environment(self):
        rig = Rig(connect=False, env={"IG_ACCESS_TOKEN": ia.SIM_TOKEN})
        try:
            self.assertTrue(rig.ok("GET", "/api/status")["connected"])
        finally:
            rig.close()
        rig = Rig(connect=False, env={"IG_ACCESS_TOKEN": "IGAA" + "z" * 40})   # a stale one does not stop the start
        try:
            self.assertFalse(rig.ok("GET", "/api/status")["connected"])
        finally:
            rig.close()


class PageSwitchTests(Base):
    def prepare(self):
        self.rig.tick()
        self.rule = self.rig.ok("POST", "/api/rules", {"scope": "comment", "keywords": "قیمت", "replies": ["سلام"]})
        self.rig.ok("POST", "/api/settings", {"brand": {"about": "کافه"}})
        self.post = self.rig.new_post(action="schedule", scheduled_at=time.time() + 3600, caption="برای پیج اول")
        self.draft = self.rig.ok("POST", "/api/posts", {"kind": "image", "caption": "ایده", "media": [], "action": "draft"})

    def test_disconnect_stops_everything_and_forgets_the_token(self):
        self.prepare()
        st = self.rig.ok("POST", "/api/disconnect")
        self.assertEqual((st["connected"], st["account"]["last_username"], st["account"]["username"]), (False, "demo.cafe", None))
        self.assertIsNone(self.agent.db.get("secret.token"))
        self.assertEqual(self.agent.graph.token, "")
        folder = self.rig.app.cfg.data_dir
        for name in os.listdir(folder):                                   # not in the database, its journal, or any other file
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    self.assertNotIn(ia.SIM_TOKEN.encode(), f.read(), name)
        n = len(self.sim.calls)
        self.agent.db.x("UPDATE posts SET scheduled_at=? WHERE id=?", (time.time() - 5, self.post["id"]))
        self.rig.tick(3)
        self.assertEqual(len(self.sim.calls), n)
        self.assertEqual(self.rig.post_status(self.post["id"])["status"], "scheduled")

    def test_same_page_again_keeps_everything(self):
        self.prepare()
        self.rig.ok("POST", "/api/disconnect")
        self.rig.ok("POST", "/api/connect", {"token": ia.SIM_TOKEN})
        st = self.rig.ok("GET", "/api/status")["counts"]
        self.assertEqual((st["open_comments"], st["scheduled"], st["drafts"]), (5, 1, 1))

    def test_another_page_starts_clean(self):
        self.prepare()
        self.sim.user.update(user_id="17841499999999999", id="9000000000000777", username="other.shop")
        st = self.rig.ok("POST", "/api/connect", {"token": ia.SIM_TOKEN})
        self.assertEqual(st["account"]["username"], "other.shop")
        counts = st["counts"]
        self.assertEqual((counts["open_comments"], counts["open_dms"], counts["scheduled"], counts["drafts"]), (0, 0, 0, 2))
        got = self.rig.post_status(self.post["id"])                      # nothing meant for the old page goes out on the new one
        self.assertEqual((got["status"], got["caption"]), ("draft", "برای پیج اول"))
        self.assertEqual(self.rig.ok("GET", "/api/comments?filter=all")["items"], [])
        self.assertEqual(self.rig.ok("GET", "/api/dm")["items"], [])
        self.assertEqual([r["id"] for r in self.rig.ok("GET", "/api/rules")["items"] if r["id"] == self.rule["id"]], [self.rule["id"]])
        self.assertEqual(self.rig.ok("GET", "/api/settings")["brand"]["about"], "کافه")
        self.assertEqual(len(self.rig.ok("GET", "/api/insights")["followers"]["series"]), 1)


class TokenTests(Base):
    def test_renewed_on_its_own(self):
        old = self.sim.token
        self.agent.ig.save_acct(token_next=time.time() - 1)
        self.rig.tick()
        new = self.agent.db.get("secret.token")
        self.assertNotEqual(new, old)
        self.assertEqual((new, self.agent.graph.token), (self.sim.token, self.sim.token))
        a = self.agent.ig.acct
        self.assertAlmostEqual(a["token_expires"] - time.time(), 5183944, delta=60)
        self.assertAlmostEqual(a["token_next"] - time.time(), 7 * 86400, delta=60)
        self.assertTrue(any("تمدید شد" in n for n in self.notes()))
        self.rig.tick()                                                   # and everything keeps working with the new one
        self.assertFalse(self.agent.ig.acct.get("invalid"))
        self.assertEqual(len(self.calls(r"refresh_access_token")), 1)
        raw = [c for c in self.calls(r"refresh_access_token")][0][2]
        self.assertEqual(raw["grant_type"], "ig_refresh_token")

    def test_not_renewed_before_it_is_a_day_old(self):
        self.rig.tick(3)
        self.assertEqual(self.calls(r"refresh_access_token"), [])
        self.assertGreater(self.agent.ig.acct["token_next"], time.time() + 24 * 3600)

    def test_button_in_the_panel(self):
        out = self.rig.ok("POST", "/api/token/refresh")
        self.assertGreater(out["token_expires"], time.time() + 50 * 86400)
        self.assertEqual(self.agent.db.get("secret.token"), self.sim.token)
        self.assertEqual(self.rig.ok("GET", "/api/status")["account"]["token_expires"], out["token_expires"])

    def test_refused_renewal_is_not_the_end(self):
        self.sim.fail(r"refresh_access_token", code=190, message="Error validating access token")
        self.agent.ig.save_acct(token_next=time.time() - 1)
        self.rig.tick()
        a = self.agent.ig.acct
        self.assertFalse(a.get("invalid"))
        self.assertEqual(self.agent.db.get("secret.token"), ia.SIM_TOKEN)
        self.assertAlmostEqual(a["token_next"] - time.time(), 86400, delta=60)   # tries again tomorrow
        self.assertEqual(self.notes("alert"), [])

    def test_warns_when_the_end_is_near(self):
        self.rig.ok("POST", "/api/settings", {"telegram": {"token": "1:a", "chat_id": "9"}})
        self.sim.fail(r"refresh_access_token", code=190, times=5)
        self.agent.ig.save_acct(token_next=time.time() - 1, token_expires=time.time() + 3 * 86400 + 60)
        self.rig.tick(2)
        alerts = self.notes("alert")
        self.assertEqual(len(alerts), 1)                                  # once a day, not every round
        self.assertIn("۳ روز", alerts[0])
        self.assertEqual(len(self.sim.telegram), 1)


class NumbersTests(Base):
    def setUp(self):
        super().setUp()
        self.rig.tick()

    def test_overview(self):
        d = self.rig.ok("GET", "/api/insights?days=7")
        keys = [m["key"] for m in d["metrics"]]
        self.assertEqual(keys[:4], ["reach", "views", "accounts_engaged", "total_interactions"])
        self.assertEqual(len(keys), 10)
        self.assertTrue(all(m["value"] > 0 and m["label"] and isinstance(m["change"], int) for m in d["metrics"]))
        self.assertEqual((d["days"], d["error"], d["followers"]["now"]), (7, "", 1840))
        self.assertEqual(len(d["best_hours"]), 3)
        self.assertLessEqual(len(d["top"]), 5)
        likes = [t["likes"] + 2 * t["comments"] for t in d["top"]]
        self.assertEqual(likes, sorted(likes, reverse=True))
        asked = self.calls(r"/insights$", "GET")
        self.assertEqual(len(asked), 2)                                   # this week and the week before, one call each
        self.assertEqual(asked[0][2]["metric_type"], "total_value")
        self.assertNotIn("impressions", asked[0][2]["metric"])            # names Instagram has removed are never asked
        self.rig.ok("GET", "/api/insights?days=7")
        self.assertEqual(len(self.calls(r"/insights$", "GET")), 2)        # kept for half an hour
        self.rig.ok("GET", "/api/insights?days=7&refresh=1")
        self.assertEqual(len(self.calls(r"/insights$", "GET")), 4)

    def test_month_view_stays_inside_instagrams_range(self):
        d = self.rig.ok("GET", "/api/insights?days=28")
        self.assertEqual((d["days"], d["error"], len(d["metrics"])), (28, "", 10))
        for c in self.calls(r"/insights$", "GET"):
            self.assertLessEqual(int(c[2]["until"]) - int(c[2]["since"]), 30 * 86400)

    def test_one_refused_metric_does_not_blank_the_page(self):
        real = self.sim.account_insights

        def picky(p):                                                     # Instagram retires a metric name overnight
            if "views" in p.get("metric", "").split(","):
                return self.sim.err(100, "metric[1] must be one of the following values: …")
            return real(p)

        self.sim.account_insights = picky
        d = self.rig.ok("GET", "/api/insights?days=7")
        keys = [m["key"] for m in d["metrics"]]
        self.assertEqual((d["error"], len(keys)), ("", 9))
        self.assertNotIn("views", keys)
        self.assertIn("reach", keys)

    def test_no_permission_for_insights(self):
        self.sim.fail(r"/insights$", code=10, times=99, method="GET")
        d = self.rig.ok("GET", "/api/insights?days=7")
        self.assertEqual(d["metrics"], [])
        self.assertIn("دسترسی", d["error"])
        self.assertEqual(d["followers"]["now"], 1840)                     # what does not need that permission still shows
        self.assertTrue(d["top"])

    def test_audience(self):
        d = self.rig.ok("GET", "/api/insights/audience")
        g = d["groups"]
        self.assertEqual((sorted(g), d["error"]), (["age", "city", "country", "gender"], ""))
        self.assertEqual(g["gender"], [{"name": "F", "value": 1012}, {"name": "M", "value": 736}, {"name": "U", "value": 92}])
        self.assertEqual([r["name"] for r in g["age"]][:2], ["25-34", "18-24"])
        self.assertEqual(g["country"][0], {"name": "IR", "value": 1500})
        asked = self.calls(r"/insights$", "GET")
        self.assertEqual([c[2]["breakdown"] for c in asked], ["gender", "age", "city", "country"])
        self.assertTrue(all(c[2]["metric"] == "follower_demographics" and c[2]["period"] == "lifetime" for c in asked))

    def test_audience_of_a_small_page(self):
        self.sim.fail(r"/insights$", code=100, message="Not enough followers", times=9, method="GET")
        d = self.rig.ok("GET", "/api/insights/audience")
        self.assertEqual([len(v) for v in d["groups"].values()], [])
        self.assertIn("۱۰۰ دنبال‌کننده", d["error"])
        self.assertFalse(self.agent.ig.acct.get("invalid"))

    def test_post_detail(self):
        mid = self.sim.media[0]["id"]
        d = self.rig.ok("GET", "/api/media/" + mid)
        self.assertEqual((d["media"]["id"], d["error"], d["open_comments"]), (mid, "", 3))
        self.assertEqual([m["key"] for m in d["metrics"]], ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions"])
        self.assertEqual(next(m for m in d["metrics"] if m["key"] == "likes")["value"], 214)
        self.assertEqual(self.rig.get("/api/media/123456")[0], 502)       # unknown post: Instagram's answer, explained

    def test_followers_are_recorded_once_a_day(self):
        self.sim.user["followers_count"] = 1900
        self.agent.due.clear()
        self.rig.tick()
        rows = self.agent.db.q("SELECT day, followers FROM snapshots")
        self.assertEqual([(r["day"], r["followers"]) for r in rows], [(time.strftime("%Y-%m-%d"), 1900)])
        self.agent.db.x("INSERT INTO snapshots (day, ts, followers, follows, media_count) VALUES ('2026-01-01', 0, 1700, 300, 9)")
        d = self.rig.ok("GET", "/api/insights")
        self.assertEqual((d["followers"]["delta"], len(d["followers"]["series"])), (200, 2))

    def test_evening_report(self):
        self.rig.ok("POST", "/api/settings", {"auto": {"daily_report": True}, "telegram": {"token": "1:a", "chat_id": "9"}})
        real = time.localtime
        try:
            ia.time.localtime = lambda *a: real(*a) if a else time.struct_time((2026, 11, 13, 20, 59, 0, 4, 317, 0))
            self.agent.daily_job()
            self.assertEqual(self.sim.telegram, [])                       # not before nine in the evening
            ia.time.localtime = lambda *a: real(*a) if a else time.struct_time((2026, 11, 13, 21, 0, 0, 4, 317, 0))
            self.agent.daily_job()
            self.agent.daily_job()
        finally:
            ia.time.localtime = real
        self.assertEqual(len(self.sim.telegram), 1)                       # once a day
        text = self.sim.telegram[0]["text"]
        self.assertIn("@demo.cafe", text)
        self.assertIn("۱٬۸۴۰", text)
        self.assertIn("۵ کامنت و ۲ دایرکت", text)
        self.assertEqual(self.sim.telegram[0]["chat_id"], "9")


class AssistantOfflineTests(Base):
    def test_captions_hashtags_ideas_without_any_service(self):
        self.rig.ok("POST", "/api/settings", {"brand": {"hashtags": "کافه_دمو، #قهوه_تازه"}})
        c = self.rig.ok("POST", "/api/ai/captions", {"topic": "لاتهٔ پاییزی", "kind": "reel"})
        self.assertEqual((c["source"], len(c["items"])), ("offline", 3))
        self.assertTrue(all("لاتهٔ پاییزی" in x and "#کافه_دمو" in x for x in c["items"]))
        self.assertTrue(all(len(x) <= 2200 for x in c["items"]))
        h = self.rig.ok("POST", "/api/ai/hashtags", {"topic": "قهوه دمی صبحگاهی"})
        self.assertEqual(h["items"][:2], ["#کافه_دمو", "#قهوه_تازه"])
        self.assertIn("#قهوه", h["items"])
        self.assertEqual(len(h["items"]), len(set(h["items"])))
        self.assertTrue(all(re.fullmatch(r"#[^\s#]+", t) for t in h["items"]))
        i = self.rig.ok("POST", "/api/ai/ideas", {"count": 4})
        self.assertEqual((i["source"], len(i["items"])), ("offline", 4))
        self.assertEqual(self.rig.post("/api/ai/captions", {"topic": "  "})[0], 400)

    def test_plan_becomes_drafts(self):
        out = self.rig.ok("POST", "/api/ai/plan", {"count": 3})
        self.assertEqual(len(out["items"]), 3)
        drafts = self.rig.ok("GET", "/api/posts?group=drafts")["items"]
        self.assertEqual(len(drafts), 3)
        self.assertTrue(all(d["status"] == "draft" and "#" in d["caption"] and not d["media"] for d in drafts))
        self.rig.tick(2)
        self.assertEqual(self.rig.feed_count(), 10)                       # a plan publishes nothing

    def test_chat_answers_with_the_page_facts(self):
        self.rig.tick()
        out = self.rig.ok("POST", "/api/chat", {"messages": [{"role": "user", "content": "وضعیت پیج چطوره؟"}]})
        self.assertEqual(out["source"], "offline")
        for needle in ("۱٬۸۴۰", "کامنت منتظر پاسخ: ۵", "دایرکت منتظر پاسخ: ۲"):
            self.assertIn(needle, out["text"])
        for bad in ({}, {"messages": []}, {"messages": "سلام"}, {"messages": ["سلام"]}, {"messages": [{"role": "assistant", "content": "x"}]}):
            self.assertEqual(self.rig.post("/api/chat", bad)[0], 400, bad)

    def test_status_says_the_assistant_is_off(self):
        self.assertEqual(self.rig.ok("GET", "/api/status")["ai"], "off")


class AssistantOnlineTests(unittest.TestCase):
    def setUp(self):
        self.ai = FakeAI()
        self.rig = Rig(env={"AGENT_AI_URL": self.ai.url})

    def tearDown(self):
        self.rig.close()
        self.ai.close()

    def test_captions_are_split_and_cleaned(self):
        self.ai.answer = "<think>باید سه کپشن بنویسم</think>\n1. کوتاه ☕️ #قهوه\n===\nکپشن ۲: معمولی‌تر #کافه\n\n===\n\n۳) داستانی و بلند\nدر دو خط #پاییز\n"
        out = self.rig.ok("POST", "/api/ai/captions", {"topic": "لاته"})
        self.assertEqual(out["source"], "ai")
        self.assertEqual(out["items"], ["کوتاه ☕️ #قهوه", "معمولی‌تر #کافه", "داستانی و بلند\nدر دو خط #پاییز"])
        asked = self.ai.asked[0]
        self.assertEqual(asked["path"], "/v1/chat/completions")
        self.assertIn("لاته", asked["body"]["messages"][-1]["content"])
        self.assertIsNone(asked["auth"])

    def test_hashtags_and_ideas(self):
        self.ai.answer = "حتماً! #قهوه، #کافه #coffee #قهوه #لاته_آرت"
        self.assertEqual(self.rig.ok("POST", "/api/ai/hashtags", {"topic": "قهوه"}),
                         {"items": ["#قهوه", "#کافه", "#coffee", "#لاته_آرت"], "source": "ai"})
        self.ai.answer = "- پشت‌صحنهٔ برشته‌کاری قهوه\n2. معرفی باریستای ماه\n\n• نظرسنجی طعم جدید\nباشه"
        self.assertEqual(self.rig.ok("POST", "/api/ai/ideas", {"count": 5})["items"],
                         ["پشت‌صحنهٔ برشته‌کاری قهوه", "معرفی باریستای ماه", "نظرسنجی طعم جدید"])

    def test_chat_keeps_the_conversation_and_adds_facts(self):
        self.ai.answer = "پیشنهاد می‌کنم امروز یک ریل بگذاری."
        msgs = [{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام 🌹"}, {"role": "user", "content": "امروز چی پست کنم؟"}]
        out = self.rig.ok("POST", "/api/chat", {"messages": msgs})
        self.assertEqual(out, {"text": "پیشنهاد می‌کنم امروز یک ریل بگذاری.", "source": "ai"})
        sent = self.ai.asked[0]["body"]["messages"]
        self.assertEqual([m["role"] for m in sent], ["system", "user", "assistant", "user"])
        self.assertIn("دنبال‌کننده: ۱٬۸۴۰", sent[0]["content"])
        self.assertNotIn(ia.SIM_TOKEN, str(sent))

    def test_own_service_with_key_and_model(self):
        self.rig.ok("POST", "/api/settings", {"ai": {"mode": "custom", "url": self.ai.url + "/chat/completions", "key": "sk-test-123", "model": "my-model"}})
        self.assertEqual(self.rig.ok("GET", "/api/status")["ai"], "custom")
        self.rig.ok("POST", "/api/ai/ideas", {"count": 2})
        asked = self.ai.asked[0]
        self.assertEqual((asked["path"], asked["auth"], asked["body"]["model"]), ("/v1/chat/completions", "Bearer sk-test-123", "my-model"))

    def test_switched_off_means_no_calls(self):
        self.rig.ok("POST", "/api/settings", {"ai": {"mode": "off"}})
        self.assertEqual(self.rig.ok("POST", "/api/ai/captions", {"topic": "لاته"})["source"], "offline")
        self.assertEqual(self.ai.asked, [])

    def test_broken_service_falls_back(self):
        for status, answer in ((500, "x"), (200, ""), (200, "<think>فقط فکر</think>")):
            self.ai.status, self.ai.answer = status, answer
            out = self.rig.ok("POST", "/api/ai/captions", {"topic": "لاته"})
            self.assertEqual((out["source"], len(out["items"])), ("offline", 3))
        self.ai.close()                                                   # the service disappears completely
        self.assertEqual(self.rig.ok("POST", "/api/ai/hashtags", {"topic": "لاته"})["source"], "offline")
        self.ai = FakeAI()


class AlertsAndSettingsTests(Base):
    def test_telegram_test_button(self):
        status, body, _ = self.rig.post("/api/telegram/test")
        self.assertEqual(status, 400)
        self.rig.ok("POST", "/api/settings", {"telegram": {"token": "123456:ABC-def", "chat_id": "-100200"}})
        self.rig.ok("POST", "/api/telegram/test")
        self.assertEqual(len(self.sim.telegram), 1)
        self.assertEqual(self.sim.telegram[0]["chat_id"], "-100200")
        self.rig.ok("POST", "/api/settings", {"telegram": {"token_clear": True}})
        self.assertEqual(self.rig.post("/api/telegram/test")[0], 400)

    def test_notifications_badge(self):
        self.assertEqual(self.rig.ok("GET", "/api/status")["counts"]["unseen"], 1)   # "page connected"
        self.agent.note("یک هشدار", "warn", "x")
        self.agent.note("همان هشدار", "warn", "same", dedupe=3600)
        self.agent.note("همان هشدار", "warn", "same", dedupe=3600)                   # not repeated within the hour
        self.assertEqual(self.rig.ok("GET", "/api/status")["counts"]["unseen"], 3)
        items = self.rig.ok("GET", "/api/log?limit=2")["items"]
        self.assertEqual([i["text"] for i in items], ["همان هشدار", "یک هشدار"])
        self.rig.ok("POST", "/api/log/seen")
        self.assertEqual(self.rig.ok("GET", "/api/status")["counts"]["unseen"], 0)

    def test_log_does_not_grow_forever(self):
        for i in range(450):
            self.agent.note("رویداد %d" % i)
        self.assertLessEqual(self.agent.db.val("SELECT COUNT(*) FROM log"), 401)

    def test_rules_from_the_panel(self):
        self.assertEqual([r["enabled"] for r in self.rig.ok("GET", "/api/rules")["items"]], [False, False, False])   # examples, switched off
        r = self.rig.ok("POST", "/api/rules", {"scope": "comment", "name": "", "keywords": "ارسال، پست", "mode": "all", "replies": ["بله 🌹", " ", "ارسال داریم"]})
        self.assertEqual((r["name"], r["keywords"], r["replies"], r["mode"], r["enabled"]), ("ارسال", ["ارسال", "پست"], ["بله 🌹", "ارسال داریم"], "all", True))
        t = self.rig.ok("POST", "/api/rules/test", {"scope": "comment", "text": "ارسال با پست دارید؟"})
        self.assertEqual((t["rule"]["id"], t["spam"]), (r["id"], False))
        self.assertIsNone(self.rig.ok("POST", "/api/rules/test", {"scope": "comment", "text": "ارسال دارید؟"})["rule"])
        self.assertTrue(self.rig.ok("POST", "/api/rules/test", {"text": "فالوور ارزان www.x.xyz"})["spam"])
        r2 = self.rig.ok("POST", "/api/rules/%d" % r["id"], dict(r, enabled=False))
        self.assertFalse(r2["enabled"])
        self.assertIsNone(self.rig.ok("POST", "/api/rules/test", {"scope": "comment", "text": "ارسال با پست دارید؟"})["rule"])
        for bad in ({"scope": "comment", "keywords": "", "replies": ["x"]}, {"scope": "comment", "keywords": "a", "replies": []},
                    {"scope": "story", "keywords": "a", "replies": ["x"]}, {"scope": "dm", "keywords": "a", "replies": [], "hide": True}):
            self.assertEqual(self.rig.post("/api/rules", bad)[0], 400, bad)
        self.rig.ok("DELETE", "/api/rules/%d" % r["id"])
        self.assertNotIn(r["id"], [x["id"] for x in self.rig.ok("GET", "/api/rules")["items"]])

    def test_proxy_setting_is_really_used(self):
        seen = []

        class Proxy(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                seen.append(self.path)
                body = b"<html>blocked by test proxy</html>"
                self.send_response(502)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        try:
            self.rig.ok("POST", "/api/settings", {"network": {"proxy": "127.0.0.1:%d" % srv.server_address[1]}})
            status, body, _ = self.rig.post("/api/comments/sync")
            self.assertEqual((status, body["kind"]), (502, "transient"))
            self.assertTrue(seen and seen[0].startswith("http://127.0.0.1:%d/_sim/ig/" % self.rig.app.port), seen)
            self.assertFalse(self.agent.ig.acct.get("invalid"))           # a bad proxy is not a bad token
            self.rig.ok("POST", "/api/settings", {"network": {"proxy": ""}})
            self.assertEqual(self.rig.post("/api/comments/sync")[0], 200)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_network_down_is_reported_once_not_every_minute(self):
        real = self.agent.graph.http

        def down(*a, **kw):
            raise ia.GraphError("network: unreachable", kind="network")

        self.agent.graph.http = down
        try:
            for _ in range(8):
                self.rig.tick()
        finally:
            self.agent.graph.http = real
        warns = [n for n in self.notes("warn") if "ارتباط با اینستاگرام" in n]
        self.assertEqual(len(warns), 1)
        self.assertFalse(self.agent.ig.acct.get("invalid"))
        self.rig.tick()
        self.assertEqual(self.rig.ok("GET", "/api/status")["counts"]["open_comments"], 5)   # and it recovers alone


class RestartTests(unittest.TestCase):
    def test_everything_survives_a_restart(self):
        rig = Rig(auth=True)
        key = rig.app.web.key
        rig.cookie = rig.post("/api/login", {"key": key})[2]["Set-Cookie"].split(";")[0]
        rig.tick()
        rig.ok("POST", "/api/settings", {"auto": {"comment_reply": True}, "brand": {"about": "کافهٔ ما"}})
        rule = rig.ok("POST", "/api/rules", {"scope": "comment", "keywords": "قیمت", "replies": ["سلام"]})
        post = rig.new_post(action="schedule", scheduled_at=time.time() + 7200, caption="فردا")
        rig.ok("POST", "/api/comments/%s/dismiss" % next(c["id"] for c in rig.sim.comments.values() if "قیمت لاته" in c["text"]))
        since = rig.agent.settings.get("since.comment_reply")
        data_dir, tmp, cookie = rig.app.cfg.data_dir, rig.tmp, rig.cookie
        rig.app.stop()
        try:
            app = ia.App(["--port", "0", "--no-browser", "--data", data_dir], {"AGENT_QUIET": "1", "HOME": tmp, "AGENT_SIM": "1", "AGENT_NO_LOOP": "1"})
            app.start()
            try:
                self.assertEqual(app.web.key, key)
                again = Rig.__new__(Rig)
                again.base, again.cookie = "http://127.0.0.1:%d" % app.port, cookie
                st = again.ok("GET", "/api/status")                       # the old login is still good
                self.assertTrue(st["connected"])
                self.assertEqual((st["account"]["username"], st["auto"]["comment_reply"], st["counts"]["scheduled"]), ("demo.cafe", True, 1))
                self.assertEqual(st["next_post"]["id"], post["id"])
                self.assertEqual(st["counts"]["open_comments"], 4)
                self.assertEqual(app.agent.settings.get("since.comment_reply"), since)   # "from now on" is not moved by a restart
                self.assertIn(rule["id"], [r["id"] for r in again.ok("GET", "/api/rules")["items"]])
                self.assertEqual(again.get(post["media"][0]["preview"])[0], 200)
            finally:
                app.stop()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_show_key_and_version(self):
        tmp = tempfile.mkdtemp(prefix="ia-cli-")
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ia.main(["--show-key", "--data", os.path.join(tmp, "d")])
            key = out.getvalue().strip()
            self.assertEqual(code, 0)
            self.assertRegex(key, r"^[A-HJ-NP-Z2-9]{5}-[A-HJ-NP-Z2-9]{5}$")
            out2 = io.StringIO()
            with contextlib.redirect_stdout(out2):
                ia.main(["--show-key", "--data", os.path.join(tmp, "d")])
            self.assertEqual(out2.getvalue().strip(), key)                # the same key every time
            out3 = io.StringIO()
            with contextlib.redirect_stdout(out3), self.assertRaises(SystemExit) as stop:
                ia.main(["--version"])
            self.assertEqual((stop.exception.code, ia.VERSION in out3.getvalue()), (0, True))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RealProcessTests(unittest.TestCase):
    """The file exactly as a user starts it: `python insta_agent.py --demo`."""

    def test_demo_from_the_command_line(self):
        tmp = tempfile.mkdtemp(prefix="ia-proc-")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENT_", "IG_", "FB_", "TELEGRAM_")) and k != "PORT"}
        env.update(HOME=tmp, PYTHONIOENCODING="utf-8", AGENT_TICK_SEC="0.2")
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "insta_agent.py"), "--demo", "--port", "0", "--no-browser"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=tmp)
        try:
            link, lines = None, []
            end = time.time() + 20
            while time.time() < end and link is None:
                line = proc.stdout.readline().decode("utf-8", "replace")
                if not line:
                    break
                lines.append(line)
                m = re.search(r"Panel : (http://127\.0\.0\.1:\d+/\?k=\S+)", line)
                if m:
                    link = m.group(1)
            self.assertIsNotNone(link, "".join(lines))
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor())
            page = opener.open(link, timeout=10)                          # follows the redirect with the fresh cookie
            self.assertEqual(page.geturl().split("?")[0].rstrip("/"), link.split("/?")[0])
            self.assertNotIn("?k=", page.geturl())
            self.assertIn("ایجنت اینستاگرام", page.read().decode("utf-8"))
            st = ia.jload(opener.open(link.split("/?")[0] + "/api/status", timeout=10).read().decode("utf-8"))
            self.assertTrue(st["demo"] and st["connected"])
            self.assertTrue(os.path.isdir(os.path.join(tmp, ".insta_agent_demo")))
            self.assertFalse(os.path.exists(os.path.join(tmp, ".insta_agent")))   # the demo never touches real data
            if os.name == "posix":
                proc.send_signal(signal.SIGTERM)
                self.assertEqual(proc.wait(timeout=20), 0)                # a clean stop, not a crash
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
