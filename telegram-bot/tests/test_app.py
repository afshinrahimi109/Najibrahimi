import tempfile
import unittest
from pathlib import Path

from app import BotConfig, REMINDER_PATTERN, PERSIAN_DIGITS, _chat, build_application, _split_long_text
from unittest.mock import patch


class AppFeatureTests(unittest.TestCase):
    def test_reminder_duration_accepts_farsi_digits_and_units(self):
        duration = "۳۰ دقیقه".translate(PERSIAN_DIGITS).replace(" ", "")
        self.assertIsNotNone(REMINDER_PATTERN.fullmatch(duration))
        self.assertIsNotNone(REMINDER_PATTERN.fullmatch("2h"))

    @patch("app.gemini_completion", return_value="جواب Gemini")
    def test_gemini_is_preferred_over_the_old_groq_key(self, gemini_completion):
        config = BotConfig(
            telegram_token="123:ABC",
            owner_id=123,
            openrouter_api_key="",
            openrouter_model="openai/gpt-4o-mini",
            database_path=":memory:",
            openrouter_timeout_seconds=10,
            groq_api_key="old-invalid-key",
            gemini_api_key="new-key",
        )
        answer = _chat(config, [{"role": "user", "content": "سلام"}])
        self.assertEqual(answer, "جواب Gemini")
        gemini_completion.assert_called_once()

    def test_long_text_is_split_within_telegram_limit(self):
        chunks = _split_long_text(("یک متن بلند. " * 500), limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))

    def test_application_registers_every_practical_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = BotConfig(
                telegram_token="123:ABC",
                owner_id=123,
                openrouter_api_key="",
                openrouter_model="openai/gpt-4o-mini",
                database_path=str(Path(temp_dir) / "bot.sqlite3"),
                openrouter_timeout_seconds=10,
            )
            application = build_application(config)
            registered = {
                command
                for handler in application.handlers[0]
                for command in getattr(handler, "commands", ())
            }
            self.assertTrue(
                {
                    "note", "notes", "notedel", "todo", "remind", "reminders",
                    "cancelreminder", "search", "summarize", "post", "reel",
                    "image", "publish",
                }.issubset(registered)
            )
            self.assertIsNotNone(application.job_queue)


if __name__ == "__main__":
    unittest.main()
