from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"
MAPPING = REPOSITORY / "config" / "unicode-mapping.json"
sys.path.insert(0, str(SCRIPTS))


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


builder = load_script("build_unicode_fonts", "build_unicode_fonts.py")
checker = load_script("check_unicode_dist", "check_unicode_dist.py")


def fixture_bdf() -> str:
    return '''STARTFONT 2.1
COMMENT Fixture raw CADR bitmap
COMMENT ENCODING values are original CADR character codes, not Unicode
FONT -Misc-MIT CADR Fixture-Unknown-OT-Unknown--5-50-72-72-P-40-Misc-FontSpecific
SIZE 5 72 72
FONTBOUNDINGBOX 5 4 -1 0
STARTPROPERTIES 16
FOUNDRY "Misc"
FAMILY_NAME "MIT CADR Fixture"
WEIGHT_NAME "Unknown"
SLANT "OT"
SETWIDTH_NAME "Unknown"
ADD_STYLE_NAME ""
PIXEL_SIZE 5
POINT_SIZE 50
RESOLUTION_X 72
RESOLUTION_Y 72
SPACING "P"
AVERAGE_WIDTH 40
CHARSET_REGISTRY "Misc"
CHARSET_ENCODING "FontSpecific"
FONT_ASCENT 4
FONT_DESCENT 1
ENDPROPERTIES
CHARS 3
STARTCHAR C0000
ENCODING 0
SWIDTH 600 0
DWIDTH 3 0
BBX 3 3 0 0
BITMAP
00
00
00
ENDCHAR
STARTCHAR C0041
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
STARTCHAR C0042
ENCODING 66
SWIDTH 800 0
DWIDTH 4 0
BBX 2 2 1 1
BITMAP
C0
40
ENDCHAR
ENDFONT
'''


def fixture_mapping() -> dict[int, dict[str, object]]:
    return {
        0: {
            "unicode": 0x00B7,
            "unicode_hex": "U+00B7",
            "kind": "standard",
            "label": "MIDDLE DOT",
            "status": "fixture-standard",
        },
        65: {
            "unicode": 0xE000,
            "unicode_hex": "U+E000",
            "kind": "private-use",
            "label": "FIXTURE PRIVATE A",
            "status": "documented-private-use",
        },
        66: {
            "unicode": 0x2190,
            "unicode_hex": "U+2190",
            "kind": "standard",
            "label": "LEFT ARROW",
            "status": "fixture-standard",
        },
    }


def pua_repertoire(index: int, prefix: str = "FIXTURE") -> dict[str, object]:
    return {
        "mapping_kind": "pua-block",
        "pua_block_index": index,
        "pua_base": builder.PUA_FIRST + index * builder.PUA_BLOCK_SIZE,
        "label_prefix": prefix,
    }


def explicit_repertoire() -> dict[str, object]:
    mappings = {}
    for code in range(128):
        scalar = 0x0100 + code
        mappings[f"{code:03o}"] = {
            "unicode": scalar,
            "unicode_hex": f"U+{scalar:04X}",
            "unicode_name": f"FIXTURE {code:03o}",
            "status": "fixture",
            "label": f"FIXTURE {code:03o}",
        }
    return {"mapping_kind": "explicit", "mappings": mappings}


def derived_repertoire(
    *,
    base: str = "standard",
    index: int | None = 3,
    private_use_codes: list[str] | None = None,
    overrides: dict[str, dict[str, object]] | None = None,
    prefix: str = "DERIVED",
) -> dict[str, object]:
    result: dict[str, object] = {
        "mapping_kind": "derived",
        "base_repertoire": base,
        "private_use_codes": private_use_codes or [],
        "overrides": overrides or {},
    }
    if index is not None:
        result.update(
            {
                "pua_block_index": index,
                "pua_base": builder.PUA_FIRST + index * builder.PUA_BLOCK_SIZE,
                "label_prefix": prefix,
            }
        )
    return result


def manifest_with(repertoires: dict[str, dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mapping_id": "fixture-v1",
        "unicode_version": "fixture",
        "unicode_standard": {
            "version": "fixture",
            "ucd_url": "https://www.unicode.org/Public/fixture/ucd/UnicodeData.txt",
            "names_list_url": "https://www.unicode.org/Public/fixture/ucd/NamesList.txt",
            "private_use_specification_url": (
                "https://www.unicode.org/versions/Unicodefixture/"
                "core-spec/chapter-23/"
            ),
            "x_charset_registry": "ISO10646",
            "x_charset_encoding": "1",
            "xlfd_suffix": "iso10646-1",
        },
        "evidence": {},
        "expected": {
            key: "0" * 64 for key in builder.REQUIRED_SEMANTIC_ORACLES
        },
        "bmp_private_use": {
            "first": builder.PUA_FIRST,
            "last": builder.PUA_LAST,
            "capacity": builder.PUA_LAST - builder.PUA_FIRST + 1,
            "block_size": builder.PUA_BLOCK_SIZE,
            "allocation_formula": (
                "unicode = first + (pua_block_index * block_size) + "
                "original_cadr_code"
            ),
        },
        "repertoires": repertoires,
    }


class UnicodeMappingTests(unittest.TestCase):
    def write_manifest(self, directory: str, manifest: dict[str, object]) -> Path:
        path = Path(directory) / "mapping.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_pua_block_formula_has_stable_first_and_last_blocks(self) -> None:
        manifest = manifest_with(
            {
                "first": pua_repertoire(0, "FIRST"),
                "last": pua_repertoire(49, "LAST"),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            loaded = builder.load_mapping(self.write_manifest(directory, manifest))
        first = builder.repertoire_mapping(loaded, "first")
        last = builder.repertoire_mapping(loaded, "last")
        self.assertEqual((first[0]["unicode"], first[127]["unicode"]), (0xE000, 0xE07F))
        self.assertEqual((last[0]["unicode"], last[127]["unicode"]), (0xF880, 0xF8FF))
        self.assertEqual(last[7]["label"], "LAST CADR 007")

    def test_duplicate_json_object_keys_are_rejected(self) -> None:
        payload = json.dumps(manifest_with({"standard": explicit_repertoire()}))
        payload = payload.replace(
            '"schema_version": 1',
            '"schema_version": 1, "schema_version": 1',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.json"
            path.write_text(payload, encoding="utf-8")
            with self.assertRaisesRegex(
                builder.UnicodeBuildError,
                "duplicate JSON object key 'schema_version'",
            ):
                builder.load_mapping(path)

    def test_private_use_allocation_formula_is_part_of_the_schema(self) -> None:
        manifest = manifest_with({"standard": explicit_repertoire()})
        manifest["bmp_private_use"]["allocation_formula"] = "close enough"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                builder.UnicodeBuildError,
                "BMP PUA allocation formula changed",
            ):
                builder.load_mapping(self.write_manifest(directory, manifest))

    def test_standard_entries_may_not_assign_bmp_private_use_scalars(self) -> None:
        explicit = explicit_repertoire()
        explicit["mappings"]["000"].update(
            {"unicode": builder.PUA_FIRST, "unicode_hex": "U+E000"}
        )
        override = {
            "unicode": builder.PUA_FIRST,
            "unicode_hex": "U+E000",
            "unicode_name": "INVALID PRIVATE OVERRIDE",
            "status": "reviewed-repertoire-remap",
            "label": "INVALID PRIVATE OVERRIDE",
        }
        cases = (
            manifest_with({"standard": explicit}),
            manifest_with(
                {
                    "standard": explicit_repertoire(),
                    "derived": derived_repertoire(overrides={"000": override}),
                }
            ),
        )
        for manifest in cases:
            with self.subTest(), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(
                    builder.UnicodeBuildError,
                    "standard mapping may not assign BMP PUA",
                ):
                    builder.load_mapping(self.write_manifest(directory, manifest))

    def test_unknown_repertoire_fields_are_rejected(self) -> None:
        derived = derived_repertoire(private_use_codes=["000"])
        derived["private_use_code"] = "001"
        manifest = manifest_with(
            {"standard": explicit_repertoire(), "derived": derived}
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                builder.UnicodeBuildError,
                "unknown repertoire fields: private_use_code",
            ):
                builder.load_mapping(self.write_manifest(directory, manifest))

    def test_repertoire_evidence_must_name_the_manifest_registry(self) -> None:
        derived = derived_repertoire()
        derived["evidence"] = ["known-evidence"]
        manifest = manifest_with(
            {"standard": explicit_repertoire(), "derived": derived}
        )
        manifest["evidence"] = {
            "known-evidence": {
                "url": "https://example.invalid/evidence",
                "finding": "fixture",
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            builder.load_mapping(self.write_manifest(directory, manifest))

        derived["evidence"] = ["missing-evidence"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                builder.UnicodeBuildError,
                "unknown evidence IDs: missing-evidence",
            ):
                builder.load_mapping(self.write_manifest(directory, manifest))

    def test_all_four_semantic_oracles_are_mandatory(self) -> None:
        for oracle in builder.REQUIRED_SEMANTIC_ORACLES:
            manifest = manifest_with({"standard": explicit_repertoire()})
            del manifest["expected"][oracle]
            with self.subTest(oracle=oracle), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(
                    builder.UnicodeBuildError,
                    f"lowercase SHA-256 oracle: {oracle}",
                ):
                    builder.load_mapping(self.write_manifest(directory, manifest))

    def test_unicode_standard_must_match_the_emitted_profile(self) -> None:
        cases = (
            ("version", "other", "differs from unicode_version"),
            ("x_charset_registry", "ISO8859", "emitted ISO10646-1"),
            ("x_charset_encoding", 1, "emitted ISO10646-1"),
            ("x_charset_encoding", "99", "emitted ISO10646-1"),
            ("xlfd_suffix", "iso8859-1", "emitted ISO10646-1"),
            ("ucd_url", "https://example.invalid/ucd", "UCD URL"),
        )
        for field, value, message in cases:
            manifest = manifest_with({"standard": explicit_repertoire()})
            manifest["unicode_standard"][field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(builder.UnicodeBuildError, message):
                    builder.load_mapping(self.write_manifest(directory, manifest))

    def test_committed_evidence_records_match_the_pinned_sources(self) -> None:
        manifest = builder.load_mapping(MAPPING)
        source_manifest = json.loads(
            (REPOSITORY / "config" / "source-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        source_repository = {
            "url": source_manifest["repository"],
            "revision": source_manifest["revision"],
            "submodule_path": "sources/mit-cadr-system-software",
        }
        builder.validate_evidence_contract(
            manifest, source_repository
        )

        cases = (
            (
                "pinned-alto-font-loader",
                "sha256",
                "0" * 64,
                "pinned evidence SHA-256 changed",
            ),
            (
                "pinned-old-leftarrow-reader",
                "path",
                "src/lmio1/fntcnv.28",
                "pinned evidence path changed",
            ),
            (
                "pinned-cadr-character-table",
                "url",
                "https://example.invalid/char.18",
                "pinned evidence URL changed",
            ),
            (
                "rfc734-stanford-its-character-set",
                "url",
                "https://example.invalid/rfc734",
                "reviewed evidence URL changed",
            ),
        )
        for evidence_id, field, value, message in cases:
            changed = copy.deepcopy(manifest)
            changed["evidence"][evidence_id][field] = value
            with self.subTest(evidence_id=evidence_id, field=field):
                with self.assertRaisesRegex(builder.UnicodeBuildError, message):
                    builder.validate_evidence_contract(
                        changed, source_repository
                    )

    def test_duplicate_and_overflow_pua_blocks_are_rejected(self) -> None:
        cases = (
            (
                manifest_with(
                    {"first": pua_repertoire(0), "second": pua_repertoire(0)}
                ),
                "PUA block 0 is shared",
            ),
            (
                manifest_with(
                    {
                        "standard": explicit_repertoire(),
                        "first": pua_repertoire(3),
                        "derived": derived_repertoire(index=3),
                    }
                ),
                "PUA block 3 is shared",
            ),
            (manifest_with({"overflow": pua_repertoire(50)}), "invalid PUA block"),
        )
        for manifest, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(builder.UnicodeBuildError, message):
                    builder.load_mapping(self.write_manifest(directory, manifest))

    def test_duplicate_explicit_unicode_target_is_rejected(self) -> None:
        explicit = explicit_repertoire()
        explicit["mappings"]["001"]["unicode"] = explicit["mappings"]["000"][
            "unicode"
        ]
        explicit["mappings"]["001"]["unicode_hex"] = explicit["mappings"]["000"][
            "unicode_hex"
        ]
        manifest = manifest_with({"duplicate": explicit})
        with tempfile.TemporaryDirectory() as directory:
            loaded = builder.load_mapping(self.write_manifest(directory, manifest))
        with self.assertRaisesRegex(builder.UnicodeBuildError, "not injective"):
            builder.repertoire_mapping(loaded, "duplicate")

    def test_derived_repertoire_inherits_private_maps_then_overrides(self) -> None:
        override = {
            "unicode": 0x2603,
            "unicode_hex": "U+2603",
            "unicode_name": "SNOWMAN",
            "status": "reviewed-repertoire-remap",
            "label": "SNOWMAN",
        }
        manifest = manifest_with(
            {
                "standard": explicit_repertoire(),
                "hybrid": derived_repertoire(
                    private_use_codes=["000-002", "010"],
                    overrides={"001": override},
                ),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            loaded = builder.load_mapping(self.write_manifest(directory, manifest))
        standard = builder.repertoire_mapping(loaded, "standard")
        hybrid = builder.repertoire_mapping(loaded, "hybrid")
        base = builder.PUA_FIRST + 3 * builder.PUA_BLOCK_SIZE

        self.assertEqual(hybrid[0o000]["unicode"], base)
        self.assertEqual(hybrid[0o000]["kind"], "private-use")
        self.assertEqual(hybrid[0o000]["status"], "documented-private-use")
        self.assertEqual(hybrid[0o001]["unicode"], 0x2603)
        self.assertEqual(hybrid[0o001]["kind"], "standard")
        self.assertEqual(hybrid[0o001]["status"], "reviewed-repertoire-remap")
        self.assertEqual(hybrid[0o002]["unicode"], base + 0o002)
        self.assertEqual(hybrid[0o010]["unicode"], base + 0o010)
        self.assertEqual(hybrid[0o040], standard[0o040])
        self.assertEqual(len({value["unicode"] for value in hybrid.values()}), 128)

    def test_derived_private_use_ranges_reject_overlap_and_bad_bounds(self) -> None:
        cases = (
            (["000-010", "010-020"], "overlap at 010"),
            (["027-000"], "range is reversed"),
            (["000-200"], "outside 000-177"),
        )
        for selectors, message in cases:
            manifest = manifest_with(
                {
                    "standard": explicit_repertoire(),
                    "derived": derived_repertoire(private_use_codes=selectors),
                }
            )
            with self.subTest(selectors=selectors), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(builder.UnicodeBuildError, message):
                    builder.load_mapping(self.write_manifest(directory, manifest))

    def test_derived_repertoire_requires_an_earlier_explicit_base(self) -> None:
        cases = (
            (
                {"derived": derived_repertoire(base="missing")},
                "unknown or not earlier",
            ),
            (
                {
                    "private": pua_repertoire(0),
                    "derived": derived_repertoire(base="private", index=1),
                },
                "is not explicit",
            ),
            (
                {
                    "derived": derived_repertoire(base="standard"),
                    "standard": explicit_repertoire(),
                },
                "unknown or not earlier",
            ),
        )
        for repertoires, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(builder.UnicodeBuildError, message):
                    builder.load_mapping(
                        self.write_manifest(directory, manifest_with(repertoires))
                    )

    def test_derived_final_mapping_rejects_duplicate_unicode_target(self) -> None:
        duplicate = {
            "unicode": 0x0102,
            "unicode_hex": "U+0102",
            "unicode_name": "FIXTURE DUPLICATE",
            "status": "reviewed-repertoire-remap",
            "label": "FIXTURE DUPLICATE",
        }
        manifest = manifest_with(
            {
                "standard": explicit_repertoire(),
                "derived": derived_repertoire(
                    private_use_codes=[],
                    overrides={"001": duplicate},
                ),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            loaded = builder.load_mapping(self.write_manifest(directory, manifest))
        with self.assertRaisesRegex(builder.UnicodeBuildError, "not injective"):
            builder.repertoire_mapping(loaded, "derived")

    def test_appending_a_pua_registry_entry_does_not_change_existing_maps(self) -> None:
        initial = manifest_with(
            {
                "standard": explicit_repertoire(),
                "first": derived_repertoire(
                    index=0,
                    private_use_codes=["000-017"],
                ),
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            first_loaded = builder.load_mapping(
                self.write_manifest(directory, initial)
            )
        before = {
            repertoire_id: builder.repertoire_mapping(first_loaded, repertoire_id)
            for repertoire_id in first_loaded["repertoires"]
        }

        appended = copy.deepcopy(initial)
        appended["repertoires"]["second"] = derived_repertoire(
            index=1,
            private_use_codes=["020-037"],
        )
        with tempfile.TemporaryDirectory() as directory:
            appended_loaded = builder.load_mapping(
                self.write_manifest(directory, appended)
            )
        for repertoire_id, mapping in before.items():
            self.assertEqual(
                builder.repertoire_mapping(appended_loaded, repertoire_id), mapping
            )

    def test_committed_mapping_is_closed_and_documents_expected_repertoires(self) -> None:
        manifest = builder.load_mapping(MAPPING)
        self.assertEqual(len(manifest["assignments"]["source_logical_names"]), 88)
        self.assertEqual(len(manifest["assignments"]["runtime_artifacts"]), 49)
        self.assertEqual(
            set(manifest["repertoires"]),
            set(manifest["assignments"]["source_logical_names"].values())
            | set(manifest["assignments"]["runtime_artifacts"].values()),
        )
        self.assertEqual(
            {
                name
                for name, repertoire_id in manifest["assignments"][
                    "source_logical_names"
                ].items()
                if repertoire_id == "standard-cadr"
            },
            {
                "13FG",
                "13FGB",
                "16FG",
                "43VXMS",
                "5X5",
                "CPTFON",
                "HAFONT",
            },
        )
        self.assertEqual(
            {
                name
                for name, repertoire_id in manifest["assignments"][
                    "runtime_artifacts"
                ].items()
                if repertoire_id == "standard-cadr"
            },
            {
                "13FGB",
                "16FG",
                "31VR",
                "40VR",
                "43VXMS",
                "5X5",
                "BIGVG",
                "CPT-13FG",
                "CPTFONT",
                "MEDFNB",
                "MEDFNT",
                "N43XMS",
                "S35GER",
            },
        )
        standard = builder.repertoire_mapping(manifest, "standard-cadr")
        self.assertEqual(
            {
                repertoire_id: record["pua_block_index"]
                for repertoire_id, record in manifest["repertoires"].items()
                if "pua_block_index" in record
            },
            {
                "apl14": 0,
                "arr10": 1,
                "arrow": 2,
                "bug": 3,
                "clargk": 4,
                "cyr12": 5,
                "gates": 6,
                "math": 7,
                "musc10": 8,
                "plnk16": 9,
                "mouse": 10,
                "tog": 11,
                "swfont": 12,
                "search": 13,
                "ship": 14,
                "s30chs": 15,
                "alto-latin": 16,
                "alto-stanford": 17,
                "alto-greek": 18,
                "cadr-solid-zero": 19,
                "bigfnt": 20,
                "cm": 21,
                "gls7x9": 22,
                "mets": 23,
                "sail": 24,
                "vshd": 25,
                "vr20": 26,
                "germ35": 27,
            },
        )
        self.assertEqual(
            builder.canonical_sha256(
                [standard[code]["unicode"] for code in range(128)]
            ),
            "320781e69a390a2f67acc5c8a7b7beaaadd25143aa81c72c271be37583014958",
        )
        self.assertEqual(standard[0o000]["unicode"], 0x22C5)
        self.assertEqual(standard[0o002]["unicode"], 0x03B1)
        self.assertEqual(standard[0o030]["unicode"], 0x2190)
        self.assertEqual(standard[0o033]["unicode"], 0x25CA)
        self.assertEqual(standard[0o040]["unicode"], 0x0020)
        self.assertEqual(standard[0o101]["unicode"], 0x0041)
        self.assertEqual(standard[0o177]["unicode"], 0x222B)


class UnicodeTransformTests(unittest.TestCase):
    def test_transform_changes_only_addresses_and_unicode_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_path = root / "raw.bdf"
            unicode_path = root / "unicode.bdf"
            raw_path.write_text(fixture_bdf(), encoding="ascii")
            before = raw_path.read_bytes()
            result = builder.transform_bdf(
                raw_path,
                unicode_path,
                fixture_mapping(),
                mapping_id="fixture-v1",
            )
            raw = checker.parse_bdf(raw_path)
            unicode = checker.parse_bdf(unicode_path)
            self.assertEqual(raw_path.read_bytes(), before)

        self.assertEqual(result["glyph_count"], 3)
        self.assertEqual(result["standard_glyph_count"], 2)
        self.assertEqual(result["private_use_glyph_count"], 1)
        self.assertEqual(
            result["font_geometry"],
            {
                "size": "5 72 72",
                "font_bounding_box": "5 4 -1 0",
                "font_ascent": 4,
                "font_descent": 1,
            },
        )
        self.assertEqual(list(unicode["glyphs"]), [0x00B7, 0xE000, 0x2190])
        self.assertEqual(
            unicode["font"],
            "-Misc-MIT CADR Fixture-Unknown-OT-Unknown-Unicode-5-50-72-72-"
            "P-40-ISO10646-1",
        )
        self.assertEqual(unicode["properties"]["CHARSET_REGISTRY"], "ISO10646")
        self.assertEqual(unicode["properties"]["CHARSET_ENCODING"], "1")
        pairs = {record["cadr_code"]: record["unicode"] for record in result["resolved_mappings"]}
        statuses = {
            record["cadr_code"]: record["status"]
            for record in result["resolved_mappings"]
        }
        self.assertEqual(
            statuses,
            {
                0: "fixture-standard",
                65: "documented-private-use",
                66: "fixture-standard",
            },
        )
        for raw_code, scalar in pairs.items():
            raw_glyph = raw["glyphs"][raw_code]
            unicode_glyph = unicode["glyphs"][scalar]
            self.assertEqual(
                {key: raw_glyph[key] for key in ("swidth", "dwidth", "bbx", "bitmap")},
                {key: unicode_glyph[key] for key in ("swidth", "dwidth", "bbx", "bitmap")},
            )
        self.assertEqual(unicode["glyphs"][0x00B7]["dwidth"], "3 0")
        self.assertEqual(unicode["glyphs"][0x00B7]["bitmap"], ["00", "00", "00"])

    def test_transform_rejects_two_raw_codes_at_one_unicode_address(self) -> None:
        mapping = copy.deepcopy(fixture_mapping())
        mapping[66]["unicode"] = mapping[65]["unicode"]
        mapping[66]["unicode_hex"] = mapping[65]["unicode_hex"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_path = root / "raw.bdf"
            raw_path.write_text(fixture_bdf(), encoding="ascii")
            with self.assertRaisesRegex(builder.UnicodeBuildError, "same Unicode scalar"):
                builder.transform_bdf(
                    raw_path,
                    root / "unicode.bdf",
                    mapping,
                    mapping_id="fixture-v1",
                )


if __name__ == "__main__":
    unittest.main()
