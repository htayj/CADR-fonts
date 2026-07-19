#!/usr/bin/env python3
"""Build reviewed ISO10646 BDF derivatives from the raw CADR profiles.

The raw ``Misc-FontSpecific`` BDFs remain the archival artifacts.  This
postprocessor changes only character addresses and the BDF/XLFD character-set
identity.  It neither decodes historical inputs nor synthesizes glyphs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import string
from typing import Iterable

from lisp_machine_fonts import (
    BitmapFont,
    Glyph,
    prepare_output_directory,
    safe_filename,
    write_text_specimen,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = ROOT / "config" / "unicode-mapping.json"
PUA_FIRST = 0xE000
PUA_LAST = 0xF8FF
PUA_BLOCK_SIZE = 128
PANGRAM_SENTENCE = "The five boxing Lisp wizards jump quickly."
PANGRAM_SCALE = 2
PANGRAM_MAX_ADVANCE = 640
PANGRAM_PADDING = 3
PANGRAM_VSP = 2
PANGRAM_LATIN_CODES = frozenset({ord(" "), *map(ord, string.ascii_uppercase)})
REQUIRED_SEMANTIC_ORACLES = (
    "source_resolution_inventory_sha256",
    "source_unicode_geometry_sha256",
    "runtime_resolution_inventory_sha256",
    "runtime_unicode_geometry_sha256",
)
PINNED_SOURCE_EVIDENCE_PATHS = {
    "pinned-cadr-character-table": "src/lmdoc/char.18",
    "pinned-alto-font-loader": "src/lmio1/fntcnv.28",
    "pinned-old-leftarrow-reader": "src/lmio/fread.21",
}
EXTERNAL_EVIDENCE_URLS = {
    "rfc734-stanford-its-character-set": "https://www.rfc-editor.org/rfc/rfc734.html",
    "unicode-17-ucd": "https://www.unicode.org/Public/17.0.0/ucd/UnicodeData.txt",
}
RUNTIME_COMPATIBILITY_ALIASES = {
    "cm10": "CPT-CM10",
    "cm12": "CPT-CM12",
    "cptfon": "CPTFONT",
}


class UnicodeBuildError(ValueError):
    """The derivative cannot be built without violating its closed mapping."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise UnicodeBuildError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_unicode_standard_contract(manifest: dict[str, object]) -> None:
    """Require the manifest metadata to describe the profile we emit."""

    unicode_version = manifest.get("unicode_version")
    require(
        isinstance(unicode_version, str) and bool(unicode_version),
        "unicode_version must be a non-empty string",
    )
    standard = manifest.get("unicode_standard")
    require(isinstance(standard, dict), "mapping lacks unicode_standard")
    require(
        standard.get("version") == unicode_version,
        "unicode_standard version differs from unicode_version",
    )
    require(
        (
            standard.get("x_charset_registry"),
            standard.get("x_charset_encoding"),
            standard.get("xlfd_suffix"),
        )
        == ("ISO10646", "1", "iso10646-1"),
        "unicode_standard does not describe emitted ISO10646-1 fonts",
    )
    expected_ucd_url = (
        f"https://www.unicode.org/Public/{unicode_version}/ucd/UnicodeData.txt"
    )
    expected_names_url = (
        f"https://www.unicode.org/Public/{unicode_version}/ucd/NamesList.txt"
    )
    expected_private_use_url = (
        "https://www.unicode.org/versions/Unicode"
        f"{unicode_version}/core-spec/chapter-23/"
    )
    require(
        standard.get("ucd_url") == expected_ucd_url,
        "unicode_standard UCD URL differs from unicode_version",
    )
    require(
        standard.get("names_list_url") == expected_names_url,
        "unicode_standard NamesList URL differs from unicode_version",
    )
    require(
        standard.get("private_use_specification_url")
        == expected_private_use_url,
        "unicode_standard Private Use specification URL differs from unicode_version",
    )


def validate_required_semantic_oracles(manifest: dict[str, object]) -> None:
    """Keep the reviewed mapping and geometry inventories mandatory."""

    expected = manifest.get("expected")
    require(isinstance(expected, dict), "mapping lacks expected invariants")
    for key in REQUIRED_SEMANTIC_ORACLES:
        require(
            _is_sha256(expected.get(key)),
            f"mapping requires a lowercase SHA-256 oracle: {key}",
        )


def validate_evidence_contract(
    manifest: dict[str, object], source_repository: dict[str, object]
) -> None:
    """Verify every evidence record used by the mapping against its pin."""

    evidence = manifest["evidence"]
    used_evidence = {
        evidence_id
        for record in manifest["repertoires"].values()
        for evidence_id in record.get("evidence", [])
    }
    require(
        set(evidence) == used_evidence,
        "evidence registry must contain exactly the records used by repertoires",
    )
    require(
        set(evidence)
        == set(PINNED_SOURCE_EVIDENCE_PATHS) | set(EXTERNAL_EVIDENCE_URLS),
        "mapping evidence registry differs from the reviewed evidence set",
    )
    require(
        source_repository.get("submodule_path")
        == "sources/mit-cadr-system-software",
        "Unicode evidence source submodule path changed",
    )
    source_root = ROOT / str(source_repository["submodule_path"])
    for evidence_id, expected_path in PINNED_SOURCE_EVIDENCE_PATHS.items():
        record = evidence[evidence_id]
        repository_url = str(source_repository.get("url", ""))
        expected_url = (
            repository_url.removesuffix(".git")
            + "/blob/"
            + str(source_repository.get("revision", ""))
            + "/"
            + expected_path
        )
        require(
            record.get("path") == expected_path,
            f"{evidence_id}: pinned evidence path changed",
        )
        require(
            record.get("repository") == source_repository.get("url"),
            f"{evidence_id}: evidence repository differs from the raw source",
        )
        require(
            record.get("revision") == source_repository.get("revision"),
            f"{evidence_id}: evidence revision differs from the raw source",
        )
        require(
            record.get("url") == expected_url,
            f"{evidence_id}: pinned evidence URL changed",
        )
        evidence_path = source_root / expected_path
        require(
            evidence_path.is_file()
            and _is_sha256(record.get("sha256"))
            and sha256(evidence_path) == record["sha256"],
            f"{evidence_id}: pinned evidence SHA-256 changed",
        )
    for evidence_id, expected_url in EXTERNAL_EVIDENCE_URLS.items():
        require(
            evidence[evidence_id].get("url") == expected_url,
            f"{evidence_id}: reviewed evidence URL changed",
        )


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _parse_octal_code(value: object) -> int:
    require(
        isinstance(value, str)
        and len(value) == 3
        and all(character in "01234567" for character in value),
        f"invalid three-digit CADR octal code {value!r}",
    )
    code = int(value, 8)
    require(0 <= code < PUA_BLOCK_SIZE, f"CADR code is outside 000-177: {value}")
    return code


def _parse_private_use_codes(
    value: object, *, repertoire_id: str
) -> frozenset[int]:
    """Expand exact/range selectors and reject ambiguous overlapping claims."""

    require(
        isinstance(value, list),
        f"{repertoire_id}: private_use_codes must be a list",
    )
    result: set[int] = set()
    owners: dict[int, str] = {}
    for selector in value:
        require(
            isinstance(selector, str),
            f"{repertoire_id}: private-use selector must be a string",
        )
        fields = selector.split("-")
        require(
            len(fields) in {1, 2} and all(fields),
            f"{repertoire_id}: invalid private-use selector {selector!r}",
        )
        first = _parse_octal_code(fields[0])
        last = _parse_octal_code(fields[-1])
        require(
            first <= last,
            f"{repertoire_id}: private-use range is reversed: {selector}",
        )
        for code in range(first, last + 1):
            require(
                code not in result,
                f"{repertoire_id}: private-use selectors {owners.get(code)!r} and "
                f"{selector!r} overlap at {code:03o}",
            )
            result.add(code)
            owners[code] = selector
    return frozenset(result)


def _validate_mapping_entry(
    repertoire_id: str, code_key: object, mapping: object
) -> None:
    code = _parse_octal_code(code_key)
    require(
        isinstance(mapping, dict),
        f"{repertoire_id}/{code:03o}: invalid map",
    )
    scalar = mapping.get("unicode")
    require(
        type(scalar) is int,
        f"{repertoire_id}/{code:03o}: Unicode not int",
    )
    require(
        0 <= scalar <= 0xFFFF and not 0xD800 <= scalar <= 0xDFFF,
        f"{repertoire_id}/{code:03o}: Unicode is not a BMP scalar",
    )
    require(
        not PUA_FIRST <= scalar <= PUA_LAST,
        f"{repertoire_id}/{code:03o}: standard mapping may not assign BMP PUA",
    )
    require(
        mapping.get("unicode_hex") == f"U+{scalar:04X}",
        f"{repertoire_id}/{code:03o}: unicode_hex mismatch",
    )
    for field in ("unicode_name", "status", "label"):
        require(
            isinstance(mapping.get(field), str) and bool(mapping[field]),
            f"{repertoire_id}/{code:03o}: {field} must be a non-empty string",
        )


def _claim_pua_block(
    repertoire_id: str,
    record: dict[str, object],
    block_owners: dict[int, str],
) -> int:
    block_index = record.get("pua_block_index")
    require(
        type(block_index) is int and 0 <= block_index < 50,
        f"{repertoire_id}: invalid PUA block index",
    )
    require(
        block_index not in block_owners,
        f"PUA block {block_index} is shared by {block_owners.get(block_index)} "
        f"and {repertoire_id}",
    )
    block_owners[block_index] = repertoire_id
    base = PUA_FIRST + block_index * PUA_BLOCK_SIZE
    require(
        base + PUA_BLOCK_SIZE - 1 <= PUA_LAST,
        f"{repertoire_id}: PUA block exceeds the BMP PUA",
    )
    if "pua_base" in record:
        require(
            record["pua_base"] == base,
            f"{repertoire_id}: pua_base does not follow the allocation formula",
        )
    prefix = record.get("label_prefix")
    require(
        isinstance(prefix, str) and bool(prefix),
        f"{repertoire_id}: label_prefix must be a non-empty string",
    )
    return block_index


def load_mapping(path: Path) -> dict[str, object]:
    manifest = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    require(isinstance(manifest, dict), "Unicode mapping root must be an object")
    require(manifest.get("schema_version") == 1, "unsupported Unicode mapping schema")
    require(
        isinstance(manifest.get("mapping_id"), str) and bool(manifest["mapping_id"]),
        "mapping_id must be a non-empty string",
    )
    validate_unicode_standard_contract(manifest)
    validate_required_semantic_oracles(manifest)
    private = manifest.get("bmp_private_use")
    require(isinstance(private, dict), "mapping lacks bmp_private_use")
    require(private.get("first") == PUA_FIRST, "BMP PUA first value changed")
    require(private.get("last") == PUA_LAST, "BMP PUA last value changed")
    require(private.get("capacity") == PUA_LAST - PUA_FIRST + 1,
            "BMP PUA capacity changed")
    require(private.get("block_size") == PUA_BLOCK_SIZE, "PUA block size changed")
    require(
        private.get("allocation_formula")
        == "unicode = first + (pua_block_index * block_size) + original_cadr_code",
        "BMP PUA allocation formula changed",
    )

    repertoires = manifest.get("repertoires")
    require(isinstance(repertoires, dict) and repertoires, "mapping has no repertoires")
    evidence_registry = manifest.get("evidence")
    require(
        isinstance(evidence_registry, dict),
        "mapping evidence registry must be an object",
    )
    for evidence_id, evidence_record in evidence_registry.items():
        require(
            isinstance(evidence_id, str) and bool(evidence_id),
            "empty evidence identifier",
        )
        require(
            isinstance(evidence_record, dict),
            f"{evidence_id}: evidence record must be an object",
        )
        for field in ("url", "finding"):
            require(
                isinstance(evidence_record.get(field), str)
                and bool(evidence_record[field]),
                f"{evidence_id}: evidence {field} must be a non-empty string",
            )
        if "path" in evidence_record:
            for field in ("repository", "revision", "path"):
                require(
                    isinstance(evidence_record.get(field), str)
                    and bool(evidence_record[field]),
                    f"{evidence_id}: pinned evidence {field} must be a non-empty string",
                )
            require(
                _is_sha256(evidence_record.get("sha256")),
                f"{evidence_id}: pinned evidence sha256 must be lowercase SHA-256",
            )
    used_evidence: set[str] = set()
    block_owners: dict[int, str] = {}
    preceding_kinds: dict[str, str] = {}
    for repertoire_id, raw_record in repertoires.items():
        require(isinstance(repertoire_id, str) and repertoire_id,
                "empty repertoire identifier")
        require(isinstance(raw_record, dict), f"invalid repertoire {repertoire_id}")
        mapping_kind = raw_record.get("mapping_kind")
        require(isinstance(mapping_kind, str)
                and mapping_kind in {"explicit", "pua-block", "derived"},
                f"{repertoire_id}: unsupported mapping_kind {mapping_kind!r}")
        common_fields = {"mapping_kind", "label", "evidence", "expected"}
        kind_fields = {
            "explicit": {"mappings"},
            "pua-block": {"pua_block_index", "pua_base", "label_prefix"},
            "derived": {
                "base_repertoire",
                "private_use_codes",
                "overrides",
                "pua_block_index",
                "pua_base",
                "label_prefix",
            },
        }
        unknown_fields = set(raw_record) - common_fields - kind_fields[mapping_kind]
        require(
            not unknown_fields,
            f"{repertoire_id}: unknown repertoire fields: "
            + ", ".join(sorted(unknown_fields)),
        )
        evidence_ids = raw_record.get("evidence", [])
        require(
            isinstance(evidence_ids, list),
            f"{repertoire_id}: evidence must be a list",
        )
        require(
            all(isinstance(evidence_id, str) and evidence_id for evidence_id in evidence_ids),
            f"{repertoire_id}: evidence IDs must be non-empty strings",
        )
        require(
            len(evidence_ids) == len(set(evidence_ids)),
            f"{repertoire_id}: evidence IDs must not repeat",
        )
        unknown_evidence = set(evidence_ids) - set(evidence_registry)
        require(
            not unknown_evidence,
            f"{repertoire_id}: unknown evidence IDs: "
            + ", ".join(sorted(unknown_evidence)),
        )
        used_evidence.update(evidence_ids)
        if mapping_kind == "explicit":
            mappings = raw_record.get("mappings")
            require(isinstance(mappings, dict), f"{repertoire_id}: mappings missing")
            observed_codes = {_parse_octal_code(key) for key in mappings}
            require(observed_codes == set(range(PUA_BLOCK_SIZE)),
                    f"{repertoire_id}: explicit map must cover every code 000-177")
            for key, mapping in mappings.items():
                _validate_mapping_entry(repertoire_id, key, mapping)
        elif mapping_kind == "pua-block":
            _claim_pua_block(repertoire_id, raw_record, block_owners)
        else:
            base_repertoire = raw_record.get("base_repertoire")
            require(
                isinstance(base_repertoire, str) and bool(base_repertoire),
                f"{repertoire_id}: base_repertoire must name an earlier explicit repertoire",
            )
            require(
                base_repertoire in preceding_kinds,
                f"{repertoire_id}: base_repertoire {base_repertoire!r} is unknown or not earlier",
            )
            require(
                preceding_kinds[base_repertoire] == "explicit",
                f"{repertoire_id}: base_repertoire {base_repertoire!r} is not explicit",
            )
            private_codes = _parse_private_use_codes(
                raw_record.get("private_use_codes", []),
                repertoire_id=repertoire_id,
            )
            has_block = "pua_block_index" in raw_record
            has_prefix = "label_prefix" in raw_record
            require(
                has_block == has_prefix,
                f"{repertoire_id}: pua_block_index and label_prefix must appear together",
            )
            require(
                not private_codes or has_block,
                f"{repertoire_id}: private_use_codes require a reserved PUA block",
            )
            if has_block:
                _claim_pua_block(repertoire_id, raw_record, block_owners)
            else:
                require(
                    "pua_base" not in raw_record,
                    f"{repertoire_id}: pua_base requires a reserved PUA block",
                )
            overrides = raw_record.get("overrides", {})
            require(
                isinstance(overrides, dict),
                f"{repertoire_id}: overrides must be an object",
            )
            for key, mapping in overrides.items():
                _validate_mapping_entry(repertoire_id, key, mapping)
        preceding_kinds[repertoire_id] = mapping_kind
    require(
        used_evidence == set(evidence_registry),
        "evidence registry contains records unused by every repertoire",
    )
    return manifest


def repertoire_mapping(
    manifest: dict[str, object], repertoire_id: str
) -> dict[int, dict[str, object]]:
    repertoires = manifest["repertoires"]
    require(repertoire_id in repertoires, f"unknown repertoire {repertoire_id}")
    record = repertoires[repertoire_id]
    result: dict[int, dict[str, object]] = {}
    mapping_kind = record["mapping_kind"]
    if mapping_kind == "explicit":
        for octal, mapping in record["mappings"].items():
            code = _parse_octal_code(octal)
            result[code] = {
                "unicode": mapping["unicode"],
                "unicode_hex": mapping["unicode_hex"],
                "kind": "standard",
                "label": mapping["label"],
                "unicode_name": mapping["unicode_name"],
                "status": mapping["status"],
            }
    elif mapping_kind == "pua-block":
        block_index = record["pua_block_index"]
        base = PUA_FIRST + block_index * PUA_BLOCK_SIZE
        prefix = record["label_prefix"]
        for code in range(PUA_BLOCK_SIZE):
            scalar = base + code
            result[code] = {
                "unicode": scalar,
                "unicode_hex": f"U+{scalar:04X}",
                "kind": "private-use",
                "label": f"{prefix} CADR {code:03o}",
                "unicode_name": None,
                "status": "documented-private-use",
            }
    else:
        result = {
            code: dict(mapping)
            for code, mapping in repertoire_mapping(
                manifest, record["base_repertoire"]
            ).items()
        }
        private_codes = _parse_private_use_codes(
            record.get("private_use_codes", []),
            repertoire_id=repertoire_id,
        )
        if private_codes:
            block_index = record["pua_block_index"]
            base = PUA_FIRST + block_index * PUA_BLOCK_SIZE
            prefix = record["label_prefix"]
            for code in private_codes:
                scalar = base + code
                result[code] = {
                    "unicode": scalar,
                    "unicode_hex": f"U+{scalar:04X}",
                    "kind": "private-use",
                    "label": f"{prefix} CADR {code:03o}",
                    "unicode_name": None,
                    "status": "documented-private-use",
                }
        for octal, mapping in record.get("overrides", {}).items():
            code = _parse_octal_code(octal)
            result[code] = {
                "unicode": mapping["unicode"],
                "unicode_hex": mapping["unicode_hex"],
                "kind": "standard",
                "label": mapping["label"],
                "unicode_name": mapping["unicode_name"],
                "status": mapping["status"],
            }
    require(
        set(result) == set(range(PUA_BLOCK_SIZE)),
        f"{repertoire_id}: Unicode mapping is not closed over 000-177",
    )
    scalars = [mapping["unicode"] for mapping in result.values()]
    require(len(scalars) == len(set(scalars)),
            f"{repertoire_id}: Unicode mapping is not injective")
    return result


def _replace_xlfd(raw_name: str) -> tuple[str, str]:
    require(raw_name.startswith("-"), f"BDF FONT is not an XLFD: {raw_name}")
    fields = raw_name[1:].split("-")
    require(len(fields) == 14, f"BDF FONT does not have 14 XLFD fields: {raw_name}")
    raw_style = fields[5]
    unicode_style = f"{raw_style} Unicode" if raw_style else "Unicode"
    fields[5] = unicode_style
    fields[12] = "ISO10646"
    fields[13] = "1"
    result = "-" + "-".join(fields)
    require(len(result) <= 255, f"Unicode XLFD exceeds 255 bytes: {result}")
    return result, unicode_style


def _one_line(lines: list[str], prefix: str, path: Path) -> tuple[int, str]:
    matches = [
        (index, line[len(prefix):])
        for index, line in enumerate(lines)
        if line.startswith(prefix)
    ]
    require(len(matches) == 1, f"{path}: expected exactly one {prefix.strip()}")
    return matches[0]


def _glyph_geometry(block: list[str], path: Path, raw_code: int) -> dict[str, object]:
    def value(prefix: str) -> str:
        matches = [line[len(prefix):] for line in block if line.startswith(prefix)]
        require(len(matches) == 1, f"{path}: code {raw_code:03o} lacks {prefix.strip()}")
        return matches[0]

    bitmap_index = block.index("BITMAP")
    return {
        "swidth": value("SWIDTH "),
        "dwidth": value("DWIDTH "),
        "bbx": value("BBX "),
        "bitmap": block[bitmap_index + 1:-1],
    }


def _unicode_bitmap_font(
    name: str,
    source_name: str,
    transformed: dict[str, object],
) -> BitmapFont:
    """Rebuild the common bitmap model from one reviewed Unicode transform."""

    font_geometry = transformed["font_geometry"]
    ascent = int(font_geometry["font_ascent"])
    descent = int(font_geometry["font_descent"])
    box_fields = tuple(map(int, str(font_geometry["font_bounding_box"]).split()))
    require(len(box_fields) == 4, f"{source_name}: malformed FONTBOUNDINGBOX")
    glyphs: list[Glyph] = []
    for record in transformed["geometry"]:
        dwidth = tuple(map(int, str(record["dwidth"]).split()))
        bbx = tuple(map(int, str(record["bbx"]).split()))
        require(
            len(dwidth) == 2 and dwidth[1] == 0,
            f"{source_name}: non-horizontal Unicode DWIDTH",
        )
        require(len(bbx) == 4, f"{source_name}: malformed Unicode BBX")
        width, height, x_offset, y_offset = bbx
        require(width >= 0 and height >= 0, f"{source_name}: negative Unicode BBX")
        bitmap = record["bitmap"]
        require(
            isinstance(bitmap, list) and len(bitmap) == height,
            f"{source_name}: Unicode bitmap height differs from BBX",
        )
        byte_width = max(1, (width + 7) // 8)
        padding = byte_width * 8 - width
        padding_mask = (1 << padding) - 1 if padding else 0
        rows: list[int] = []
        for row in bitmap:
            require(
                isinstance(row, str)
                and len(row) == byte_width * 2
                and all(character in "0123456789ABCDEF" for character in row),
                f"{source_name}: malformed Unicode bitmap row",
            )
            stored = int(row, 16)
            require(
                stored & padding_mask == 0,
                f"{source_name}: Unicode bitmap has set storage-padding bits",
            )
            rows.append(stored >> padding)
        glyphs.append(
            Glyph(
                code=int(record["unicode"]),
                bitmap_width=width,
                advance=dwidth[0],
                x_offset=x_offset,
                y_offset=y_offset,
                rows=tuple(rows),
            )
        )
    return BitmapFont(
        name=name,
        character_height=ascent + descent,
        raster_height=box_fields[1],
        baseline=ascent,
        glyphs=tuple(glyphs),
        source_format="reviewed ISO10646-1 derivative",
        source_name=source_name,
        metadata={"unicode_xlfd_name": transformed["unicode_xlfd_name"]},
    )


def _glyph_is_visible(glyph: Glyph) -> bool:
    return any(glyph.rows)


def pangram_specimen_choice(font: BitmapFont) -> dict[str, str] | None:
    """Choose mixed-case text or an uppercase fallback without substitution."""

    glyphs = {glyph.code: glyph for glyph in font.glyphs}
    if not PANGRAM_LATIN_CODES <= set(glyphs):
        return None
    if glyphs[ord(" ")].advance <= 0 or any(
        not _glyph_is_visible(glyphs[code])
        for code in PANGRAM_LATIN_CODES - {ord(" ")}
    ):
        return None

    sentence_without_period = PANGRAM_SENTENCE.removesuffix(".")
    candidates = (
        ("mixed", PANGRAM_SENTENCE),
        ("mixed", sentence_without_period),
        ("uppercase", PANGRAM_SENTENCE.upper()),
        ("uppercase", sentence_without_period.upper()),
    )
    for case, text in candidates:
        supported = True
        for character in set(text):
            glyph = glyphs.get(ord(character))
            if glyph is None or (
                character == " " and glyph.advance <= 0
            ) or (character != " " and not _glyph_is_visible(glyph)):
                supported = False
                break
        if supported:
            return {
                "case": case,
                "text": text,
                "terminal_punctuation": (
                    "present" if text.endswith(".") else "omitted-unavailable"
                ),
            }
    raise UnicodeBuildError(
        f"{font.name}: complete visible uppercase Latin font cannot render pangram"
    )


def _write_pangram_specimen(
    font: BitmapFont,
    path: Path,
    *,
    path_display: str,
) -> dict[str, object] | None:
    choice = pangram_specimen_choice(font)
    if choice is None:
        return None
    layout = write_text_specimen(
        font,
        choice["text"],
        path,
        max_advance=PANGRAM_MAX_ADVANCE,
        scale=PANGRAM_SCALE,
        padding=PANGRAM_PADDING,
    )
    return {
        "path": path_display,
        "sha256": sha256(path),
        "coverage_policy": "visible U+0041-U+005A plus positive-advance U+0020",
        **layout,
        **choice,
    }


def transform_bdf(
    raw_path: Path,
    unicode_path: Path,
    mapping: dict[int, dict[str, object]],
    *,
    mapping_id: str,
) -> dict[str, object]:
    lines = raw_path.read_text(encoding="ascii").splitlines()
    require(lines[:1] == ["STARTFONT 2.1"] and lines[-1:] == ["ENDFONT"],
            f"{raw_path}: malformed BDF 2.1")
    font_index, raw_xlfd = _one_line(lines, "FONT ", raw_path)
    unicode_xlfd, unicode_style = _replace_xlfd(raw_xlfd)
    _chars_index, declared_text = _one_line(lines, "CHARS ", raw_path)
    declared_chars = int(declared_text)
    _size_index, size_text = _one_line(lines, "SIZE ", raw_path)
    _box_index, font_box_text = _one_line(lines, "FONTBOUNDINGBOX ", raw_path)
    _ascent_index, ascent_text = _one_line(lines, "FONT_ASCENT ", raw_path)
    _descent_index, descent_text = _one_line(lines, "FONT_DESCENT ", raw_path)

    starts = [index for index, line in enumerate(lines) if line.startswith("STARTCHAR ")]
    require(len(starts) == declared_chars, f"{raw_path}: CHARS count mismatch")
    first_start = starts[0]
    header = lines[:first_start]
    blocks: list[tuple[int, int, list[str], dict[str, object]]] = []
    cursor = first_start
    while cursor < len(lines) - 1:
        require(lines[cursor].startswith("STARTCHAR "),
                f"{raw_path}: text outside glyph blocks")
        try:
            end = lines.index("ENDCHAR", cursor + 1)
        except ValueError as error:
            raise UnicodeBuildError(f"{raw_path}: unterminated glyph") from error
        block = lines[cursor:end + 1]
        encoding_matches = [
            (index, line[len("ENCODING "):])
            for index, line in enumerate(block)
            if line.startswith("ENCODING ")
        ]
        require(len(encoding_matches) == 1, f"{raw_path}: glyph ENCODING count")
        encoding_index, raw_encoding = encoding_matches[0]
        fields = raw_encoding.split()
        require(len(fields) == 1, f"{raw_path}: secondary encoding is unsupported")
        raw_code = int(fields[0])
        require(raw_code in mapping, f"{raw_path}: no map for code {raw_code:03o}")
        scalar = int(mapping[raw_code]["unicode"])
        transformed = list(block)
        transformed[0] = f"STARTCHAR U{scalar:04X}_C{raw_code:03o}"
        transformed[encoding_index] = f"ENCODING {scalar}"
        blocks.append(
            (scalar, raw_code, transformed, _glyph_geometry(block, raw_path, raw_code))
        )
        cursor = end + 1
    require(cursor == len(lines) - 1, f"{raw_path}: malformed BDF tail")
    scalars = [scalar for scalar, _raw, _block, _geometry in blocks]
    require(len(scalars) == len(set(scalars)),
            f"{raw_path}: two emitted glyphs resolve to the same Unicode scalar")

    header[font_index] = f"FONT {unicode_xlfd}"
    replacements = {
        "ADD_STYLE_NAME ": f'ADD_STYLE_NAME "{unicode_style}"',
        "CHARSET_REGISTRY ": 'CHARSET_REGISTRY "ISO10646"',
        "CHARSET_ENCODING ": 'CHARSET_ENCODING "1"',
    }
    replacement_counts = {prefix: 0 for prefix in replacements}
    for index, line in enumerate(header):
        for prefix, replacement in replacements.items():
            if line.startswith(prefix):
                header[index] = replacement
                replacement_counts[prefix] += 1
                break
        if line.startswith("COMMENT ENCODING values are original CADR"):
            header[index] = (
                f"COMMENT Unicode derivative via mapping {mapping_id}; "
                "original CADR codes are in STARTCHAR suffixes"
            )
    require(all(count == 1 for count in replacement_counts.values()),
            f"{raw_path}: missing or duplicate Unicode BDF properties")

    output_lines = list(header)
    for _scalar, _raw, block, _geometry in blocks:
        output_lines.extend(block)
    output_lines.append("ENDFONT")
    unicode_path.parent.mkdir(parents=True, exist_ok=True)
    unicode_path.write_text("\n".join(output_lines) + "\n", encoding="ascii")

    resolved = [
        {
            "cadr_code": raw_code,
            "cadr_octal": f"{raw_code:03o}",
            "unicode": scalar,
            "unicode_hex": mapping[raw_code]["unicode_hex"],
            "kind": mapping[raw_code]["kind"],
            "label": mapping[raw_code]["label"],
            "status": mapping[raw_code]["status"],
        }
        for scalar, raw_code, _block, _geometry in sorted(blocks)
    ]
    geometry = [
        {
            "cadr_code": raw_code,
            "unicode": scalar,
            **geometry_record,
        }
        for scalar, raw_code, _block, geometry_record in sorted(blocks)
    ]
    return {
        "raw_xlfd_name": raw_xlfd,
        "unicode_xlfd_name": unicode_xlfd,
        "glyph_count": len(blocks),
        "standard_glyph_count": sum(
            mapping[raw_code]["kind"] == "standard"
            for _scalar, raw_code, _block, _geometry in blocks
        ),
        "private_use_glyph_count": sum(
            mapping[raw_code]["kind"] == "private-use"
            for _scalar, raw_code, _block, _geometry in blocks
        ),
        "resolved_mappings": resolved,
        "font_geometry": {
            "size": size_text,
            "font_bounding_box": font_box_text,
            "font_ascent": int(ascent_text),
            "font_descent": int(descent_text),
        },
        "geometry": geometry,
    }


def _write_indexes(
    bdf_directory: Path,
    artifacts: list[dict[str, object]],
    aliases: dict[str, str],
    *,
    description: str,
) -> None:
    entries = sorted(
        (Path(record["unicode_bdf"]).name, record["unicode_xlfd_name"])
        for record in artifacts
    )
    (bdf_directory / "fonts.dir").write_text(
        str(len(entries)) + "\n"
        + "".join(f"{filename} {xlfd}\n" for filename, xlfd in entries),
        encoding="ascii",
    )
    (bdf_directory / "fonts.alias").write_text(
        f"! {description}\n"
        + "".join(f'{alias} "{aliases[alias]}"\n' for alias in sorted(aliases)),
        encoding="ascii",
    )


def _add_alias(aliases: dict[str, str], name: str, xlfd: str) -> None:
    previous = aliases.get(name)
    require(previous is None or previous == xlfd, f"Unicode alias collision for {name}")
    aliases[name] = xlfd


def _validate_assignment_closure(
    manifest: dict[str, object],
    source_catalog: dict[str, object],
    runtime_catalog: dict[str, object],
) -> None:
    assignments = manifest.get("assignments")
    require(isinstance(assignments, dict), "mapping lacks assignments")
    source_assignments = assignments.get("source_logical_names")
    runtime_assignments = assignments.get("runtime_artifacts")
    require(isinstance(source_assignments, dict), "source assignments missing")
    require(isinstance(runtime_assignments, dict), "runtime assignments missing")
    actual_source = {record["logical_name"] for record in source_catalog["fonts"]}
    actual_runtime = {record["artifact_name"] for record in runtime_catalog["font_artifacts"]}
    require(set(source_assignments) == actual_source,
            "source logical-name mapping is not closed over the raw catalog")
    require(set(runtime_assignments) == actual_runtime,
            "runtime artifact mapping is not closed over the raw catalog")
    used = set(source_assignments.values()) | set(runtime_assignments.values())
    require(used == set(manifest["repertoires"]),
            "Unicode repertoires must be used and assignments must name only declared repertoires")

    expected = manifest.get("expected", {})
    observed = {
        "raw_source_artifact_count": source_catalog["font_count"],
        "raw_runtime_artifact_count": runtime_catalog["artifact_count"],
        "source_emitted_glyph_count": sum(
            record["bdf"]["bdf_glyph_count"] for record in source_catalog["fonts"]
        ),
        "runtime_emitted_glyph_count": sum(
            record["bdf_profile"]["bdf_glyph_count"]
            for record in runtime_catalog["font_artifacts"]
        ),
    }
    for key, value in observed.items():
        require(expected.get(key) == value,
                f"Unicode mapping expected {key}={expected.get(key)!r}, observed {value}")

    per_repertoire = {
        repertoire_id: {
            "raw_source_artifact_count": 0,
            "raw_runtime_artifact_count": 0,
            "source_emitted_glyph_count": 0,
            "runtime_emitted_glyph_count": 0,
        }
        for repertoire_id in manifest["repertoires"]
    }
    for record in source_catalog["fonts"]:
        repertoire_id = source_assignments[record["logical_name"]]
        counts = per_repertoire[repertoire_id]
        counts["raw_source_artifact_count"] += 1
        counts["source_emitted_glyph_count"] += record["bdf"]["bdf_glyph_count"]
    for record in runtime_catalog["font_artifacts"]:
        repertoire_id = runtime_assignments[record["artifact_name"]]
        counts = per_repertoire[repertoire_id]
        counts["raw_runtime_artifact_count"] += 1
        counts["runtime_emitted_glyph_count"] += record["bdf_profile"][
            "bdf_glyph_count"
        ]
    for repertoire_id, counts in per_repertoire.items():
        require(
            manifest["repertoires"][repertoire_id].get("expected") == counts,
            f"{repertoire_id}: per-repertoire artifact/glyph counts changed: {counts}",
        )


def _write_catalog(
    path: Path,
    *,
    profile: str,
    raw_catalog_path: Path,
    raw_catalog_display: str,
    mapping_copy: Path,
    mapping_id: str,
    unicode_version: str,
    artifacts: list[dict[str, object]],
    aliases: dict[str, str],
    resolution_digest: str,
    geometry_digest: str,
) -> dict[str, object]:
    catalog = {
        "schema_version": 1,
        "profile": profile,
        "mapping_id": mapping_id,
        "unicode_version": unicode_version,
        "charset_registry": "ISO10646",
        "charset_encoding": "1",
        "raw_catalog": {
            "path": raw_catalog_display,
            "sha256": sha256(raw_catalog_path),
        },
        "mapping_manifest": {
            "path": "../UNICODE-MAPPING.json",
            "sha256": sha256(mapping_copy),
        },
        "generator": {
            "path": "scripts/build_unicode_fonts.py",
            "sha256": sha256(Path(__file__)),
        },
        "artifact_count": len(artifacts),
        "emitted_glyph_count": sum(record["glyph_count"] for record in artifacts),
        "standard_glyph_count": sum(
            record["standard_glyph_count"] for record in artifacts
        ),
        "private_use_glyph_count": sum(
            record["private_use_glyph_count"] for record in artifacts
        ),
        "pangram_specimens": {
            "sentence": PANGRAM_SENTENCE,
            "sheet_count": sum("pangram_specimen" in record for record in artifacts),
            "latin_eligibility": (
                "visible U+0041-U+005A plus positive-advance U+0020 in the "
                "emitted Unicode BDF"
            ),
            "case_policy": (
                "use the mixed-case sentence when every requested non-space glyph "
                "has ink and U+0020 has positive advance; otherwise use the same "
                "sentence in uppercase"
            ),
            "missing_period_policy": (
                "omit only the terminal full stop when the otherwise eligible font "
                "does not represent a visible U+002E"
            ),
            "scale": PANGRAM_SCALE,
            "maximum_native_line_advance": PANGRAM_MAX_ADVANCE,
            "native_padding": PANGRAM_PADDING,
            "vertical_spacing_pixels": PANGRAM_VSP,
            "renderer": {
                "path": "scripts/lisp_machine_fonts.py",
                "sha256": sha256(ROOT / "scripts" / "lisp_machine_fonts.py"),
            },
        },
        "resolution_inventory_sha256": resolution_digest,
        "unicode_geometry_sha256": geometry_digest,
        "derivative_policy": (
            "only BDF primary encoding, STARTCHAR identity, XLFD add-style, and "
            "ISO10646 properties change; metrics and bitmap rows remain raw-profile exact"
        ),
        "missing_character_policy": (
            "no glyph is synthesized and raw BDF omissions remain omissions; host fallback "
            "for an undefined Unicode character is outside the conformance claim"
        ),
        "font_artifacts": artifacts,
        "x_indexes": {
            "fonts_dir": "bdf/fonts.dir",
            "fonts_alias": "bdf/fonts.alias",
            "alias_count": len(aliases),
            "aliases": [
                {"name": alias, "xlfd": aliases[alias]}
                for alias in sorted(aliases)
            ],
        },
    }
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return catalog


def build_unicode_distribution(
    output: Path,
    mapping_path: Path = DEFAULT_MAPPING,
    *,
    clean: bool = True,
) -> dict[str, object]:
    """Build and return catalogs/aliases for both Unicode derivatives."""

    output = output.resolve()
    mapping_path = mapping_path.resolve()
    source_catalog_path = output / "catalog.json"
    runtime_catalog_path = output / "runtime" / "catalog.json"
    require(source_catalog_path.is_file(), "raw source catalog is missing")
    require(runtime_catalog_path.is_file(), "raw runtime catalog is missing")
    manifest = load_mapping(mapping_path)
    source_catalog = json.loads(source_catalog_path.read_text(encoding="utf-8"))
    runtime_catalog = json.loads(runtime_catalog_path.read_text(encoding="utf-8"))
    validate_evidence_contract(manifest, source_catalog["source_repository"])
    _validate_assignment_closure(manifest, source_catalog, runtime_catalog)

    unicode_root = output / "unicode"
    prepare_output_directory(
        unicode_root,
        clean=clean,
        owned_names={"source", "runtime", "UNICODE-MAPPING.json"},
    )
    mapping_copy = unicode_root / "UNICODE-MAPPING.json"
    shutil.copyfile(mapping_path, mapping_copy)
    for profile_name in ("source", "runtime"):
        (unicode_root / profile_name / "bdf").mkdir(parents=True)
        (unicode_root / profile_name / "pangrams").mkdir(parents=True)

    mapping_id = manifest["mapping_id"]
    unicode_version = manifest["unicode_version"]
    source_assignments = manifest["assignments"]["source_logical_names"]
    runtime_assignments = manifest["assignments"]["runtime_artifacts"]

    source_artifacts: list[dict[str, object]] = []
    source_resolution: list[dict[str, object]] = []
    source_geometry: list[dict[str, object]] = []
    for raw_record in source_catalog["fonts"]:
        repertoire = source_assignments[raw_record["logical_name"]]
        mapping = repertoire_mapping(manifest, repertoire)
        raw_relative = Path(raw_record["outputs"]["bdf"])
        raw_path = output / raw_relative
        filename = raw_relative.name
        unicode_path = unicode_root / "source" / "bdf" / filename
        transformed = transform_bdf(
            raw_path, unicode_path, mapping, mapping_id=mapping_id
        )
        specimen_name = Path(filename).with_suffix(".png").name
        specimen = _write_pangram_specimen(
            _unicode_bitmap_font(raw_record["name"], str(unicode_path), transformed),
            unicode_root / "source" / "pangrams" / specimen_name,
            path_display=f"pangrams/{specimen_name}",
        )
        artifact = {
            "artifact_name": raw_record["name"],
            "logical_name": raw_record["logical_name"],
            "repertoire": repertoire,
            "raw_bdf": f"../../{raw_relative.as_posix()}",
            "raw_bdf_sha256": sha256(raw_path),
            "raw_xlfd_name": transformed["raw_xlfd_name"],
            "unicode_bdf": f"bdf/{filename}",
            "unicode_bdf_sha256": sha256(unicode_path),
            "unicode_xlfd_name": transformed["unicode_xlfd_name"],
            "glyph_count": transformed["glyph_count"],
            "standard_glyph_count": transformed["standard_glyph_count"],
            "private_use_glyph_count": transformed["private_use_glyph_count"],
            "resolved_mappings": transformed["resolved_mappings"],
        }
        if specimen is not None:
            artifact["pangram_specimen"] = specimen
        source_artifacts.append(artifact)
        source_resolution.extend(
            {
                "artifact": raw_record["name"],
                "repertoire": repertoire,
                **record,
            }
            for record in transformed["resolved_mappings"]
        )
        source_geometry.append(
            {
                "artifact": raw_record["name"],
                "font_geometry": transformed["font_geometry"],
                "glyphs": transformed["geometry"],
            }
        )

    current_runtime_names = {
        safe_filename(record["runtime_name"])
        for record in runtime_catalog["font_artifacts"]
        if record["classification"] != "legacy-compiled-version"
    }
    reserved_source_names = current_runtime_names | set(RUNTIME_COMPATIBILITY_ALIASES)
    source_aliases: dict[str, str] = {}
    for artifact in source_artifacts:
        xlfd = artifact["unicode_xlfd_name"]
        name = safe_filename(artifact["artifact_name"])
        _add_alias(source_aliases, f"cadr-unicode-source-{name}", xlfd)
        if name not in reserved_source_names:
            _add_alias(source_aliases, f"cadr-unicode-{name}", xlfd)
    _write_indexes(
        unicode_root / "source" / "bdf",
        source_artifacts,
        source_aliases,
        description="Unicode source-profile aliases; raw profiles are separate.",
    )

    runtime_artifacts: list[dict[str, object]] = []
    runtime_resolution: list[dict[str, object]] = []
    runtime_geometry: list[dict[str, object]] = []
    for raw_record in runtime_catalog["font_artifacts"]:
        repertoire = runtime_assignments[raw_record["artifact_name"]]
        mapping = repertoire_mapping(manifest, repertoire)
        raw_relative = Path("runtime") / raw_record["outputs"]["bdf"]
        raw_path = output / raw_relative
        filename = Path(raw_record["outputs"]["bdf"]).name
        unicode_path = unicode_root / "runtime" / "bdf" / filename
        transformed = transform_bdf(
            raw_path, unicode_path, mapping, mapping_id=mapping_id
        )
        specimen_name = Path(filename).with_suffix(".png").name
        specimen = _write_pangram_specimen(
            _unicode_bitmap_font(
                raw_record["artifact_name"], str(unicode_path), transformed
            ),
            unicode_root / "runtime" / "pangrams" / specimen_name,
            path_display=f"pangrams/{specimen_name}",
        )
        artifact = {
            "artifact_name": raw_record["artifact_name"],
            "runtime_name": raw_record["runtime_name"],
            "classification": raw_record["classification"],
            "repertoire": repertoire,
            "raw_bdf": f"../../{raw_relative.as_posix()}",
            "raw_bdf_sha256": sha256(raw_path),
            "raw_xlfd_name": transformed["raw_xlfd_name"],
            "unicode_bdf": f"bdf/{filename}",
            "unicode_bdf_sha256": sha256(unicode_path),
            "unicode_xlfd_name": transformed["unicode_xlfd_name"],
            "glyph_count": transformed["glyph_count"],
            "standard_glyph_count": transformed["standard_glyph_count"],
            "private_use_glyph_count": transformed["private_use_glyph_count"],
            "resolved_mappings": transformed["resolved_mappings"],
        }
        if specimen is not None:
            artifact["pangram_specimen"] = specimen
        runtime_artifacts.append(artifact)
        runtime_resolution.extend(
            {
                "artifact": raw_record["artifact_name"],
                "repertoire": repertoire,
                **record,
            }
            for record in transformed["resolved_mappings"]
        )
        runtime_geometry.append(
            {
                "artifact": raw_record["artifact_name"],
                "font_geometry": transformed["font_geometry"],
                "glyphs": transformed["geometry"],
            }
        )

    runtime_aliases: dict[str, str] = {}
    current_by_name: dict[str, dict[str, object]] = {}
    for artifact in runtime_artifacts:
        xlfd = artifact["unicode_xlfd_name"]
        artifact_name = safe_filename(artifact["artifact_name"])
        if artifact["classification"] == "legacy-compiled-version":
            _add_alias(
                runtime_aliases,
                f"cadr-unicode-runtime-legacy-{artifact_name}",
                xlfd,
            )
            continue
        runtime_name = safe_filename(artifact["runtime_name"])
        _add_alias(runtime_aliases, f"cadr-unicode-runtime-{runtime_name}", xlfd)
        _add_alias(runtime_aliases, f"cadr-unicode-{runtime_name}", xlfd)
        current_by_name[artifact["runtime_name"]] = artifact
    for alias, runtime_name in RUNTIME_COMPATIBILITY_ALIASES.items():
        require(runtime_name in current_by_name,
                f"Unicode compatibility alias target is absent: {runtime_name}")
        _add_alias(
            runtime_aliases,
            f"cadr-unicode-{alias}",
            current_by_name[runtime_name]["unicode_xlfd_name"],
        )
    _write_indexes(
        unicode_root / "runtime" / "bdf",
        runtime_artifacts,
        runtime_aliases,
        description="Unicode runtime aliases; current System 46 names win.",
    )

    source_resolution_digest = canonical_sha256(source_resolution)
    source_geometry_digest = canonical_sha256(source_geometry)
    runtime_resolution_digest = canonical_sha256(runtime_resolution)
    runtime_geometry_digest = canonical_sha256(runtime_geometry)
    expected = manifest["expected"]
    observed_oracles = {
        "source_resolution_inventory_sha256": source_resolution_digest,
        "source_unicode_geometry_sha256": source_geometry_digest,
        "runtime_resolution_inventory_sha256": runtime_resolution_digest,
        "runtime_unicode_geometry_sha256": runtime_geometry_digest,
    }
    for key, observed in observed_oracles.items():
        require(
            expected[key] == observed,
            f"Unicode oracle {key} changed: expected {expected[key]}, observed {observed}",
        )

    source_unicode_catalog = _write_catalog(
        unicode_root / "source" / "catalog.json",
        profile="unicode_authoring_source",
        raw_catalog_path=source_catalog_path,
        raw_catalog_display="../../catalog.json",
        mapping_copy=mapping_copy,
        mapping_id=mapping_id,
        unicode_version=unicode_version,
        artifacts=source_artifacts,
        aliases=source_aliases,
        resolution_digest=source_resolution_digest,
        geometry_digest=source_geometry_digest,
    )
    runtime_unicode_catalog = _write_catalog(
        unicode_root / "runtime" / "catalog.json",
        profile="unicode_system_46_runtime",
        raw_catalog_path=runtime_catalog_path,
        raw_catalog_display="../../runtime/catalog.json",
        mapping_copy=mapping_copy,
        mapping_id=mapping_id,
        unicode_version=unicode_version,
        artifacts=runtime_artifacts,
        aliases=runtime_aliases,
        resolution_digest=runtime_resolution_digest,
        geometry_digest=runtime_geometry_digest,
    )
    return {
        "source_catalog": source_unicode_catalog,
        "runtime_catalog": runtime_unicode_catalog,
        "source_aliases": source_aliases,
        "runtime_aliases": runtime_aliases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    try:
        result = build_unicode_distribution(
            args.output, args.mapping, clean=args.clean
        )
    except (OSError, UnicodeBuildError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "output": str(args.output.resolve() / "unicode"),
                "source_artifact_count": result["source_catalog"]["artifact_count"],
                "runtime_artifact_count": result["runtime_catalog"]["artifact_count"],
                "source_alias_count": len(result["source_aliases"]),
                "runtime_alias_count": len(result["runtime_aliases"]),
                "source_pangram_sheet_count": result["source_catalog"][
                    "pangram_specimens"
                ]["sheet_count"],
                "runtime_pangram_sheet_count": result["runtime_catalog"][
                    "pangram_specimens"
                ]["sheet_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
