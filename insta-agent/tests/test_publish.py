"""Publishing: the four kinds, scheduling, and above all "never twice, never silently lost"."""
import http.server
import os
import re
import sys
import threading
import time
import unittest

from harness import Rig, ia, jpeg, mp4


class Base(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.sim, self.pub = self.rig.sim, self.rig.agent.publisher
        self.feed0 = self.rig.feed_count()

    def tearDown(self):
        self.rig.close()

    def calls(self, pattern, method="POST"):
        return [c for c in self.sim.calls if c[0] == method and re.search(pattern, c[1])]

    def publishes(self):
        return len(self.calls(r"/media_publish$"))

    def due(self, pid, seconds_ago=1):
        """Makes a scheduled post due (as if its time had come)."""
        self.rig.agent.db.x("UPDATE posts SET scheduled_at=? WHERE id=?", (time.time() - seconds_ago, pid))

    def state(self, pid):
        return ia.jload(self.pub.raw(pid)["state"], {})

    def until(self, pid, test, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            self.pub.tick()
            if test(self.rig.post_status(pid)):
                return self.rig.post_status(pid)
            time.sleep(0.01)
        self.fail("state not reached: %r" % (self.rig.post_status(pid),))


class KindsTests(Base):
    def test_image_now(self):
        p = self.rig.new_post(caption="لاتهٔ امروز ☕️ #کافه")
        self.assertEqual((p["status"], p["manual"]), ("scheduled", True))
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published", done)
        top = self.sim.media[0]
        self.assertEqual((top["caption"], top["media_type"], top["media_product_type"]), ("لاتهٔ امروز ☕️ #کافه", "IMAGE", "FEED"))
        self.assertEqual(done["ig_media_id"], top["id"])
        self.assertTrue(done["permalink"].startswith("https://www.instagram.com/p/"))
        self.assertEqual((self.rig.feed_count(), self.publishes()), (self.feed0 + 1, 1))
        # Instagram fetched the file from the media-only port, not from the panel
        self.assertEqual(self.sim.fetched, ["%s/m/%s.jpg" % (self.rig.media_base, done["media"][0]["file"])])
        self.assertEqual(self.rig.ok("GET", "/api/posts?group=published")["items"][0]["id"], p["id"])
        self.assertIn("پست منتشر شد", self.rig.ok("GET", "/api/log")["items"][0]["text"])

    def test_reel_waits_for_processing(self):
        self.sim.video_seconds = 0.3
        p = self.rig.new_post("reel", caption="ریل تازه 🎬", opts={"share_to_feed": False})
        waiting = self.until(p["id"], lambda x: self.state(p["id"]).get("stage") == "wait")
        self.assertEqual(waiting["status"], "publishing")
        self.assertIn("پردازش", waiting["progress"])
        self.assertEqual(self.publishes(), 0)                              # not before Instagram says FINISHED
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published", done)
        top = self.sim.media[0]
        self.assertEqual((top["media_type"], top["media_product_type"], top["caption"]), ("VIDEO", "REELS", "ریل تازه 🎬"))
        sent = self.calls(r"/media$")[0][2]
        self.assertEqual((sent["media_type"], sent["share_to_feed"]), ("REELS", "false"))
        self.assertTrue(sent["video_url"].endswith(".mp4"))

    def test_carousel(self):
        files = [self.rig.upload(jpeg(1080, 1080, pad=i))["id"] for i in range(3)]
        clip = self.rig.upload(mp4())["id"]
        media = [{"file": f} for f in files] + [{"file": clip}]
        p = self.rig.new_post("carousel", media=media, caption="ورق بزنید 🍰")
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published", done)
        top = self.sim.media[0]
        self.assertEqual((top["media_type"], top["caption"]), ("CAROUSEL_ALBUM", "ورق بزنید 🍰"))
        made = [c[2] for c in self.calls(r"/media$")]
        self.assertEqual(len(made), 5)                                     # four children and the album itself
        self.assertTrue(all(c.get("is_carousel_item") == "true" and "caption" not in c for c in made[:4]))
        self.assertEqual((made[3]["media_type"], made[4]["media_type"]), ("VIDEO", "CAROUSEL"))
        self.assertEqual(len(made[4]["children"].split(",")), 4)
        self.assertEqual((self.rig.feed_count(), self.publishes()), (self.feed0 + 1, 1))

    def test_story_image_and_video(self):
        tall = self.rig.upload(jpeg(1080, 1920))["id"]                     # 9:16 is fine for a story
        p = self.rig.new_post("story", media=[{"file": tall}], caption="این متن فرستاده نمی‌شود")
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual((len(self.sim.stories), self.rig.feed_count()), (1, self.feed0))
        sent = self.calls(r"/media$")[0][2]
        self.assertEqual(sent["media_type"], "STORIES")
        self.assertNotIn("caption", sent)
        v = self.rig.new_post("story", media=[{"file": self.rig.upload(mp4())["id"]}])
        self.assertEqual(self.rig.run_post(v["id"])["status"], "published")
        self.assertEqual((len(self.sim.stories), self.sim.stories[0]["media_type"]), (2, "VIDEO"))

    def test_options(self):
        p = self.rig.new_post(caption="با گزینه‌ها", opts={"alt_text": "یک فنجان قهوه روی میز چوبی", "first_comment": "#قهوه #کافه",
                                                         "comments_off": True})
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published")
        self.assertEqual(self.calls(r"/media$")[0][2]["alt_text"], "یک فنجان قهوه روی میز چوبی")
        mid = done["ig_media_id"]
        mine = [c for c in self.sim.comments.values() if c["media_id"] == mid]
        self.assertEqual([(c["text"], c["username"]) for c in mine], [("#قهوه #کافه", "demo.cafe")])
        self.assertFalse(self.sim.media[0]["comment_enabled"])

    def test_published_without_its_caption_is_reported(self):
        self.rig.ok("POST", "/api/settings", {"telegram": {"token": "111:abc", "chat_id": "42"}})
        self.sim.config_issue = "CAPTION_NOT_ATTACHED"
        p = self.rig.new_post(caption="متن پست")
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], self.rig.feed_count()), ("published", self.feed0 + 1))
        self.assertEqual(self.sim.media[0]["caption"], "")
        notes = [n for n in self.rig.ok("GET", "/api/log")["items"] if n["level"] == "alert"]
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("کپشن را روی آن نگذاشت", notes[0]["text"])
        self.assertTrue(any("کپشن را روی آن نگذاشت" in m["text"] for m in self.sim.telegram), self.sim.telegram)
        self.sim.config_issue = ""
        q = self.rig.new_post(caption="متن دوم")                          # and nothing is said when all is well
        self.rig.run_post(q["id"])
        self.assertEqual(len([n for n in self.rig.ok("GET", "/api/log")["items"] if n["level"] == "alert"]), 1)

    def test_refused_extra_does_not_stop_the_post(self):
        self.sim.refused_params = {"share_to_feed", "alt_text"}
        clip = self.rig.upload(mp4())["id"]
        reel = self.rig.ok("POST", "/api/posts", {"kind": "reel", "media": [{"file": clip}], "caption": "ریل", "action": "now"})
        self.assertEqual(self.rig.run_post(reel["id"])["status"], "published")
        img = self.rig.new_post(caption="با متن جایگزین", opts={"alt_text": "یک فنجان قهوه"})
        self.assertEqual(self.rig.run_post(img["id"])["status"], "published")
        self.assertEqual(self.rig.feed_count(), self.feed0 + 2)
        self.assertEqual([m["caption"] for m in self.sim.media[:2]], ["با متن جایگزین", "ریل"])
        warns = [n["text"] for n in self.rig.ok("GET", "/api/log")["items"] if n["level"] == "warn"]
        self.assertEqual(len(warns), 2, warns)
        self.assertTrue(any("نمایش ریل در صفحهٔ اصلی" in w for w in warns) and any("متن جایگزین عکس" in w for w in warns), warns)
        sent = [c[2] for c in self.calls(r"/media$")]
        self.assertEqual([("share_to_feed" in x, "alt_text" in x) for x in sent],
                         [(True, False), (False, False), (False, True), (False, False)])    # each: once with, once without

    def test_refusal_that_is_not_about_an_extra_still_fails(self):
        self.sim.refused_params = {"image_url"}
        p = self.rig.new_post(caption="x", opts={"alt_text": "توضیح"})
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], self.rig.feed_count()), ("failed", self.feed0))
        self.assertIn("image_url", done["error"])
        self.assertEqual([n for n in self.rig.ok("GET", "/api/log")["items"] if n["level"] == "warn"], [])

    def test_first_comment_failure_does_not_undo_the_post(self):
        self.sim.fail(r"/comments$", code=100, method="POST")
        p = self.rig.new_post(opts={"first_comment": "سلام"})
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], self.rig.feed_count()), ("published", self.feed0 + 1))
        notes = [n["text"] for n in self.rig.ok("GET", "/api/log")["items"]]
        self.assertTrue(any("تنظیم کامنت" in n for n in notes), notes)

    def test_media_by_direct_link(self):
        f = self.rig.upload(jpeg())
        url = "%s/m/%s.jpg" % (self.rig.media_base, f["id"])
        p = self.rig.new_post(media=[{"url": url}])
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.sim.fetched, [url])


class RulesOfThePlatformTests(Base):
    def refuse(self, **body):
        status, out, _ = self.rig.post("/api/posts", body)
        self.assertEqual(status, 400, out)
        self.assertTrue(out["error"])
        return out["error"]

    def test_wrong_combinations_are_refused_before_anything_is_sent(self):
        img, clip = self.rig.upload(jpeg())["id"], self.rig.upload(mp4())["id"]
        strip = self.rig.upload(jpeg(500, 2000))["id"]
        wide = self.rig.upload(jpeg(2000, 500))["id"]
        one = [{"file": img}]
        self.refuse(kind="image", media=[{"file": clip}], action="now")
        self.refuse(kind="image", media=one + one, action="now")
        self.refuse(kind="image", media=[], action="now")
        self.refuse(kind="reel", media=one, action="now")
        self.refuse(kind="carousel", media=one, action="now")
        self.refuse(kind="carousel", media=one * 21, action="now")
        self.refuse(kind="carousel", media=one * 21, action="draft")
        self.refuse(kind="story", media=one + one, action="now")
        self.refuse(kind="image", media=[{"file": strip}], action="now")
        self.refuse(kind="image", media=[{"file": wide}], action="now")
        self.refuse(kind="image", media=one, action="now", caption="آ" * 2201)
        self.assertIn("حداکثر ۳۰ هشتگ", self.refuse(kind="image", media=one, action="now", caption="سلام " + " ".join("#t%d" % i for i in range(31))))
        self.refuse(kind="image", media=one, action="now", caption=" ".join("@u%d" % i for i in range(21)))
        self.refuse(kind="image", media=[{"url": "http://example.com/a.jpg"}], action="now")
        self.refuse(kind="image", media=[{"url": "https://example.com/عکس.jpg"}], action="now")
        self.refuse(kind="image", media=[{"file": "0" * 24}], action="now")
        self.refuse(kind="poll", media=one, action="now")
        self.refuse(kind="image", media=one, action="schedule", scheduled_at=time.time() - 60)
        self.refuse(kind="image", media=one, action="schedule")
        self.refuse(kind="image", media=one, action="explode")
        self.assertEqual(self.sim.calls, [c for c in self.sim.calls if c[0] == "GET"])   # nothing was sent to Instagram
        self.assertEqual(self.rig.ok("GET", "/api/posts")["items"], [])

    def test_more_than_five_hashtags_is_the_owners_choice(self):
        img = self.rig.upload(jpeg())["id"]
        post = lambda caption, action="now": self.rig.ok("POST", "/api/posts", {"kind": "image", "media": [{"file": img}],
                                                                              "action": action, "caption": caption})
        twelve = "قهوهٔ تازه ☕️ " + " ".join("#t%d" % i for i in range(12))
        self.assertEqual(self.rig.run_post(post(twelve)["id"])["status"], "published")
        self.assertEqual(self.sim.media[0]["caption"], twelve)             # sent as written: nothing trimmed, nothing refused
        thirty = " ".join("#t%d" % i for i in range(30))
        self.assertEqual(self.rig.run_post(post(thirty)["id"])["status"], "published")
        d = post(thirty + " #t30", "draft")                                # 31 can wait as a draft, but cannot be sent
        self.assertEqual(self.rig.post("/api/posts/%d/publish" % d["id"])[0], 400)
        self.assertEqual(self.rig.post("/api/posts/%d" % d["id"], {"kind": "image", "media": [{"file": img}], "caption": thirty + " #t30",
                                                                 "action": "schedule", "scheduled_at": time.time() + 3600})[0], 400)
        self.assertEqual(self.rig.feed_count(), self.feed0 + 2)
        self.assertEqual([n for n in self.rig.ok("GET", "/api/log")["items"] if n["level"] in ("warn", "alert")], [])

    def test_instagram_refusing_the_hashtags_is_explained(self):
        self.sim.hashtag_cap = 5                                           # Instagram may be stricter than its API reference
        p = self.rig.new_post(caption="سلام " + " ".join("#t%d" % i for i in range(6)))
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], self.rig.feed_count()), ("failed", self.feed0))
        self.assertIn("این تعداد هشتگ را نپذیرفت", done["error"])
        self.assertIn("۵ تا یا کمتر", done["error"])
        self.assertEqual(len(self.calls(r"/media$")), 1)                   # a clear "no" is not sent again and again
        self.rig.tick(2)
        self.assertEqual(len(self.calls(r"/media$")), 1)
        self.rig.ok("POST", "/api/posts/%d" % p["id"], {"kind": "image", "media": p["media"], "caption": "سلام #t0 #t1", "action": "now"})
        self.assertEqual((self.rig.run_post(p["id"])["status"], self.rig.feed_count()), ("published", self.feed0 + 1))
        self.assertEqual(self.sim.media[0]["caption"], "سلام #t0 #t1")

    def test_story_video_has_a_smaller_size_limit(self):
        clip = self.rig.upload(mp4())["id"]
        self.rig.agent.db.x("UPDATE files SET size=? WHERE id=?", (101 * 1024 * 1024, clip))
        self.assertIn("۱۰۰ مگابایت", self.refuse(kind="story", media=[{"file": clip}], action="now"))
        p = self.rig.ok("POST", "/api/posts", {"kind": "reel", "media": [{"file": clip}], "action": "now"})   # fine as a reel
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")

    def test_twenty_items_are_the_most(self):
        img = self.rig.upload(jpeg())["id"]
        p = self.rig.ok("POST", "/api/posts", {"kind": "carousel", "media": [{"file": img}] * 20, "action": "now"})
        self.assertEqual(len(p["media"]), 20)
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(len(self.calls(r"/media$")), 21)

    def test_a_draft_needs_nothing(self):
        p = self.rig.ok("POST", "/api/posts", {"kind": "reel", "caption": "ایدهٔ خام", "media": [], "action": "draft"})
        self.assertEqual(p["status"], "draft")
        status, out, _ = self.rig.post("/api/posts/%d/publish" % p["id"])
        self.assertEqual(status, 400)
        clip = self.rig.upload(mp4())["id"]
        p2 = self.rig.ok("POST", "/api/posts/%d" % p["id"], {"kind": "reel", "caption": "ایدهٔ پخته", "media": [{"file": clip}],
                                                              "action": "now"})
        self.assertEqual(p2["id"], p["id"])
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.sim.media[0]["caption"], "ایدهٔ پخته")


class ScheduleTests(Base):
    def schedule(self, **kw):
        return self.rig.new_post(action="schedule", scheduled_at=time.time() + 3600, **kw)

    def test_waits_for_its_time(self):
        p = self.schedule(caption="برای بعد")
        self.assertEqual((p["status"], p["manual"]), ("scheduled", False))
        self.rig.tick(3)
        self.assertEqual((self.rig.post_status(p["id"])["status"], len(self.calls(r"/media$"))), ("scheduled", 0))
        self.assertEqual(self.rig.ok("GET", "/api/status")["next_post"]["id"], p["id"])
        self.due(p["id"])
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")

    def test_runs_from_the_background_loop(self):
        rig = Rig(loop=True)
        try:
            p = rig.new_post(caption="با حلقهٔ پس‌زمینه")
            end = time.time() + 8
            while time.time() < end and rig.post_status(p["id"])["status"] != "published":
                time.sleep(0.05)
            self.assertEqual(rig.post_status(p["id"])["status"], "published")
        finally:
            rig.close()

    def test_missed_when_the_agent_was_off(self):
        p = self.schedule()
        self.due(p["id"], 7 * 3600)
        self.rig.tick()
        got = self.rig.post_status(p["id"])
        self.assertEqual(got["status"], "missed")
        self.assertTrue(got["error"])
        self.assertEqual(self.rig.feed_count(), self.feed0)
        self.assertEqual(self.rig.ok("GET", "/api/status")["counts"]["failed"], 1)
        self.rig.ok("POST", "/api/posts/%d/publish" % p["id"])           # the owner still wants it
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")

    def test_a_little_late_is_still_published(self):
        p = self.schedule()
        self.due(p["id"], 5 * 3600)
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")

    def test_pause_holds_scheduled_posts_but_not_a_manual_one(self):
        self.rig.ok("POST", "/api/settings", {"autopilot": False})
        held = self.schedule(caption="زمان‌بندی‌شده")
        self.due(held["id"])
        self.rig.tick(3)
        self.assertEqual((self.rig.post_status(held["id"])["status"], self.rig.feed_count()), ("scheduled", self.feed0))
        now_post = self.rig.new_post(caption="همین الان")                 # an explicit tap on "publish" always works
        self.assertEqual(self.rig.run_post(now_post["id"])["status"], "published")
        self.assertEqual(self.rig.post_status(held["id"])["status"], "scheduled")
        self.rig.ok("POST", "/api/settings", {"autopilot": True})
        self.assertEqual(self.rig.run_post(held["id"])["status"], "published")

    def test_own_daily_cap(self):
        self.rig.ok("POST", "/api/settings", {"limits": {"daily_posts": 1}})
        first = self.rig.new_post(caption="اولی")
        self.assertEqual(self.rig.run_post(first["id"])["status"], "published")
        second = self.schedule(caption="دومی")
        self.due(second["id"])
        self.rig.tick(2)
        got = self.rig.post_status(second["id"])
        self.assertEqual(got["status"], "scheduled")
        self.assertIn("سقف روزانه", got["progress"])
        self.assertEqual(self.rig.feed_count(), self.feed0 + 1)
        self.rig.ok("POST", "/api/settings", {"limits": {"daily_posts": 5}})
        self.rig.agent.db.x("UPDATE posts SET next_try_at=0 WHERE id=?", (second["id"],))
        self.assertEqual(self.rig.run_post(second["id"])["status"], "published")

    def test_edit_cancel_duplicate_delete(self):
        p = self.schedule(caption="نسخهٔ اول")
        url = "/api/posts/%d" % p["id"]
        back = self.rig.ok("POST", url + "/cancel")
        self.assertEqual(back["status"], "draft")
        self.assertEqual([x["id"] for x in self.rig.ok("GET", "/api/posts?group=drafts")["items"]], [p["id"]])
        edited = self.rig.ok("POST", url, {"kind": "image", "caption": "نسخهٔ دوم", "media": [{"file": p["media"][0]["file"]}],
                                           "action": "now"})
        self.assertEqual(edited["caption"], "نسخهٔ دوم")
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.sim.media[0]["caption"], "نسخهٔ دوم")
        for path, body in ((url, {"kind": "image", "caption": "x", "media": [], "action": "draft"}), (url + "/cancel", None),
                           (url + "/publish", None)):
            self.assertEqual(self.rig.post(path, body)[0], 400, path)     # a published post is final
        copy = self.rig.ok("POST", url + "/duplicate")
        self.assertEqual((copy["status"], copy["caption"], copy["media"][0]["file"]), ("draft", "نسخهٔ دوم", p["media"][0]["file"]))
        self.assertNotEqual(copy["id"], p["id"])
        self.rig.ok("DELETE", "/api/posts/%d" % copy["id"])
        self.assertEqual(self.rig.get("/api/posts/%d" % copy["id"])[0], 404)
        self.assertEqual(self.rig.feed_count(), self.feed0 + 1)

    def test_suggested_slots_are_free_future_times(self):
        slots = self.rig.ok("GET", "/api/slots")
        self.assertEqual(len(slots["items"]), 6)
        self.assertTrue(all(t > time.time() + 600 for t in slots["items"]))
        self.assertEqual(sorted(slots["items"]), slots["items"])
        taken = slots["items"][0]
        self.rig.new_post(action="schedule", scheduled_at=taken)
        self.assertNotIn(taken, self.rig.ok("GET", "/api/slots")["items"])


class NeverTwiceTests(Base):
    """Instagram has no "undo" for a double post, so every unclear answer is checked on the page itself."""

    def test_lost_answer_is_verified_not_repeated(self):
        self.sim.fail(r"/media_publish$", drop=True)                      # the post goes live, the answer never arrives
        p = self.rig.new_post(caption="فقط یک بار")
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published", done)
        self.assertEqual((self.rig.feed_count(), self.publishes()), (self.feed0 + 1, 1))
        self.assertEqual(done["ig_media_id"], self.sim.media[0]["id"])

    def test_lost_answer_for_a_story(self):
        self.sim.fail(r"/media_publish$", drop=True)
        p = self.rig.new_post("story")
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], len(self.sim.stories), self.publishes()), ("published", 1, 1))

    def test_lost_answer_for_a_carousel(self):
        self.sim.fail(r"/media_publish$", drop=True)
        media = [{"file": self.rig.upload(jpeg(1080, 1080, pad=i))["id"]} for i in range(2)]
        p = self.rig.new_post("carousel", media=media, caption="آلبوم")
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], self.rig.feed_count(), self.publishes()), ("published", self.feed0 + 1, 1))

    def test_server_error_without_publishing_is_sent_again_once(self):
        self.sim.fail(r"/media_publish$", code=1, status=500)             # a real failure: nothing went live
        p = self.rig.new_post(caption="بار دوم موفق")
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published", done)
        self.assertEqual((self.rig.feed_count(), self.publishes()), (self.feed0 + 1, 2))

    def test_garbage_answer_is_treated_like_a_lost_one(self):
        self.sim.fail(r"/media_publish$", drop=True)                      # 502 with an HTML body from a proxy
        p = self.rig.new_post()
        waiting = self.until(p["id"], lambda x: self.state(p["id"]).get("stage") == "verify")
        self.assertEqual(waiting["status"], "publishing")
        self.assertIn("بررسی نتیجه", waiting["progress"])
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.publishes(), 1)

    def test_twin_captions_are_not_confused(self):
        a = self.rig.new_post(caption="")
        self.assertEqual(self.rig.run_post(a["id"])["status"], "published")
        self.sim.fail(r"/media_publish$", code=1, status=500)             # the twin's first try really fails
        b = self.rig.new_post(caption="")
        done = self.rig.run_post(b["id"])
        self.assertEqual(done["status"], "published", done)
        self.assertEqual(self.rig.feed_count(), self.feed0 + 2)           # both exist
        self.assertNotEqual(done["ig_media_id"], self.rig.post_status(a["id"])["ig_media_id"])

    def test_a_crash_right_after_sending_is_picked_up_from_the_database(self):
        self.sim.video_seconds = 0.3
        p = self.rig.new_post("reel", caption="بعد از خاموشی")
        self.until(p["id"], lambda x: self.state(p["id"]).get("stage") == "wait")
        time.sleep(0.35)                                                   # Instagram finishes processing the video
        st = self.state(p["id"])
        # the app wrote "sent", the request reached Instagram, and then the phone died:
        st.update(stage="verify", sent=time.time(), verify_at=0, checks=0)
        self.pub.put(p["id"], st)
        self.sim.publish({"creation_id": st["container"]})
        before = self.publishes()
        reborn = ia.Publisher(self.rig.agent)                              # nothing but the database survives a restart
        for _ in range(50):
            reborn.tick()
            if self.rig.post_status(p["id"])["status"] == "published":
                break
            time.sleep(0.01)
        self.assertEqual(self.rig.post_status(p["id"])["status"], "published")
        self.assertEqual((self.rig.feed_count(), self.publishes()), (self.feed0 + 1, before))

    def test_stopping_is_refused_once_the_request_has_left(self):
        old = ia.PUBLISH_RECHECK_SEC
        ia.PUBLISH_RECHECK_SEC = 60
        try:
            self.sim.fail(r"/media_publish$", drop=True)
            p = self.rig.new_post()
            self.until(p["id"], lambda x: self.state(p["id"]).get("sent"))
            url = "/api/posts/%d" % p["id"]
            self.assertEqual(self.rig.post(url + "/cancel")[0], 400)
            self.assertEqual(self.rig.req("DELETE", url)[0], 400)
            self.assertEqual(self.rig.post(url, {"kind": "image", "caption": "x", "media": [], "action": "draft"})[0], 400)
            self.assertEqual(self.rig.post(url + "/publish")[0], 400)
        finally:
            ia.PUBLISH_RECHECK_SEC = old
        self.rig.agent.db.x("UPDATE posts SET next_try_at=0 WHERE id=?", (p["id"],))
        st = self.state(p["id"])
        st["verify_at"] = 0
        self.pub.put(p["id"], st)
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual((self.rig.feed_count(), self.publishes()), (self.feed0 + 1, 1))

    def test_two_ticks_at_once_publish_once(self):
        self.sim.video_seconds = 0.05
        p = self.rig.new_post("reel")
        threads = [threading.Thread(target=lambda: [self.pub.tick() or time.sleep(0.005) for _ in range(120)]) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.rig.post_status(p["id"])["status"], "published")
        self.assertEqual((self.rig.feed_count(), self.publishes()), (self.feed0 + 1, 1))


class TroubleTests(Base):
    def test_download_failure_is_retried(self):
        self.sim.fail(r"/media$", code=9004, sub=2207052, times=2, method="POST")
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], done["attempts"]), ("published", 2))
        self.assertEqual(self.rig.feed_count(), self.feed0 + 1)

    def test_gives_up_after_all_retries_and_says_why(self):
        self.sim.fail(r"/media$", code=9004, sub=2207052, times=99, method="POST")
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("لینک", done["error"])
        self.assertEqual(len(self.calls(r"/media$")), len(ia.RETRY_BACKOFF) + 1)
        self.assertEqual(self.rig.ok("GET", "/api/log")["items"][0]["level"], "alert")
        self.sim.faults.clear()
        self.rig.ok("POST", "/api/posts/%d/publish" % p["id"])           # "try again" in the panel
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")

    def test_a_file_instagram_rejects_fails_at_once(self):
        p = self.rig.new_post(media=[{"url": self.rig.base + "/_sim/img/1.svg"}])
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], done["attempts"]), ("failed", 0))
        self.assertIn("JPEG", done["error"])
        self.assertEqual(len(self.calls(r"/media$")), 1)

    def test_a_video_instagram_cannot_process(self):
        f = self.rig.upload(jpeg())
        p = self.rig.new_post("reel", media=[{"url": "%s/m/%s.jpg" % (self.rig.media_base, f["id"]), "type": "video"}])
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("Unsupported video format", done["error"])
        self.assertEqual(self.publishes(), 0)

    def test_expired_upload_is_started_again(self):
        self.sim.video_seconds = 0.2
        p = self.rig.new_post("reel", caption="دوباره از اول")
        self.until(p["id"], lambda x: self.state(p["id"]).get("container"))
        self.sim.containers[self.state(p["id"])["container"]]["expired"] = True
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published", done)
        self.assertEqual((len(self.calls(r"/media$")), self.publishes(), self.rig.feed_count()), (2, 1, self.feed0 + 1))

    def test_expired_at_the_moment_of_publishing(self):
        self.sim.fail(r"/media_publish$", code=24, sub=2207008)
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "published", done)
        self.assertEqual((len(self.calls(r"/media$")), self.rig.feed_count()), (2, self.feed0 + 1))

    def test_an_upload_that_keeps_expiring_stops(self):
        self.sim.fail(r"/media_publish$", code=24, sub=2207008, times=99)
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], self.rig.feed_count()), ("failed", self.feed0))
        self.assertLessEqual(len(self.calls(r"/media$")), 3)

    def test_not_ready_answer_just_waits(self):
        self.sim.fail(r"/media_publish$", code=9007, sub=2207027, times=2)
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], done["attempts"], self.publishes()), ("published", 0, 3))
        self.assertEqual(self.rig.feed_count(), self.feed0 + 1)

    def test_instagram_quota_full(self):
        self.sim.quota_used = self.sim.quota_total
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("سقف انتشار", done["error"])
        self.assertEqual(self.rig.feed_count(), self.feed0)
        self.sim.quota_used = 0
        self.rig.ok("POST", "/api/posts/%d/publish" % p["id"])
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.rig.feed_count(), self.feed0 + 1)

    def test_quota_frees_up_while_waiting(self):
        self.sim.quota_used = self.sim.quota_total
        p = self.rig.new_post()
        self.until(p["id"], lambda x: x["attempts"] >= 2)
        self.sim.quota_used = 0
        done = self.rig.run_post(p["id"])
        self.assertEqual((done["status"], self.rig.feed_count()), ("published", self.feed0 + 1))
        self.assertEqual(len(self.calls(r"/media$")), 1)                  # the finished upload was reused, not sent again

    def test_dead_token_stops_everything_and_tells_the_owner(self):
        self.rig.ok("POST", "/api/settings", {"telegram": {"token": "111:abc", "chat_id": "42"}})
        self.sim.fail(r"/media$", code=190, sub=460, method="POST", message="session invalidated: password changed")
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "failed")
        st = self.rig.ok("GET", "/api/status")
        self.assertIn("رمز پیج عوض شده", st["account"]["invalid"])
        self.assertTrue(any("اتصال پیج قطع شد" in m["text"] for m in self.sim.telegram), self.sim.telegram)
        n = len(self.sim.calls)
        self.rig.tick(3)
        self.assertEqual(len(self.sim.calls), n)                          # no hammering with a dead token
        self.rig.ok("POST", "/api/connect", {"token": ia.SIM_TOKEN})
        self.assertEqual(self.rig.ok("GET", "/api/status")["account"]["invalid"], "")
        self.rig.ok("POST", "/api/posts/%d/publish" % p["id"])
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")

    def test_rate_limit_pauses_the_agent(self):
        self.sim.fail(r"/media$", code=4, method="POST", message="Application request limit reached")
        p = self.rig.new_post()
        self.until(p["id"], lambda x: x["attempts"] == 1)
        self.assertTrue(self.rig.ok("GET", "/api/status")["busy"])
        n = len(self.calls(r"/comments$", "GET"))
        self.rig.tick(2)
        self.assertEqual(len(self.calls(r"/comments$", "GET")), n)        # reading is paused…
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")   # …but the post still goes out

    def test_file_removed_from_the_phone(self):
        p = self.rig.new_post(action="schedule", scheduled_at=time.time() + 3600)
        f = self.rig.agent.store.get(p["media"][0]["file"])
        os.remove(self.rig.agent.store.path(f))
        self.due(p["id"])
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("فایل", done["error"])
        self.assertEqual(len(self.calls(r"/media$")), 0)

    def test_waiting_post_can_be_stopped_and_sent_later(self):
        old = ia.RETRY_BACKOFF
        ia.RETRY_BACKOFF = [600] * 5
        try:
            self.sim.fail(r"/media$", code=9004, sub=2207052, method="POST")
            p = self.rig.new_post(caption="صبر کن")
            waiting = self.until(p["id"], lambda x: x["attempts"] == 1)
            self.assertEqual(waiting["status"], "publishing")
            self.assertIn("تلاش دوباره", waiting["progress"])
            back = self.rig.ok("POST", "/api/posts/%d/cancel" % p["id"])
            self.assertEqual((back["status"], back["attempts"], back["next_try_at"]), ("draft", 0, 0))
            self.rig.tick(3)
            self.assertEqual(self.rig.feed_count(), self.feed0)
        finally:
            ia.RETRY_BACKOFF = old
        self.rig.ok("POST", "/api/posts/%d/publish" % p["id"])
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.rig.feed_count(), self.feed0 + 1)

    def test_token_renewed_during_a_call(self):
        graph, real = self.rig.agent.graph, self.rig.agent.graph.http
        fresh = "IGAA" + "n" * 40
        state = {"n": 0}

        def http(method, url, *a, **kw):
            state["n"] += 1
            if state["n"] == 1:                                           # the weekly renewal finishes while this call is under way
                self.sim.token = fresh
                graph.token = fresh
            return real(method, url, *a, **kw)

        graph.http = http
        try:
            items = self.rig.agent.ig.media(5)
        finally:
            graph.http = real
        self.assertEqual((len(items), state["n"]), (5, 2))
        self.assertFalse(self.rig.agent.ig.acct.get("invalid"))


class PublicLinkTests(Base):
    def test_fixed_public_address(self):
        self.rig.ok("POST", "/api/settings", {"media": {"method": "public", "public_url": self.rig.media_base + "/"}})
        p = self.rig.new_post()
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.sim.fetched, ["%s/m/%s.jpg" % (self.rig.media_base, p["media"][0]["file"])])

    def test_no_way_to_make_a_link_is_explained(self):
        self.rig.agent.store.tunnel.available = lambda: False
        self.rig.ok("POST", "/api/settings", {"media": {"method": "tunnel"}})
        p = self.rig.new_post()
        done = self.rig.run_post(p["id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("cloudflared", done["error"])
        self.assertEqual(len(self.calls(r"/media$")), 0)

    def test_tunnel_that_never_comes_up(self):
        rig = Rig(env={"AGENT_TUNNEL_CMD": "%s -c \"import time; time.sleep(60)\"" % sys.executable})
        old = ia.LINK_WAIT_SEC
        try:
            rig.ok("POST", "/api/settings", {"media": {"method": "tunnel"}})
            p = rig.new_post()
            rig.agent.publisher.tick()
            waiting = rig.post_status(p["id"])
            self.assertEqual(waiting["status"], "publishing")
            self.assertIn("لینک عمومی", waiting["progress"])
            proc = rig.agent.store.tunnel.proc
            self.assertIsNone(proc.poll())
            ia.LINK_WAIT_SEC = -1
            rig.agent.db.x("UPDATE posts SET next_try_at=0 WHERE id=?", (p["id"],))
            done = rig.run_post(p["id"])
            self.assertEqual(done["status"], "failed")
            self.assertIn("لینک عمومی", done["error"])
        finally:
            ia.LINK_WAIT_SEC = old
            rig.close()
        self.assertIsNotNone(proc.poll())                                  # the helper program is not left running

    def test_tunnel_link_is_used_once_it_answers(self):
        fake = "https://quick-test-tunnel.trycloudflare.com"
        script = "import sys, time; sys.stderr.write('INF |  %s  |\\n'); sys.stderr.flush(); time.sleep(60)" % fake
        rig = Rig(env={"AGENT_TUNNEL_CMD": "%s -c \"%s\"" % (sys.executable, script)})
        try:
            rig.ok("POST", "/api/settings", {"media": {"method": "tunnel"}})
            graph, real_http, real_fetch = rig.agent.graph, rig.agent.graph.http, rig.sim.fetch
            # the outside world is not reachable in tests: the tunnel's public name is mapped onto the media port by hand
            graph.http = lambda m, url, *a, **kw: real_http(m, url.replace(fake, rig.media_base), *a, **kw)
            seen = []
            rig.sim.fetch = lambda url: (seen.append(url), real_fetch(url.replace(fake, rig.media_base)))[1]
            p = rig.new_post()
            done = rig.run_post(p["id"], timeout=10)
            self.assertEqual(done["status"], "published", done)
            self.assertEqual(seen, ["%s/m/%s.jpg" % (fake, p["media"][0]["file"])])
            self.assertTrue(rig.ok("GET", "/api/status")["media"]["tunnel_up"])
        finally:
            rig.close()

    def test_temporary_host(self):
        store = {}

        class Host(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
                parts = body.split(b"--" + boundary)
                fields = {}
                for part in parts:
                    head, _, data = part.partition(b"\r\n\r\n")
                    m = re.search(rb'name="([^"]+)"', head)
                    if m:
                        fields[m.group(1).decode()] = data[:-2]
                store["fields"] = {k: v for k, v in fields.items() if k != "fileToUpload"}
                store["blob"] = fields["fileToUpload"]
                out = ("http://127.0.0.1:%d/files/abc.jpg\n" % self.server.server_address[1]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(store["blob"])))
                self.end_headers()
                self.wfile.write(store["blob"])

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Host)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        rig = Rig(env={"AGENT_TEMP_HOST": "http://127.0.0.1:%d/api" % srv.server_address[1]})
        try:
            rig.ok("POST", "/api/settings", {"media": {"method": "temp"}})
            data = jpeg(1080, 1080, pad=777)
            f = rig.upload(data)
            p = rig.new_post(media=[{"file": f["id"]}])
            done = rig.run_post(p["id"])
            self.assertEqual(done["status"], "published", done)
            self.assertEqual(store["blob"], data)
            self.assertEqual(store["fields"], {"reqtype": b"fileupload", "time": b"1h"})
            self.assertEqual(rig.sim.fetched, ["http://127.0.0.1:%d/files/abc.jpg" % srv.server_address[1]])
            again = rig.new_post(media=[{"file": f["id"]}], caption="همان فایل")
            self.assertEqual(rig.run_post(again["id"])["status"], "published")
            self.assertEqual(len(rig.sim.fetched), 2)                      # the one-hour link is reused, not uploaded twice
        finally:
            rig.close()
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
