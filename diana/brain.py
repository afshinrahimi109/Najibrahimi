# -*- coding: utf-8 -*-
"""
🧠 Diana Orchestrator — مغز رهبر سیستم چندعامله دیانا
دقیقاً با الگوی ارکستراتور–کارگر سیستم تحقیقاتی کلود (Anthropic):
  1) رهبر (دیانا) هدف را تحلیل و به زیروظیفه‌های مستقل تجزیه می‌کند
  2) برنامه در حافظه ذخیره می‌شود
  3) ایجنت‌های متخصص به‌صورت موازی و مستقل اجرا می‌شوند
  4) ارزیاب کیفیت هر خروجی را نمره می‌دهد؛ خروجی ضعیف دوباره اجرا می‌شود (retry)
  5) رهبر همه نتایج را ترکیب و گزارش نهایی را تحویل می‌دهد
همه رویدادها زنده (SSE) به صفحه «مرکز فرماندهی» و آکواریوم دیانا مخابره می‌شوند.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import agents as agent_registry
import local_brain
import tools
from llm import LLMClient, DIANA_PERSONA

FA_EN_WORDS = {
    "قلعه": "castle", "کوه": "mountain", "غروب": "sunset", "ماهی": "fish", "دریا": "sea ocean",
    "جنگل": "forest", "شهر": "city", "فضا": "space galaxy", "اژدها": "dragon", "گربه": "cat",
    "سگ": "dog", "گل": "flowers", "درخت": "tree", "خانه": "house", "ماشین": "car", "ربات": "robot",
    "دختر": "girl", "پسر": "boy", "آسمان": "sky", "ستاره": "stars", "ماه": "moon", "خورشید": "sun",
    "رودخانه": "river", "پل": "bridge", "جزیره": "island", "اقیانوس": "ocean", "زیر آب": "underwater",
    "آکواریوم": "aquarium", "طلایی": "golden", "جادویی": "magical", "آتش": "fire", "برف": "snow",
    "باران": "rain", "رنگین کمان": "rainbow", "پروانه": "butterfly", "پرنده": "bird", "اسب": "horse",
    "شیر": "lion", "فیل": "elephant", "موشک": "rocket", "سیاره": "planet", "کتابخانه": "library",
    "باغ": "garden", "صحرا": "desert", "آبشار": "waterfall", "غار": "cave", "کشتی": "ship",
    "هواپیما": "airplane", "قطار": "train", "دوچرخه": "bicycle", "کوهستان": "mountains",
    "طلوع": "sunrise", "شب": "night", "فانوس": "lantern", "مسجد": "mosque", "کاخ": "palace",
    "روستا": "village", "بازار": "bazaar market", "لوگو": "logo design minimal", "پوستر": "poster",
}


class Orchestrator:
    def __init__(self, memory, emit):
        self.memory = memory
        self.emit = emit  # تابع پخش رویداد زنده
        self.llm = LLMClient(memory)
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="diana-agent")
        self._counter = int(time.time()) % 100000
        self._lock = threading.Lock()

    # ================= ورودی اصلی گفتگو =================
    def handle_message(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"kind": "chat", "reply": "🐠 چیزی نگفتی که فرمانده! من اینجام، بگو چی تو ذهنته؟", "source": "local"}
        self.memory.log_chat("user", text)
        intent = local_brain.classify(text)
        kind = intent["kind"]
        name = self.memory.user_name()

        # ---- دستورات کاربردی حافظه ----
        if kind == "set_name":
            self.memory.set_user_name(intent["name"])
            self.memory.add_fact(f"اسم کاربر {intent['name']} است")
            reply = (f"چه اسم قشنگی! 🐠💙 از آشناییت خیلی خوشحالم **{intent['name']}** جان! "
                     f"اسمت رو برای همیشه تو حافظه‌ام ذخیره کردم. حالا بگو اولین مأموریتمون چیه؟")
            self.memory.log_chat("diana", reply, "local")
            return {"kind": kind, "reply": reply, "source": "local"}

        if kind == "remember":
            self.memory.add_fact(intent["fact"])
            reply = f"حتماً! 💾🐠 تو حافظه بلندمدتم ذخیره‌اش کردم: «{intent['fact']}» — دیگه هیچ‌وقت یادم نمیره!"
            self.memory.log_chat("diana", reply, "local")
            return {"kind": kind, "reply": reply, "source": "local"}

        if kind == "reminder":
            self.memory.add_reminder(text)
            reply = "چشم فرمانده! ⏰🐠 این یادآوری رو ثبت کردم و تو صفحه «گاوصندوق و حافظه» همیشه جلو چشممونه."
            self.memory.log_chat("diana", reply, "local")
            return {"kind": kind, "reply": reply, "source": "local"}

        if kind == "recall":
            facts = self.memory.data["facts"][-15:]
            if facts or name:
                lines = ["این چیزاییه که ازت یاد گرفتم و تو حافظه‌ام نگه داشتم 🧠💙:"]
                if name:
                    lines.append(f"• اسم تو **{name}** هست")
                for f in facts:
                    if not f["text"].startswith("اسم کاربر"):
                        lines.append(f"• {f['text']}")
                reply = "\n".join(lines) + "\n\nاگه چیز دیگه‌ای هم باید یادم بمونه بگو: «یادت باشه که...» 🐠"
            else:
                reply = ("هنوز چیزی ازت به خاطرم نسپردی فرمانده 🐠💭\n"
                         "مثلا بگو: «اسمم علی‌ست» یا «یادت باشه که روز تولدم ۵ فروردینه» تا برای همیشه یادم بمونه!")
            self.memory.log_chat("diana", reply, "local")
            return {"kind": kind, "reply": reply, "source": "local"}

        # ---- مأموریت: ورود به چرخه ارکستراتور ----
        if kind == "task":
            mission_id = self.start_mission(text)
            reply = ("چشم فرمانده! 🐠🧠 مأموریت رو گرفتم و دارم تجزیه‌اش می‌کنم...\n\n"
                     "متخصص‌های مناسب رو موازی به کار می‌اندازم، ارزیاب کیفیت روشون نظارت می‌کنه و خودم نتیجه نهایی رو ترکیب می‌کنم. "
                     "تو صفحه **«مرکز فرماندهی»** می‌تونی زنده ببینی مغزم چطور کار می‌کنه! ⚡")
            self.memory.log_chat("diana", reply, "orchestrator")
            return {"kind": "mission", "reply": reply, "mission_id": mission_id, "source": "orchestrator"}

        # ---- گفتگوی آزاد و سؤال: مغز ابری رایگان ← مغز آفلاین ----
        reply, source = self._cloud_chat(text)
        if reply:
            self.memory.log_chat("diana", reply, source)
            return {"kind": kind, "reply": reply, "source": source}
        reply = local_brain.chat_reply(kind, text, self.memory, en=intent.get("en", False))
        upgradeable = kind in ("chat", "question", "greeting", "how_are_you", "identity", "capabilities")
        if not upgradeable:
            self.memory.log_chat("diana", reply, "local")
        return {"kind": kind, "reply": reply, "source": "local", "upgradeable": upgradeable}

    def _cloud_chat(self, text):
        ctx = self.memory.context_for_llm()
        system = DIANA_PERSONA + (("\n\n" + ctx) if ctx else "")
        history = []
        for c in self.memory.recent_chat(8)[:-1]:
            history.append({"role": "user" if c["role"] == "user" else "assistant", "content": c["text"][:1200]})
        history.append({"role": "user", "content": text})
        return self.llm.chat(history, system=system)

    # ================= چرخه مأموریت =================
    def start_mission(self, goal: str, forced_agent_id: str = None) -> str:
        with self._lock:
            self._counter += 1
            mid = f"m{self._counter}"
        mission = {
            "id": mid, "goal": goal, "status": "planning", "plan": [], "results": [],
            "report": "", "score": None,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.memory.add_mission(mission)
        self.emit({"type": "mission_created", "mission": mission})
        t = threading.Thread(target=self._run_mission, args=(mid, goal, forced_agent_id), daemon=True)
        t.start()
        return mid

    def _run_mission(self, mid, goal, forced_agent_id=None):
        try:
            self.emit({"type": "orchestrator_log", "mission_id": mid,
                       "text": "🧠 ارکستراتور: در حال تحلیل هدف و تجزیه به زیروظیفه‌های مستقل..."})
            plan = self.decompose(goal, forced_agent_id)
            self.memory.update_mission(mid, status="running", plan=plan)
            self.emit({"type": "plan_ready", "mission_id": mid, "plan": plan})
            self.emit({"type": "orchestrator_log", "mission_id": mid,
                       "text": f"📋 برنامه آماده شد: {len(plan)} زیروظیفه — اجرا موازی توسط متخصص‌ها شروع می‌شه ⚡"})

            futures = {}
            for sub in plan:
                agent = agent_registry.AGENT_BY_ID[sub["agent_id"]]
                self.emit({"type": "agent_started", "mission_id": mid, "subtask": sub,
                           "agent": self._pub_agent(agent)})
                futures[self.pool.submit(self._execute_with_eval, mid, sub)] = sub

            results = []
            for fut in futures:
                try:
                    results.append(fut.result())
                except Exception as e:
                    sub = futures[fut]
                    results.append({**sub, "ok": False, "output": f"خطای غیرمنتظره: {e}", "score": 0, "verdict": "خطا در اجرا", "artifacts": []})

            order = {s["id"]: i for i, s in enumerate(plan)}
            results.sort(key=lambda r: order.get(r["id"], 99))

            self.emit({"type": "orchestrator_log", "mission_id": mid,
                       "text": "🧠 ارکستراتور: همه متخصص‌ها گزارش دادن — در حال ترکیب نتیجه نهایی..."})
            report, score = self.synthesize(goal, results)
            report_file = tools.vault_write(f"report-{mid}.md", report)
            self.memory.update_mission(mid, status="done", results=results, report=report, score=score, report_file=report_file)
            self.memory.mission_done_inc()
            self.emit({"type": "mission_done", "mission_id": mid, "report": report, "score": score, "report_file": report_file})
            ok_count = sum(1 for r in results if r.get("ok"))
            say = (f"مأموریت با موفقیت تموم شد فرمانده! 🎉🐠 {ok_count} متخصص روی هدفت کار کردن و امتیاز کیفی نهایی {score} از ۱۰۰ شد. "
                   f"گزارش کامل رو همین‌جا و تو «مرکز فرماندهی» گذاشتم و فایلش رو هم تو گاوصندوق ذخیره کردم 📁")
            self.memory.log_chat("diana", say + "\n\n" + report, "orchestrator")
            self.emit({"type": "diana_say", "mission_id": mid, "text": say, "report": report})
        except Exception as e:
            self.memory.update_mission(mid, status="failed", report=f"خطا: {e}")
            self.emit({"type": "mission_failed", "mission_id": mid, "error": str(e)})

    def _pub_agent(self, a):
        return {k: a[k] for k in ("id", "fa", "en", "emoji", "dept", "dept_fa", "color", "executor", "desc")}

    # ---------- تجزیه هدف ----------
    def decompose(self, goal, forced_agent_id=None):
        if forced_agent_id and forced_agent_id in agent_registry.AGENT_BY_ID:
            a = agent_registry.AGENT_BY_ID[forced_agent_id]
            return [{"id": "s1", "title": f"{a['emoji']} {a['fa']}", "instruction": goal, "agent_id": a["id"]}]

        # مسیر هوشمند: تجزیه با LLM
        llm_plan = self._decompose_llm(goal)
        if llm_plan:
            return llm_plan

        # مسیر آفلاین: تجزیه اکتشافی
        parts = [p.strip() for p in re.split(r"(?:\s+و بعد\s+|\s+سپس\s+|؛|;|\n+|\.\s+|\s+and then\s+|\s+then\s+)", goal) if len(p.strip()) > 4]
        subs, used = [], set()
        if len(parts) >= 2:
            for p in parts[:5]:
                best = agent_registry.find_agents(p, 3)
                agent = next((b for b in best if b["id"] not in used), best[0] if best else agent_registry.AGENTS[0])
                used.add(agent["id"])
                subs.append({"id": f"s{len(subs)+1}", "title": f"{agent['emoji']} {agent['fa']}", "instruction": p, "agent_id": agent["id"]})
            return subs

        candidates = agent_registry.find_agents(goal, 10)
        if not candidates:
            candidates = [agent_registry.AGENT_BY_ID["research-01"]]
        main = candidates[0]
        subs.append({"id": "s1", "title": f"{main['emoji']} {main['fa']}", "instruction": goal, "agent_id": main["id"]})
        used.add(main["id"])
        t = agent_registry.norm(goal)
        deep = any(w in t for w in ["جامع", "کامل", "عمیق", "گزارش", "تحقیق", "همه", "دقیق", "حرفه ای", "research", "complete", "full"])
        if deep:
            rest = sorted(candidates[1:], key=lambda c: 0 if c["dept"] == main["dept"] else 1)
            for c in rest:
                if len(subs) >= 4:
                    break
                if c["id"] not in used and c["executor"] != main["executor"]:
                    subs.append({"id": f"s{len(subs)+1}", "title": f"{c['emoji']} {c['fa']}", "instruction": goal, "agent_id": c["id"]})
                    used.add(c["id"])
            if main["dept"] == "research" and "research-10" not in used and len(subs) < 4:
                rep = agent_registry.AGENT_BY_ID["research-10"]
                subs.append({"id": f"s{len(subs)+1}", "title": f"{rep['emoji']} {rep['fa']}",
                             "instruction": f"چارچوب و نکات کلیدی گزارش درباره: {goal}", "agent_id": rep["id"]})
        return subs

    def _decompose_llm(self, goal):
        try:
            depts = "، ".join(f"{d['id']} ({d['fa']})" for d in agent_registry.public_registry()["departments"])
            prompt = (f"هدف کاربر: «{goal}»\n\n"
                      f"این هدف را به حداکثر ۴ زیروظیفه مستقل و موازی تجزیه کن. برای هرکدام یکی از این دپارتمان‌ها را انتخاب کن: {depts}\n"
                      "فقط و فقط یک آرایه JSON برگردان، بدون توضیح اضافه. مثال:\n"
                      '[{"task": "جستجو درباره تاریخچه موضوع", "dept": "research"}, {"task": "نوشتن متن نهایی", "dept": "writing"}]')
            txt, _src = self.llm.generate(prompt, system="تو مغز ارکستراتور یک سیستم چندعامله هستی و فقط JSON برمی‌گردانی.")
            if not txt:
                return None
            m = re.search(r"\[.*\]", txt, re.S)
            if not m:
                return None
            items = json.loads(m.group(0))
            subs, used = [], set()
            for it in items[:5]:
                task = str(it.get("task", "")).strip()
                dept = str(it.get("dept", "")).strip()
                if not task:
                    continue
                cands = [a for a in agent_registry.find_agents(task + " " + goal, 8) if a["dept"] == dept] or agent_registry.find_agents(task, 3)
                agent = next((c for c in cands if c["id"] not in used), cands[0] if cands else agent_registry.AGENTS[0])
                used.add(agent["id"])
                subs.append({"id": f"s{len(subs)+1}", "title": f"{agent['emoji']} {agent['fa']}", "instruction": task, "agent_id": agent["id"]})
            return subs or None
        except Exception:
            return None

    # ---------- اجرا + ارزیابی + تلاش مجدد ----------
    def _execute_with_eval(self, mid, sub):
        agent = agent_registry.AGENT_BY_ID[sub["agent_id"]]
        result = self.execute(agent, sub["instruction"])
        score, verdict = self.evaluate(agent, sub["instruction"], result)
        self.emit({"type": "evaluation", "mission_id": mid, "subtask_id": sub["id"],
                   "agent_id": agent["id"], "score": score, "verdict": verdict, "attempt": 1})
        if score < 55:
            self.emit({"type": "orchestrator_log", "mission_id": mid,
                       "text": f"⚠️ ارزیاب کیفیت: خروجی {agent['fa']} امتیاز {score} گرفت — ارکستراتور دستور اجرای مجدد با روش جایگزین داد 🔁"})
            retry_agent = dict(agent)
            retry_agent["executor"] = "llm" if agent["executor"] != "llm" else ("data" if tools.find_math_expr(sub["instruction"]) else "text")
            r2 = self.execute(retry_agent, sub["instruction"])
            s2, v2 = self.evaluate(agent, sub["instruction"], r2)
            self.emit({"type": "evaluation", "mission_id": mid, "subtask_id": sub["id"],
                       "agent_id": agent["id"], "score": s2, "verdict": v2, "attempt": 2})
            if s2 > score:
                result, score, verdict = r2, s2, v2 + " (تلاش دوم)"
        self.memory.bump_agent_stat(agent["id"])
        out = {**sub, "ok": result.get("ok", False), "output": result.get("output", ""),
               "artifacts": result.get("artifacts", []), "score": score, "verdict": verdict,
               "agent": self._pub_agent(agent)}
        self.emit({"type": "agent_done", "mission_id": mid, "result": out})
        return out

    def evaluate(self, agent, instruction, result):
        out = (result.get("output") or "").strip()
        score = 0
        notes = []
        if result.get("ok"):
            score += 50
            notes.append("اجرا موفق")
        else:
            notes.append("اجرا ناقص")
        if len(out) > 35:
            score += 18
        if len(out) > 250:
            score += 12
        if len(out) > 600:
            score += 8
        if result.get("artifacts"):
            score += 12
            notes.append("دارای خروجی قابل تحویل")
        if any(w in out for w in ["خطا", "Error", "Traceback", "ناموفق"]):
            score -= 25
            notes.append("دارای خطا")
        if "آفلاین" in out:
            score -= 8
            notes.append("حالت آفلاین")
        if result.get("generic"):
            score -= 25
            notes.append("خروجی قالبی (نیازمند مغز ابری)")
        if "خروجی واقعی اجرا" in out or "اجرا موفق" in out:
            score += 8
            notes.append("اجرای واقعی تأیید شد")
        score = max(0, min(100, score))
        level = "عالی 🌟" if score >= 85 else "خوب ✅" if score >= 70 else "قابل قبول 👍" if score >= 55 else "ضعیف ⚠️"
        return score, f"{level} — {'، '.join(notes)}"

    # ---------- ترکیب نهایی ----------
    def synthesize(self, goal, results):
        score = round(sum(r.get("score", 0) for r in results) / len(results)) if results else 0
        sections = []
        for r in results:
            a = r.get("agent", {})
            sections.append(f"### {a.get('emoji','🤖')} {a.get('fa','ایجنت')} — امتیاز ارزیاب: {r.get('score',0)}/۱۰۰\n{r.get('output','')}")
        body = "\n\n---\n\n".join(sections)

        conclusion = None
        try:
            brief = "\n\n".join(f"[{r.get('agent',{}).get('fa','')}]: {(r.get('output') or '')[:700]}" for r in results)
            prompt = (f"هدف کاربر: «{goal}»\n\nنتایج متخصص‌ها:\n{brief}\n\n"
                      "به‌عنوان دیانا (مغز رهبر)، یک جمع‌بندی نهایی فارسی، گرم و کاربردی بنویس: مهم‌ترین نتیجه چیه و کاربر الان چی داره. حداکثر ۶ خط.")
            conclusion, _ = self.llm.generate(prompt, system=DIANA_PERSONA)
        except Exception:
            conclusion = None
        if not conclusion:
            ok_agents = "، ".join(r.get("agent", {}).get("fa", "") for r in results if r.get("ok"))
            conclusion = (f"مأموریت «{goal}» توسط تیم متخصص‌ها ({ok_agents or '—'}) انجام شد. "
                          f"امتیاز کیفی میانگین ارزیاب: **{score} از ۱۰۰**. جزئیات کامل هر متخصص اینجاست و فایل گزارش هم در گاوصندوق ذخیره شد 📁🐠")

        report = (f"# 🎁 گزارش نهایی مأموریت دیانا\n\n**🎯 هدف فرمانده:** {goal}\n\n"
                  f"**📊 امتیاز کیفی نهایی:** {score}/۱۰۰\n\n## 🐠 جمع‌بندی دیانا\n{conclusion}\n\n"
                  f"## 👥 نتایج متخصص‌ها\n\n{body}\n")
        return report, score

    # ================= موتورهای اجرایی ایجنت‌ها =================
    def execute(self, agent, instruction):
        ex = agent.get("executor", "llm")
        fn = {
            "llm": self.exec_llm, "web": self.exec_web, "coder": self.exec_coder,
            "data": self.exec_data, "text": self.exec_text, "files": self.exec_files,
            "memory": self.exec_memory, "planner": self.exec_planner,
            "artist": self.exec_artist, "system": self.exec_system,
        }.get(ex, self.exec_llm)
        try:
            return fn(agent, instruction)
        except Exception as e:
            return {"ok": False, "output": f"در اجرای {agent['fa']} خطایی رخ داد: {e}", "artifacts": []}

    def _agent_system(self, agent):
        return (f"تو «{agent['fa']}» ({agent['en']}) هستی؛ یکی از ۱۲۰ ایجنت متخصص سیستم دیانا در دپارتمان «{agent['dept_fa']}».\n"
                f"تخصص تو: {agent['desc']}\n"
                "فقط روی وظیفه خودت تمرکز کن و خروجی کامل، حرفه‌ای و کاربردی به فارسی (یا زبان کاربر) تحویل بده. از قالب‌بندی Markdown استفاده کن.")

    def exec_llm(self, agent, instruction):
        txt, src = self.llm.generate(instruction, system=self._agent_system(agent))
        if txt:
            return {"ok": True, "output": txt, "artifacts": []}
        # --- پشتیبان آفلاین: تولید ساخت‌یافته بر اساس نوع وظیفه ---
        subject = tools.extract_subject_text(instruction)
        lines = [f"**{agent['emoji']} گزارش {agent['fa']}** *(حالت آفلاین — مغز ابری در دسترس نیست، اما ابزارهای واقعی من کار می‌کنن)*\n"]
        if subject:
            st = tools.text_stats(subject)
            lines.append(f"**تحلیل متن دریافتی:** {st['words']} واژه، {st['sentences']} جمله، زمان مطالعه ~{st['reading_minutes']} دقیقه")
            lines.append("\n**خلاصه استخراجی متن:**\n" + tools.summarize_text(subject, 4))
            if st["top_words"]:
                lines.append("\n**واژه‌های کلیدی:** " + "، ".join(f"{w} ({c})" for w, c in st["top_words"]))
            return {"ok": True, "output": "\n".join(lines), "artifacts": []}
        topic = re.sub(r"(بنویس|بساز|انجام بده|درست کن|لطفا|لطفاً|درباره|در مورد|تحقیق کن|گزارش کامل بده|گزارش بده)", " ", instruction)
        topic = re.sub(r"\s+", " ", topic).strip()
        topic = re.sub(r"\s+(و|رو|را)$", "", topic)[:120] or instruction[:120]
        lines.append(f"**موضوع مأموریت:** {topic}\n")
        dept = agent.get("dept", "")
        if dept in ("research", "education"):
            lines.append(f"**🔬 چارچوب پژوهشی «{topic}»:**\n"
                         f"۱. **{topic} چیست؟** تعریف دقیق و ساده موضوع\n"
                         f"۲. **پیشینه و تاریخچه:** {topic} از کجا آمد و چطور شکل گرفت؟\n"
                         f"۳. **اجزا و سازوکار:** مهم‌ترین بخش‌ها و نحوه کارکرد\n"
                         f"۴. **کاربردها و اهمیت:** چرا {topic} در زندگی و علم مهم است؟\n"
                         f"۵. **چالش‌ها و پرسش‌های باز:** نکات بحث‌برانگیز و ناشناخته‌ها\n"
                         f"۶. **آینده و چشم‌انداز:** مسیر پیش‌روی این حوزه\n\n"
                         "📌 *با اتصال اینترنت سرور، برای هر بخش منابع واقعی وب و ویکی‌پدیا با لینک می‌آورم.*")
        elif dept in ("writing", "marketing", "admin"):
            lines.append(f"**✍️ اسکلت محتوای «{topic}»:**\n"
                         "• **قلاب شروع:** یک جمله قدرتمند که مخاطب را نگه می‌دارد\n"
                         "• **بدنه اصلی:** ۳ نکته کلیدی با مثال ملموس\n"
                         "• **نقطه اوج احساسی/منطقی:** مهم‌ترین پیام متن\n"
                         "• **پایان‌بندی و دعوت به اقدام:** قدم بعدی خواننده چیست؟\n\n"
                         "📌 *با مغز ابری، همین اسکلت را به متن کامل و آماده انتشار تبدیل می‌کنم.*")
        elif dept in ("business",):
            lines.append(f"**💼 چارچوب تحلیل «{topic}»:**\n"
                         "• **فرصت بازار:** اندازه تقاضا و مشتری هدف\n"
                         "• **مدل درآمدی:** پول از کجا و چطور می‌آید؟\n"
                         "• **هزینه‌های کلیدی و نقطه سربه‌سر**\n"
                         "• **مزیت رقابتی و ریسک‌های اصلی**\n"
                         "• **نقشه راه ۹۰ روزه اجرا**\n\n"
                         "📌 *با مغز ابری، تحلیل کامل با اعداد و سناریوهای مالی می‌سازم.*")
        elif dept in ("life",):
            lines.append(f"**🏠 نقشه عملی «{topic}»:**\n"
                         "• **قدم صفر:** آماده‌سازی و وسایل لازم\n"
                         "• **قدم‌های اصلی به ترتیب:** از ساده‌ترین شروع کن\n"
                         "• **نکات طلایی حرفه‌ای‌ها**\n"
                         "• **اشتباهات رایجی که باید ازشون دوری کرد**\n\n"
                         "📌 *با مغز ابری، نسخه قدم‌به‌قدم کامل و شخصی‌سازی‌شده می‌دهم.*")
        elif dept in ("creative",):
            lines.append(f"**🎨 بوم ایده «{topic}»:**\n"
                         "• **کانسپت مرکزی:** یک تصویر/ایده فراموش‌نشدنی\n"
                         "• **پالت رنگ و حال‌وهوا**\n"
                         "• **سه جهت خلاقانه متفاوت برای انتخاب**\n"
                         "• **جزئیات امضادار که اثر را خاص می‌کند**\n\n"
                         "📌 *برای ساخت تصویر واقعی، ایجنت‌های نقاش من همین حالا هم آنلاینن!*")
        else:
            lines.append("**چارچوب اجرایی پیشنهادی من:**\n"
                         "۱. **تعریف دقیق خروجی:** مشخص‌کردن قالب و مخاطب نتیجه نهایی\n"
                         "۲. **جمع‌آوری مواد اولیه:** نکات و داده‌های کلیدی مرتبط با موضوع\n"
                         "۳. **ساخت نسخه اول:** تولید پیش‌نویس کامل بر اساس چارچوب\n"
                         "۴. **بازبینی و صیقل:** بهبود کیفیت، لحن و ساختار\n"
                         "۵. **تحویل:** ارائه نسخه نهایی آماده استفاده")
        lines.append("\n💡 *به‌محض اتصال اینترنت سرور (یا افزودن کلید رایگان Groq/Gemini در تنظیمات)، همین وظیفه را با مغز ابری و کیفیت کامل بازتولید می‌کنم.*")
        return {"ok": True, "output": "\n".join(lines), "artifacts": [], "generic": True}

    def exec_web(self, agent, instruction):
        url = tools.extract_url(instruction)
        if url:
            if not tools.internet_available():
                return {"ok": False, "output": "🌐 سرور در این لحظه به اینترنت دسترسی نداره و نتونستم صفحه رو بخونم. وقتی دیانا روی هاست اینترنتی اجرا بشه، خوندن لینک‌ها کامل کار می‌کنه.", "artifacts": []}
            page = tools.fetch_url(url)
            summary = tools.summarize_text(page["text"], 6)
            return {"ok": True, "output": f"**🌐 صفحه خوانده شد:** [{page['title']}]({page['url']})\n\n**خلاصه محتوای صفحه:**\n{summary}", "artifacts": [{"type": "link", "url": page["url"], "title": page["title"]}]}
        if not tools.internet_available():
            return {"ok": False, "output": "🌐 جستجوی زنده وب نیاز به اینترنت سرور داره که الان در دسترس نیست. روی هاست اینترنتی یا با اجرای محلیِ وصل به اینترنت، من واقعاً در وب و ویکی‌پدیا جستجو می‌کنم و منابع رو با لینک میارم.", "artifacts": []}
        query = re.sub(r"(درباره|تحقیق کن|جستجو کن|سرچ کن|بگرد|پیدا کن|بررسی کن|اطلاعات|در مورد|راجع به|لطفا|لطفاً|به من بگو)", " ", instruction)
        query = re.sub(r"\s+", " ", query).strip()[:120] or instruction[:120]
        wiki = tools.wiki_search(query, limit=3)
        web = tools.web_search(query, limit=4)
        items = wiki + web
        if not items:
            return {"ok": False, "output": f"🔍 برای «{query}» نتیجه قابل اتکایی پیدا نکردم. موضوع رو دقیق‌تر بگو تا عمیق‌تر بگردم.", "artifacts": []}
        out = [f"**🔍 نتایج جستجوی زنده برای:** «{query}»\n"]
        for it in items:
            out.append(f"**[{it['title']}]({it['url']})** — *{it['source']}*\n{it['text']}")
        artifacts = [{"type": "link", "url": it["url"], "title": it["title"]} for it in items]
        return {"ok": True, "output": "\n\n".join(out), "artifacts": artifacts}

    def exec_coder(self, agent, instruction):
        code = tools.extract_code(instruction)
        if code:
            r = tools.run_python(code)
            status = "✅ اجرا موفق بود" if r["ok"] else "❌ اجرا با خطا مواجه شد"
            out = f"**{status}** — کد شما واقعاً روی سرور اجرا شد:\n\n```python\n{code}\n```\n\n**خروجی:**\n```\n{r['stdout'] or '(بدون خروجی)'}\n```"
            if r["stderr"]:
                out += f"\n\n**خطا:**\n```\n{r['stderr']}\n```"
            return {"ok": r["ok"], "output": out, "artifacts": []}

        expr = tools.find_math_expr(instruction)
        if expr and re.search(r"\d", expr):
            try:
                val = tools.safe_calc(expr)
                return {"ok": True, "output": f"🧮 محاسبه با اجرای واقعی:\n\n`{expr.strip()}` = **{val}**", "artifacts": []}
            except Exception:
                pass

        # تولید کد با مغز ابری
        txt, _ = self.llm.generate(
            f"وظیفه: {instruction}\n\nبرنامه پایتون کاملی بنویس که این کار را انجام دهد و نتیجه را print کند. فقط یک بلوک کد ```python برگردان، بدون توضیح.",
            system=self._agent_system(agent))
        gen = tools.extract_code(txt or "")
        if not gen:
            gen = self._heuristic_program(instruction)
        if not gen:
            return {"ok": False, "output": "💻 برای نوشتن این برنامه خاص به مغز ابری نیاز دارم که الان آفلاینه. اما اگه کد آماده بدی فوراً اجراش می‌کنم، یا مسائل کلاسیک (اعداد اول، فیبوناچی، فاکتوریل، جدول ضرب، مرتب‌سازی) رو آفلاین هم می‌نویسم و اجرا می‌کنم!", "artifacts": []}
        r = tools.run_python(gen)
        if not r["ok"] and txt:
            fix, _ = self.llm.generate(f"این کد خطا داده. اصلاحش کن و فقط بلوک کد برگردان:\n\n```python\n{gen}\n```\n\nخطا:\n{r['stderr']}", system=self._agent_system(agent))
            fixed = tools.extract_code(fix or "")
            if fixed:
                r = tools.run_python(fixed)
                gen = fixed
        fname = tools.vault_write(f"program-{int(time.time())%100000}.py", gen)
        status = "✅ برنامه نوشته و با موفقیت اجرا شد" if r["ok"] else "⚠️ برنامه نوشته شد ولی در اجرا خطا داد"
        out = (f"**{status}** و فایلش در گاوصندوق ذخیره شد (`{fname}`):\n\n```python\n{gen}\n```\n\n"
               f"**🖥️ خروجی واقعی اجرا:**\n```\n{r['stdout'] or '(بدون خروجی)'}\n```")
        if r["stderr"]:
            out += f"\n\n**خطا:**\n```\n{r['stderr']}\n```"
        return {"ok": r["ok"], "output": out, "artifacts": [{"type": "file", "name": fname}]}

    def _heuristic_program(self, instruction):
        t = agent_registry.norm(instruction)
        nums = re.findall(r"\d+", t.replace("۰", "0").replace("۱", "1").replace("۲", "2").replace("۳", "3").replace("۴", "4").replace("۵", "5").replace("۶", "6").replace("۷", "7").replace("۸", "8").replace("۹", "9"))
        n = int(nums[0]) if nums else 100
        if "اعداد اول" in t or "عدد اول" in t or "prime" in t:
            return (f"# یافتن اعداد اول تا {n}\ndef is_prime(x):\n    if x < 2: return False\n"
                    f"    for i in range(2, int(x**0.5)+1):\n        if x % i == 0: return False\n    return True\n\n"
                    f"primes = [x for x in range(2, {n}+1) if is_prime(x)]\nprint(primes)\nprint('تعداد اعداد اول:', len(primes))")
        if "مجموع" in t and ("تا" in t or "اعداد" in t):
            return f"n = {n}\nprint(f'مجموع اعداد ۱ تا {{n}} =', n*(n+1)//2)\nprint('بررسی با حلقه:', sum(range(1, n+1)))"
        if "ب م م" in t or "بزرگترین مقسوم" in t or "gcd" in t:
            a = int(nums[0]) if len(nums) > 0 else 48
            b = int(nums[1]) if len(nums) > 1 else 36
            return f"import math\na, b = {a}, {b}\nprint('ب.م.م:', math.gcd(a, b))\nprint('ک.م.م:', a*b//math.gcd(a, b))"
        if "پالیندروم" in t or "معکوس" in t:
            return ("def reverse(s): return s[::-1]\nwords = ['گرگ', 'دنیا', 'کیک', 'سلام']\n"
                    "for w in words:\n    print(w, '← معکوس:', reverse(w), '| متقارن است؟', w == reverse(w))")
        if ("زوج" in t or "فرد" in t) and "برنامه" in t:
            return (f"evens = [x for x in range(1, {n}+1) if x % 2 == 0]\n"
                    f"odds = [x for x in range(1, {n}+1) if x % 2 == 1]\n"
                    "print('زوج‌ها:', evens)\nprint('فردها:', odds)")
        if "فیبوناچی" in t or "fibonacci" in t:
            c = n if n <= 100 else 20
            return (f"# دنباله فیبوناچی — {c} جمله اول\na, b, seq = 0, 1, []\nfor _ in range({c}):\n"
                    "    seq.append(a)\n    a, b = b, a+b\nprint(seq)")
        if "فاکتوریل" in t or "factorial" in t:
            v = n if n <= 500 else 20
            return f"import math\nn = {v}\nprint(f'{{n}}! =', math.factorial(n))"
        if "جدول ضرب" in t:
            v = n if n <= 20 else 10
            return (f"# جدول ضرب تا {v}\nfor i in range(1, {v}+1):\n    print(' | '.join(f'{{i}}x{{j}}={{i*j}}' for j in range(1, {v}+1)))")
        if "مرتب" in t or "sort" in t:
            data = [int(x) for x in nums] or [42, 7, 19, 3, 88, 25, 1, 56]
            return f"data = {data}\nprint('قبل:', data)\ndata.sort()\nprint('بعد از مرتب‌سازی:', data)"
        if "شانس" in t or "تصادفی" in t or "random" in t or "تاس" in t:
            return ("import random\nprint('🎲 تاس:', random.randint(1,6))\nprint('🎲 تاس دوم:', random.randint(1,6))\n"
                    "print('🔢 ده عدد تصادفی ۱ تا ۱۰۰:', [random.randint(1,100) for _ in range(10)])")
        return None

    def exec_data(self, agent, instruction):
        parts = []
        conv = tools.convert_units(instruction)
        if conv:
            parts.append(f"**{conv}**")
        m = re.search(r"([\d\.]+)\s*درصد\s+(?:از\s+)?([\d\.]+)", instruction.replace(",", ""))
        if m:
            p, base = float(m.group(1)), float(m.group(2))
            parts.append(f"🧮 **{p:g} درصد از {base:,}** = **{base*p/100:,}**")
        expr = tools.find_math_expr(instruction)
        if expr and re.search(r"[\+\-\*/\^\(\)]", expr):
            try:
                val = tools.safe_calc(expr)
                parts.append(f"🧮 **محاسبه:** `{expr.strip()}` = **{val}**")
            except Exception:
                pass
        # آمار: اگه «میانگین/مجموع اعداد» گفته شده، اعداد بعد از اون بخش رو تحلیل کن
        stat_text = instruction
        sm = re.search(r"(میانگین|معدل|مجموع|آمار|تحلیل)\s*(?:اعداد|عددهای)?\s*[:：]?\s*(.+)", instruction)
        if sm and re.search(r"\d", sm.group(2)):
            stat_text = sm.group(2)
        stats = tools.number_stats(stat_text)
        if stats and (sm or not parts):
            chart = tools.text_chart(stats["numbers"])
            parts.append(f"**📊 تحلیل آماری {stats['count']} عدد** ({'، '.join(f'{x:g}' for x in stats['numbers'][:12])}):\n\n"
                         f"• مجموع: **{stats['sum']:g}**\n• میانگین: **{stats['mean']:.2f}**\n• میانه: **{stats['median']:g}**\n"
                         f"• کمترین: **{stats['min']:g}** | بیشترین: **{stats['max']:g}** | دامنه: **{stats['range']:g}**\n"
                         f"• انحراف معیار: **{stats['stdev']:.2f}**\n\n**نمودار:**\n```\n{chart}\n```")
        if parts:
            return {"ok": True, "output": "\n\n---\n\n".join(parts), "artifacts": []}
        return self.exec_llm(agent, instruction)

    def exec_text(self, agent, instruction):
        url = tools.extract_url(instruction)
        subject = tools.extract_subject_text(instruction)
        if url and tools.internet_available():
            page = tools.fetch_url(url)
            subject = page["text"]
        if subject and len(subject) > 60:
            st = tools.text_stats(subject)
            summary = tools.summarize_text(subject, 5)
            out = (f"**📄 تحلیل متن انجام شد:** {st['words']} واژه | {st['sentences']} جمله | {st['unique_words']} واژه یکتا | زمان مطالعه ~{st['reading_minutes']} دقیقه\n\n"
                   f"**📃 خلاصه:**\n{summary}")
            if st["top_words"]:
                out += "\n\n**🔑 واژه‌های کلیدی:** " + "، ".join(f"{w} ({c} بار)" for w, c in st["top_words"])
            fname = tools.vault_write(f"summary-{int(time.time())%100000}.txt", summary)
            out += f"\n\n📁 خلاصه در گاوصندوق ذخیره شد: `{fname}`"
            return {"ok": True, "output": out, "artifacts": [{"type": "file", "name": fname}]}
        return self.exec_llm(agent, instruction)

    def exec_files(self, agent, instruction):
        t = agent_registry.norm(instruction)
        files = tools.vault_list()
        wants_create = any(w in t for w in ["بساز", "درست کن", "ایجاد", "بنویس", "ذخیره کن", "ثبت کن"])
        if not wants_create and any(w in t for w in ["لیست فایل", "چه فایل", "فایل ها", "فایل‌ها", "نشون بده فایل", "فایل ها رو", "list"]):
            if not files:
                return {"ok": True, "output": "📁 گاوصندوق فعلاً خالیه فرمانده! بگو چه فایلی بسازم تا اولین سندت رو ذخیره کنم.", "artifacts": []}
            lines = "\n".join(f"• `{f['name']}` — {f['size']} بایت — {f['modified']}" for f in files)
            return {"ok": True, "output": f"**📁 فایل‌های گاوصندوق دیانا ({len(files)} فایل):**\n\n{lines}", "artifacts": []}
        if any(w in t for w in ["بخون", "بخوان", "باز کن", "محتوای", "read"]):
            for f in files:
                if f["name"].lower() in instruction.lower():
                    content = tools.vault_read(f["name"]) or ""
                    return {"ok": True, "output": f"**📄 محتوای `{f['name']}`:**\n\n{content[:3000]}", "artifacts": [{"type": "file", "name": f["name"]}]}
        # ساخت فایل
        m = re.search(r"فایل(?:ی)?\s+(?:به نام\s+)?[«\"]?([^\s»\"]+)", instruction)
        name = m.group(1) if m else f"note-{datetime.now().strftime('%H%M%S')}.txt"
        if "." not in name:
            name += ".txt"
        content_m = re.search(r"(?:با محتوای|محتوا|بنویس(?:\s+که)?)[:：]?\s*(.+)", instruction, re.S)
        content = content_m.group(1).strip() if content_m and len(content_m.group(1).strip()) > 3 else None
        if not content:
            txt, _ = self.llm.generate(f"یک متن کامل و مفید برای ذخیره در فایل بنویس. موضوع درخواست کاربر: {instruction}", system=self._agent_system(agent))
            content = txt or f"یادداشت دیانا\n{'='*30}\nدرخواست فرمانده: {instruction}\nتاریخ ثبت: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        fname = tools.vault_write(name, content)
        return {"ok": True, "output": f"**📁 فایل با موفقیت در گاوصندوق دیانا ساخته شد:** `{fname}`\n\nمی‌تونی از صفحه «گاوصندوق و حافظه» دانلودش کنی.\n\n**پیش‌نمایش:**\n{content[:600]}", "artifacts": [{"type": "file", "name": fname}]}

    def exec_memory(self, agent, instruction):
        t = agent_registry.norm(instruction)
        if any(w in t for w in ["یادته", "یادت هست", "چی میدونی", "یادآوری", "recall", "remember what"]):
            found = self.memory.recall(instruction)
            facts = self.memory.data["facts"][-10:]
            if found:
                return {"ok": True, "output": "**🧠 از حافظه‌ام پیدا کردم:**\n\n" + "\n".join(f"• {f['text']} *(ثبت: {f['ts']})*" for f in found), "artifacts": []}
            if facts:
                return {"ok": True, "output": "**🧠 آخرین چیزهایی که ازت یاد گرفتم:**\n\n" + "\n".join(f"• {f['text']}" for f in facts), "artifacts": []}
            return {"ok": True, "output": "🧠 حافظه‌ام هنوز خالیه فرمانده! هرچی بگی «یادت باشه که...» برای همیشه ذخیره‌اش می‌کنم.", "artifacts": []}
        fact = re.sub(r"(یادت باشه که|یادت باشه|به خاطر بسپار که|به خاطر بسپار|ذخیره کن که|یاد بگیر)", "", instruction).strip()
        self.memory.add_fact(fact)
        return {"ok": True, "output": f"**💾 در حافظه بلندمدت دیانا ذخیره شد:**\n\n«{fact}»\n\nاز حالا به بعد تو همه گفتگوها و مأموریت‌ها این رو به یاد دارم 🐠", "artifacts": []}

    def exec_planner(self, agent, instruction):
        txt, _ = self.llm.generate(
            f"یک برنامه اجرایی کامل و قدم‌به‌قدم فارسی بساز برای: {instruction}\n"
            "شامل: هدف نهایی، فازها با زمان‌بندی، چک‌لیست کارها با ☐، نکات طلایی و اشتباهات رایج. Markdown تمیز.",
            system=self._agent_system(agent))
        if not txt and any(w in instruction for w in ["سفر", "مسافرت", "گردش"]):
            days_m = re.search(r"(\d+)\s*روز", instruction)
            days = int(days_m.group(1)) if days_m else 3
            dest_m = re.search(r"به\s+([^\s،.]+)", instruction)
            dest = dest_m.group(1) if dest_m else "مقصد"
            day_blocks = "\n".join(
                f"## روز {i} — {'رسیدن و آشنایی با شهر 🚶' if i == 1 else 'گشت اصلی و جاهای دیدنی 📸' if i < days else 'خرید سوغات و بازگشت 🧳'}\n"
                f"☐ صبحانه محلی و شروع گشت\n☐ بازدید از مهم‌ترین جاذبه‌های {dest}\n☐ ناهار در رستوران محلی معروف\n☐ گشت عصرگاهی و عکاسی\n"
                for i in range(1, days + 1))
            txt = (f"# ✈️ برنامه سفر {days} روزه به {dest}\n\n"
                   "## 🎒 قبل از حرکت\n☐ رزرو اقامت نزدیک مرکز شهر\n☐ بلیط رفت‌وبرگشت\n☐ لیست وسایل: شارژر، کفش راحت، داروهای ضروری، پول نقد کم\n\n"
                   + day_blocks +
                   "\n## 💰 مدیریت بودجه\n• اقامت اقتصادی نزدیک حمل‌ونقل عمومی\n• غذاهای محلی به‌جای رستوران توریستی\n• بازدیدها را بر اساس نزدیکی مکانی گروه‌بندی کن تا هزینه رفت‌وآمد کم شود\n\n"
                   "💡 *(اسکلت آفلاین سفر است؛ با مغز ابری، نام دقیق جاذبه‌ها، ساعت بازدید و هزینه هر روز را کامل می‌کنم)*")
        if not txt:
            goal = re.sub(r"(برنامه|برنامه ریزی|بچین|بساز|کن|برای)", " ", instruction).strip()[:100] or instruction[:100]
            txt = (f"# 🗓️ برنامه اجرایی: {goal}\n\n"
                   "## 🎯 هدف نهایی\nرسیدن به نتیجه مطلوب با قدم‌های کوچک و پیوسته.\n\n"
                   "## فاز ۱ — آماده‌سازی (روزهای ۱ تا ۳)\n☐ مشخص‌کردن دقیق هدف و معیار موفقیت\n☐ جمع‌آوری ابزار و منابع لازم\n☐ حذف موانع و مزاحمت‌ها\n\n"
                   "## فاز ۲ — اجرای اصلی (هفته ۱ و ۲)\n☐ شروع با کوچک‌ترین قدم ممکن (قانون ۲ دقیقه)\n☐ اجرای روزانه در ساعت ثابت\n☐ ثبت پیشرفت هر روز\n\n"
                   "## فاز ۳ — تثبیت و بهینه‌سازی (هفته ۳ و ۴)\n☐ مرور نتایج و اصلاح مسیر\n☐ افزایش تدریجی سطح دشواری\n☐ جشن‌گرفتن موفقیت‌های کوچک 🎉\n\n"
                   "## 💡 نکات طلایی\n• استمرار مهم‌تر از شدت است\n• پیشرفت ۱٪ روزانه = ۳۷ برابر در سال\n• محیط را طوری بچین که مسیر درست، آسان‌ترین مسیر باشد\n\n"
                   "*(این چارچوب آفلاین ساخته شد؛ با مغز ابری، نسخه کاملاً شخصی‌سازی‌شده می‌سازم)*")
        fname = tools.vault_write(f"plan-{int(time.time())%100000}.md", txt)
        return {"ok": True, "output": txt + f"\n\n📁 این برنامه در گاوصندوق ذخیره شد: `{fname}`", "artifacts": [{"type": "file", "name": fname}]}

    def exec_artist(self, agent, instruction):
        prompt_en = None
        txt, _ = self.llm.generate(
            f"Convert this image request into ONE detailed English image-generation prompt (only the prompt, no quotes, no explanation): {instruction}",
            system="You translate image requests into vivid English prompts for an image generator.")
        if txt and len(txt) > 8:
            prompt_en = txt.strip().strip('"')[:280]
        if not prompt_en:
            words = []
            padded = " " + re.sub(r"[،؛.!؟?()«»]", " ", instruction) + " "
            for fa, en in FA_EN_WORDS.items():
                if f" {fa} " in padded or f" {fa}‌" in padded:
                    words.append(en)
            latin = re.findall(r"[A-Za-z]{3,}", instruction)
            words.extend(latin)
            prompt_en = (", ".join(words) + ", beautiful detailed digital art, vibrant colors, high quality") if words else \
                        "a magical golden fish in a beautiful underwater kingdom, vibrant colors, digital art"
        url = tools.image_url(prompt_en)
        out = (f"**🎨 تصویر شما ساخته شد!**\n\n![تصویر ساخته دیانا]({url})\n\n"
               f"پرامپت اثر: *{prompt_en}*\n\n💡 اگه دوست داشتی بگو «یکی دیگه با سبک متفاوت بساز» تا نسخه تازه خلق کنم!")
        return {"ok": True, "output": out, "artifacts": [{"type": "image", "url": url, "prompt": prompt_en}]}

    def exec_system(self, agent, instruction):
        info = tools.system_info()
        name = self.memory.user_name()
        out = (f"**🖥️ وضعیت زنده سیستم دیانا:**\n\n"
               f"• سیستم‌عامل سرور: **{info['platform']}** ({info['machine']})\n"
               f"• موتور اجرا: Python {info['python']}\n"
               f"• ساعت سرور: **{info['time']}**\n"
               f"• فضای آزاد دیسک: **{info['disk_free_gb']} گیگابایت** از {info['disk_total_gb']}\n"
               f"• اینترنت سرور: **{'متصل ✅' if info['internet'] else 'قطع (حالت آفلاین) 📴'}**\n"
               f"• مغز فعال: **{self.llm.mode()}**\n"
               f"• فایل‌های گاوصندوق: **{info['vault_files']}** فایل\n"
               f"• ایجنت‌های ارتش: **{len(agent_registry.AGENTS)} متخصص** در {len(agent_registry.DEPARTMENTS)} دپارتمان\n"
               f"• فرمانده: **{name or 'هنوز خودش رو معرفی نکرده'}** 🐠")
        return {"ok": True, "output": out, "artifacts": []}
