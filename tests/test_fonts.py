from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"
sys.path.insert(0, str(SCRIPTS))

import lisp_machine_fonts as common  # noqa: E402


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


cadr = load_script("extract_cadr_fonts", "extract-cadr-fonts.py")
builder = load_script("build_cadr_fonts", "build.py")


def pack_seven_bit_text(data: bytes) -> list[int]:
    padded = data + b"\x03" * ((-len(data)) % 5)
    return [
        sum(
            character << shift
            for character, shift in zip(
                padded[index : index + 5], (29, 22, 15, 8, 1)
            )
        )
        for index in range(0, len(padded), 5)
    ]


def pack_al_values(values: list[int]) -> list[int]:
    padded = values + [0] * (len(values) % 2)
    return [
        (padded[index] << 20) | (padded[index + 1] << 4)
        for index in range(0, len(padded), 2)
    ]


class CadrAstTests(unittest.TestCase):
    def test_metrics_bearing_bitmap_and_authored_raster_height(self) -> None:
        source = (
            b"KSTID\n3\n2\n0\n"
            b"\f101\n3\n4\n-1\n **\n* *\n"
            b"\f102\n2\n4\n0\n**\n"
        )
        font = cadr.parse_ast(Path("demo.ast"), pack_seven_bit_text(source))
        self.assertEqual(font.character_height, 3)
        self.assertEqual(font.raster_height, 2)
        first, second = font.glyphs
        self.assertEqual(first.advance, 4)
        self.assertEqual(first.x_offset, 1)
        self.assertEqual(first.y_offset, 0)
        self.assertEqual(first.rows, (0b011, 0b101))
        self.assertEqual(second.rows, (0b11, 0))
        self.assertEqual(
            font.metadata["source_metrics"][str(0o102)]["source_raster_row_count"],
            1,
        )

    def test_nonzero_column_adjustment_is_not_silently_treated_as_tracking(self) -> None:
        source = b"KSTID\n1\n1\n1\n\f101\n1\n1\n0\n*\n"
        with self.assertRaisesRegex(cadr.SourceError, "column-position adjustment"):
            cadr.parse_ast(Path("tracking.ast"), pack_seven_bit_text(source))

    def test_truncated_raster_is_rejected(self) -> None:
        source = b"KSTID\n2\n1\n0\n\f101\n3\n4\n0\n***"
        with self.assertRaisesRegex(cadr.SourceError, "truncated AST raster row"):
            cadr.parse_ast(Path("short.ast"), pack_seven_bit_text(source))


class CadrKstTests(unittest.TestCase):
    @staticmethod
    def one_glyph_words() -> list[int]:
        return [
            0,
            (1 << 18) | 1,
            1,
            0o101,
            (1 << 18) | 1,
            1 << 28,
            cadr.MASK36,
        ]

    def test_declared_raster_and_metrics(self) -> None:
        font = cadr.parse_kst(Path("demo.kst"), self.one_glyph_words())
        self.assertEqual(font.glyphs[0].code, 0o101)
        self.assertEqual(font.glyphs[0].rows, (1,))
        self.assertEqual(font.glyphs[0].advance, 1)

    def test_nonzero_column_adjustment_is_rejected(self) -> None:
        words = self.one_glyph_words()
        words[1] |= 1 << 27
        with self.assertRaisesRegex(cadr.SourceError, "column-position adjustment"):
            cadr.parse_kst(Path("tracking.kst"), words)

    def test_padding_and_truncation_are_rejected(self) -> None:
        truncated = self.one_glyph_words()[:-1]
        with self.assertRaisesRegex(cadr.SourceError, "truncated KST raster"):
            cadr.parse_kst(Path("short.kst"), truncated)
        low_bits = self.one_glyph_words()
        low_bits[-2] |= 1
        with self.assertRaisesRegex(cadr.SourceError, "low four bits"):
            cadr.parse_kst(Path("low-bits.kst"), low_bits)


class CadrAlTests(unittest.TestCase):
    def test_pixels_below_declared_line_height_are_preserved(self) -> None:
        pointers = [256 - code for code in range(256)]
        code = 0o30
        descriptor_index = 260
        pointers[code] = descriptor_index - code
        words = pack_al_values(
            [
                15,
                0x0C10,
                *pointers,
                17,
                0,
                0x8000,
                0x8000,
                17,
                (14 << 8) | 2,
            ]
        )
        font = cadr.parse_al(Path("overflow.al"), words)
        glyph = next(glyph for glyph in font.glyphs if glyph.code == code)
        self.assertEqual(len(glyph.rows), 16)
        self.assertNotEqual(glyph.rows[15], 0)
        self.assertEqual(glyph.y_offset, font.baseline - 16)
        self.assertEqual(font.metadata["vertical_overflow_codes"], [code])


def synthetic_font(
    name: str, advances: tuple[int, ...], boxes: tuple[tuple[int, int, int], ...]
) -> common.BitmapFont:
    glyphs = tuple(
        common.Glyph(
            code=code + 65,
            bitmap_width=box[0],
            advance=advance,
            x_offset=box[1],
            y_offset=-1,
            rows=(1 << max(0, box[0] - 1),) * box[2],
        )
        for code, (advance, box) in enumerate(zip(advances, boxes))
    )
    return common.BitmapFont(
        name=name,
        character_height=3,
        raster_height=3,
        baseline=2,
        glyphs=glyphs,
        source_format="synthetic test",
        source_name="fixture",
    )


class XlfdOutputTests(unittest.TestCase):
    def test_zero_width_no_op_slots_stay_in_json_but_not_bdf(self) -> None:
        font = common.BitmapFont(
            name="Placeholder",
            character_height=3,
            raster_height=3,
            baseline=2,
            glyphs=(
                common.Glyph(
                    code=64,
                    bitmap_width=0,
                    advance=0,
                    x_offset=0,
                    y_offset=-1,
                    rows=(0, 0, 0),
                ),
                common.Glyph(
                    code=65,
                    bitmap_width=3,
                    advance=4,
                    x_offset=0,
                    y_offset=-1,
                    rows=(0b010, 0b101, 0b111),
                ),
            ),
            source_format="synthetic test",
            source_name="fixture",
        )
        profile = common.bdf_profile(
            font, foundry="Misc", family_name="Placeholder"
        )
        self.assertEqual(profile["source_glyph_count"], 2)
        self.assertEqual(profile["bdf_glyph_count"], 1)
        self.assertEqual(profile["omitted_nonrendering_placeholder_count"], 1)
        self.assertEqual(profile["spacing"], "C")
        with tempfile.TemporaryDirectory() as directory:
            outputs = common.write_font_outputs(
                font,
                Path(directory),
                foundry="Misc",
                bdf_metadata=profile,
            )
            bdf = (Path(directory) / outputs["bdf"]).read_text(encoding="ascii")
            normalized = json.loads(
                (Path(directory) / outputs["json"]).read_text(encoding="utf-8")
            )
            self.assertIn("CHARS 1", bdf)
            self.assertNotIn("ENCODING 64", bdf)
            self.assertIn("ENCODING 65", bdf)
            self.assertEqual([glyph["code"] for glyph in normalized["glyphs"]], [64, 65])

    def test_spacing_classes_follow_xlfd_definitions(self) -> None:
        charcell = synthetic_font("Cell", (4, 4), ((3, 0, 3), (4, 0, 3)))
        monospace = synthetic_font("Mono", (4, 4), ((5, 0, 3), (4, 0, 3)))
        proportional = synthetic_font("Prop", (3, 4), ((3, 0, 3), (4, 0, 3)))
        self.assertEqual(
            common.bdf_profile(charcell, foundry="Misc", family_name="Cell")[
                "spacing"
            ],
            "C",
        )
        self.assertEqual(
            common.bdf_profile(monospace, foundry="Misc", family_name="Mono")[
                "spacing"
            ],
            "M",
        )
        self.assertEqual(
            common.bdf_profile(
                proportional, foundry="Misc", family_name="Prop"
            )["spacing"],
            "P",
        )

    def test_output_is_deterministic_addressable_and_xlfd_named(self) -> None:
        font = synthetic_font("Demo / Font", (4,), ((3, 0, 3),))
        profile = common.bdf_profile(
            font,
            foundry="Misc",
            family_name="MIT CADR DEMO",
            add_style_name="AST",
        )
        self.assertEqual(profile["xlfd_name"].count("-"), 14)
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_paths = common.write_font_outputs(
                font,
                Path(first),
                foundry="Misc",
                sheet_label_radix=8,
                bdf_metadata=profile,
            )
            second_paths = common.write_font_outputs(
                font,
                Path(second),
                foundry="Misc",
                sheet_label_radix=8,
                bdf_metadata=profile,
            )
            self.assertEqual(first_paths, second_paths)
            for relative in first_paths.values():
                self.assertEqual(
                    (Path(first) / relative).read_bytes(),
                    (Path(second) / relative).read_bytes(),
                )
            bdf = (Path(first) / first_paths["bdf"]).read_text(encoding="ascii")
            self.assertIn(f"FONT {profile['xlfd_name']}", bdf)
            self.assertIn("ENCODING 65", bdf)
            self.assertNotIn("ENCODING -1", bdf)
            self.assertIn('CHARSET_ENCODING "FontSpecific"', bdf)
            png = (Path(first) / first_paths["sheet"]).read_bytes()
            self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(struct.unpack(">I", png[8:12])[0], 13)


class TextSpecimenTests(unittest.TestCase):
    @staticmethod
    def font() -> common.BitmapFont:
        return common.BitmapFont(
            name="Text specimen",
            character_height=3,
            raster_height=3,
            baseline=2,
            glyphs=(
                common.Glyph(32, 0, 1, 0, 0, ()),
                common.Glyph(65, 2, 3, 0, -1, (0b10, 0b01, 0b11)),
                common.Glyph(66, 2, 3, 0, -1, (0b11, 0b10, 0b11)),
            ),
            source_format="synthetic test",
            source_name="fixture",
        )

    def test_greedy_wrap_vsp_metadata_and_deterministic_png(self) -> None:
        font = self.font()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.png"
            second = Path(directory) / "second.png"
            metadata = common.write_text_specimen(
                font, "AA BB", first, max_advance=7, scale=2
            )
            repeated = common.write_text_specimen(
                font, "AA BB", second, max_advance=7, scale=2
            )
            self.assertEqual(metadata, repeated)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                [line["text"] for line in metadata["lines"]], ["AA", "BB"]
            )
            self.assertEqual(
                [line["advance"] for line in metadata["lines"]], [6, 6]
            )
            self.assertEqual(
                [line["baseline"] for line in metadata["lines"]], [2, 7]
            )
            self.assertEqual(metadata["vsp"], 2)
            self.assertEqual(metadata["native_line_height"], 5)
            self.assertEqual(metadata["native_padding"], 3)
            self.assertEqual(metadata["content_native_width"], 6)
            self.assertEqual(metadata["content_native_height"], 8)
            self.assertEqual(metadata["canvas_native_width"], 12)
            self.assertEqual(metadata["canvas_native_height"], 14)
            self.assertEqual((metadata["width"], metadata["height"]), (24, 28))
            self.assertEqual(
                [line["canvas_baseline"] for line in metadata["lines"]], [5, 10]
            )
            self.assertEqual(
                [line["pixel_baseline"] for line in metadata["lines"]], [10, 20]
            )
            png = first.read_bytes()
            self.assertEqual(struct.unpack(">II", png[16:24]), (24, 28))

    def test_all_bearing_and_vertical_overflow_pixels_are_retained(self) -> None:
        font = common.BitmapFont(
            name="Overflow",
            character_height=3,
            raster_height=3,
            baseline=2,
            glyphs=(
                common.Glyph(65, 3, 2, -1, 0, (0b100, 0b010, 0b001)),
                common.Glyph(66, 3, 2, 1, -2, (0b100, 0b010, 0b001)),
            ),
            source_format="synthetic test",
            source_name="fixture",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "overflow.png"
            metadata = common.write_text_specimen(
                font, "AB", path, max_advance=4, scale=1
            )
            self.assertEqual(
                metadata["content_native_bounds"],
                {"left": -1, "top": -1, "right": 6, "bottom": 4},
            )
            self.assertEqual(metadata["content_native_width"], 7)
            self.assertEqual(metadata["content_native_height"], 5)
            self.assertEqual(metadata["canvas_native_width"], 13)
            self.assertEqual(metadata["canvas_native_height"], 11)
            self.assertEqual((metadata["width"], metadata["height"]), (13, 11))

            png = path.read_bytes()
            compressed = bytearray()
            offset = 8
            while offset < len(png):
                length = struct.unpack(">I", png[offset : offset + 4])[0]
                kind = png[offset + 4 : offset + 8]
                payload = png[offset + 8 : offset + 8 + length]
                if kind == b"IDAT":
                    compressed.extend(payload)
                offset += 12 + length
            scanlines = zlib.decompress(bytes(compressed))
            row_size = 13 * 3 + 1
            self.assertEqual(scanlines[0], 0)
            self.assertEqual(tuple(scanlines[1:4]), (250, 250, 248))
            first_pixel = 3 * row_size + 1 + 3 * 3
            self.assertEqual(
                tuple(scanlines[first_pixel : first_pixel + 3]), (18, 20, 22)
            )
            last_pixel = 7 * row_size + 1 + 9 * 3
            self.assertEqual(
                tuple(scanlines[last_pixel : last_pixel + 3]), (18, 20, 22)
            )

    def test_missing_characters_and_unfittable_glyphs_are_rejected(self) -> None:
        font = self.font()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unused.png"
            with self.assertRaisesRegex(ValueError, r"lacks.*U\+0043"):
                common.write_text_specimen(
                    font, "AC", path, max_advance=20, scale=1
                )
            with self.assertRaisesRegex(ValueError, r"U\+0041 advance 3 exceeds"):
                common.write_text_specimen(
                    font, "A", path, max_advance=2, scale=1
                )
            self.assertFalse(path.exists())


class XIndexTests(unittest.TestCase):
    def test_alias_targets_with_xlfd_spaces_are_quoted(self) -> None:
        xlfd = "-Misc-MIT CADR Demo-Unknown-OT-Unknown--12-120-72-72-P-70-Misc-FontSpecific"
        catalog = {
            "fonts": [
                {
                    "name": "Demo",
                    "runtime_name": "Demo Runtime",
                    "variant_of": None,
                    "outputs": {"bdf": "bdf/demo.bdf"},
                    "bdf": {"xlfd_name": xlfd},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "bdf").mkdir()
            builder.write_x_indexes(output, catalog)
            self.assertEqual(
                (output / "bdf" / "fonts.alias").read_text(encoding="ascii"),
                "! Source-profile aliases; XLFD names remain authoritative.\n"
                f'cadr-demo "{xlfd}"\n'
                f'cadr-source-demo "{xlfd}"\n',
            )

    def test_runtime_names_reserve_unqualified_source_aliases(self) -> None:
        xlfd = "-Misc-MIT CADR Demo-Unknown-OT-Unknown--12-120-72-72-P-70-Misc-FontSpecific"
        catalog = {
            "fonts": [
                {
                    "name": "Demo",
                    "runtime_name": "Demo",
                    "variant_of": None,
                    "outputs": {"bdf": "bdf/demo.bdf"},
                    "bdf": {"xlfd_name": xlfd},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "bdf").mkdir()
            builder.write_x_indexes(
                output, catalog, reserved_convenience_names={"demo"}
            )
            self.assertEqual(
                (output / "bdf" / "fonts.alias").read_text(encoding="ascii"),
                "! Source-profile aliases; XLFD names remain authoritative.\n"
                f'cadr-source-demo "{xlfd}"\n',
            )

    def test_runtime_aliases_keep_legacy_explicit(self) -> None:
        current_xlfd = "-Misc-MIT CADR Demo-Unknown-OT-Unknown--12-120-72-72-P-70-Misc-FontSpecific"
        legacy_xlfd = "-Misc-MIT CADR Demo-Unknown-OT-Unknown-Legacy Old-12-120-72-72-P-70-Misc-FontSpecific"
        catalog = {
            "font_artifacts": [
                {
                    "artifact_name": "DEMO",
                    "runtime_name": "DEMO",
                    "classification": "compiled-only",
                    "outputs": {"bdf": "bdf/demo.bdf"},
                    "bdf_profile": {"xlfd_name": current_xlfd},
                },
                {
                    "artifact_name": "OLD-DEMO",
                    "runtime_name": "DEMO",
                    "classification": "legacy-compiled-version",
                    "outputs": {"bdf": "bdf/old-demo.bdf"},
                    "bdf_profile": {"xlfd_name": legacy_xlfd},
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "bdf").mkdir()
            aliases = builder.write_runtime_x_indexes(
                output, catalog, compatibility_aliases={}
            )
            self.assertEqual(aliases["cadr-demo"], current_xlfd)
            self.assertEqual(aliases["cadr-runtime-demo"], current_xlfd)
            self.assertEqual(
                aliases["cadr-runtime-legacy-old-demo"], legacy_xlfd
            )
            self.assertNotIn("cadr-old-demo", aliases)

    def test_colliding_aliases_with_different_targets_are_rejected(self) -> None:
        catalog = {
            "fonts": [
                {
                    "name": name,
                    "runtime_name": name,
                    "variant_of": "base",
                    "outputs": {"bdf": f"bdf/{index}.bdf"},
                    "bdf": {"xlfd_name": f"-target-{index}"},
                }
                for index, name in enumerate(("A B", "A-B"))
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "bdf").mkdir()
            with self.assertRaisesRegex(builder.BuildError, "alias collision"):
                builder.write_x_indexes(output, catalog)


class OutputDirectoryTests(unittest.TestCase):
    def test_clean_never_removes_unrecognized_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            common.prepare_output_directory(
                output, clean=False, owned_names={"bdf", "catalog.json"}
            )
            unknown = output / "keep.txt"
            unknown.write_text("not generated", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "unrecognized"):
                common.prepare_output_directory(
                    output, clean=True, owned_names={"bdf", "catalog.json"}
                )
            self.assertEqual(unknown.read_text(encoding="ascii"), "not generated")


if __name__ == "__main__":
    unittest.main()
