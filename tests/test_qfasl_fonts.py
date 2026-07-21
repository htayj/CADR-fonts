from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"
SOURCE = REPOSITORY / "sources" / "mit-cadr-system-software" / "src" / "lmfont"
MANIFEST = REPOSITORY / "config" / "runtime-source-manifest.json"
sys.path.insert(0, str(SCRIPTS))


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


qfasl = load_script("extract_cadr_qfasl_fonts", "extract-cadr-qfasl-fonts.py")


class RuntimeManifestTests(unittest.TestCase):
    def test_manifest_is_the_closed_49_file_runtime_corpus(self) -> None:
        manifest, specs = qfasl.load_runtime_manifest(MANIFEST)
        self.assertEqual(len(specs), 49)
        self.assertEqual(len({spec.runtime_name for spec in specs}), 47)
        self.assertEqual(
            Counter(spec.classification for spec in specs),
            {
                "source-backed-current": 30,
                "compiled-only": 17,
                "legacy-compiled-version": 2,
            },
        )
        self.assertEqual(
            {spec.source_file for spec in specs},
            {path.name for path in SOURCE.glob("*.qfasl")},
        )
        self.assertNotIn("medfnt.oqfasl", {spec.source_file for spec in specs})
        self.assertEqual(
            manifest["decoder_lineage"]["revision"],
            qfasl.DECODER_ANCESTOR_REVISION,
        )
        self.assertEqual(
            manifest["decoder_lineage"]["sha256"],
            qfasl.DECODER_ANCESTOR_SHA256,
        )

    def test_all_source_backed_records_name_the_reviewed_reference(self) -> None:
        _manifest, specs = qfasl.load_runtime_manifest(MANIFEST)
        source_backed = {
            spec.artifact_name: spec
            for spec in specs
            if spec.classification == "source-backed-current"
        }
        self.assertEqual(len(source_backed), 30)
        self.assertEqual(
            source_backed["CPT-CM10"].source_reference_artifact, "CM10"
        )
        self.assertEqual(
            source_backed["CPT-CM12"].source_reference_artifact, "CM12"
        )
        self.assertEqual(
            source_backed["CPTFONT"].source_reference_artifact, "CPTFON"
        )
        self.assertEqual(
            source_backed["ARROW"].source_reference_artifact, "ARROW-KST"
        )
        self.assertEqual(
            source_backed["BIGFNT"].source_reference_artifact, "BIGFNT-KST"
        )
        self.assertEqual(
            source_backed["MEDFNT"].expected_source_relation,
            "known-current-compiled-divergence",
        )
        self.assertEqual(
            source_backed["MOUSE"].expected_source_relation,
            "source-visible-subset",
        )
        self.assertEqual(
            source_backed["MOUSE"].expected_source_relation_details[
                "runtime_extra_visible_codes"
            ],
            [28, 29, 30],
        )
        self.assertEqual(
            source_backed["MEDFNT"].expected_source_relation_details,
            {
                "codes_are_original_cadr_numeric_values": True,
                "runtime_extra_visible_codes": [0, 9, 10, 12, 13, 127],
                "changed_common_rendering_glyph_count": 57,
                "total_rendering_difference_code_count": 63,
                "common_advance_difference_code_count": 0,
            },
        )
        exact = {
            spec.artifact_name
            for spec in source_backed.values()
            if spec.expected_source_relation == "exact-runtime-visible"
        }
        self.assertEqual(len(exact), 28)

    def test_germ35_raster_order_exception_has_pinned_evidence(self) -> None:
        manifest, _specs = qfasl.load_runtime_manifest(MANIFEST)
        self.assertEqual(set(manifest["raster_order_overrides"]), {"GERM35"})
        profile = manifest["raster_order_overrides"]["GERM35"]
        self.assertEqual(profile["historical_screen_mode"], "16-bit")
        self.assertEqual(profile["reference_compiler_entrypoint"], "FCMP-16")
        self.assertEqual(
            profile["structural_signature"],
            {
                "indexing_table": True,
                "raster_width": 16,
                "rasters_per_word": 2,
            },
        )
        evidence = {
            record["path"]: record["sha256"]
            for record in profile["historical_evidence"]
        }
        self.assertEqual(
            evidence,
            {
                "src/lmio1/fcmp.66": (
                    "c6efa82ffcb242ee6258e514689e8ddab5d3f9a244f88ca225ab9fd4c9e24a07"
                ),
                "src/lmio/tvdefs.52": (
                    "3049634797d9e9a1333a8bbc6b6e5a704fc0e4cf75e9af625051d526046cd13a"
                ),
                "src/lmio/tv.347": (
                    "bf6c732a7eaad10f03ce703507bc4362d5b61d18fd3331d4ee5c97e08738a318"
                ),
                "src/moon/wall.3": (
                    "f3e82f13d17ef8927f219b6e3cf637587d95665dc5d6110b63e8c7829295b224"
                ),
            },
        )


class RuntimeDecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.decoded = qfasl.decode_reviewed_fonts(SOURCE, MANIFEST)
        cls.by_artifact = {item.spec.artifact_name: item for item in cls.decoded}

    def test_every_reviewed_font_decodes_without_evaluation(self) -> None:
        self.assertEqual(len(self.decoded), 49)
        self.assertEqual(set(self.by_artifact), {item.font.name for item in self.decoded})
        self.assertTrue(
            all(
                item.font.metadata["decoder_safety"]
                == "strict inert reviewed subset; no QFASL operation evaluated"
                for item in self.decoded
            )
        )

    def test_runtime_names_and_legacy_artifacts_are_distinct(self) -> None:
        self.assertEqual(
            self.by_artifact["CPTFONT"].spec.runtime_symbol, "FONTS:CPTFONT"
        )
        self.assertEqual(self.by_artifact["MOUSE"].spec.runtime_symbol, "MOUSE")
        self.assertEqual(
            self.by_artifact["N43XMS"].spec.runtime_name, "43VXMS"
        )
        self.assertEqual(self.by_artifact["NTOG"].spec.runtime_name, "TOG")
        self.assertEqual(
            self.by_artifact["N43XMS"].spec.classification,
            "legacy-compiled-version",
        )

    def test_runtime_only_visible_glyphs_are_recovered(self) -> None:
        arrow = {
            glyph.code: glyph for glyph in self.by_artifact["ARROW"].font.glyphs
        }
        mouse = {
            glyph.code: glyph for glyph in self.by_artifact["MOUSE"].font.glyphs
        }
        self.assertTrue(any(arrow[0o3].rows))
        self.assertTrue(any(arrow[0o6].rows))
        self.assertEqual(arrow[0o3].advance, 14)
        for code in (0o34, 0o35, 0o36):
            self.assertTrue(any(mouse[code].rows), f"missing visible MOUSE {code:o}")

    def test_germ35_uses_reviewed_16_bit_display_order(self) -> None:
        corrected = [
            item
            for item in self.decoded
            if item.font.metadata["display_raster_normalization"] != "none"
        ]
        self.assertEqual([item.spec.artifact_name for item in corrected], ["GERM35"])

        structural_matches = sorted(
            item.spec.artifact_name
            for item in self.decoded
            if item.font.metadata["raster_width"] == 16
            and item.font.metadata["rasters_per_word"] == 2
            and item.font.metadata["indexing_table"]
        )
        self.assertEqual(structural_matches, ["GERM35"])

        germ = self.by_artifact["GERM35"].font
        self.assertEqual(germ.metadata["historical_screen_mode"], "16-bit")
        self.assertEqual(
            germ.metadata["raster_order_reference"],
            "FCMP-16 in pinned fcmp.66",
        )
        self.assertEqual(
            germ.metadata["serialized_raster_order"], "16-bit-screen"
        )
        self.assertEqual(len(germ.glyphs), 128)
        self.assertEqual(len(qfasl._bdf_semantic_glyphs(germ)), 75)
        self.assertEqual(sum(any(glyph.rows) for glyph in germ.glyphs), 74)
        self.assertEqual(
            qfasl.bdf_profile(
                germ,
                foundry="Misc",
                family_name="MIT CADR GERM35",
                add_style_name="System 46 Runtime",
            )["spacing"],
            "P",
        )

        glyphs = {glyph.code: glyph for glyph in germ.glyphs}
        capital_a = glyphs[ord("A")]
        self.assertEqual(
            (
                capital_a.bitmap_width,
                capital_a.advance,
                capital_a.x_offset,
                capital_a.y_offset,
            ),
            (32, 23, 0, -9),
        )
        self.assertEqual(capital_a.rows[7], 0x1F007000)
        self.assertEqual(capital_a.rows[8], 0x3F99F000)
        self.assertEqual(capital_a.rows[30], 0x00010000)
        self.assertEqual(
            hashlib.sha256(
                b"".join(row.to_bytes(4, "big") for row in capital_a.rows)
            ).hexdigest(),
            "2a8e52c6f116e1f4a15d6f0d5b691d7ddd563e5b2b66f3d33148c1be288a9741",
        )

        lowercase_a = glyphs[ord("a")]
        self.assertEqual(lowercase_a.rows[14:17], (0x0600, 0x0FC0, 0x1FF0))
        self.assertEqual(lowercase_a.rows[27], 0x7FF8)

    def test_germ35_rows_match_the_historical_16_bit_packing_formula(self) -> None:
        """Reconstruct display rows directly from serialized QRAST words."""

        item = self.by_artifact["GERM35"]
        _symbol, raster = qfasl._serialized_font_binding(item.parser.bindings)
        indexes = raster.leader[0o14].values()
        words_per_character = raster.leader[0o10]
        raster_qs = [
            int(raster.initialization[index])
            | (int(raster.initialization[index + 1]) << 16)
            for index in range(0, len(raster.initialization), 2)
        ]

        for glyph in item.font.glyphs:
            bitmap_width = (
                indexes[glyph.code + 1] - indexes[glyph.code]
            ) * 16
            self.assertEqual(glyph.bitmap_width, bitmap_width)
            expected_rows = []
            for row in range(item.font.raster_height):
                packed_row = 0
                for column in range(bitmap_width):
                    storage_character = indexes[glyph.code] + column // 16
                    word_index = (
                        words_per_character * storage_character + row // 2
                    )
                    bit_position = (1 - row % 2) * 16 + (15 - column % 16)
                    packed_row = (
                        packed_row << 1
                    ) | ((raster_qs[word_index] >> bit_position) & 1)
                expected_rows.append(packed_row)
            self.assertEqual(
                glyph.rows,
                tuple(expected_rows),
                f"GERM35 code {glyph.code:o} differs from QIFY-RASTER-HARD",
            )

    def test_germ35_normalization_changes_only_display_pixels(self) -> None:
        item = self.by_artifact["GERM35"]
        serialized, _parser, _words = qfasl._decode_bytes(
            (SOURCE / item.spec.source_file).read_bytes(),
            item.spec.source_file,
            item.spec.artifact_name,
            item.spec.runtime_name,
            item.spec.runtime_symbol,
        )
        corrected = item.font
        self.assertEqual(
            (
                corrected.character_height,
                corrected.raster_height,
                corrected.baseline,
            ),
            (
                serialized.character_height,
                serialized.raster_height,
                serialized.baseline,
            ),
        )
        corrected_metrics = [
            (
                glyph.code,
                glyph.bitmap_width,
                glyph.advance,
                glyph.x_offset,
                glyph.y_offset,
            )
            for glyph in corrected.glyphs
        ]
        serialized_metrics = [
            (
                glyph.code,
                glyph.bitmap_width,
                glyph.advance,
                glyph.x_offset,
                glyph.y_offset,
            )
            for glyph in serialized.glyphs
        ]
        self.assertEqual(corrected_metrics, serialized_metrics)
        self.assertEqual(
            sum(
                corrected_glyph.rows != serialized_glyph.rows
                for corrected_glyph, serialized_glyph in zip(
                    corrected.glyphs, serialized.glyphs
                )
            ),
            74,
        )

    def test_reviewed_semantic_oracles_cover_lossless_and_bdf_geometry(self) -> None:
        observed = qfasl.runtime_semantic_inventory_digests(self.decoded)
        expected = {
            name: record["sha256"]
            for name, record in self.manifest["semantic_inventories"].items()
        }
        self.assertEqual(observed, expected)
        self.assertEqual(
            self.manifest["semantic_inventories"][
                "normalized_runtime_font_geometry"
            ]["glyph_count"],
            6170,
        )
        self.assertEqual(
            self.manifest["semantic_inventories"]["bdf_geometry"][
                "emitted_glyph_count"
            ],
            5689,
        )

    def test_unknown_eval_opcode_is_rejected_before_any_execution(self) -> None:
        parser = qfasl.FontQfaslParser([0o100011])
        with self.assertRaisesRegex(qfasl.QfaslError, "never evaluated"):
            parser._parse_group()

    def test_reviewed_byte_hash_rejects_same_length_mutation(self) -> None:
        source = SOURCE / "cptfon.qfasl"
        raw = source.read_bytes()
        mutated = bytes([raw[0] ^ 1]) + raw[1:]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / source.name
            path.write_bytes(mutated)
            with self.assertRaisesRegex(qfasl.QfaslError, "SHA-256"):
                qfasl._reviewed_bytes(
                    path,
                    len(raw),
                    qfasl._sha256(raw),
                )

    def test_distribution_writes_all_profiles_and_supports_omit_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "runtime"
            catalog = qfasl.write_runtime_distribution(
                self.decoded,
                font_identities=qfasl.load_font_identities(),
                manifest=self.manifest,
                manifest_path=MANIFEST,
                source=SOURCE,
                output=output,
                clean=False,
                sheet_columns=16,
                sheet_scale=1,
                include_json=False,
            )
            self.assertEqual(catalog["artifact_count"], 49)
            self.assertEqual(len(list((output / "bdf").glob("*.bdf"))), 49)
            self.assertEqual(len(list((output / "sheets").glob("*.png"))), 49)
            self.assertFalse((output / "json").exists())
            self.assertTrue(
                all("json" not in record["outputs"] for record in catalog["font_artifacts"])
            )
            profiles = {
                record["artifact_name"]: record["bdf_profile"]
                for record in catalog["font_artifacts"]
            }
            self.assertEqual(
                len({profile["xlfd_name"] for profile in profiles.values()}),
                49,
            )
            self.assertIn("MIT CADR Fixed", profiles["CPTFONT"]["xlfd_name"])
            self.assertEqual(
                profiles["CPTFONT"]["add_style_name"], "System 46 Runtime"
            )
            self.assertEqual(
                profiles["N43XMS"]["add_style_name"],
                "System 46 Legacy N43XMS",
            )
            records = {
                record["artifact_name"]: record
                for record in catalog["font_artifacts"]
            }
            self.assertEqual(
                records["CPTFONT"]["logical_identity"]["typographic"]["family_name"],
                "MIT CADR Fixed",
            )
            self.assertNotIn("representation", records["CPTFONT"]["logical_identity"])
            self.assertEqual(
                records["CPTFONT"]["representation"]["style_name"],
                "System 46 Runtime",
            )
            self.assertEqual(
                catalog["display_layout_policy"][
                    "system_46_sheet_default_vertical_spacing_pixels"
                ],
                2,
            )
            copied_manifest = json.loads(
                (output / "runtime-source-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(copied_manifest, self.manifest)
            self.assertEqual(
                catalog["raster_order_overrides"],
                self.manifest["raster_order_overrides"],
            )
            raster_orders = {
                record["artifact_name"]: record["raster_order_override"]
                for record in catalog["font_artifacts"]
                if record["raster_order_override"] is not None
            }
            self.assertEqual(set(raster_orders), {"GERM35"})


if __name__ == "__main__":
    unittest.main()
