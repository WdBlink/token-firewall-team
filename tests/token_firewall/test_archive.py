from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.token_firewall.archive import archive_run_snapshot, verify_run_snapshot


class RunSnapshotArchiveTests(unittest.TestCase):
    def test_archive_round_trip_and_corruption_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            (run / "nested").mkdir(parents=True)
            (run / "events.jsonl").write_text('{"event":1}\n', encoding="utf-8")
            (run / "nested" / "payload.bin").write_bytes(b"payload")
            archive = root / "archives" / "run.zip"
            receipt = archive_run_snapshot(run, archive)
            self.assertEqual(len(receipt["files"]), 2)
            self.assertTrue(verify_run_snapshot(archive)["ok"])
            with archive.open("ab") as handle:
                handle.write(b"tamper")
            result = verify_run_snapshot(archive)
            self.assertFalse(result["ok"])
            self.assertIn("archive_sha256 mismatch", result["findings"])

    def test_archive_refuses_symlink_and_in_place_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            run.mkdir()
            (run / "file").write_text("x")
            with self.assertRaisesRegex(ValueError, "outside"):
                archive_run_snapshot(run, run / "archive.zip")
            (run / "link").symlink_to(run / "file")
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                archive_run_snapshot(run, root / "archive.zip")


if __name__ == "__main__":
    unittest.main()
