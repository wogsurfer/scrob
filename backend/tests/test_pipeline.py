import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.pipeline import explain, log_problems, unpacked_leftovers, unpackerr_keys, worst

CONF = '''
debug = false
[[radarr]]
url = "http://127.0.0.1:7878"
api_key = "radarr-key"
protocols = "torrent"

[[sonarr]]
url = "http://127.0.0.1:8989"
api_key = "sonarr-key"
'''


class PipelineTests(unittest.TestCase):
    def test_reads_unpackerrs_keys(self):
        self.assertEqual(unpackerr_keys(CONF), {"radarr": "radarr-key", "sonarr": "sonarr-key"})

    def test_explains_errors_in_plain_english(self):
        app, text, kind = explain("Radarr (http://127.0.0.1:7878): api.Get(queue): invalid status code, 401 >= 300")
        self.assertEqual((app, kind), ("Radarr", "connection"))
        self.assertIn("API key for Radarr is wrong", text)
        _, text, _ = explain(
            "Sonarr (http://127.0.0.1:8989): api.Get(v3/queue): httpClient.Do(req): dial tcp 127.0.0.1:8989: "
            "connectex: No connection could be made because the target machine actively refused it."
        )
        self.assertIn("couldn't reach Sonarr", text)
        _, text, kind = explain(
            r"Extraction Failed: Silo.S03E08.2160p.WEB.H265-CAKES: D:\Downloads\tv-sonarr\silo.r11: copying io: rardecode: bad file checksum"
        )
        self.assertEqual(kind, "unpack")
        self.assertEqual(text, "Couldn't unpack Silo.S03E08.2160p.WEB.H265-CAKES: one of its archive parts is damaged, so it needs downloading again.")

    def test_groups_problems_and_marks_fixed_ones(self):
        lines = [
            "[ERROR] 2026/10/25 10:00:00 Radarr (http://127.0.0.1:7878): api.Get(queue): invalid status code, 401 >= 300",
            "[ERROR] 2026/10/25 10:01:00 Radarr (http://127.0.0.1:7878): api.Get(queue): invalid status code, 401 >= 300",
            "[INFO] 2026/10/25 10:02:00 [Radarr] Updated (http://127.0.0.1:7878): 0 Items Queued, 0 Retrieved",
            r"[ERROR] 2026/10/25 10:05:00 Extraction Failed: NCIS.S23E19: D:\x.r19: copying io: rardecode: bad file checksum",
            "[ERROR] 2026/10/20 10:00:00 an old error",
        ]
        problems = log_problems(lines, datetime(2026, 10, 24, 12, 0))
        self.assertEqual(len(problems), 2)
        unpack, refused = problems  # current problems first
        self.assertFalse(unpack["fixed"])
        self.assertIn("NCIS.S23E19", unpack["text"])
        self.assertTrue(refused["fixed"])
        self.assertEqual((refused["count"], refused["last"]), (2, datetime(2026, 10, 25, 10, 1)))

    def test_refusals_since_the_last_success_are_current(self):
        lines = [
            "[INFO] 2026/10/25 09:00:00 [Radarr] Updated (http://127.0.0.1:7878): 0 Items Queued",
            "[ERROR] 2026/10/25 10:00:00 Radarr (http://127.0.0.1:7878): api.Get(queue): invalid status code, 401 >= 300",
        ]
        self.assertFalse(log_problems(lines, datetime(2026, 10, 24))[0]["fixed"])

    def test_finds_downloads_left_packed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = time.time() - 2 * 86400

            def make(rel, names):
                folder = root / rel
                folder.mkdir(parents=True)
                for n in names:
                    f = folder / n
                    f.write_bytes(b"x")
                    os.utime(f, (old, old))

            make("radarr/Packed.Movie", ["movie.rar", "movie.r00", "movie.nfo"])
            make("radarr/Unpacked.Movie", ["movie.rar", "movie.mkv"])
            make("tv-sonarr/Plain.Episode", ["episode.mkv"])
            fresh = root / "radarr/Still.Downloading"
            fresh.mkdir()
            (fresh / "part.rar").write_bytes(b"x")
            self.assertEqual(unpacked_leftovers(root, timedelta(hours=6)), ["radarr/Packed.Movie"])

    def test_worst_status(self):
        self.assertEqual(worst(["ok", "warn", "ok"]), "warn")
        self.assertEqual(worst(["warn", "error"]), "error")
        self.assertEqual(worst([]), "ok")


if __name__ == "__main__":
    unittest.main()
