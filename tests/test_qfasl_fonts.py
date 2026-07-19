from __future__ import annotations

from collections import Counter
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
            self.assertIn("MIT CADR CPTFONT", profiles["CPTFONT"]["xlfd_name"])
            self.assertEqual(
                profiles["CPTFONT"]["add_style_name"], "System 46 Runtime"
            )
            self.assertEqual(
                profiles["N43XMS"]["add_style_name"],
                "System 46 Legacy N43XMS",
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


if __name__ == "__main__":
    unittest.main()
