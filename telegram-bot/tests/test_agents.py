import asyncio
import unittest

from agents import run_specialist_mission


class MultiAgentTests(unittest.TestCase):
    def test_mission_runs_specialists_and_final_coordinator(self):
        calls = []

        def fake_chat(_config, messages, max_tokens=1000):
            role = messages[0]["content"]
            calls.append(role)
            if "منابع" in messages[1]["content"]:
                return "تحلیل با منبع"
            return f"گزارش {len(calls)}"

        def fake_search(query):
            return [{"title": "منبع", "snippet": "نتیجه", "url": "https://example.test"}]

        report, roles = asyncio.run(
            run_specialist_mission(
                "تحقیق و مقایسهٔ ابزارهای هوش مصنوعی", config=object(),
                chat=fake_chat, search=fake_search,
            )
        )
        self.assertIn("منابع وب:", report)
        self.assertIn("https://example.test", report)
        self.assertEqual(len(calls), 4)
        self.assertIn("پژوهشگر", roles)
        self.assertEqual(roles[-1], "هماهنگ‌کنندهٔ نهایی")


if __name__ == "__main__":
    unittest.main()
