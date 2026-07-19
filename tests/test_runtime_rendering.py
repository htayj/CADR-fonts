from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "check_runtime_rendering.py"


def load_script():
    spec = importlib.util.spec_from_file_location("check_runtime_rendering", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve postponed annotations through the registered module.
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rendering = load_script()


def fixture_bdf(
    *,
    name: str = "-Misc-CADR Render Test-Medium-R-Normal--5-50-72-72-P-40-Misc-FontSpecific",
) -> str:
    return f'''STARTFONT 2.1
FONT {name}
SIZE 5 72 72
FONTBOUNDINGBOX 5 5 -1 -1
STARTPROPERTIES 17
FONT_ASCENT 4
FONT_DESCENT 1
FOUNDRY "Misc"
FAMILY_NAME "CADR Render Test"
WEIGHT_NAME "Medium"
SLANT "R"
SETWIDTH_NAME "Normal"
ADD_STYLE_NAME ""
PIXEL_SIZE 5
POINT_SIZE 50
RESOLUTION_X 72
RESOLUTION_Y 72
SPACING "P"
AVERAGE_WIDTH 40
CHARSET_REGISTRY "Misc"
CHARSET_ENCODING "FontSpecific"
DEFAULT_CHAR 0
ENDPROPERTIES
CHARS 3
STARTCHAR ZERO
ENCODING 0
SWIDTH 600 0
DWIDTH 3 0
BBX 3 3 0 -1
BITMAP
40
A0
E0
ENDCHAR
STARTCHAR A
ENCODING 65
SWIDTH 1000 0
DWIDTH 5 0
BBX 5 4 -1 0
BITMAP
70
88
F8
88
ENDCHAR
STARTCHAR HIGH
ENCODING 255
SWIDTH 800 0
DWIDTH 4 0
BBX 2 2 1 1
BITMAP
C0
40
ENDCHAR
ENDFONT
'''


def write_fixture(directory: str, filename: str = "fixture.bdf", **kwargs) -> Path:
    path = Path(directory) / filename
    path.write_text(fixture_bdf(**kwargs), encoding="ascii")
    return path


def unicode_fixture_bdf(
    *,
    name: str = (
        "-Misc-CADR Unicode Render Test-Medium-R-Normal-Unicode-5-50-72-72-"
        "P-40-ISO10646-1"
    ),
) -> str:
    return (
        fixture_bdf(name=name)
        .replace('ADD_STYLE_NAME ""', 'ADD_STYLE_NAME "Unicode"')
        .replace('CHARSET_REGISTRY "Misc"', 'CHARSET_REGISTRY "ISO10646"')
        .replace('CHARSET_ENCODING "FontSpecific"', 'CHARSET_ENCODING "1"')
        .replace("DEFAULT_CHAR 0", "DEFAULT_CHAR 183")
        .replace("ENCODING 0\n", "ENCODING 183\n")
        .replace("ENCODING 65\n", "ENCODING 8592\n")
        .replace("ENCODING 255\n", "ENCODING 57344\n")
    )


def write_unicode_fixture(
    directory: str, filename: str = "unicode-fixture.bdf", **kwargs
) -> Path:
    path = Path(directory) / filename
    path.write_text(unicode_fixture_bdf(**kwargs), encoding="ascii")
    return path


class BdfRenderingTests(unittest.TestCase):
    def test_raw_eight_bit_pixels_bearings_and_extents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            font = rendering.parse_bdf(write_fixture(directory))
        data = bytes((0, 65, 255))
        extents = rendering.measure_defined_text(font, data)
        self.assertEqual(
            extents,
            rendering.TextExtents(
                lbearing=0,
                rbearing=11,
                width=12,
                ascent=4,
                descent=1,
            ),
        )
        raster = rendering.render_defined_text(font, data, baseline_y=10)
        # ZERO starts at x=0 and top=8; A has a -1 bearing after a 3px
        # advance; HIGH has a +1 bearing after total advance 8.
        self.assertIn((1, 8), raster.pixels)
        self.assertIn((4, 6), raster.pixels)
        self.assertIn((9, 7), raster.pixels)
        self.assertNotIn((0, 8), raster.pixels)

    def test_undefined_codes_are_excluded_from_probes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            font = rendering.parse_bdf(write_fixture(directory))
        self.assertEqual(rendering.probe_strings(font), ((0, 65, 255),))
        with self.assertRaisesRegex(rendering.RenderCheckError, "undefined code 66"):
            rendering.render_defined_text(font, b"B")

    def test_unicode_bmp_codepoints_are_measured_and_rendered_as_int_sequences(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            font = rendering.parse_bdf(write_unicode_fixture(directory))
        data = (0x00B7, 0x2190, 0xE000)
        self.assertTrue(font.is_iso10646)
        self.assertEqual(rendering._x_character_width(font), 16)
        self.assertEqual(rendering.probe_strings(font), (data,))
        self.assertEqual(
            rendering.measure_defined_text(font, data),
            rendering.TextExtents(0, 11, 12, 4, 1),
        )
        self.assertEqual(
            rendering.render_defined_text(font, data).pixels,
            rendering.render_defined_text(font, list(data)).pixels,
        )

    def test_cadr_default_vsp_and_mixed_font_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = rendering.parse_bdf(write_fixture(directory, "first.bdf"))
            second_text = fixture_bdf(
                name="-Misc-CADR Short-Medium-R-Normal--4-40-72-72-P-40-Misc-FontSpecific"
            ).replace("SIZE 5 72 72", "SIZE 4 72 72").replace(
                "FONT_ASCENT 4\nFONT_DESCENT 1", "FONT_ASCENT 2\nFONT_DESCENT 2"
            )
            second_path = Path(directory) / "second.bdf"
            second_path.write_text(second_text, encoding="ascii")
            second = rendering.parse_bdf(second_path)
        layout = rendering.render_cadr_lines(
            [[(second, b"A"), (first, bytes((0,)))], [(first, b"A")]],
            font_map=[first, second],
        )
        self.assertEqual(layout.sheet_baseline, 4)
        self.assertEqual(layout.line_height, 7)  # max character height 5 + VSP 2
        self.assertEqual([run.baseline_y for run in layout.runs], [4, 4, 11])
        self.assertEqual([run.x for run in layout.runs], [0, 5, 0])

    def test_parser_accepts_bmp_boundary_and_rejects_non_scalar_encodings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(directory)
            path.write_text(
                path.read_text(encoding="ascii").replace(
                    "ENCODING 255", "ENCODING 65535"
                ),
                encoding="ascii",
            )
            font = rendering.parse_bdf(path)
            self.assertIn(0xFFFF, font.glyphs)

            for encoding, message in (
                (-1, "outside the Unicode BMP"),
                (0x10000, "outside the Unicode BMP"),
                (0xD800, "surrogate"),
                (0xDFFF, "surrogate"),
            ):
                path.write_text(
                    fixture_bdf().replace(
                        "ENCODING 255", f"ENCODING {encoding}"
                    ),
                    encoding="ascii",
                )
                with self.subTest(encoding=encoding):
                    with self.assertRaisesRegex(
                        rendering.RenderCheckError, message
                    ):
                        rendering.parse_bdf(path)

    def test_xchar2b_uses_big_endian_codepoint_bytes(self) -> None:
        encoded = rendering._xchar2b_array((0x00B7, 0x2190, 0xE000, 0xFFFF))
        self.assertEqual(
            [(item.byte1, item.byte2) for item in encoded],
            [(0x00, 0xB7), (0x21, 0x90), (0xE0, 0x00), (0xFF, 0xFF)],
        )

    def test_font_specific_profiles_retain_the_raw_eight_bit_x_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            font = rendering.parse_bdf(write_fixture(directory))
        self.assertFalse(font.is_iso10646)
        self.assertEqual(rendering._x_character_width(font), 8)

    def test_discovery_is_closed_over_the_four_distribution_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            expected = []
            for relative in (
                Path("bdf/source.bdf"),
                Path("runtime/bdf/runtime.bdf"),
                Path("unicode/source/bdf/unicode-source.bdf"),
                Path("unicode/runtime/bdf/unicode-runtime.bdf"),
            ):
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                expected.append(path)
            ignored = output / "other" / "bdf" / "unowned.bdf"
            ignored.parent.mkdir(parents=True)
            ignored.touch()
            self.assertEqual(rendering.discover_bdfs(output), sorted(expected))

    def test_constant_bdf_metrics_select_computed_ink_extents(self) -> None:
        font = rendering.BdfFont(
            path=Path("constant.bdf"),
            name="constant",
            ascent=3,
            descent=0,
            spacing="C",
            glyphs={
                1: rendering.Glyph(1, 4, 4, 3, 0, 0, (0b1000, 0, 0)),
                2: rendering.Glyph(2, 4, 4, 3, 0, 0, (0, 0, 0b0001)),
            },
        )
        self.assertEqual(
            rendering.expected_xtext_extents(font, bytes((1,))),
            rendering.TextExtents(0, 1, 4, 3, -2),
        )


class ExternalXRenderingTests(unittest.TestCase):
    @unittest.skipUnless(
        all(rendering.external_dependencies().values()),
        "bdftopcf, mkfontdir, Xvfb, and libX11 are not all installed",
    )
    def test_x_framebuffer_extents_and_combined_alias_paths_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_directory = Path(directory) / "bdf"
            runtime_directory = Path(directory) / "runtime" / "bdf"
            unicode_directory = (
                Path(directory) / "unicode" / "source" / "bdf"
            )
            source_directory.mkdir(parents=True)
            runtime_directory.mkdir(parents=True)
            unicode_directory.mkdir(parents=True)
            source_name = (
                "-Misc-CADR Source Test-Medium-R-Normal--5-50-72-72-P-40-"
                "Misc-FontSpecific"
            )
            runtime_name = (
                "-Misc-CADR Runtime Test-Medium-R-Normal--5-50-72-72-P-40-"
                "Misc-FontSpecific"
            )
            source = write_fixture(str(source_directory), name=source_name)
            runtime = write_fixture(
                str(runtime_directory), filename="runtime.bdf", name=runtime_name
            )
            unicode_name = (
                "-Misc-CADR Unicode Source Test-Medium-R-Normal-Unicode-5-50-"
                "72-72-P-40-ISO10646-1"
            )
            unicode_source = write_unicode_fixture(
                str(unicode_directory), name=unicode_name
            )
            (source_directory / "fonts.alias").write_text(
                f'cadr-source-test "{source_name}"\n', encoding="ascii"
            )
            (runtime_directory / "fonts.alias").write_text(
                f'cadr-runtime-test "{runtime_name}"\n', encoding="ascii"
            )
            (unicode_directory / "fonts.alias").write_text(
                f'cadr-unicode-source-test "{unicode_name}"\n',
                encoding="ascii",
            )
            result = rendering.validate_external(
                [source, runtime, unicode_source]
            )
        self.assertEqual(
            result,
            {
                "font_count": 3,
                "probe_count": 3,
                "glyph_count": 9,
                "font_path_count": 3,
                "alias_count": 3,
            },
        )


if __name__ == "__main__":
    unittest.main()
