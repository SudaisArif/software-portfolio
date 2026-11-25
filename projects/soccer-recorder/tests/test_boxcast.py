from datetime import date, time
import json
import unittest

from soccer_recorder.boxcast import BoxCastAdapter
from soccer_recorder.models import Game
from soccer_recorder.providers import adapter_for_url, provider_key_for_url


class FakeHttp:
    def get_text(self, url: str) -> str:
        if url.endswith("/view"):
            return json.dumps({"status": "live", "reason": "", "playlist": "https://example.test/live.m3u8"})
        return json.dumps(
            {
                "id": "ibm38tgtsn0hqh9g8pfu",
                "name": "Men's Soccer vs. Juniata",
                "starts_at": "2026-09-09T22:30:00Z",
                "stops_at": "2026-09-10T01:30:00Z",
                "timeframe": "current",
                "is_private": False,
                "is_ticketed": False,
            }
        )


class BoxCastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.url = "https://boxcast.tv/view/mens-soccer-vs-juniata-ibm38tgtsn0hqh9g8pfu"
        self.game = Game(1, date(2026, 9, 9), "Mount Aloysius", "Juniata", time(19, 0), self.url)

    def test_provider_detection_and_event_id(self) -> None:
        self.assertEqual(provider_key_for_url(self.url), "boxcast")
        self.assertIsInstance(adapter_for_url(self.url), BoxCastAdapter)
        self.assertEqual(BoxCastAdapter._event_id_from_url(self.url), "ibm38tgtsn0hqh9g8pfu")

    def test_resolve_and_snapshot(self) -> None:
        adapter = BoxCastAdapter(FakeHttp())
        event = adapter.resolve(self.game)
        snapshot = adapter.snapshot(event.event_id)
        self.assertEqual(event.provider, "boxcast")
        self.assertTrue(snapshot.streaming)
        self.assertEqual(snapshot.content_url, "https://example.test/live.m3u8")


if __name__ == "__main__":
    unittest.main()
