from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


release = load_script("build_release", "build_release.py")
release_check = load_script("check_release_dist", "check_release_dist.py")


def fixture_bdf(glyphs: list[tuple[int, list[str]]]) -> str:
    blocks = []
    for code, rows in glyphs:
        blocks.append(
            "\n".join(
                [
                    f"STARTCHAR U{code:04X}",
                    f"ENCODING {code}",
                    "SWIDTH 1000 0",
                    "DWIDTH 8 0",
                    f"BBX 8 {len(rows)} 0 0",
                    "BITMAP",
                    *rows,
                    "ENDCHAR",
                ]
            )
        )
    return (
        "STARTFONT 2.1\n"
        "FONT -Misc-CADR Fixture-Unknown-OT-Unknown-Unicode-8-80-72-72-C-80-ISO10646-1\n"
        "SIZE 8 72 72\n"
        "FONTBOUNDINGBOX 8 8 0 0\n"
        f"CHARS {len(glyphs)}\n"
        + "\n".join(blocks)
        + "\nENDFONT\n"
    )


class ReleaseClassificationTests(unittest.TestCase):
    def summary(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bdf"
            path.write_text(text, encoding="ascii")
            return release.read_bdf_summary(path)

    def test_any_visible_basic_latin_letter_selects_latin(self) -> None:
        uppercase = self.summary(fixture_bdf([(0x41, ["80"]), (0xE000, ["00"])]))
        lowercase = self.summary(fixture_bdf([(0x7A, ["01"])]))
        self.assertEqual(uppercase.content_class, "latin")
        self.assertEqual(lowercase.content_class, "latin")

    def test_blank_latin_and_visible_private_use_select_symbols(self) -> None:
        summary = self.summary(
            fixture_bdf([(0x41, ["00", "00"]), (0xE000, ["80", "00"])])
        )
        self.assertEqual(summary.content_class, "symbols")
        self.assertEqual(summary.visible_codes, frozenset({0xE000}))

    def test_declared_glyph_count_and_duplicate_encoding_are_rejected(self) -> None:
        wrong_count = fixture_bdf([(0x41, ["80"])]).replace("CHARS 1", "CHARS 2")
        with self.assertRaisesRegex(release.ReleaseError, "CHARS declares"):
            self.summary(wrong_count)
        duplicate = fixture_bdf([(0x41, ["80"]), (0x41, ["40"])])
        with self.assertRaisesRegex(release.ReleaseError, "duplicate encoding"):
            self.summary(duplicate)


class ReleaseIndexTests(unittest.TestCase):
    def test_filtered_indexes_are_sorted_and_alias_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "full"
            destination = root / "selected"
            source.mkdir()
            source.joinpath("fonts.dir").write_text(
                "3\n"
                "z.bdf -xlfd-z\n"
                "a.bdf -xlfd-a\n"
                "m.bdf -xlfd-m\n",
                encoding="ascii",
            )
            source.joinpath("fonts.alias").write_text(
                "! fixture aliases\n"
                'zeta "-xlfd-z"\n'
                'middle "-xlfd-m"\n'
                'alpha "-xlfd-a"\n'
                'another-alpha "-xlfd-a"\n',
                encoding="ascii",
            )
            count = release.write_filtered_indexes(
                source,
                destination,
                {"z.bdf": "-xlfd-z", "a.bdf": "-xlfd-a"},
            )
            self.assertEqual(count, 3)
            self.assertEqual(
                destination.joinpath("fonts.dir").read_text(encoding="ascii"),
                "2\na.bdf -xlfd-a\nz.bdf -xlfd-z\n",
            )
            aliases = destination.joinpath("fonts.alias").read_text(encoding="ascii")
            self.assertNotIn("middle", aliases)
            self.assertEqual(
                release._parse_fonts_alias(destination / "fonts.alias")[1],
                {
                    "alpha": "-xlfd-a",
                    "another-alpha": "-xlfd-a",
                    "zeta": "-xlfd-z",
                },
            )

    def test_alias_to_unknown_full_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "full"
            source.mkdir()
            source.joinpath("fonts.dir").write_text("1\na.bdf -xlfd-a\n", encoding="ascii")
            source.joinpath("fonts.alias").write_text(
                'broken "-xlfd-missing"\n', encoding="ascii"
            )
            with self.assertRaisesRegex(release.ReleaseError, "alias target is absent"):
                release.write_filtered_indexes(
                    source, root / "selected", {"a.bdf": "-xlfd-a"}
                )


class FonttosfntIdentityTests(unittest.TestCase):
    def test_accepts_reviewed_fonttosfnt_version(self) -> None:
        process = mock.Mock(stdout="fonttosfnt 1.2.5\n", stderr="")
        with mock.patch.object(
            release.shutil, "which", return_value="/tmp/fonttosfnt"
        ), mock.patch.object(release.subprocess, "run", return_value=process):
            self.assertEqual(
                release._fonttosfnt_version("fonttosfnt"), "fonttosfnt 1.2.5"
            )

    def test_rejects_unreviewed_fonttosfnt_version(self) -> None:
        process = mock.Mock(stdout="fonttosfnt 1.0.4\n", stderr="")
        with mock.patch.object(
            release.shutil, "which", return_value="/tmp/fonttosfnt"
        ), mock.patch.object(release.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(
                release.ReleaseError, "expected 'fonttosfnt 1.2.5'"
            ):
                release._fonttosfnt_version("fonttosfnt")

    def test_rejects_fonttosfnt_without_version_support(self) -> None:
        error = release.subprocess.CalledProcessError(1, ["fonttosfnt", "--version"])
        with mock.patch.object(
            release.shutil, "which", return_value="/tmp/fonttosfnt"
        ), mock.patch.object(release.subprocess, "run", side_effect=error):
            with self.assertRaisesRegex(
                release.ReleaseError, "cannot identify fonttosfnt version"
            ):
                release._fonttosfnt_version("fonttosfnt")


class DeterministicArchiveTests(unittest.TestCase):
    def test_archive_order_metadata_and_gzip_timestamp_are_deterministic(self) -> None:
        epoch = 1_731_361_680
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / "CADR-fonts-latin-test"
            (root / "nested").mkdir(parents=True)
            (root / "z.txt").write_text("z\n", encoding="ascii")
            (root / "nested" / "a.txt").write_text("a\n", encoding="ascii")
            first = workspace / "first.tar.gz"
            second = workspace / "second.tar.gz"
            release.write_deterministic_archive(root, first, epoch)
            root.joinpath("z.txt").touch()
            release.write_deterministic_archive(root, second, epoch)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(struct.unpack("<I", first.read_bytes()[4:8])[0], epoch)

            with tarfile.open(first, "r:gz") as archive:
                members = archive.getmembers()
                self.assertEqual(
                    [member.name for member in members],
                    [
                        "CADR-fonts-latin-test",
                        "CADR-fonts-latin-test/nested",
                        "CADR-fonts-latin-test/nested/a.txt",
                        "CADR-fonts-latin-test/z.txt",
                    ],
                )
                for member in members:
                    self.assertEqual((member.uid, member.gid), (0, 0))
                    self.assertEqual((member.uname, member.gname), ("", ""))
                    self.assertEqual(member.mtime, epoch)
                    self.assertEqual(member.mode, 0o755 if member.isdir() else 0o644)

    def test_unsafe_version_is_rejected_before_reading_distribution(self) -> None:
        with self.assertRaisesRegex(release.ReleaseError, "unsafe release version"):
            release.build_release(
                distribution=Path("does-not-exist"),
                release_dir=Path("does-not-matter"),
                version="../escape",
                source_date_epoch=1,
            )


class ReleaseArchiveReaderTests(unittest.TestCase):
    def test_duplicate_tar_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "duplicate.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for payload in (b"first", b"second"):
                    member = tarfile.TarInfo("root/file")
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))
            with self.assertRaisesRegex(
                release_check.ReleaseDistError, "duplicate archive member"
            ):
                release_check._read_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
