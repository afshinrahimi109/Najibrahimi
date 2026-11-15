"""Posting by hand (no page connected) and the studio that turns an idea into words and pictures."""
import collections
import hashlib
import json
import os
import shutil
import time
import unittest
import urllib.parse

from harness import Rig, ia, jpeg, mp4

ia.HORDE_POLL = 0.01
ia.GRACE = 0.05

WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01" + b"\x00" * 200

PLAN = {
    "caption": "لاتهٔ پاییزی تا آخر هفته ۲۰٪ تخفیف دارد ☕️ منتظرتان هستیم. #نباید_بماند",
    "hashtags": ["#لاته", "کافه", "#پاییز", "#قهوه تازه", "#لاته", "#a", "#b"],
    "headline": "لاتهٔ پاییزی با ۲۰٪ تخفیف",
    "sub": "فقط تا آخر هفته",
    "image": "close-up of a steaming latte with autumn leaves on a wooden table, natural light",
    "scenes": [{"text": "صبح با لاتهٔ تازه", "image": "hand pouring latte into a mug, soft morning light"},
               {"text": "۲۰٪ تخفیف", "image": "coffee cup with autumn leaves in the background"},
               {"text": "تا آخر هفته منتظرتیم", "image": "cozy cafe corner with a latte and a notebook"}],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(connect=False)
        self.sim = self.rig.sim
        self.addCleanup(self.rig.close)
        self.rig.ok("POST", "/api/settings", {"manual": True})

    def text_ai(self, answer):
        """Points the assistant at the simulated free text service."""
        self.rig.agent.ai.FREE_URL = self.rig.base + "/_sim/ai/ptxt/openai"
        self.sim.ai_text = answer if callable(answer) or isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)

    def calls(self, service, tail=""):
        return [c for c in self.sim.ai_calls if c[0] == service and c[2].startswith(tail)]

    def wait(self, job, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            job = self.rig.ok("GET", "/api/studio/job/" + job["id"])
            if job["status"] != "running":
                return job
            time.sleep(0.02)
        self.fail("the job did not finish: %s" % job)

    def make(self, **body):
        return self.wait(self.rig.ok("POST", "/api/studio/make", body))


class HandTests(Base):
    def post(self, action="draft", kind="image", data=None, **extra):
        media = [] if data is False else [{"file": self.rig.upload(data or (mp4() if kind == "reel" else jpeg()))["id"]}]
        body = dict(kind=kind, caption="سلام دنیا", media=media, action=action)
        body.update(extra)
        return self.rig.req("POST", "/api/posts", body)

    def test_without_a_page_the_owner_must_choose_to_post_by_hand(self):
        self.rig.ok("POST", "/api/settings", {"manual": False})
        st = self.rig.ok("GET", "/api/status")
        self.assertEqual((st["connected"], st["manual"]), (False, False))
        status, out, _ = self.post("now")
        self.assertEqual(status, 400)
        self.assertIn("اول پیج را وصل کن", out["error"])
        self.assertEqual(self.post("draft")[0], 200)                       # a draft is always possible
        self.rig.ok("POST", "/api/settings", {"manual": True})
        st = self.rig.ok("GET", "/api/status")
        self.assertEqual((st["connected"], st["manual"]), (False, True))

    def test_now_means_ready_for_the_owner_and_nothing_is_sent(self):
        status, p, _ = self.post("now")
        self.assertEqual((status, p["status"]), (200, "due"))
        self.rig.tick(3)
        self.assertEqual(self.rig.post_status(p["id"])["status"], "due")
        self.assertEqual([c for c in self.sim.calls if c[0] == "POST"], [])   # Instagram was never asked for anything
        st = self.rig.ok("GET", "/api/status")
        self.assertEqual(st["counts"]["due"], 1)

    def test_a_reminder_becomes_due_at_its_time_and_the_owner_is_told(self):
        self.rig.ok("POST", "/api/settings", {"telegram": {"token": "1:abc", "chat_id": "42"}})
        status, p, _ = self.post("schedule", scheduled_at=time.time() + 3600, caption="لاتهٔ پاییزی رسید\nخط دوم")
        self.assertEqual((status, p["status"]), (200, "scheduled"))
        self.rig.tick(2)
        self.assertEqual(self.rig.post_status(p["id"])["status"], "scheduled")
        self.rig.agent.db.x("UPDATE posts SET scheduled_at=? WHERE id=?", (time.time() - 5, p["id"]))
        self.rig.tick()
        self.assertEqual(self.rig.post_status(p["id"])["status"], "due")
        notes = [n for n in self.rig.ok("GET", "/api/log")["items"] if n["kind"] == "due"]
        self.assertEqual((len(notes), notes[0]["level"]), (1, "alert"))
        self.assertIn("«لاتهٔ پاییزی رسید»", notes[0]["text"])
        # Telegram got the file itself, then the caption alone (one tap copies it), then the reminder
        sent = self.sim.telegram_files
        self.assertEqual([(m["method"], m["field"], m["chat_id"], m["head"][:3]) for m in sent], [("sendDocument", "document", "42", b"\xff\xd8\xff")])
        self.assertEqual(sent[0]["filename"], "insta-%d.jpg" % p["id"])
        self.assertEqual([m["text"] for m in self.sim.telegram][0], "لاتهٔ پاییزی رسید\nخط دوم")
        self.assertIn("وقت انتشار", self.sim.telegram[1]["text"])
        self.assertIn("در تلگرام برایت فرستادم", self.sim.telegram[1]["text"])
        self.rig.tick(3)                                                   # told once, not on every round
        self.assertEqual((len(self.sim.telegram), len(self.sim.telegram_files)), (2, 1))

    def test_file_and_caption_to_the_owners_telegram(self):
        _, p, _ = self.post("draft", kind="reel", caption="ریل تازه #کافه")
        status, out, _ = self.rig.post("/api/posts/%d/telegram" % p["id"])
        self.assertEqual(status, 400)
        self.assertIn("ربات خودت را وصل کن", out["error"])
        self.assertFalse(self.rig.ok("GET", "/api/status")["telegram"])
        self.rig.ok("POST", "/api/settings", {"telegram": {"token": "1:abc", "chat_id": "42"}})
        self.assertTrue(self.rig.ok("GET", "/api/status")["telegram"])
        self.assertEqual(self.rig.ok("POST", "/api/posts/%d/telegram" % p["id"]), {"ok": True, "files": 1})
        video = self.sim.telegram_files[0]
        self.assertEqual((video["method"], video["field"], video["supports_streaming"], video["filename"]), ("sendVideo", "video", "true", "insta-%d.mp4" % p["id"]))
        self.assertEqual(video["head"][4:8], b"ftyp")
        self.assertEqual(self.sim.telegram[-1]["text"], "ریل تازه #کافه")
        _, webm, _ = self.post("draft", kind="reel", data=WEBM, caption="")
        self.rig.ok("POST", "/api/posts/%d/telegram" % webm["id"])
        self.assertEqual(self.sim.telegram_files[-1]["method"], "sendDocument")      # Telegram would not play it as a video
        self.assertEqual(len(self.sim.telegram), 1)                         # no caption, no empty message
        _, empty, _ = self.post("draft", data=False, caption="")
        self.assertEqual(self.rig.post("/api/posts/%d/telegram" % empty["id"])[0], 400)

    def test_a_reminder_waits_for_the_agent_however_late(self):
        _, p, _ = self.post("schedule", scheduled_at=time.time() + 3600)
        self.rig.agent.db.x("UPDATE posts SET scheduled_at=? WHERE id=?", (time.time() - 3 * 86400, p["id"]))
        self.rig.tick()
        self.assertEqual(self.rig.post_status(p["id"])["status"], "due")   # never "missed": nothing was to be sent anyway

    def test_done_by_hand(self):
        _, p, _ = self.post("now")
        done = self.rig.ok("POST", "/api/posts/%d/done" % p["id"])
        self.assertEqual((done["status"], done["by_hand"], done["permalink"]), ("published", True, ""))
        self.assertAlmostEqual(done["published_at"], time.time(), delta=5)
        self.assertEqual(self.rig.post("/api/posts/%d/done" % p["id"])[0], 400)
        st = self.rig.ok("GET", "/api/status")
        self.assertEqual((st["counts"]["due"], st["counts"]["published_today"]), (0, 1))
        self.assertEqual(self.rig.post("/api/posts/%d" % p["id"], {"kind": "image", "caption": "x", "media": [], "action": "draft"})[0], 400)

    def test_the_publish_button_only_hands_the_post_over(self):
        _, p, _ = self.post("draft")
        out = self.rig.ok("POST", "/api/posts/%d/publish" % p["id"])
        self.assertEqual(out["status"], "due")
        back = self.rig.ok("POST", "/api/posts/%d/cancel" % p["id"])
        self.assertEqual(back["status"], "draft")

    def test_a_reminder_may_be_only_a_caption(self):
        status, p, _ = self.post("schedule", data=False, scheduled_at=time.time() + 3600)
        self.assertEqual((status, p["status"], p["media"]), (200, "scheduled", []))
        self.rig.agent.connect(ia.SIM_TOKEN)                                # with a page, a post needs its file
        status, out, _ = self.post("schedule", data=False, scheduled_at=time.time() + 3600)
        self.assertEqual(status, 400)

    def test_the_caption_rules_still_hold(self):
        self.assertEqual(self.post("now", caption="x" * 2201)[0], 400)
        self.assertEqual(self.post("now", caption=" ".join("#t%d" % i for i in range(31)))[0], 400)
        self.assertEqual(self.post("now", caption=" ".join("#t%d" % i for i in range(12)))[0], 200)
        self.assertEqual(self.post("now", kind="reel", data=jpeg())[0], 400)   # a reel is still a video

    def test_shape_and_format_are_the_instagram_apps_business(self):
        self.assertEqual(self.post("now", data=jpeg(1080, 1920))[0], 200)   # 9:16 photo: the app crops it itself
        status, p, _ = self.post("now", kind="reel", data=WEBM)
        self.assertEqual((status, p["media"][0]["type"]), (200, "video"))
        self.rig.agent.connect(ia.SIM_TOKEN)
        self.assertEqual(self.post("now", data=jpeg(1080, 1920))[0], 400)
        status, out, _ = self.post("now", kind="reel", data=WEBM)
        self.assertEqual(status, 400)
        self.assertIn("WebM", out["error"])

    def test_due_posts_lead_the_queue(self):
        _, later, _ = self.post("schedule", scheduled_at=time.time() + 600)
        _, due, _ = self.post("now")
        _, draft, _ = self.post("draft")
        queue = [p["id"] for p in self.rig.ok("GET", "/api/posts?group=queue")["items"]]
        self.assertEqual(queue, [due["id"], later["id"]])
        self.assertEqual([p["id"] for p in self.rig.ok("GET", "/api/posts?group=drafts")["items"]], [draft["id"]])

    def test_connecting_a_page_ends_posting_by_hand(self):
        _, p, _ = self.post("now")
        self.rig.agent.connect(ia.SIM_TOKEN)
        st = self.rig.ok("GET", "/api/status")
        self.assertEqual((st["connected"], st["manual"]), (True, False))
        self.assertEqual(self.rig.post_status(p["id"])["status"], "due")   # still the owner's to post, or to publish now
        out = self.rig.ok("POST", "/api/posts/%d/publish" % p["id"])
        self.assertEqual(out["status"], "scheduled")
        self.assertEqual(self.rig.run_post(p["id"])["status"], "published")
        self.assertEqual(self.rig.post_status(p["id"])["by_hand"], False)
        self.rig.ok("POST", "/api/disconnect")
        self.assertTrue(self.rig.ok("GET", "/api/status")["manual"])

    def test_the_assistant_knows_there_is_no_page(self):
        self.post("now")
        out = self.rig.ok("POST", "/api/chat", {"messages": [{"role": "user", "content": "چه خبر؟"}]})
        self.assertEqual(out["source"], "offline")
        self.assertIn("پیج به ایجنت وصل نیست", out["text"])
        self.assertIn("آمادهٔ انتشار: ۱", out["text"])

    def test_page_handle_setting(self):
        out = self.rig.ok("POST", "/api/settings", {"brand": {"handle": " @My.Page_1 "}})
        self.assertEqual(out["brand"]["handle"], "My.Page_1")
        self.assertEqual(self.rig.post("/api/settings", {"brand": {"handle": "کافه من"}})[0], 400)
        self.assertIn("@My.Page_1", self.rig.agent.ai.persona())


class StudioTests(Base):
    def test_idea_is_needed(self):
        self.assertEqual(self.rig.post("/api/studio/make", {"idea": " "})[0], 400)
        self.assertEqual(self.rig.get("/api/studio/job/0123456789abcdef")[0], 404)

    def test_the_plan_comes_from_the_assistant(self):
        self.text_ai("```json\n%s\n```\nامیدوارم مفید باشد!" % json.dumps(PLAN, ensure_ascii=False))
        job = self.make(idea="تخفیف ۲۰ درصدی لاتهٔ پاییزی تا آخر هفته", kind="reel", scenes=3)
        plan = job["plan"]
        self.assertEqual((job["status"], plan["source"], plan["why"]), ("done", "ai", ""))
        self.assertEqual(plan["caption"], "لاتهٔ پاییزی تا آخر هفته ۲۰٪ تخفیف دارد ☕️ منتظرتان هستیم.")
        self.assertEqual(plan["hashtags"], ["#لاته", "#کافه", "#پاییز", "#قهوه_تازه", "#a"])     # five, each once
        self.assertEqual((plan["headline"], plan["sub"]), ("لاتهٔ پاییزی با ۲۰٪ تخفیف", "فقط تا آخر هفته"))
        self.assertEqual([s["text"] for s in plan["scenes"]], ["صبح با لاتهٔ تازه", "۲۰٪ تخفیف", "تا آخر هفته منتظرتیم"])
        asked = self.calls("ptxt")[0][4]
        self.assertEqual((asked["model"], asked["reasoning_effort"], asked["temperature"]), ("openai-fast", "low", 0.4))
        self.assertNotIn("max_tokens", asked)                              # the free model's thinking counts as output
        self.assertIn("ریل 3 صحنه‌ای", asked["messages"][-1]["content"])
        self.assertIn("«تخفیف ۲۰ درصدی لاتهٔ پاییزی تا آخر هفته»", asked["messages"][-1]["content"])
        # each scene got its own picture, described in English, in the reel's shape
        self.assertEqual([p["prompt"] for p in job["pictures"]], [s["image"] for s in PLAN["scenes"]])
        self.assertTrue(all(p["file"] and p["source"] in ("free", "horde") for p in job["pictures"]), job["pictures"])
        first = self.calls("pimg")[0]
        asked_for = urllib.parse.unquote(first[2])
        self.assertIn("hand pouring latte into a mug", asked_for)
        self.assertIn("professional photograph", asked_for)
        self.assertIn("no text", asked_for)
        self.assertEqual((first[3]["width"], first[3]["height"], first[3]["safe"]), ("720", "1280", "true"))
        self.assertNotIn("nologo", first[3])                               # the free picture keeps the service's logo

    def test_a_picture_is_kept_as_a_file_the_panel_can_draw_with(self):
        self.text_ai(PLAN)
        job = self.make(idea="لاتهٔ پاییزی", kind="image", style="art")
        pic = job["pictures"][0]
        self.assertEqual((len(job["pictures"]), pic["source"], pic["why"]), (1, "free", ""))
        self.assertEqual(pic["prompt"], PLAN["image"])
        self.assertIn("digital illustration", urllib.parse.unquote(self.calls("pimg")[0][2]))
        self.assertEqual((self.calls("pimg")[0][3]["width"], self.calls("pimg")[0][3]["height"]), ("768", "960"))
        status, raw, headers = self.rig.get(pic["preview"])
        self.assertEqual((status, headers["Content-Type"], raw[:8]), (200, "image/png", b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((pic["width"], pic["height"]), (480, 600))
        # it is raw material: a post takes the JPEG the panel draws from it, never the fetched file itself
        status, out, _ = self.rig.post("/api/posts", {"kind": "image", "caption": "x", "media": [{"file": pic["file"]}], "action": "now"})
        self.assertEqual(status, 400)

    def test_without_the_assistant_a_persian_idea_gets_words_but_no_picture(self):
        job = self.make(idea="تخفیف ۲۰ درصدی لاتهٔ پاییزی. فقط تا آخر هفته", kind="reel", scenes=3)
        plan = job["plan"]
        self.assertEqual((job["status"], plan["source"], plan["why"]), ("done", "offline", "off"))
        self.assertEqual(plan["headline"], "تخفیف ۲۰ درصدی لاتهٔ پاییزی")
        self.assertIn("تخفیف ۲۰ درصدی لاتهٔ پاییزی", plan["caption"])
        self.assertTrue(3 <= len(plan["hashtags"]) <= 5)
        self.assertEqual([s["text"] for s in plan["scenes"][:2]], ["تخفیف ۲۰ درصدی لاتهٔ پاییزی", "فقط تا آخر هفته"])
        self.assertEqual(len(plan["scenes"]), 3)
        self.assertTrue(all(not p["file"] and "دستیار در دسترس نبود" in p["why"] for p in job["pictures"]))
        self.assertEqual(self.calls("pimg") + self.calls("horde"), [])     # a picture of something else is worse than none

    def test_an_english_idea_can_be_drawn_without_the_assistant(self):
        job = self.make(idea="Autumn latte with cinnamon, 20% off this week", kind="image")
        self.assertEqual((job["plan"]["source"], job["pictures"][0]["source"]), ("offline", "free"))

    def test_a_broken_answer_falls_back_to_templates(self):
        self.text_ai("متأسفم، نمی‌توانم JSON بدهم.")
        job = self.make(idea="Latte art class on Friday", kind="image")
        self.assertEqual((job["plan"]["source"], job["plan"]["why"]), ("offline", "format"))
        self.text_ai({"caption": 5, "hashtags": "x", "scenes": [{"text": 1}, "bad"]})
        self.rig.agent.ai.free_at = 0
        job = self.make(idea="Latte art class on Friday", kind="reel", scenes=3)
        plan = job["plan"]
        self.assertEqual(plan["source"], "ai")                             # usable parts are taken, the rest is filled in
        self.assertIn("Latte art class on Friday", plan["caption"])
        self.assertEqual(len(plan["scenes"]), 3)
        self.assertTrue(all(isinstance(s["text"], str) and s["text"] for s in plan["scenes"]))

    def test_the_second_free_picture_comes_from_the_volunteers(self):
        self.text_ai(PLAN)
        self.sim.free_gap["image"] = 300
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3)
        self.assertEqual([p["source"] for p in job["pictures"]], ["free", "horde", "horde"])
        sent = self.calls("horde", "generate/async")[0]
        body, headers = sent[4], sent[5]
        self.assertEqual((body["params"]["width"], body["params"]["height"]), (384, 704))
        self.assertLessEqual(body["params"]["width"] * body["params"]["height"], 576 * 576)
        self.assertEqual(body["models"], ["AbsoluteReality", "Deliberate", "stable_diffusion"])    # no anime model
        self.assertEqual((body["nsfw"], body["censor_nsfw"], body["r2"]), (False, True, False))
        self.assertIn(" ### ", body["prompt"])
        self.assertEqual(headers["apikey"], "0000000000")
        self.assertTrue(headers["client-agent"].startswith("insta-agent:"))
        self.assertEqual(len(self.calls("horde", "status/models")), 1)     # the model list is asked once, not per picture
        self.assertTrue(40 <= self.rig.ok("GET", "/api/studio")["free_wait"] <= 46)     # the agent knows the 45-second rule

    def test_unknown_models_on_the_network_are_filtered(self):
        self.text_ai(PLAN)
        self.sim.free_gap["image"] = 300
        self.sim.horde_names = ["WAI-NSFW-illustrious-SDXL", "Nova Anime XL", "CyberRealistic Pony", "RealVis", "Juggernaut XL"]
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=2)
        self.assertEqual(job["pictures"][1]["source"], "horde")
        self.assertEqual(self.calls("horde", "generate/async")[0][4]["models"], ["RealVis"])

    def test_waiting_for_the_free_turn_when_it_is_the_only_service(self):
        self.text_ai(PLAN)
        self.rig.ok("POST", "/api/settings", {"studio": {"image": "pollinations"}})
        self.rig.app.cfg.free_gap = 1.2
        self.sim.free_gap["image"] = 1.2
        started = time.time()
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=2)
        self.assertEqual([p["source"] for p in job["pictures"]], ["free", "free"])
        self.assertGreater(time.time() - started, 1.0)
        self.assertEqual(self.calls("horde"), [])

    def test_a_long_queue_is_given_up_and_cancelled(self):
        self.text_ai(PLAN)
        self.rig.ok("POST", "/api/settings", {"studio": {"image": "horde"}})
        self.sim.horde_polls = 10 ** 6
        old, ia.HORDE_WAIT = ia.HORDE_WAIT, 0.2
        self.addCleanup(setattr, ia, "HORDE_WAIT", old)
        job = self.make(idea="لاتهٔ پاییزی", kind="image")
        self.assertEqual((job["status"], job["pictures"][0]["file"]), ("done", ""))
        self.assertIn("صف شبکهٔ داوطلبانه طولانی بود", job["pictures"][0]["why"])
        self.assertTrue(all(j["canceled"] for j in self.sim.horde_jobs.values()))

    def test_when_nothing_answers_the_rest_is_not_tried_for_minutes(self):
        self.text_ai(PLAN)
        self.sim.script("pimg", 500, {"error": "down"}, times=20)
        self.sim.script("horde", 500, {"message": "down"}, times=20)
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=5)
        self.assertEqual(job["status"], "done")
        self.assertTrue(all(not p["file"] and p["why"] for p in job["pictures"]))
        self.assertEqual(len(self.calls("pimg")), 2)                       # two scenes failed: the other three are not even asked
        self.assertEqual(len(job["plan"]["scenes"]), 5)

    def test_pictures_can_be_left_out_or_switched_off(self):
        self.text_ai(PLAN)
        job = self.make(idea="لاتهٔ پاییزی", kind="image", pictures=False)
        self.assertEqual((job["pictures"][0]["file"], job["pictures"][0]["why"]), ("", ""))
        self.rig.ok("POST", "/api/settings", {"studio": {"image": "off"}})
        self.rig.agent.ai.free_at = 0
        job = self.make(idea="لاتهٔ پاییزی", kind="image")
        self.assertIn("خاموش", job["pictures"][0]["why"])
        self.assertEqual(self.calls("pimg") + self.calls("horde"), [])

    def test_with_a_pollinations_key_words_and_pictures_use_it(self):
        self.sim.ai_text = json.dumps(PLAN, ensure_ascii=False)
        self.rig.ok("POST", "/api/settings", {"studio": {"pollen": self.sim.ai_key}})
        st = self.rig.ok("GET", "/api/status")
        self.assertEqual((st["ai"], st["studio"]["pollen"]), ("pollen", True))
        self.assertEqual(self.rig.ok("GET", "/api/settings")["studio"]["pollen"], "")      # never sent back to the page
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3)
        self.assertEqual(job["plan"]["source"], "ai")
        self.assertEqual([p["source"] for p in job["pictures"]], ["key"] * 3)
        text = self.calls("pgen", "v1/chat/completions")[0]
        self.assertEqual(text[5]["authorization"], "Bearer " + self.sim.ai_key)
        self.assertNotIn("temperature", text[4])
        self.assertNotIn("model", text[4])                                 # the service's own default model
        pic = self.calls("pgen", "image/")[0]
        self.assertEqual((pic[3]["width"], pic[3]["height"]), ("720", "1280"))
        self.assertEqual(self.calls("pimg") + self.calls("horde"), [])
        self.assertEqual(job["notes"], [])

    def test_a_refused_key_is_reported_and_the_free_services_step_in(self):
        self.text_ai(PLAN)
        self.rig.ok("POST", "/api/settings", {"studio": {"pollen": "sk_wrong"}, "ai": {"mode": "off"}})
        job = self.make(idea="Autumn latte", kind="image")
        self.assertEqual(job["pictures"][0]["source"], "free")
        self.assertEqual(len(job["notes"]), 1)
        self.assertIn("کلید Pollinations پذیرفته نشد", job["notes"][0])

    def test_an_own_picture_service(self):
        self.text_ai(PLAN)
        self.rig.ok("POST", "/api/settings", {"studio": {"image": "custom", "url": self.rig.base + "/_sim/ai/oimg/", "key": self.sim.ai_key,
                                                         "model": "my-model"}})
        job = self.make(idea="لاتهٔ پاییزی", kind="image")
        self.assertEqual(job["pictures"][0]["source"], "custom")
        sent = self.calls("oimg")[0]
        self.assertEqual((sent[2], sent[4]["model"], sent[4]["size"], sent[4]["n"]), ("images/generations", "my-model", "1024x1536", 1))
        self.assertEqual(sent[5]["authorization"], "Bearer " + self.sim.ai_key)
        self.rig.ok("POST", "/api/settings", {"studio": {"key_clear": True}})
        self.rig.agent.ai.free_at = 0
        job = self.make(idea="لاتهٔ پاییزی", kind="image")
        self.assertEqual(job["pictures"][0]["file"], "")
        self.assertIn("سرویس تصویر خودت", job["notes"][0])

    def test_descriptions_are_cleaned_and_a_missing_one_costs_only_its_own_picture(self):
        plan = dict(PLAN, scenes=[{"text": "یک", "image": 'A card that reads "20% OFF" beside a latte, cozy café'},
                                  {"text": "دو", "image": "تصویر یک فنجان قهوه"}, {"text": "سه"}],
                    image="نمی‌دانم")
        self.text_ai(plan)
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3)
        self.assertEqual(job["pictures"][0]["prompt"], "A card beside a latte, cozy cafe")          # no writing asked for
        self.assertTrue(job["pictures"][0]["file"])
        for pic in job["pictures"][1:]:                                    # Persian or absent: not sent to an English-only service
            self.assertEqual((pic["file"], pic["prompt"]), ("", ""))
            self.assertIn("دستیار برای این تصویر توصیفی نداد", pic["why"])
        self.assertEqual(len(self.calls("pimg")) + len(self.calls("horde", "generate/async")), 1)

    def test_a_persian_description_is_put_into_english_first(self):
        self.text_ai(lambda body: '"A slice of carrot cake on a white plate, top view."')
        job = self.wait(self.rig.ok("POST", "/api/studio/picture", {"prompt": "یک برش کیک هویج روی بشقاب سفید"}))
        pic = job["pictures"][0]
        self.assertEqual((pic["prompt"], pic["source"]), ("A slice of carrot cake on a white plate, top view", "free"))
        asked = self.calls("ptxt")[0][4]["messages"]
        self.assertEqual(asked[-1]["content"], "یک برش کیک هویج روی بشقاب سفید")
        self.assertIn("A slice of carrot cake on a white plate", urllib.parse.unquote(self.calls("pimg")[0][2]))
        # without the assistant nothing is drawn from a description the services cannot read
        self.sim.ai_text = None
        self.rig.agent.ai.free_at = 0
        job = self.wait(self.rig.ok("POST", "/api/studio/picture", {"prompt": "یک برش کیک هویج روی بشقاب سفید"}))
        self.assertEqual(job["pictures"][0]["file"], "")
        self.assertIn("تصویرسازها فقط انگلیسی می‌فهمند", job["pictures"][0]["why"])
        self.assertEqual(len(self.calls("pimg")), 1)

    def test_a_blocked_service_is_noticed_in_seconds_not_minutes(self):
        self.text_ai(PLAN)
        dead = "http://127.0.0.1:9"                                        # nothing listens there
        self.rig.app.cfg.image_api, self.rig.app.cfg.horde_api = dead + "/pimg", dead + "/horde"
        self.rig.agent.ai.FREE_URL = dead + "/openai"
        started = time.time()
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=4)
        self.assertLess(time.time() - started, 10)
        self.assertEqual((job["status"], job["plan"]["source"], job["plan"]["why"]), ("done", "offline", "down"))
        self.assertTrue(all(not p["file"] for p in job["pictures"]))
        graph = self.rig.agent.graph
        self.assertEqual(graph.reachable(dead + "/anything"), False)       # remembered: not asked again for a while
        self.assertEqual(graph.reachable(self.rig.base + "/_sim/ai/pimg"), True)
        job = self.wait(self.rig.ok("POST", "/api/studio/picture", {"prompt": "a red bicycle"}))
        self.assertIn("ارتباط با سرویس تصویر برقرار نشد", job["pictures"][0]["why"])

    def test_one_more_picture(self):
        job = self.wait(self.rig.ok("POST", "/api/studio/picture", {"prompt": "a red bicycle in the rain", "shape": "square", "style": "3d"}))
        self.assertEqual((job["kind"], job["status"], job["plan"], len(job["pictures"])), ("picture", "done", None, 1))
        self.assertTrue(job["pictures"][0]["file"])
        call = self.calls("pimg")[0]
        self.assertIn("a red bicycle in the rain, 3D render", urllib.parse.unquote(call[2]))
        self.assertEqual((call[3]["width"], call[3]["height"]), ("896", "896"))
        self.assertEqual(self.rig.post("/api/studio/picture", {"prompt": ""})[0], 400)

    def test_jobs_can_be_stopped_and_do_not_pile_up(self):
        self.text_ai(PLAN)
        self.sim.ai_delay = 0.6
        a = self.rig.ok("POST", "/api/studio/make", {"idea": "Autumn latte", "kind": "reel", "scenes": 4})
        b = self.rig.ok("POST", "/api/studio/picture", {"prompt": "a red bicycle"})
        status, out, _ = self.rig.post("/api/studio/picture", {"prompt": "a blue bicycle"})
        self.assertEqual(status, 429)
        self.rig.ok("POST", "/api/studio/job/%s/cancel" % a["id"])
        a = self.wait(a)
        self.assertEqual(a["status"], "canceled")
        self.assertLess(sum(1 for p in a["pictures"] if p["file"]), 4)
        self.assertEqual(self.wait(b)["status"], "done")

    def test_the_free_text_service_answers_once_in_a_while(self):
        self.text_ai("کپشن یک\n===\nکپشن دو")
        self.sim.free_gap["text"] = 300
        first = self.rig.ok("POST", "/api/ai/captions", {"topic": "لاته"})
        self.assertEqual((first["source"], first["items"]), ("ai", ["کپشن یک", "کپشن دو"]))
        second = self.rig.ok("POST", "/api/ai/captions", {"topic": "لاته"})
        self.assertEqual(second["source"], "offline")
        self.assertTrue(40 <= second["wait"] <= 46, second)
        self.assertEqual(len(self.calls("ptxt")), 1)                       # the second question was not even sent
        self.rig.agent.ai.free_at = 0                                      # e.g. another program on the same address used the turn
        third = self.rig.ok("POST", "/api/ai/hashtags", {"topic": "لاته"})
        self.assertEqual(third["source"], "offline")
        self.assertTrue(290 <= third["wait"] <= 300, third)
        chat = self.rig.ok("POST", "/api/chat", {"messages": [{"role": "user", "content": "سلام"}]})
        self.assertIn("هر ۴۵ ثانیه یک پاسخ", chat["text"])

    def test_the_plan_waits_for_its_turn(self):
        self.text_ai(PLAN)
        self.sim.free_gap["text"] = 1.2
        self.rig.ok("POST", "/api/ai/captions", {"topic": "لاته"})
        self.rig.agent.ai.free_at = 0                                      # the agent does not know yet; the service says "wait"
        job = self.make(idea="لاتهٔ پاییزی", kind="image", pictures=False)
        self.assertEqual(job["plan"]["source"], "ai")
        self.assertEqual(len(self.calls("ptxt")), 3)                       # captions, refused plan, plan


SAYS = ["لاتهٔ پاییزی ما این هفته بیست درصد تخفیف دارد.", "هر روز صبح با قهوهٔ تازه منتظر شما هستیم.", "فقط تا آخر همین هفته فرصت دارید."]
TOLD = dict(PLAN, scenes=[dict(sc, say=say) for sc, say in zip(PLAN["scenes"], SAYS)])


class VoiceTests(Base):
    """The narrator of a reel: a speech service reads one line per scene; the panel lays the clips on the video."""

    def key(self, plan=TOLD, **more):
        self.sim.ai_text = json.dumps(plan, ensure_ascii=False)
        self.rig.ok("POST", "/api/settings", {"studio": dict({"pollen": self.sim.ai_key}, **more)})

    def said(self, service="pgen", tail="v1/audio/speech"):
        return [c[4] for c in self.calls(service, tail)]

    def test_without_a_key_the_narrator_on_the_device_is_the_speaker(self):
        self.text_ai(TOLD)
        st = self.rig.ok("GET", "/api/status")["studio"]
        self.assertEqual((st["voice"], st["speaker"], st["pack"]["state"]), (False, "device", "none"))
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3, voice=True, pictures=False)
        self.assertEqual([v["text"] for v in job["voices"]], SAYS)        # the lines are there; the panel reads them on the device
        self.assertEqual([(v["say"], v["source"], v["file"], v["why"]) for v in job["voices"]], [(ia.spoken(t), "device", "", "") for t in SAYS])
        self.assertEqual(job["voices"][0]["say"], "لاتهٔ پاییزی ما این هفته بیست درصد تخفیف دارد.")
        self.assertEqual([sc["say"] for sc in job["plan"]["scenes"]], SAYS)
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["ساعت ۸:۳۰ باز می‌کنیم ☕️", "خداحافظ"]}))
        self.assertEqual((job["status"], job["notes"], [v["say"] for v in job["voices"]]), ("done", [], ["ساعت هشت و سی باز می‌کنیم", "خداحافظ"]))
        self.assertEqual(self.said() + self.said("oimg", "audio/speech"), [])           # no service was asked

    def test_a_service_speaker_without_a_key_says_what_is_missing(self):
        self.text_ai(TOLD)
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3, voice=True, pictures=False, speaker="nova")
        self.assertEqual([(v["file"], v["why"]) for v in job["voices"]], [("", ia.NO_VOICE)] * 3)
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا", "خداحافظ"], "speaker": "onyx"}))
        self.assertEqual((job["status"], [v["why"] for v in job["voices"]], job["notes"]), ("done", [ia.NO_VOICE] * 2, [ia.NO_VOICE]))
        self.assertEqual(self.said() + self.said("oimg", "audio/speech"), [])

    def test_with_a_key_the_narrator_on_the_device_can_still_be_chosen(self):
        self.key()
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3, voice=True, pictures=False, speaker="device")
        self.assertEqual([v["source"] for v in job["voices"]], ["device"] * 3)
        self.rig.ok("POST", "/api/settings", {"studio": {"speaker": "device"}})
        self.assertEqual(self.rig.ok("GET", "/api/status")["studio"]["speaker"], "device")
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا"]}))
        self.assertEqual(job["voices"][0]["source"], "device")
        self.assertEqual(self.said(), [])

    def test_narration_is_only_made_when_asked_for(self):
        self.key()
        self.assertEqual(self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3, pictures=False)["voices"], [])
        self.assertEqual(self.make(idea="لاتهٔ پاییزی", kind="image", voice=True, pictures=False)["voices"], [])      # a picture has no sound
        self.assertEqual(self.said(), [])

    def test_with_a_key_every_scene_is_read_before_the_pictures_come(self):
        self.key()
        st = self.rig.ok("GET", "/api/status")["studio"]
        self.assertEqual((st["voice"], st["speaker"]), (True, "nova"))
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3, voice=True)
        self.assertEqual([(v["text"], v["source"], v["why"]) for v in job["voices"]], [(t, "key", "") for t in SAYS])
        self.assertEqual([c["input"] for c in self.said()], SAYS)
        self.assertEqual({(c["model"], c["voice"], c["response_format"]) for c in self.said()}, {("openai/tts-1", "nova", "mp3")})
        self.assertEqual(self.calls("pgen", "v1/audio/speech")[0][5]["authorization"], "Bearer " + self.sim.ai_key)
        order = [c[2].split("/")[1 if c[2].startswith("v1/") else 0] for c in self.calls("pgen")]
        self.assertEqual(order, ["chat"] + ["audio"] * 3 + ["image"] * 3)
        self.assertEqual([p["source"] for p in job["pictures"]], ["key"] * 3)
        self.assertEqual(job["notes"], [])
        status, clip, headers = self.rig.req("GET", job["voices"][1]["preview"])        # what the panel decodes and mixes
        self.assertEqual((status, headers["Content-Type"]), (200, "audio/wav"))
        self.assertEqual(clip, ia.fake_speech(SAYS[1]))

    def test_the_line_is_cleaned_before_it_is_read(self):
        plan = dict(TOLD, scenes=[dict(TOLD["scenes"][0], say="۲۰٪ تخفیف ☕️ تا ساعت ۸:۳۰ #کافه_ما"), dict(PLAN["scenes"][1], say="   "),
                                  dict(PLAN["scenes"][2])])
        self.key(plan)
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3, voice=True, pictures=False)
        self.assertEqual([c["input"] for c in self.said()], ["بیست درصد تخفیف تا ساعت هشت و سی کافه ما", "بیست درصد تخفیف", "تا آخر هفته منتظرتیم"])
        self.assertEqual([v["text"] for v in job["voices"]], ["۲۰٪ تخفیف ☕️ تا ساعت ۸:۳۰ #کافه_ما", "۲۰٪ تخفیف", "تا آخر هفته منتظرتیم"])   # no line: the words on the picture are read

    def test_the_speaker_can_be_chosen(self):
        self.key(speaker="onyx")
        self.assertEqual(self.rig.ok("GET", "/api/status")["studio"]["speaker"], "onyx")
        self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=2, voice=True, pictures=False)
        self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا"], "speaker": "shimmer"}))
        self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا"], "speaker": "../etc <script>"}))      # not a name: the saved one
        self.assertEqual([c["voice"] for c in self.said()], ["onyx", "onyx", "shimmer", "onyx"])
        self.rig.ok("POST", "/api/settings", {"studio": {"speaker": "no such speaker!"}})
        self.assertEqual(self.rig.ok("GET", "/api/settings")["studio"]["speaker"], "")           # no choice ...
        self.assertEqual(self.rig.ok("GET", "/api/status")["studio"]["speaker"], "nova")         # ... so, with a key, the service's first voice

    def test_lines_can_be_read_again_one_by_one(self):
        self.key()
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["کیک هویج تازه از تنور درآمد."]}))
        self.assertEqual((job["kind"], job["status"], len(job["voices"]), job["voices"][0]["source"]), ("voice", "done", 1, "key"))
        self.assertTrue(job["voices"][0]["preview"].startswith("/api/file/"))
        for bad in ({}, {"texts": []}, {"texts": "سلام"}, {"texts": ["سلام", "☕️"]}, {"texts": [""]}):
            status, out, _ = self.rig.req("POST", "/api/studio/voice", bad)
            self.assertEqual(status, 400, bad)
            self.assertIn("بنویس گوینده چه چیزی را بخواند", out["error"])
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام"] * 30}))
        self.assertEqual(len(job["voices"]), 8)                            # more scenes than a reel can have are not read

    def test_no_credit_is_said_once_and_the_reel_is_still_made(self):
        self.key()
        self.sim.pollen = 0
        job = self.make(idea="لاتهٔ پاییزی", kind="reel", scenes=3, voice=True, pictures=False)
        self.assertEqual(job["status"], "done")
        self.assertEqual(len(self.said()), 1)                              # the second scene would hear the same
        self.assertEqual(len(job["notes"]), 1)
        self.assertIn("اعتبار این کلید برای ساخت صدا کافی نیست", job["notes"][0])
        self.assertEqual([v["why"] for v in job["voices"]], [job["notes"][0]] * 3)
        self.assertEqual(len(job["plan"]["scenes"]), 3)

    def test_a_refused_key_is_said_in_plain_words(self):
        self.text_ai(TOLD)
        self.rig.ok("POST", "/api/settings", {"studio": {"pollen": "sk_wrong"}, "ai": {"mode": "off"}})
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا", "خداحافظ"]}))
        self.assertEqual(len(self.said()), 1)
        self.assertIn("کلید سرویس صدا پذیرفته نشد", job["notes"][0])
        self.assertEqual([bool(v["file"]) for v in job["voices"]], [False, False])

    def test_a_busy_speech_service_is_asked_once_more(self):
        self.key()
        self.sim.script("pgen", 429, {"error": {"message": "Too many requests"}}, {"Retry-After": "0"})
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا"]}))
        self.assertEqual((len(self.said()), job["voices"][0]["source"], job["notes"]), (2, "key", []))
        self.sim.script("pgen", 503, {"error": "down"}, {"Retry-After": "0"}, times=2)
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا", "خداحافظ"]}))
        self.assertIn("HTTP 503", job["voices"][0]["why"])
        self.assertEqual(job["voices"][1]["source"], "key")                # one bad answer does not cost the other scenes
        self.assertEqual(job["notes"], [])

    def test_an_answer_that_is_not_sound_is_not_kept(self):
        self.key()
        self.sim.script("pgen", 200, {"message": "this is not audio"})
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا"]}))
        self.assertEqual(job["voices"][0]["file"], "")
        self.assertIn("جواب قابل‌استفاده‌ای نداد", job["voices"][0]["why"])

    def test_an_own_speech_service(self):
        self.text_ai(TOLD)
        self.rig.ok("POST", "/api/settings", {"studio": {"url": self.rig.base + "/_sim/ai/oimg/images/generations", "key": self.sim.ai_key}})
        self.assertIs(self.rig.ok("GET", "/api/status")["studio"]["voice"], False)       # a picture service alone does not speak
        self.rig.ok("POST", "/api/settings", {"studio": {"tts_model": "my-tts", "speaker": "alloy"}})
        self.assertIs(self.rig.ok("GET", "/api/status")["studio"]["voice"], True)
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا"]}))
        self.assertEqual(job["voices"][0]["source"], "custom")
        sent = self.calls("oimg", "audio/speech")
        self.assertEqual((len(sent), sent[0][4]["model"], sent[0][4]["voice"], sent[0][4]["input"]), (1, "my-tts", "alloy", "سلام دنیا"))
        self.assertEqual(sent[0][5]["authorization"], "Bearer " + self.sim.ai_key)
        self.assertEqual(self.said(), [])                                  # Pollinations was not asked

    def test_the_demo_has_a_stand_in_narrator(self):
        rig = Rig(demo=True)
        self.addCleanup(rig.close)
        self.assertIs(rig.ok("GET", "/api/status")["studio"]["voice"], True)
        job = rig.ok("POST", "/api/studio/make", {"idea": "معرفی کیک هویج خانگی", "kind": "reel", "scenes": 3, "voice": True, "pictures": False})
        end = time.time() + 60
        while job["status"] == "running" and time.time() < end:
            time.sleep(0.05)
            job = rig.ok("GET", "/api/studio/job/" + job["id"])
        self.assertEqual((job["status"], [v["source"] for v in job["voices"]]), ("done", ["key"] * 3))
        self.assertTrue(all(len(v["text"]) > 12 for v in job["voices"]), job["voices"])
        self.assertEqual(rig.agent.pack.sources, ia.VOICE_SOURCES)        # the demo would fetch the real narrator ...
        self.assertEqual(rig.ok("GET", "/api/status")["studio"]["speaker"], "nova")
        rig.agent.pack.files = {}                                          # ... and once it is there, it is the one that reads
        self.assertEqual(rig.ok("GET", "/api/status")["studio"]["speaker"], "device")

    def test_a_narration_clip_is_not_a_post(self):
        self.key()
        job = self.wait(self.rig.ok("POST", "/api/studio/voice", {"texts": ["سلام دنیا"]}))
        for kind, why in (("reel", "ریل یک ویدیو می‌خواهد"), ("image", "پست تکی یک عکس می‌خواهد"), ("story", "این فایل صداست")):
            status, out, _ = self.rig.req("POST", "/api/posts", {"kind": kind, "caption": "سلام", "action": "now", "media": [{"file": job["voices"][0]["file"]}]})
            self.assertEqual(status, 400, kind)
            self.assertIn(why, out["error"])

    def test_the_key_can_be_tried_out(self):
        status, out, _ = self.rig.req("POST", "/api/studio/key", {})
        self.assertEqual(status, 400)
        self.assertIn("اول کلید را بنویس", out["error"])
        self.key()
        self.assertEqual(self.rig.ok("POST", "/api/studio/key"), {"ok": True, "name": "insta-agent", "balance": 1.25, "audio": True})
        self.assertEqual([c[2] for c in self.calls("pgen", "account/")], ["account/key", "account/balance"])
        self.sim.pollen = None                                             # a key that may not see the balance: still a good key
        self.assertEqual(self.rig.ok("POST", "/api/studio/key")["balance"], None)
        self.sim.script("pgen", 200, {"valid": True, "name": "pictures only", "permissions": {"models": ["image", "text"]}, "pollenBudget": 3})
        out = self.rig.ok("POST", "/api/studio/key")
        self.assertEqual((out["audio"], out["balance"], out["name"]), (False, 3, "pictures only"))
        self.rig.ok("POST", "/api/settings", {"studio": {"pollen": "sk_wrong"}})
        status, out, _ = self.rig.req("POST", "/api/studio/key", {})
        self.assertEqual(status, 400)
        self.assertIn("این کلید را نپذیرفت", out["error"])
        self.sim.script("pgen", 500, {"error": "boom"})
        status, out, _ = self.rig.req("POST", "/api/studio/key", {})
        self.assertEqual(status, 502)
        self.assertIn("جواب روشنی نداد", out["error"])


class PackTests(Base):
    """The narrator that runs on the owner's device: its files are fetched once, checked against known hashes, and
    handed to the panel. (Here the simulator hands out small stand-ins; the steps are the same.)"""

    def setUp(self):
        super().setUp()
        self.pack = self.rig.agent.pack
        self.names = sorted(self.sim.pack_files)

    def fetched(self):
        return [c[2] for c in self.calls("voice")]

    def settle(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            view = self.rig.ok("GET", "/api/studio/pack")
            if view["state"] != "loading":
                return view
            time.sleep(0.02)
        self.fail("the download did not end: %s" % view)

    def get(self):
        self.rig.ok("POST", "/api/studio/pack")
        return self.settle()

    def on_disk(self):
        return sorted(os.listdir(self.pack.dir)) if os.path.isdir(self.pack.dir) else []

    def test_the_real_list_is_sound(self):
        self.assertEqual(sorted(ia.VOICE_FILES), self.names)              # the stand-ins have the names of the real files
        for name, (size, sha) in ia.VOICE_FILES.items():
            self.assertGreater(size, 100000, name)
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
        covered = {}
        for base, archive, inside, names in ia.VOICE_SOURCES:
            self.assertTrue(base.startswith("https://"), base)
            self.assertEqual(bool(archive), base.endswith(".tgz"), base)
            self.assertEqual(bool(archive), bool(inside), base)
            if not archive and not base.endswith("/"):
                self.assertEqual(len(names), 1, base)
            for n in names:
                self.assertIn(n, ia.VOICE_FILES)
                covered[n] = covered.get(n, 0) + 1
        self.assertEqual(sorted(covered), self.names)
        self.assertTrue(all(v >= 2 for v in covered.values()), covered)    # no file hangs on one server alone
        total = sum(v[0] for v in ia.VOICE_FILES.values())
        self.assertEqual(self.pack.view()["fetch_mb"], ia.VOICE_FETCH_MB)
        self.assertLess(abs(total / 1e6 - 93), 1)

    def test_nothing_is_there_before_the_owner_asks(self):
        view = self.rig.ok("GET", "/api/studio/pack")
        self.assertEqual((view["state"], view["pct"], view["why"]), ("none", 0, ""))
        self.assertEqual(self.rig.ok("GET", "/api/status")["studio"]["pack"], view)
        for name in self.names:
            self.assertEqual(self.rig.req("GET", "/api/voice/" + name)[0], 404, name)
        self.assertEqual(self.fetched(), [])
        self.assertEqual(self.on_disk(), [])

    def test_the_files_are_fetched_checked_and_served(self):
        view = self.get()
        self.assertEqual((view["state"], view["pct"], view["why"]), ("ready", 100, ""))
        self.assertEqual(self.fetched(), ["pack.tgz", "ort.wasm.min.js", "ort-wasm-simd.wasm", "voice.onnx"])     # the archive brings three of the six
        self.assertEqual(self.on_disk(), self.names)                       # nothing half-done is left behind
        for name in self.names:
            status, body, headers = self.rig.req("GET", "/api/voice/" + name)
            self.assertEqual((status, body if isinstance(body, bytes) else None), (200, self.sim.pack_files[name]), name)
            self.assertEqual(headers["Cache-Control"], "private, max-age=31536000, immutable")
        self.assertTrue(self.rig.req("GET", "/api/voice/ort.wasm.min.js")[2]["Content-Type"].startswith("text/javascript"))
        self.assertEqual(self.rig.req("GET", "/api/voice/ort-wasm-simd.wasm")[2]["Content-Type"], "application/wasm")
        self.assertEqual(self.rig.req("GET", "/api/voice/voice.onnx")[2]["Content-Type"], "application/octet-stream")
        self.assertEqual(self.rig.req("GET", "/api/voice/voice.onnx", headers={"Range": "bytes=0-9"})[1], self.sim.pack_files["voice.onnx"][:10])
        self.assertEqual(self.rig.req("GET", "/api/voice/agent.db")[0], 404)
        self.assertEqual(self.rig.req("GET", "/api/voice/..%2Fagent.db")[0], 404)
        before = len(self.fetched())
        self.assertEqual(self.get()["state"], "ready")                      # asking again fetches nothing
        self.assertEqual(len(self.fetched()), before)

    def test_the_worker_is_part_of_the_agent_and_may_only_talk_to_it(self):
        status, body, headers = self.rig.req("GET", "/api/voice/worker.js")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"), ia.VOICE_WORKER_JS)
        self.assertEqual(headers["Content-Security-Policy"], "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self'")
        page = self.rig.req("GET", "/")[2]["Content-Security-Policy"]
        self.assertIn("worker-src 'self'", page)
        self.assertIn("connect-src 'self'", page)
        for word in ("http://", "https://", "eval(", "Function("):
            self.assertNotIn(word, ia.VOICE_WORKER_JS)

    def test_the_narrator_files_need_the_login(self):
        rig = Rig(connect=False, auth=True)
        self.addCleanup(rig.close)
        self.assertEqual(rig.req("GET", "/api/voice/worker.js")[0], 401)
        self.assertEqual(rig.req("GET", "/api/voice/voice.onnx")[0], 401)
        self.assertEqual(rig.req("GET", "/api/studio/pack")[0], 401)
        self.assertEqual(rig.req("POST", "/api/studio/pack")[0], 401)

    def test_a_broken_connection_is_picked_up_where_it_stopped(self):
        self.assertGreater(len(self.sim.pack_tgz()), 300)
        self.sim.voice_cut = 200                                           # the archive breaks off after 200 bytes
        self.assertEqual(self.get()["state"], "ready")
        archive = [c for c in self.calls("voice") if c[2] == "pack.tgz"]
        self.assertEqual([c[5].get("range") for c in archive], [None, "bytes=200-"])
        self.assertEqual([c[5].get("range") for c in self.calls("voice") if c[2] != "pack.tgz"], [None] * 3)
        self.assertEqual(self.on_disk(), self.names)
        for name in self.names:
            with open(os.path.join(self.pack.dir, name), "rb") as fh:
                self.assertEqual(fh.read(), self.sim.pack_files[name], name)

    def test_a_file_that_is_not_the_original_is_refused(self):
        good = self.sim.pack_files["voice.onnx"]
        self.sim.pack_files["voice.onnx"] = good[:-1] + b"!"              # same size, one byte changed
        view = self.get()
        self.assertEqual(view["state"], "failed")
        self.assertIn("«voice.onnx» با نسخهٔ اصلی یکی نبود", view["why"])
        self.assertEqual(self.on_disk(), [n for n in self.names if n != "voice.onnx"])
        self.assertEqual(self.rig.req("GET", "/api/voice/ort.wasm.min.js")[0], 404)     # an incomplete narrator is not handed out
        self.assertLess(view["pct"], 100)
        self.sim.pack_files["voice.onnx"] = good
        before = len(self.fetched())
        self.assertEqual(self.get()["state"], "ready")
        self.assertEqual(self.fetched()[before:], ["voice.onnx"])          # only what was missing is fetched

    def test_a_file_of_the_wrong_size_is_refused(self):
        self.sim.pack_files["ort.wasm.min.js"] += b"// more"
        view = self.get()
        self.assertEqual(view["state"], "failed")
        self.assertIn("اندازهٔ فایل روی سرور با نسخهٔ اصلی یکی نبود", view["why"])
        self.assertNotIn("ort.wasm.min.js", self.on_disk())
        self.assertFalse([n for n in self.on_disk() if n.endswith((".part", ".new"))])

    def test_when_a_server_refuses_the_next_one_is_asked(self):
        self.sim.script("voice", 404, {"error": "gone"})                   # the archive is not there (any more)
        self.assertEqual(self.get()["state"], "ready")
        self.assertEqual(self.fetched(), ["pack.tgz", "piper_phonemize.js", "piper_phonemize.wasm", "piper_phonemize.data",
                                          "ort.wasm.min.js", "ort-wasm-simd.wasm", "voice.onnx"])

    def test_a_busy_server_is_asked_again(self):
        self.sim.script("voice", 503, {"error": "busy"}, times=3)
        self.assertEqual(self.get()["state"], "ready")
        self.assertEqual(self.fetched()[:5], ["pack.tgz"] * 4 + ["ort.wasm.min.js"])

    def test_an_archive_that_does_not_open_is_not_the_end(self):
        tgz = self.sim.pack_tgz()
        self.sim.pack_tgz = lambda: b"\x1f\x8b" + b"x" * (len(tgz) - 2)     # right size, not an archive
        self.assertEqual(self.get()["state"], "ready")
        self.assertEqual(self.fetched()[:4], ["pack.tgz", "piper_phonemize.js", "piper_phonemize.wasm", "piper_phonemize.data"])

    def test_when_no_server_answers_the_owner_is_told_and_can_try_again(self):
        self.sim.script("voice", 404, {"error": "gone"}, times=40)
        view = self.get()
        self.assertEqual((view["state"], view["pct"]), ("failed", 0))
        self.assertIn("سرور فایل را نداد (HTTP 404)", view["why"])
        self.assertEqual(self.rig.ok("GET", "/api/status")["studio"]["pack"]["state"], "failed")
        self.sim.ai_script.clear()
        self.assertEqual(self.get()["state"], "ready")

    def test_a_server_that_cannot_be_reached(self):
        self.pack.sources = [("http://127.0.0.1:9/x/", 0, "", tuple(self.names))]
        view = self.get()
        self.assertEqual(view["state"], "failed")
        self.assertIn("به سرور دانلود دسترسی نبود", view["why"])
        self.assertIn("دانلود از همان‌جا ادامه پیدا می‌کند", view["why"])

    def test_an_own_copy_is_asked_first(self):
        self.rig.app.cfg.voice_mirror = self.rig.base + "/_sim/ai/voice"   # AGENT_VOICE_MIRROR
        self.assertEqual(self.get()["state"], "ready")
        self.assertEqual(sorted(self.fetched()), self.names)               # each file by its name; the archive was not needed

    def test_files_copied_by_hand_are_checked_before_they_are_used(self):
        os.makedirs(self.pack.dir)
        for name, blob in self.sim.pack_files.items():
            with open(os.path.join(self.pack.dir, name), "wb") as fh:
                fh.write(blob if name != "voice.onnx" else b"?" * len(blob))
        self.assertEqual(self.rig.ok("GET", "/api/studio/pack")["state"], "ready")      # by size alone it looks complete
        self.assertEqual(self.get()["state"], "ready")
        self.assertEqual(self.fetched(), ["voice.onnx"])                   # the one that was not the original was fetched anew
        with open(os.path.join(self.pack.dir, "voice.onnx"), "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), self.pack.files["voice.onnx"][1])

    def test_no_room_on_the_device(self):
        real, room = shutil.disk_usage, collections.namedtuple("usage", "total used free")
        shutil.disk_usage = lambda path: room(10 ** 9, 10 ** 9 - 1024, 1024)
        self.addCleanup(setattr, shutil, "disk_usage", real)
        view = self.get()
        self.assertEqual(view["state"], "failed")
        self.assertIn("حافظهٔ دستگاه برای گوینده جا ندارد", view["why"])
        self.assertEqual(self.fetched(), [])

    def test_the_download_can_be_stopped_and_the_files_removed(self):
        self.sim.script("voice", 503, {"error": "busy"}, times=4000)       # a download that does not get anywhere
        self.assertEqual(self.rig.ok("POST", "/api/studio/pack")["state"], "loading")
        self.assertEqual(self.rig.ok("POST", "/api/studio/pack")["state"], "loading")   # a second press starts nothing new
        self.rig.ok("POST", "/api/studio/pack/cancel")
        view = self.settle()
        self.assertEqual((view["state"], view["why"]), ("none", ""))       # stopped on request: not a failure
        self.sim.ai_script.clear()
        self.assertEqual(self.get()["state"], "ready")
        view = self.rig.ok("DELETE", "/api/studio/pack")
        self.assertEqual((view["state"], view["pct"]), ("none", 0))
        self.assertEqual(self.on_disk(), [])
        self.assertEqual(self.rig.req("GET", "/api/voice/voice.onnx")[0], 404)
        self.assertEqual(self.rig.ok("DELETE", "/api/studio/pack")["state"], "none")    # removing nothing is fine

    def test_the_progress_is_told_while_it_loads(self):
        seen = []
        real = self.pack.accept

        def slow(path, name):
            seen.append(self.pack.view())
            return real(path, name)

        self.pack.accept = slow
        self.assertEqual(self.get()["state"], "ready")
        self.assertEqual({v["state"] for v in seen}, {"loading"})
        self.assertEqual([v["pct"] for v in seen], sorted(v["pct"] for v in seen))
        self.assertTrue(0 < seen[-1]["pct"] < 100, seen)


if __name__ == "__main__":
    unittest.main()
