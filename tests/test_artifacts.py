from __future__ import annotations

import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from mujina_assist.services.artifacts import create_release_zip, create_review_zip


class ArtifactTest(unittest.TestCase):
    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_review_zip_preserves_directory_tree_and_executable_bits(self) -> None:
        repo = self._repo_root()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "review.zip"

            created = create_review_zip(repo, output)

            with zipfile.ZipFile(created) as archive:
                names = set(archive.namelist())
                self.assertIn("mujina-ros-tui/src/mujina_assist/app.py", names)
                self.assertIn("mujina-ros-tui/patches/mujina_ros/0001-harden-can-setup.patch", names)
                self.assertIn("mujina-ros-tui/third_party/mujina_ros/README.md", names)
                self.assertNotIn("app.py", names)
                start_info = archive.getinfo("mujina-ros-tui/start.sh")

            self.assertEqual((start_info.external_attr >> 16) & 0o111, 0o111)

    def test_release_zip_uses_git_archive_prefix(self) -> None:
        repo = self._repo_root()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "release.zip"

            created = create_release_zip(repo, output, ref="HEAD")

            with zipfile.ZipFile(created) as archive:
                names = set(archive.namelist())

            self.assertIn("mujina-ros-tui/src/mujina_assist/app.py", names)

    def test_start_sh_is_executable_in_git_index(self) -> None:
        repo = self._repo_root()
        result = subprocess.run(
            ["git", "ls-files", "--stage", "start.sh"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("100755 "), result.stdout)


if __name__ == "__main__":
    unittest.main()
