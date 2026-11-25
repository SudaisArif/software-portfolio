import tempfile
import unittest
from pathlib import Path

from soccer_recorder.notifications import EmailConfig, EmailNotifier
from soccer_recorder.portable import JobStore, human_size, preload_frozen_runtime


class PortableStoreTests(unittest.TestCase):
    def test_add_and_update_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            store.add({"id": "game-1", "status": "scheduled"})
            updated = store.update("game-1", status="recording", event_id="123")
            self.assertIsNotNone(updated)
            self.assertEqual(store.get("game-1")["status"], "recording")
            self.assertEqual(store.get("game-1")["event_id"], "123")

    def test_human_size(self) -> None:
        self.assertEqual(human_size(1024 * 1024), "1.0 MB")

    def test_add_many_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            store.add_many(
                [
                    {"id": "game-1", "status": "scheduled"},
                    {"id": "game-2", "status": "scheduled"},
                ]
            )
            self.assertEqual([job["id"] for job in store.jobs()], ["game-1", "game-2"])

    def test_delete_job_preserves_other_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            store.add_many(
                [
                    {"id": "game-1", "status": "scheduled"},
                    {"id": "game-2", "status": "completed"},
                ]
            )
            removed = store.delete("game-1")
            self.assertEqual(removed["id"], "game-1")
            self.assertIsNone(store.get("game-1"))
            self.assertEqual([job["id"] for job in store.jobs()], ["game-2"])

    def test_email_health_interval_defaults_and_is_bounded(self) -> None:
        self.assertEqual(EmailNotifier().health_interval_minutes, 15)
        self.assertEqual(
            EmailNotifier(EmailConfig("coach@example.com", "coach@example.com", health_interval_minutes=30)).health_interval_minutes,
            30,
        )
        self.assertEqual(
            EmailNotifier(EmailConfig("coach@example.com", "coach@example.com", health_interval_minutes=999)).health_interval_minutes,
            180,
        )

    def test_frozen_runtime_preloads_dns_codec(self) -> None:
        import codecs

        preload_frozen_runtime()
        self.assertEqual(codecs.lookup("idna").name, "idna")


if __name__ == "__main__":
    unittest.main()
