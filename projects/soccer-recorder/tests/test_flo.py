import base64
import json
from datetime import date, time
import unittest

from soccer_recorder.flo import FloCollegeAdapter
from soccer_recorder.models import Game
from soccer_recorder.providers import provider_key_for_url


def token_with_future_expiry() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 4102444800}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeSessionStore:
    def __init__(self) -> None:
        self.saved = None
        self.email = None
        self.password = None

    @property
    def configured(self):
        return self.saved is not None

    @property
    def password_configured(self):
        return self.password is not None

    def load(self):
        return dict(self.saved) if self.saved else None

    def save(self, email, session):
        self.email = email
        self.saved = {**session, "email": email}

    def load_password(self):
        return self.password

    def save_password(self, email, password):
        self.email = email
        self.password = password

    def delete_password(self, email):
        if self.email == email:
            self.password = None


class FakeFloHttp:
    def __init__(self, status="LIVE") -> None:
        self.status = status
        self.calls = []

    def request_json(self, method, url, body=None, headers=None):
        self.calls.append((method, url, body, headers))
        if url.endswith("/api/tokens"):
            return {
                "token": token_with_future_expiry(),
                "refresh_token": "refresh-secret",
                "refresh_token_exp": 4102444800,
            }
        if "legacy-core/live-events" in url:
            return {
                "data": {
                    "id": 269367,
                    "title": "John Carroll vs Catholic",
                    "start_at": "2026-09-04T23:00:00+00:00",
                    "status_v2": "PRE-AIR",
                    "premium": True,
                    "disable_login": False,
                    "deleted_at": None,
                }
            }
        if "/events/269367" in url:
            return {
                "data": {
                    "id": 269367,
                    "name": "John Carroll vs Catholic",
                    "startAt": "2026-09-04T23:00:00Z",
                    "status": self.status,
                    "streams": [{"id": 378484, "isActive": True, "isDefault1": True, "sortOrder": 1}],
                }
            }
        if "/streams/378484/tokens" in url:
            return {
                "data": {
                    "adTech": "psai+ssai",
                    "cleanUri": "https://stream.example/live.m3u8?token=secret",
                    "uri": "https://stream.example/ad.m3u8?token=secret",
                    "token": {"id": "playback-token"},
                }
            }
        if "/heartbeat" in url or method == "DELETE":
            return {}
        raise AssertionError(f"Unexpected request: {method} {url}")


class FloCollegeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.game = Game(
            row=0,
            game_date=date(2026, 9, 4),
            home_team="John Carroll",
            away_team="Catholic",
            kickoff=time(19, 0),
            livestream_url="https://www.flocollege.com/live/269367",
        )

    def test_extracts_event_from_direct_and_signup_urls(self) -> None:
        self.assertEqual(FloCollegeAdapter._event_id_from_url(self.game.livestream_url), "269367")
        signup = "https://www.flocollege.com/signup?redirect=%2Flive%2F269367&utm_source=test"
        self.assertEqual(FloCollegeAdapter._event_id_from_url(signup), "269367")
        self.assertEqual(provider_key_for_url(signup), "flocollege")
        self.assertEqual(provider_key_for_url("https://www.flofc.com/live/269367-event"), "flocollege")

    def test_login_saves_tokens_but_never_password(self) -> None:
        http = FakeFloHttp()
        store = FakeSessionStore()
        adapter = FloCollegeAdapter(http, store)
        adapter.login("coach@example.edu", "do-not-save-this")
        self.assertEqual(store.email, "coach@example.edu")
        self.assertNotIn("password", store.saved)
        self.assertNotIn("do-not-save-this", json.dumps(store.saved))
        self.assertEqual(store.password, "do-not-save-this")

    def test_saved_password_restores_a_missing_session(self) -> None:
        http = FakeFloHttp()
        store = FakeSessionStore()
        store.email = "coach@example.edu"
        store.password = "keychain-only-password"
        adapter = FloCollegeAdapter(http, store)
        self.assertEqual(adapter.validate_session(), "coach@example.edu")
        self.assertIsNotNone(store.saved)
        login_call = next(call for call in http.calls if call[1].endswith("/api/tokens"))
        self.assertEqual(login_call[2]["email"], "coach@example.edu")

    def test_resolves_public_event_metadata(self) -> None:
        adapter = FloCollegeAdapter(FakeFloHttp(), FakeSessionStore())
        event = adapter.resolve(self.game)
        self.assertEqual(event.event_id, "269367")
        self.assertEqual(event.provider, "flocollege")
        self.assertTrue(event.require_login)

    def test_pre_air_does_not_request_playback_token(self) -> None:
        http = FakeFloHttp(status="NEW")
        adapter = FloCollegeAdapter(http, FakeSessionStore())
        snapshot = adapter.snapshot("269367")
        self.assertFalse(snapshot.streaming)

    def test_post_ad_status_is_final(self) -> None:
        http = FakeFloHttp(status="ADS-POST")
        adapter = FloCollegeAdapter(http, FakeSessionStore())

        snapshot = adapter.snapshot("269367")

        self.assertEqual(snapshot.status, "Concluded")
        self.assertFalse(snapshot.streaming)
        self.assertFalse(any("/streams/" in call[1] for call in http.calls))

    def test_live_event_uses_authenticated_hls_and_heartbeat(self) -> None:
        http = FakeFloHttp(status="LIVE")
        store = FakeSessionStore()
        adapter = FloCollegeAdapter(http, store)
        adapter.login("coach@example.edu", "password")
        snapshot = adapter.snapshot("269367")
        self.assertTrue(snapshot.streaming)
        self.assertEqual(snapshot.content_url, "https://stream.example/live.m3u8?token=secret")
        token_call = next(call for call in http.calls if "/streams/378484/tokens" in call[1])
        self.assertTrue(token_call[3]["Authorization"].startswith("Bearer "))
        self.assertTrue(any("/heartbeat" in call[1] for call in http.calls))


if __name__ == "__main__":
    unittest.main()
