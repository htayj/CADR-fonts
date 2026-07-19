#!/usr/bin/env python3
"""Validate the generated System 46 runtime-font profile and its source links."""

from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path

from check_runtime_rendering import BdfFont, Glyph, parse_bdf
from lisp_machine_fonts import safe_filename


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = ROOT / "config" / "runtime-source-manifest.json"
COMPATIBILITY_ALIASES = {
    "cm10": "CPT-CM10",
    "cm12": "CPT-CM12",
    "cptfon": "CPTFONT",
}


class RuntimeDistError(AssertionError):
    """A runtime artifact differs from its reviewed profile."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeDistError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_digest(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def semantic_glyph(glyph: Glyph) -> dict[str, object]:
    return {
        "code": glyph.code,
        "bitmap_width": glyph.width,
        "advance": glyph.advance,
        "x_offset": glyph.x_offset,
        "y_offset": glyph.y_offset,
        "rows": list(glyph.rows),
    }


def normalized_glyph(record: dict[str, object]) -> dict[str, object]:
    return {
        "code": int(record["code"]),
        "bitmap_width": int(record["bitmap_width"]),
        "advance": int(record["advance"]),
        "x_offset": int(record["x_offset"]),
        "y_offset": int(record["y_offset"]),
        "rows": [int(row, 16) for row in record["rows"]],
    }


def is_nonrendering_placeholder(glyph: dict[str, object]) -> bool:
    return (
        glyph["advance"] == 0
        and glyph["bitmap_width"] == 0
        and not any(glyph["rows"])
    )


def bdf_inventory_record(
    artifact_name: str, font: BdfFont
) -> dict[str, object]:
    glyphs = [font.glyphs[code] for code in sorted(font.glyphs)]
    minimum_x = min(glyph.x_offset for glyph in glyphs)
    maximum_x = max(glyph.x_offset + glyph.width for glyph in glyphs)
    minimum_y = min(glyph.y_offset for glyph in glyphs)
    maximum_y = max(glyph.y_offset + glyph.height for glyph in glyphs)
    return {
        "artifact_name": artifact_name,
        "size": font.character_height,
        "font_bounding_box": [
            maximum_x - minimum_x,
            maximum_y - minimum_y,
            minimum_x,
            minimum_y,
        ],
        "font_ascent": font.ascent,
        "font_descent": font.descent,
        "glyphs": [semantic_glyph(glyph) for glyph in glyphs],
    }


def ink_pixels(glyph: Glyph) -> frozenset[tuple[int, int]]:
    """Return baseline-relative set pixels, ignoring transparent padding."""

    pixels = set()
    for row_number, row in enumerate(glyph.rows):
        y = glyph.y_offset + glyph.height - row_number - 1
        for column in range(glyph.width):
            if row & (1 << (glyph.width - column - 1)):
                pixels.add((glyph.x_offset + column, y))
    return frozenset(pixels)


def display_signatures(
    font: BdfFont,
) -> dict[int, tuple[int, frozenset[tuple[int, int]]]]:
    """Map defined codes to the escapement and pixels visible on a line."""

    return {
        code: (glyph.advance, ink_pixels(glyph))
        for code, glyph in font.glyphs.items()
    }


def visible_codes(
    signatures: dict[int, tuple[int, frozenset[tuple[int, int]]]],
) -> set[int]:
    return {code for code, (_advance, pixels) in signatures.items() if pixels}


def parse_aliases(path: Path, expected_comment: str) -> dict[str, str]:
    lines = path.read_text(encoding="ascii").splitlines()
    require(lines[:1] == [expected_comment], f"{path}: alias header changed")
    aliases: dict[str, str] = {}
    for line in lines[1:]:
        alias, target = line.split(" ", 1)
        require(
            target.startswith('"') and target.endswith('"'),
            f"{path}: unquoted XLFD target for {alias}",
        )
        require(alias not in aliases, f"{path}: duplicate alias {alias}")
        aliases[alias] = target[1:-1]
    return aliases


def expected_runtime_aliases(
    records: list[dict[str, object]],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    current: dict[str, dict[str, object]] = {}

    def add(alias: str, target: str) -> None:
        require(
            alias not in aliases or aliases[alias] == target,
            f"reviewed runtime alias collision for {alias}",
        )
        aliases[alias] = target

    for record in records:
        target = str(record["bdf_profile"]["xlfd_name"])
        if record["classification"] == "legacy-compiled-version":
            add(
                "cadr-runtime-legacy-"
                + safe_filename(str(record["artifact_name"])),
                target,
            )
        else:
            runtime_name = safe_filename(str(record["runtime_name"]))
            add(f"cadr-runtime-{runtime_name}", target)
            add(f"cadr-{runtime_name}", target)
            current[str(record["runtime_name"])] = record

    for alias, runtime_name in COMPATIBILITY_ALIASES.items():
        require(runtime_name in current, f"runtime alias target missing: {runtime_name}")
        add(
            f"cadr-{alias}",
            str(current[runtime_name]["bdf_profile"]["xlfd_name"]),
        )
    return aliases


def check_indexes(
    output: Path, records: list[dict[str, object]]
) -> tuple[dict[str, str], set[str]]:
    runtime_root = output / "runtime"
    expected_dir = sorted(
        (
            Path(record["outputs"]["bdf"]).name,
            str(record["bdf_profile"]["xlfd_name"]),
        )
        for record in records
    )
    lines = (runtime_root / "bdf" / "fonts.dir").read_text(
        encoding="ascii"
    ).splitlines()
    require(int(lines[0]) == len(expected_dir), "runtime fonts.dir count changed")
    require(
        lines[1:] == [f"{name} {xlfd}" for name, xlfd in expected_dir],
        "runtime fonts.dir mappings changed",
    )
    expected_aliases = expected_runtime_aliases(records)
    observed_aliases = parse_aliases(
        runtime_root / "bdf" / "fonts.alias",
        "! Runtime-profile aliases; unqualified names select current System 46.",
    )
    require(observed_aliases == expected_aliases, "runtime fonts.alias changed")
    require(len(observed_aliases) == 99, "runtime alias count changed")

    source_aliases = parse_aliases(
        output / "bdf" / "fonts.alias",
        "! Source-profile aliases; XLFD names remain authoritative.",
    )
    require(len(source_aliases) == 272, "source alias count changed")
    require(
        not (set(source_aliases) & set(observed_aliases)),
        "source and runtime alias namespaces overlap",
    )
    require(
        len(source_aliases) + len(observed_aliases) == 371,
        "combined alias inventory changed",
    )
    return observed_aliases, set(source_aliases)


def check_source_relations(
    output: Path,
    source_catalog: dict[str, object],
    runtime_records: list[dict[str, object]],
    runtime_fonts: dict[str, BdfFont],
) -> dict[str, object]:
    source_records = {
        str(record["name"]): record for record in source_catalog["fonts"]
    }
    exact_count = 0
    for record in runtime_records:
        if record["classification"] != "source-backed-current":
            continue
        artifact = str(record["artifact_name"])
        reference = str(record["source_reference_artifact"])
        require(reference in source_records, f"{artifact}: missing source reference")
        source_font = parse_bdf(output / source_records[reference]["outputs"]["bdf"])
        runtime_font = runtime_fonts[artifact]
        source = display_signatures(source_font)
        runtime = display_signatures(runtime_font)
        common = set(source) & set(runtime)
        require(
            set(source) <= set(runtime),
            f"{artifact}: runtime lost source-represented codes",
        )
        relation = record["expected_source_relation"]
        details = record.get("expected_source_relation_details") or {}

        if relation == "exact-runtime-visible":
            require(
                all(source[code] == runtime[code] for code in source),
                f"{artifact}: source-represented display geometry changed",
            )
            require(
                visible_codes(source) == visible_codes(runtime),
                f"{artifact}: reviewed visible repertoire changed",
            )
            exact_count += 1
        elif relation == "source-visible-subset":
            require(
                all(source[code] == runtime[code] for code in source),
                f"{artifact}: source-represented display geometry changed",
            )
            extra_visible = sorted(visible_codes(runtime) - visible_codes(source))
            require(
                extra_visible == details["runtime_extra_visible_codes"],
                f"{artifact}: runtime-only visible codes changed: {extra_visible}",
            )
            require(
                not (visible_codes(source) - visible_codes(runtime)),
                f"{artifact}: runtime lost visible source codes",
            )
        elif relation == "known-current-compiled-divergence":
            changed_common = [
                code for code in common if source[code] != runtime[code]
            ]
            advance_differences = [
                code
                for code in common
                if source[code][0] != runtime[code][0]
            ]
            all_codes = set(source) | set(runtime)
            differences = [
                code for code in all_codes if source.get(code) != runtime.get(code)
            ]
            extra_visible = sorted(visible_codes(runtime) - visible_codes(source))
            require(
                len(changed_common)
                == details["changed_common_rendering_glyph_count"],
                f"{artifact}: changed-common count drifted",
            )
            require(
                len(advance_differences)
                == details["common_advance_difference_code_count"],
                f"{artifact}: common advance differences drifted",
            )
            require(
                len(differences)
                == details["total_rendering_difference_code_count"],
                f"{artifact}: total display-difference count drifted",
            )
            require(
                extra_visible == details["runtime_extra_visible_codes"],
                f"{artifact}: runtime extra visible codes drifted",
            )
        else:
            raise RuntimeDistError(f"{artifact}: unknown source relation {relation}")

    require(exact_count == 28, "exact source/runtime relation count changed")

    current_43 = display_signatures(runtime_fonts["43VXMS"])
    legacy_43 = display_signatures(runtime_fonts["N43XMS"])
    difference_43 = sum(
        current_43.get(code) != legacy_43.get(code)
        for code in set(current_43) | set(legacy_43)
    )
    require(difference_43 == 69, "N43XMS/current 43VXMS difference count changed")
    require(
        display_signatures(runtime_fonts["NTOG"])
        == display_signatures(runtime_fonts["TOG"]),
        "NTOG is no longer display-identical to current TOG",
    )
    return {
        "exact_source_relation_count": exact_count,
        "n43xms_difference_glyph_count": difference_43,
        "ntog_display_identical": True,
    }


def check_build_manifest(
    output: Path,
    source_catalog: dict[str, object],
    runtime_catalog: dict[str, object],
    runtime_aliases: dict[str, str],
) -> None:
    build = json.loads((output / "BUILD-MANIFEST.json").read_text(encoding="utf-8"))
    require(build["schema_version"] == 2, "unsupported build manifest schema")
    source_profile = build["profiles"]["authoring_source"]
    runtime_profile = build["profiles"]["system_46_runtime"]
    unicode_source_profile = build["profiles"]["unicode_authoring_source"]
    unicode_runtime_profile = build["profiles"]["unicode_system_46_runtime"]
    require(
        source_profile["catalog_sha256"] == sha256(output / "catalog.json"),
        "BUILD-MANIFEST source catalog hash is stale",
    )
    require(
        runtime_profile["catalog_sha256"]
        == sha256(output / "runtime" / "catalog.json"),
        "BUILD-MANIFEST runtime catalog hash is stale",
    )
    require(
        source_profile["artifact_count"] == source_catalog["font_count"] == 151,
        "BUILD-MANIFEST source count changed",
    )
    require(
        runtime_profile["artifact_count"]
        == runtime_catalog["artifact_count"]
        == 49,
        "BUILD-MANIFEST runtime count changed",
    )
    require(runtime_profile["alias_count"] == len(runtime_aliases), "runtime alias count stale")
    require(source_profile["alias_count"] == 272, "source alias count stale")
    require(
        runtime_profile["classification_counts"]
        == runtime_catalog["classification_counts"],
        "BUILD-MANIFEST runtime classifications are stale",
    )
    require(build["raw_artifact_count"] == 200, "raw artifact count changed")
    require(
        build["unicode_derivative_artifact_count"] == 200,
        "Unicode derivative artifact count changed",
    )
    require(
        build["total_installable_artifact_count"] == 400,
        "combined installable artifact count changed",
    )
    require(
        build["total_pangram_sheet_count"] == 160,
        "combined Unicode pangram sheet count changed",
    )
    require(
        unicode_source_profile["raw_profile"] == "authoring_source"
        and unicode_source_profile["artifact_count"] == 151,
        "Unicode source profile link changed",
    )
    require(
        unicode_runtime_profile["raw_profile"] == "system_46_runtime"
        and unicode_runtime_profile["artifact_count"] == 49,
        "Unicode runtime profile link changed",
    )
    require(
        unicode_source_profile["pangram_sheet_count"] == 118
        and unicode_runtime_profile["pangram_sheet_count"] == 42,
        "Unicode Latin pangram specimen counts changed",
    )
    require(
        "defined by each emitted BDF" in build["undefined_character_policy"],
        "missing-code exclusion disappeared from BUILD-MANIFEST",
    )


def check_runtime_distribution(output: Path) -> dict[str, object]:
    runtime_root = output / "runtime"
    manifest = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    copied_manifest = runtime_root / "runtime-source-manifest.json"
    require(
        copied_manifest.read_bytes() == RUNTIME_MANIFEST.read_bytes(),
        "distributed runtime manifest is stale",
    )
    catalog = json.loads((runtime_root / "catalog.json").read_text(encoding="utf-8"))
    source_catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    expected = manifest["expected"]
    require(catalog["schema_version"] == 1, "unsupported runtime catalog schema")
    require(
        catalog["runtime_manifest_sha256"] == sha256(copied_manifest),
        "runtime catalog manifest hash is stale",
    )
    require(catalog["artifact_count"] == expected["artifact_count"] == 49, "runtime artifact count changed")
    require(
        catalog["runtime_logical_name_count"]
        == expected["runtime_logical_name_count"]
        == 47,
        "runtime logical-name count changed",
    )
    require(
        catalog["classification_counts"] == expected["classification_counts"],
        "runtime classification counts changed",
    )
    require(
        catalog["display_layout_policy"][
            "system_46_sheet_default_vertical_spacing_pixels"
        ]
        == 2,
        "System 46 default VSP changed",
    )
    require(
        "maximum baseline"
        in catalog["display_layout_policy"]["system_46_mixed_font_line_map"],
        "mixed-font baseline policy changed",
    )

    records = list(catalog["font_artifacts"])
    specs = {record["artifact_name"]: record for record in manifest["artifacts"]}
    by_name = {record["artifact_name"]: record for record in records}
    require(len(records) == len(by_name) == len(specs) == 49, "runtime artifacts are not unique")
    normalized_inventory = []
    bdf_inventory = []
    runtime_fonts: dict[str, BdfFont] = {}
    xlfds = set()
    spacing = Counter()
    normalized_glyph_count = 0
    bdf_glyph_count = 0

    for artifact_name in sorted(by_name):
        record = by_name[artifact_name]
        spec = specs[artifact_name]
        for key in (
            "runtime_name",
            "runtime_symbol",
            "classification",
            "source_reference_artifact",
            "expected_source_relation",
            "expected_source_relation_details",
            "decoded_pdp10_word_count",
            "decoded_pdp10_word_sha256",
            "decoded_qfasl_nibble_count",
            "end_of_whack_count",
        ):
            require(record.get(key) == spec.get(key), f"{artifact_name}: manifest {key} drift")
        require(record["source_sha256"] == spec["sha256"], f"{artifact_name}: source hash drift")
        require(record["source_byte_size"] == spec["byte_size"], f"{artifact_name}: source size drift")

        json_path = runtime_root / record["outputs"]["json"]
        normalized = json.loads(json_path.read_text(encoding="utf-8"))
        glyphs = [normalized_glyph(glyph) for glyph in normalized["glyphs"]]
        normalized_glyph_count += len(glyphs)
        normalized_inventory.append(
            {
                "artifact_name": artifact_name,
                "character_height": normalized["character_height"],
                "raster_height": normalized["raster_height"],
                "baseline": normalized["baseline"],
                "glyphs": glyphs,
            }
        )

        bdf_path = runtime_root / record["outputs"]["bdf"]
        font = parse_bdf(bdf_path)
        runtime_fonts[artifact_name] = font
        profile = record["bdf_profile"]
        require(font.name == profile["xlfd_name"], f"{artifact_name}: XLFD drift")
        require(font.name not in xlfds, f"{artifact_name}: duplicate runtime XLFD")
        xlfds.add(font.name)
        require(font.ascent == record["baseline"], f"{artifact_name}: baseline drift")
        require(
            font.character_height == record["character_height"],
            f"{artifact_name}: character-height drift",
        )
        expected_style = (
            f"System 46 Legacy {artifact_name}"
            if record["classification"] == "legacy-compiled-version"
            else "System 46 Runtime"
        )
        require(profile["add_style_name"] == expected_style, f"{artifact_name}: runtime XLFD style drift")
        require(profile["foundry"] == "Misc", f"{artifact_name}: inferred runtime foundry")
        require(
            profile["family_name"]
            == f'MIT CADR {record["runtime_name"]}'.replace("-", " "),
            f"{artifact_name}: runtime family drift",
        )
        require(
            (profile["weight_name"], profile["slant"], profile["setwidth_name"])
            == ("Unknown", "OT", "Unknown"),
            f"{artifact_name}: inferred typography",
        )
        require(
            (profile["resolution_x"], profile["resolution_y"])
            == (72, 72),
            f"{artifact_name}: runtime interchange resolution drift",
        )
        require(
            (profile["charset_registry"], profile["charset_encoding"])
            == ("Misc", "FontSpecific"),
            f"{artifact_name}: false runtime character-set identity",
        )
        spacing[profile["spacing"]] += 1

        emitted = [glyph for glyph in glyphs if not is_nonrendering_placeholder(glyph)]
        require(
            {glyph["code"] for glyph in emitted} == set(font.glyphs),
            f"{artifact_name}: JSON/BDF repertoire drift",
        )
        for glyph in emitted:
            bdf_glyph = font.glyphs[glyph["code"]]
            require(
                semantic_glyph(bdf_glyph) == glyph,
                f"{artifact_name}: JSON/BDF geometry drift at {glyph['code']}",
            )
        bdf_glyph_count += len(font.glyphs)
        bdf_inventory.append(bdf_inventory_record(artifact_name, font))

    require(spacing == {"P": 37, "M": 5, "C": 7}, f"runtime spacing inventory changed: {spacing}")
    require(normalized_glyph_count == 6170, "normalized runtime slot count changed")
    require(bdf_glyph_count == 5689, "runtime BDF glyph count changed")
    for directory, suffix in (("bdf", ".bdf"), ("json", ".json"), ("sheets", ".png")):
        require(
            len(list((runtime_root / directory).glob(f"*{suffix}"))) == 49,
            f"runtime {directory} artifact count changed",
        )
    expected_inventories = manifest["semantic_inventories"]
    normalized_hash = semantic_digest(normalized_inventory)
    bdf_hash = semantic_digest(bdf_inventory)
    require(
        normalized_hash
        == expected_inventories["normalized_runtime_font_geometry"]["sha256"]
        == catalog["semantic_inventory_digests"]["normalized_runtime_font_geometry"],
        f"normalized runtime semantic inventory changed: {normalized_hash}",
    )
    require(
        bdf_hash
        == expected_inventories["bdf_geometry"]["sha256"]
        == catalog["semantic_inventory_digests"]["bdf_geometry"],
        f"runtime BDF semantic inventory changed: {bdf_hash}",
    )

    source_xlfds = {record["bdf"]["xlfd_name"] for record in source_catalog["fonts"]}
    require(not (source_xlfds & xlfds), "source/runtime XLFD namespaces collide")
    require(len(source_xlfds | xlfds) == 200, "combined XLFD inventory changed")
    runtime_aliases, _source_alias_names = check_indexes(output, records)
    require(
        catalog["x_indexes"]["alias_count"] == len(runtime_aliases)
        and catalog["x_indexes"]["aliases"]
        == [
            {"name": alias, "xlfd": runtime_aliases[alias]}
            for alias in sorted(runtime_aliases)
        ],
        "runtime catalog X indexes are stale",
    )

    generator = catalog["generator"]
    require(sha256(ROOT / generator["path"]) == generator["sha256"], "runtime decoder hash is stale")
    require(
        sha256(ROOT / generator["shared_writer_path"])
        == generator["shared_writer_sha256"],
        "runtime shared writer hash is stale",
    )
    require(
        sha256(ROOT / catalog["packager"]["path"])
        == catalog["packager"]["sha256"],
        "runtime packager hash is stale",
    )
    source_relations = check_source_relations(
        output, source_catalog, records, runtime_fonts
    )
    check_build_manifest(output, source_catalog, catalog, runtime_aliases)
    return {
        "runtime_artifact_count": len(records),
        "runtime_logical_name_count": catalog["runtime_logical_name_count"],
        "normalized_runtime_slot_count": normalized_glyph_count,
        "runtime_bdf_glyph_count": bdf_glyph_count,
        "runtime_alias_count": len(runtime_aliases),
        "combined_alias_count": 371,
        "normalized_semantic_inventory_sha256": normalized_hash,
        "bdf_semantic_inventory_sha256": bdf_hash,
        "source_relations": source_relations,
        "undefined_code_substitution": "excluded",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        result = check_runtime_distribution(args.output.resolve())
    except (KeyError, OSError, RuntimeDistError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"status": "ok", **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
