import tempfile
import unittest
from pathlib import Path

from database import DraftStore


class DraftStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "nested" / "drafts.sqlite3"
        self.store = DraftStore(self.database_path)
        self.store.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_saves_and_reads_a_draft(self):
        saved = self.store.save_draft(
            owner_id=1234,
            topic="موضوع ریل",
            angle="یک زاویهٔ مناسب",
            content="متن پیش‌نویس",
            model="openai/gpt-4o-mini",
        )

        self.assertGreater(saved["id"], 0)
        self.assertEqual(saved["owner_id"], 1234)
        self.assertEqual(saved["topic"], "موضوع ریل")
        self.assertEqual(saved["content"], "متن پیش‌نویس")
        self.assertEqual(saved["status"], "draft")
        self.assertTrue(saved["created_at"].endswith("Z"))
        self.assertEqual(self.store.count_drafts(owner_id=1234), 1)
        self.assertEqual(self.store.get_draft(saved["id"], owner_id=1234), saved)

    def test_drafts_are_scoped_to_the_owner(self):
        saved = self.store.save_draft(
            owner_id=1234,
            topic="موضوع",
            angle="زاویه",
            content="متن",
            model="test-model",
        )

        self.assertIsNone(self.store.get_draft(saved["id"], owner_id=9876))
        self.assertEqual(self.store.count_drafts(owner_id=9876), 0)
        self.assertEqual(self.store.list_drafts(owner_id=9876), [])

    def test_rejects_empty_draft_fields(self):
        with self.assertRaises(ValueError):
            self.store.save_draft(
                owner_id=1234,
                topic=" ",
                angle="زاویه",
                content="متن",
                model="test-model",
            )

    def test_published_draft_cannot_be_marked_twice(self):
        saved = self.store.save_draft(
            owner_id=1234, topic="موضوع", angle="زاویه", content="متن", model="test-model"
        )
        self.assertTrue(self.store.mark_published(saved["id"], owner_id=1234))
        self.assertFalse(self.store.mark_published(saved["id"], owner_id=1234))
        self.assertEqual(self.store.get_draft(saved["id"], owner_id=1234)["status"], "published")

    def test_reminders_are_persisted_and_due_items_can_be_marked(self):
        reminder_id = self.store.add_reminder(
            owner_id=1234, text="یادآوری", due_at="2026-01-01T00:00:00Z"
        )
        self.assertEqual(len(self.store.due_reminders(now="2026-01-01T00:00:01Z")), 1)
        self.store.mark_reminder_delivered(reminder_id)
        self.assertEqual(self.store.due_reminders(now="2026-01-01T00:00:01Z"), [])

    def test_list_is_newest_first_and_limit_is_bounded(self):
        first = self.store.save_draft(
            owner_id=1234,
            topic="اول",
            angle="زاویه",
            content="متن اول",
            model="test-model",
        )
        second = self.store.save_draft(
            owner_id=1234,
            topic="دوم",
            angle="زاویه",
            content="متن دوم",
            model="test-model",
        )

        rows = self.store.list_drafts(owner_id=1234, limit=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], second["id"])
        self.assertGreater(second["id"], first["id"])


if __name__ == "__main__":
    unittest.main()
