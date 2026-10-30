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

    def test_scheduled_channel_posts_are_persistent_and_publish_draft(self):
        draft = self.store.save_draft(
            owner_id=1234, topic="پست", angle="تلگرام", content="متن کانال", model="test-model"
        )
        schedule_id = self.store.schedule_post(
            owner_id=1234, draft_id=draft["id"], channel_id="@mychannel",
            scheduled_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(len(self.store.due_scheduled_posts(now="2026-01-01T00:00:01Z")), 1)
        self.assertEqual(self.store.list_scheduled_posts(owner_id=1234)[0]["id"], schedule_id)
        self.store.mark_scheduled_post_published(schedule_id, draft["id"])
        self.assertEqual(self.store.get_draft(draft["id"], owner_id=1234)["status"], "published")
        self.assertEqual(self.store.list_scheduled_posts(owner_id=1234), [])

    def test_missions_are_persisted_and_scoped_to_owner(self):
        mission_id = self.store.save_mission(
            owner_id=1234, goal="برنامه‌ریزی", report="گزارش نهایی", agents="تحلیلگر، نویسنده"
        )
        self.assertEqual(self.store.count_missions(owner_id=1234), 1)
        self.assertEqual(self.store.get_mission(mission_id, owner_id=1234)["report"], "گزارش نهایی")
        self.assertIsNone(self.store.get_mission(mission_id, owner_id=9876))
        self.assertEqual(self.store.list_missions(owner_id=9876), [])

    def test_notes_are_private_and_deletable(self):
        note_id = self.store.add_note(owner_id=1234, text="یادداشت خصوصی")
        self.assertEqual(self.store.list_notes(owner_id=1234)[0]["text"], "یادداشت خصوصی")
        self.assertEqual(self.store.list_notes(owner_id=9876), [])
        self.assertFalse(self.store.delete_note(note_id, owner_id=9876))
        self.assertTrue(self.store.delete_note(note_id, owner_id=1234))

    def test_tasks_can_be_completed_and_are_owner_scoped(self):
        task_id = self.store.add_task(owner_id=1234, text="یک کار")
        self.assertEqual(self.store.list_tasks(owner_id=1234)[0]["status"], "open")
        self.assertFalse(self.store.complete_task(task_id, owner_id=9876))
        self.assertTrue(self.store.complete_task(task_id, owner_id=1234))
        self.assertEqual(self.store.list_tasks(owner_id=1234)[0]["status"], "done")
        self.assertFalse(self.store.complete_task(task_id, owner_id=1234))

    def test_pending_reminders_can_be_listed_and_cancelled(self):
        reminder_id = self.store.add_reminder(
            owner_id=1234, text="جلسه", due_at="2026-01-01T00:00:00Z"
        )
        self.assertEqual(self.store.list_reminders(owner_id=1234)[0]["text"], "جلسه")
        self.assertFalse(self.store.cancel_reminder(reminder_id, owner_id=9876))
        self.assertTrue(self.store.cancel_reminder(reminder_id, owner_id=1234))
        self.assertEqual(self.store.list_reminders(owner_id=1234), [])

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
