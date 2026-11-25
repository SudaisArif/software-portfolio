from datetime import date, time
import unittest

from soccer_recorder.hudl import HudlAdapter, HttpClient
from soccer_recorder.models import Game


VMAP = """<?xml version="1.0"?>
<VMAP><Extensions><Extension><Broadcast id="123" title="Home vs Away" date="2026-09-01T23:00:00+00:00" status="Live" />
<Content streaming="true"><![CDATA[https://example.test/live.m3u8]]></Content>
<Notifiers><Messages live="Playing" /></Notifiers></Extension></Extensions></VMAP>"""


class FakeHttp(HttpClient):
    def get_text(self, url: str) -> str:
        return VMAP


class HudlTests(unittest.TestCase):
    def test_event_id_from_query(self) -> None:
        self.assertEqual(HudlAdapter._event_id_from_url("https://example.test/team/?B=3990417"), "3990417")

    def test_snapshot_parsing(self) -> None:
        snapshot = HudlAdapter(FakeHttp()).snapshot("123")
        self.assertTrue(snapshot.streaming)
        self.assertEqual(snapshot.content_url, "https://example.test/live.m3u8")
        self.assertEqual(snapshot.status, "Live")


if __name__ == "__main__":
    unittest.main()

