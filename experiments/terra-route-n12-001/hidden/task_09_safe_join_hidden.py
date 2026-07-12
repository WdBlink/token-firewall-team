from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path.cwd()))
from src.tasks import safe_join


class HiddenSafeJoinTests(unittest.TestCase):
    def test_rejects_sibling_prefix_trap_and_symlink_component(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "app"
            sibling = root / "app-secret"
            base.mkdir()
            sibling.mkdir()
            (base / "escape").symlink_to(sibling, target_is_directory=True)
            with self.assertRaises(ValueError):
                safe_join(base, "escape/value")
            with self.assertRaises(ValueError):
                safe_join(base, "../app-secret/value")

    def test_requires_existing_directory_base_and_string_relative_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "missing"
            file_base = root / "file"
            file_base.write_text("x")
            for base in (missing, file_base):
                with self.subTest(base=base), self.assertRaises((TypeError, ValueError)):
                    safe_join(base, "child")
            with self.assertRaises((TypeError, ValueError)):
                safe_join(root, Path("child"))


if __name__ == "__main__":
    unittest.main()
