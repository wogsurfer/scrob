import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.pipeline import recent_log_errors, unpacked_leftovers, unpackerr_keys, worst

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

    def test_groups_recent_errors_and_skips_old_ones(self):
        lines = [
            "[ERROR] 2026/10/25 10:00:00 Radarr (http://127.0.0.1:7878): api.Get(queue): invalid status code, 401 >= 300",
            "[ERROR] 2026/10/25 10:01:00 Radarr (http://127.0.0.1:7878): api.Get(queue): invalid status code, 401 >= 300",
            "[INFO] 2026/10/25 10:01:00 [Sonarr] Updated",
            "[ERROR] 2026/10/20 10:00:00 an old error",
        ]
        errors = recent_log_errors(lines, datetime(2026, 10, 24, 12, 0))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][1], 2)
        self.assertIn("401", errors[0][0])
        self.assertEqual(errors[0][2], datetime(2026, 10, 25, 10, 1))

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
