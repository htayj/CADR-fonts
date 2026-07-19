from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "package-version.sh"


class PackageVersionTests(unittest.TestCase):
    def normalize(self, value: str, package_format: str = "deb") -> str:
        process = subprocess.run(
            [str(SCRIPT), "--format", package_format, value],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return process.stdout.strip()

    def test_stable_and_prerelease_tags(self) -> None:
        self.assertEqual(self.normalize("v0.1.0"), "0.1.0")
        self.assertEqual(
            self.normalize("v0.2.0-alpha.1"), "0.2.0~alpha.1"
        )
        self.assertEqual(
            self.normalize("v0.2.0-alpha.1", "arch"),
            "0.2.0pre.alpha.1",
        )

    def test_post_tag_git_describe_is_later_build_metadata(self) -> None:
        self.assertEqual(
            self.normalize("v0.1.0-12-gDEADBEE"),
            "0.1.0+git.12.gdeadbee",
        )
        self.assertEqual(
            self.normalize("v0.2.0-alpha.1-2-gc0ffee"),
            "0.2.0~alpha.1+git.2.gc0ffee",
        )

    def test_hash_and_dirty_worktree_forms_are_safe(self) -> None:
        self.assertEqual(self.normalize("deadbee"), "0+git.deadbee")
        self.assertEqual(
            self.normalize("v0.1.0-1-gdeadbee-dirty"),
            "0.1.0+git.1.gdeadbee.dirty",
        )


if __name__ == "__main__":
    unittest.main()
