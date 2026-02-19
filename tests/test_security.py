
import unittest
import shutil
import os
from pathlib import Path
from hologram.session import Session

class TestSecurity(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_claude_dir_security").resolve()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)
        self.session = Session(claude_dir=str(self.test_dir))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

        # Cleanup files that might have been created outside
        for f in ["outside_pin.md", "outside_note.md"]:
            p = Path(f)
            if p.exists():
                p.unlink()

    def test_pin_path_traversal(self):
        """Test that pin() rejects paths outside claude_dir."""
        vulnerable_path = "../outside_pin.md"

        # This should ideally raise an error after the fix
        with self.assertRaises((ValueError, PermissionError)):
            self.session.pin("some content", anchor_file=vulnerable_path)

        self.assertFalse(Path("outside_pin.md").exists())

    def test_note_path_traversal_subdir(self):
        """Test that note() rejects subdirs outside claude_dir."""
        vulnerable_subdir = "../"

        with self.assertRaises((ValueError, PermissionError)):
            self.session.note("Security Test", "content", subdir=vulnerable_subdir)

    def test_note_path_traversal_title_manipulation(self):
        """
        Test that note() title is sanitized.
        Note: The current code already slugifies the title, but we should ensure
        it can't be used for traversal if slugification was broken.
        """
        vulnerable_title = "../../../outside_note"
        # Slugification should handle this, but let's see where it tries to write
        path = self.session.note(vulnerable_title, "content")

        # It should be inside the notes dir
        self.assertTrue(path.resolve().is_relative_to(self.test_dir))

    def test_safe_paths_allowed(self):
        """Test that normal paths within claude_dir are still allowed."""
        # Test pin
        path1 = self.session.pin("content", anchor_file="safe_anchor.md")
        self.assertTrue(path1.exists())
        self.assertTrue(path1.resolve().is_relative_to(self.test_dir))

        # Test note
        path2 = self.session.note("Safe Note", "content", subdir="safe_notes")
        self.assertTrue(path2.exists())
        self.assertTrue(path2.resolve().is_relative_to(self.test_dir))

if __name__ == "__main__":
    unittest.main()
