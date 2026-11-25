from datetime import date, time
from pathlib import Path
import tempfile
import unittest

from portable_app import MONITOR_EARLY_MINUTES, PITTSBURGH_TIMEZONE, RecorderApp
from soccer_recorder.models import Game
from soccer_recorder.portable import JobStore


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class PortableAppSchedulingTests(unittest.TestCase):
    def test_manual_schedule_is_pittsburgh_and_five_minutes_early(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = object.__new__(RecorderApp)
            app.timezone = PITTSBURGH_TIMEZONE
            app.url = Value("https://cciwnetwork.com/carrollpioneers/?B=4128409")
            app.home_team = Value("Carroll")
            app.away_team = Value("Ohio Northern")
            app.game_date = Value("2026-09-04")
            app.game_time = Value("19:00")
            app.output_dir = Value(directory)
            job = app._parse_form(False)
            self.assertEqual(job["timezone"], "America/New_York")
            self.assertEqual(job["start_early_minutes"], MONITOR_EARLY_MINUTES)
            self.assertTrue(str(job["kickoff_at"]).endswith("-04:00"))

    def test_spreadsheet_games_become_individual_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = object.__new__(RecorderApp)
            app.store = JobStore(Path(directory) / "data")
            app.output_dir = Value(str(Path(directory) / "recordings"))
            games = [
                Game(2, date(2026, 9, 4), "Carroll", "Ohio Northern", time(17), "https://example.test/?B=1"),
                Game(3, date(2026, 9, 4), "Carroll", "Catholic", time(19), "https://www.flocollege.com/live/269367"),
            ]
            jobs, skipped, invalid_links = app._jobs_for_games(games, "test.xlsx")
            self.assertEqual(skipped, 0)
            self.assertEqual(invalid_links, [])
            self.assertEqual(len(jobs), 2)
            self.assertEqual([job["source_row"] for job in jobs], [2, 3])
            self.assertTrue(all(job["start_early_minutes"] == 5 for job in jobs))
            self.assertTrue(all(job["timezone"] == "America/New_York" for job in jobs))

    def test_bad_flo_link_is_skipped_without_losing_valid_games(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = object.__new__(RecorderApp)
            app.store = JobStore(Path(directory) / "data")
            app.output_dir = Value(str(Path(directory) / "recordings"))
            games = [
                Game(2, date(2026, 9, 4), "Carroll", "Ohio Northern", time(17), "https://example.test/?B=1"),
                Game(3, date(2026, 9, 4), "Carroll", "Catholic", time(19), "https://www.flocollege.com/signup"),
            ]
            jobs, skipped, invalid_links = app._jobs_for_games(games, "test.xlsx")
            self.assertEqual(skipped, 0)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["source_row"], 2)
            self.assertEqual(invalid_links[0][0], 3)
            self.assertIn("/live/", invalid_links[0][2])


if __name__ == "__main__":
    unittest.main()
