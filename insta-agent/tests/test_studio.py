"""Posting by hand (no page connected) and the studio that turns an idea into words and pictures."""
import json
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
        self.assertEqual(len(self.sim.telegram), 1)
        self.assertIn("وقت انتشار", self.sim.telegram[0]["text"])
        self.rig.tick(3)                                                   # told once, not on every round
        self.assertEqual(len(self.sim.telegram), 1)

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
        self.assertEqual(asked["model"], "openai-fast")
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
        old, ia.FREE_GAP = ia.FREE_GAP, 1.2
        self.addCleanup(setattr, ia, "FREE_GAP", old)
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


if __name__ == "__main__":
    unittest.main()
