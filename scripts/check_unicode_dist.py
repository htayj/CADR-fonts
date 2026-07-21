#!/usr/bin/env python3
"""Validate the reviewed ISO10646 derivatives against both raw CADR profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import string
import struct
import zlib

from build_unicode_fonts import (
    DEFAULT_MAPPING,
    PUA_BLOCK_SIZE,
    PUA_FIRST,
    PUA_LAST,
    REQUIRED_SEMANTIC_ORACLES,
    RUNTIME_COMPATIBILITY_ALIASES,
    _parse_private_use_codes,
    canonical_sha256,
    load_mapping,
    repertoire_mapping,
    validate_evidence_contract,
    validate_required_semantic_oracles,
    validate_unicode_standard_contract,
)
from lisp_machine_fonts import safe_filename


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ARTIFACT_COUNT = 151
RUNTIME_ARTIFACT_COUNT = 49
SOURCE_GLYPH_COUNT = 14618
RUNTIME_GLYPH_COUNT = 5689
SOURCE_ALIAS_COUNT = 272
RUNTIME_ALIAS_COUNT = 99
SOURCE_PANGRAM_SHEET_COUNT = 118
RUNTIME_PANGRAM_SHEET_COUNT = 42
SOURCE_PANGRAM_CASE_COUNTS = {"mixed": 115, "uppercase": 3}
RUNTIME_PANGRAM_CASE_COUNTS = {"mixed": 40, "uppercase": 2}
PANGRAM_SENTENCE = "The five boxing Lisp wizards jump quickly."
PANGRAM_SCALE = 2
PANGRAM_MAX_ADVANCE = 640
PANGRAM_PADDING = 3
PANGRAM_VSP = 2
PANGRAM_LATIN_CODES = frozenset({ord(" "), *map(ord, string.ascii_uppercase)})


class UnicodeDistError(AssertionError):
    """A Unicode derivative differs from its reviewed mapping or raw BDF."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise UnicodeDistError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _one_line(lines: list[str], prefix: str, path: Path) -> str:
    values = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    require(len(values) == 1, f"{path}: expected exactly one {prefix.strip()}")
    return values[0]


def _parse_properties(lines: list[str], path: Path) -> dict[str, str | int]:
    starts = [
        index for index, line in enumerate(lines) if line.startswith("STARTPROPERTIES ")
    ]
    require(len(starts) == 1, f"{path}: expected one STARTPROPERTIES")
    start = starts[0]
    try:
        end = lines.index("ENDPROPERTIES", start + 1)
    except ValueError as error:
        raise UnicodeDistError(f"{path}: missing ENDPROPERTIES") from error
    declared = int(lines[start].split()[1])
    property_lines = lines[start + 1 : end]
    require(len(property_lines) == declared, f"{path}: property count mismatch")
    properties: dict[str, str | int] = {}
    for line in property_lines:
        key, value = line.split(" ", 1)
        require(key not in properties, f"{path}: duplicate property {key}")
        if value.startswith('"'):
            require(value.endswith('"'), f"{path}: unterminated property {key}")
            parsed: str | int = value[1:-1]
        else:
            parsed = int(value)
        properties[key] = parsed
    return properties


def parse_bdf(path: Path) -> dict[str, object]:
    """Parse the identity and byte-exact glyph geometry used by the derivative."""

    lines = path.read_text(encoding="ascii").splitlines()
    require(lines[:1] == ["STARTFONT 2.1"], f"{path}: not BDF 2.1")
    require(lines[-1:] == ["ENDFONT"], f"{path}: missing ENDFONT")
    declared = int(_one_line(lines, "CHARS ", path))
    glyphs: dict[int, dict[str, object]] = {}
    index = 0
    while index < len(lines):
        if not lines[index].startswith("STARTCHAR "):
            index += 1
            continue
        try:
            end = lines.index("ENDCHAR", index + 1)
        except ValueError as error:
            raise UnicodeDistError(f"{path}: unterminated glyph") from error
        block = lines[index : end + 1]

        def one(prefix: str) -> str:
            values = [line[len(prefix) :] for line in block if line.startswith(prefix)]
            require(len(values) == 1, f"{path}: glyph lacks one {prefix.strip()}")
            return values[0]

        encoding_fields = one("ENCODING ").split()
        require(len(encoding_fields) == 1, f"{path}: secondary encoding is unsupported")
        encoding = int(encoding_fields[0])
        require(encoding not in glyphs, f"{path}: duplicate encoding {encoding}")
        bitmap_index = block.index("BITMAP")
        bbx = one("BBX ")
        bbx_fields = tuple(map(int, bbx.split()))
        require(len(bbx_fields) == 4, f"{path}: malformed BBX at {encoding}")
        bitmap = block[bitmap_index + 1 : -1]
        require(
            len(bitmap) == bbx_fields[1],
            f"{path}: bitmap height mismatch at {encoding}",
        )
        glyphs[encoding] = {
            "startchar": block[0].split(" ", 1)[1],
            "swidth": one("SWIDTH "),
            "dwidth": one("DWIDTH "),
            "bbx": bbx,
            "bitmap": bitmap,
        }
        index = end + 1
    require(len(glyphs) == declared, f"{path}: CHARS count mismatch")
    return {
        "font": _one_line(lines, "FONT ", path),
        "size": _one_line(lines, "SIZE ", path),
        "font_bounding_box": _one_line(lines, "FONTBOUNDINGBOX ", path),
        "properties": _parse_properties(lines, path),
        "glyphs": glyphs,
    }


def _glyph_advance(glyph: dict[str, object]) -> int:
    fields = tuple(map(int, str(glyph["dwidth"]).split()))
    require(len(fields) == 2 and fields[1] == 0, "pangram glyph DWIDTH changed")
    return fields[0]


def _glyph_visible(glyph: dict[str, object]) -> bool:
    return any(int(row, 16) for row in glyph["bitmap"])


def _expected_pangram_choice(
    unicode_bdf: dict[str, object],
) -> dict[str, str] | None:
    """Independently select complete, visible Latin fonts and specimen case."""

    glyphs = unicode_bdf["glyphs"]
    if not PANGRAM_LATIN_CODES <= set(glyphs):
        return None
    if _glyph_advance(glyphs[ord(" ")]) <= 0 or any(
        not _glyph_visible(glyphs[code])
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
                character == " " and _glyph_advance(glyph) <= 0
            ) or (character != " " and not _glyph_visible(glyph)):
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
    raise UnicodeDistError(
        "complete visible uppercase Latin font cannot render the pangram"
    )


def _expected_wrapped_lines(
    text: str,
    glyphs: dict[int, dict[str, object]],
) -> list[str]:
    """Apply the documented maximum advance independently of the PNG writer."""

    def advance(value: str) -> int:
        return sum(_glyph_advance(glyphs[ord(character)]) for character in value)

    lines: list[str] = []
    for paragraph in text.split("\n"):
        remainder = paragraph
        while advance(remainder) > PANGRAM_MAX_ADVANCE:
            fitting_end = 0
            fitting_advance = 0
            last_space = -1
            for index, character in enumerate(remainder):
                candidate = fitting_advance + _glyph_advance(
                    glyphs[ord(character)]
                )
                if candidate > PANGRAM_MAX_ADVANCE:
                    break
                fitting_end = index + 1
                fitting_advance = candidate
                if character == " ":
                    last_space = index
            require(fitting_end > 0, "pangram glyph exceeds maximum line advance")
            if last_space > 0:
                lines.append(remainder[:last_space])
                remainder = remainder[last_space + 1 :]
            else:
                lines.append(remainder[:fitting_end])
                remainder = remainder[fitting_end:]
        lines.append(remainder)
    return lines


def _expected_pangram_layout(
    unicode_bdf: dict[str, object], text: str
) -> dict[str, object]:
    glyphs = unicode_bdf["glyphs"]
    properties = unicode_bdf["properties"]
    ascent = int(properties["FONT_ASCENT"])
    descent = int(properties["FONT_DESCENT"])
    character_height = ascent + descent
    lines = _expected_wrapped_lines(text, glyphs)
    line_height = character_height + PANGRAM_VSP
    minimum_x = 0
    maximum_x = 0
    minimum_y = 0
    maximum_y = character_height + (len(lines) - 1) * line_height
    line_records: list[dict[str, object]] = []
    for line_index, line in enumerate(lines):
        pen_x = 0
        baseline = ascent + line_index * line_height
        for character in line:
            glyph = glyphs[ord(character)]
            width, height, x_offset, y_offset = tuple(
                map(int, str(glyph["bbx"]).split())
            )
            glyph_x = pen_x + x_offset
            glyph_top = baseline - y_offset - height
            advance = _glyph_advance(glyph)
            minimum_x = min(minimum_x, pen_x, pen_x + advance, glyph_x)
            maximum_x = max(
                maximum_x,
                pen_x,
                pen_x + advance,
                glyph_x + width,
            )
            minimum_y = min(minimum_y, glyph_top)
            maximum_y = max(maximum_y, glyph_top + height)
            pen_x += advance
        minimum_x = min(minimum_x, pen_x)
        maximum_x = max(maximum_x, pen_x)
        line_records.append(
            {
                "index": line_index,
                "text": line,
                "advance": pen_x,
                "baseline": baseline,
            }
        )

    content_width = maximum_x - minimum_x
    content_height = maximum_y - minimum_y
    canvas_width = content_width + PANGRAM_PADDING * 2
    canvas_height = content_height + PANGRAM_PADDING * 2
    for record in line_records:
        canvas_baseline = PANGRAM_PADDING + int(record["baseline"]) - minimum_y
        record["canvas_baseline"] = canvas_baseline
        record["pixel_baseline"] = canvas_baseline * PANGRAM_SCALE
    return {
        "text": text,
        "max_native_advance": PANGRAM_MAX_ADVANCE,
        "scale": PANGRAM_SCALE,
        "native_padding": PANGRAM_PADDING,
        "vsp": PANGRAM_VSP,
        "native_line_height": line_height,
        "content_native_bounds": {
            "left": minimum_x,
            "top": minimum_y,
            "right": maximum_x,
            "bottom": maximum_y,
        },
        "content_native_width": content_width,
        "content_native_height": content_height,
        "canvas_native_width": canvas_width,
        "canvas_native_height": canvas_height,
        "width": canvas_width * PANGRAM_SCALE,
        "height": canvas_height * PANGRAM_SCALE,
        "line_count": len(line_records),
        "lines": line_records,
    }


def _read_rgb_png(path: Path) -> tuple[int, int, list[bytes]]:
    """Decode the dependency-free renderer's RGB8 PNG without sharing it."""

    data = path.read_bytes()
    require(data[:8] == b"\x89PNG\r\n\x1a\n", f"{path}: malformed PNG signature")
    offset = 8
    ihdr: bytes | None = None
    compressed = bytearray()
    saw_iend = False
    while offset < len(data):
        require(offset + 12 <= len(data), f"{path}: truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        require(end <= len(data), f"{path}: truncated PNG payload")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        observed_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        require(
            observed_crc == zlib.crc32(kind + payload) & 0xFFFFFFFF,
            f"{path}: PNG chunk CRC changed",
        )
        if kind == b"IHDR":
            require(ihdr is None, f"{path}: duplicate PNG IHDR")
            ihdr = payload
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            require(not payload, f"{path}: malformed PNG IEND")
            saw_iend = True
        else:
            raise UnicodeDistError(f"{path}: unexpected PNG chunk {kind!r}")
        offset = end
    require(offset == len(data) and saw_iend, f"{path}: malformed PNG tail")
    require(ihdr is not None and len(ihdr) == 13, f"{path}: malformed PNG IHDR")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    require(
        (depth, color, compression, filtering, interlace) == (8, 2, 0, 0, 0),
        f"{path}: PNG is not non-interlaced RGB8",
    )
    try:
        scanlines = zlib.decompress(bytes(compressed))
    except zlib.error as error:
        raise UnicodeDistError(f"{path}: malformed PNG compression") from error
    row_size = width * 3
    require(
        len(scanlines) == height * (row_size + 1),
        f"{path}: PNG scanline size changed",
    )
    rows: list[bytes] = []
    for row_number in range(height):
        start = row_number * (row_size + 1)
        require(scanlines[start] == 0, f"{path}: PNG uses a filtered scanline")
        rows.append(scanlines[start + 1 : start + 1 + row_size])
    return width, height, rows


def _expected_pangram_ink(
    unicode_bdf: dict[str, object], layout: dict[str, object]
) -> set[tuple[int, int]]:
    glyphs = unicode_bdf["glyphs"]
    bounds = layout["content_native_bounds"]
    minimum_x = int(bounds["left"])
    minimum_y = int(bounds["top"])
    pixels: set[tuple[int, int]] = set()
    for line in layout["lines"]:
        pen_x = 0
        baseline = int(line["baseline"])
        for character in line["text"]:
            glyph = glyphs[ord(character)]
            width, height, x_offset, y_offset = tuple(
                map(int, str(glyph["bbx"]).split())
            )
            byte_width = max(1, (width + 7) // 8)
            padding_bits = byte_width * 8 - width
            glyph_x = pen_x + x_offset
            glyph_top = baseline - y_offset - height
            for row_number, row in enumerate(glyph["bitmap"]):
                logical_row = int(row, 16) >> padding_bits
                for column in range(width):
                    if not logical_row & (1 << (width - column - 1)):
                        continue
                    native_x = PANGRAM_PADDING + glyph_x - minimum_x + column
                    native_y = PANGRAM_PADDING + glyph_top - minimum_y + row_number
                    for y_offset_scaled in range(PANGRAM_SCALE):
                        for x_offset_scaled in range(PANGRAM_SCALE):
                            pixels.add(
                                (
                                    native_x * PANGRAM_SCALE + x_offset_scaled,
                                    native_y * PANGRAM_SCALE + y_offset_scaled,
                                )
                            )
            pen_x += _glyph_advance(glyph)
    return pixels


def _check_pangram_png(
    path: Path,
    unicode_bdf: dict[str, object],
    layout: dict[str, object],
) -> None:
    width, height, rows = _read_rgb_png(path)
    require(
        (width, height) == (layout["width"], layout["height"]),
        f"{path}: pangram PNG dimensions changed",
    )
    ink = (18, 20, 22)
    background = (250, 250, 248)
    observed: set[tuple[int, int]] = set()
    for y, row in enumerate(rows):
        for x in range(width):
            color = tuple(row[x * 3 : x * 3 + 3])
            if color == ink:
                observed.add((x, y))
            else:
                require(
                    color == background,
                    f"{path}: pangram PNG contains an undocumented color",
                )
    expected = _expected_pangram_ink(unicode_bdf, layout)
    require(
        observed == expected,
        f"{path}: pangram pixels differ from Unicode BDF "
        f"(missing {len(expected - observed)}, extra {len(observed - expected)})",
    )


def _check_pangram_specimen(
    *,
    profile_root: Path,
    artifact: dict[str, object],
    unicode_bdf: dict[str, object],
    bdf_filename: str,
) -> str | None:
    choice = _expected_pangram_choice(unicode_bdf)
    if choice is None:
        require(
            "pangram_specimen" not in artifact,
            f"{artifact['artifact_name']}: ineligible font has a pangram specimen",
        )
        return None

    require(
        "pangram_specimen" in artifact,
        f"{artifact['artifact_name']}: eligible Latin font lacks a pangram specimen",
    )
    specimen_name = Path(bdf_filename).with_suffix(".png").name
    relative = f"pangrams/{specimen_name}"
    specimen_path = profile_root / relative
    require(specimen_path.is_file(), f"missing pangram specimen {specimen_path}")
    layout = _expected_pangram_layout(unicode_bdf, choice["text"])
    expected = {
        "path": relative,
        "sha256": sha256(specimen_path),
        "coverage_policy": (
            "visible U+0041-U+005A plus positive-advance U+0020"
        ),
        **layout,
        **choice,
    }
    require(
        artifact["pangram_specimen"] == expected,
        f"{artifact['artifact_name']}: pangram specimen catalog drift",
    )
    _check_pangram_png(specimen_path, unicode_bdf, layout)
    return choice["case"]


def _xlfd_fields(name: str, path: Path) -> list[str]:
    require(name.startswith("-"), f"{path}: FONT is not an XLFD")
    fields = name[1:].split("-")
    require(len(fields) == 14, f"{path}: XLFD does not have 14 fields")
    return fields


def validate_mapping_closure(
    manifest: dict[str, object],
    source_catalog: dict[str, object],
    runtime_catalog: dict[str, object],
) -> dict[str, object]:
    """Independently check assignment closure, BMP capacity, and injectivity."""

    validate_unicode_standard_contract(manifest)
    validate_required_semantic_oracles(manifest)
    validate_evidence_contract(manifest, source_catalog["source_repository"])
    private = manifest["bmp_private_use"]
    require(
        (private["first"], private["last"], private["capacity"], private["block_size"])
        == (PUA_FIRST, PUA_LAST, 6400, PUA_BLOCK_SIZE),
        "BMP Private Use Area contract changed",
    )
    require(
        private.get("allocation_formula")
        == "unicode = first + (pua_block_index * block_size) + original_cadr_code",
        "BMP PUA allocation formula changed",
    )
    repertoires = manifest["repertoires"]
    mappings: dict[str, dict[int, dict[str, object]]] = {}
    block_owners: dict[int, str] = {}
    for repertoire_id, record in repertoires.items():
        mapping = repertoire_mapping(manifest, repertoire_id)
        require(
            set(mapping) == set(range(PUA_BLOCK_SIZE)),
            f"{repertoire_id}: mapping is not closed over 000-177",
        )
        scalars = [int(value["unicode"]) for value in mapping.values()]
        require(
            len(scalars) == len(set(scalars)),
            f"{repertoire_id}: mapping is not injective",
        )
        require(
            all(
                0 <= scalar <= 0xFFFF and not 0xD800 <= scalar <= 0xDFFF
                for scalar in scalars
            ),
            f"{repertoire_id}: mapping contains a non-BMP scalar",
        )

        for code, value in mapping.items():
            require(
                value["kind"] in {"standard", "private-use"},
                f"{repertoire_id}/{code:03o}: unknown effective mapping kind",
            )
            require(
                isinstance(value.get("label"), str) and bool(value["label"]),
                f"{repertoire_id}/{code:03o}: effective mapping lacks a label",
            )
            require(
                isinstance(value.get("status"), str) and bool(value["status"]),
                f"{repertoire_id}/{code:03o}: effective mapping lacks a status",
            )
            if value["kind"] == "private-use":
                require(
                    value["status"] == "documented-private-use"
                    and value.get("unicode_name") is None,
                    f"{repertoire_id}/{code:03o}: private-use mapping is undocumented",
                )
            else:
                require(
                    isinstance(value.get("unicode_name"), str)
                    and bool(value["unicode_name"]),
                    f"{repertoire_id}/{code:03o}: standard mapping is undocumented",
                )
                require(
                    not PUA_FIRST <= int(value["unicode"]) <= PUA_LAST,
                    f"{repertoire_id}/{code:03o}: standard mapping uses undocumented PUA",
                )

        mapping_kind = record["mapping_kind"]
        if mapping_kind == "pua-block":
            block = record["pua_block_index"]
            require(block not in block_owners, f"PUA block {block} has two owners")
            block_owners[block] = repertoire_id
            base = PUA_FIRST + block * PUA_BLOCK_SIZE
            require(
                all(
                    int(mapping[code]["unicode"]) == base + code
                    for code in range(PUA_BLOCK_SIZE)
                ),
                f"{repertoire_id}: PUA allocation formula changed",
            )
            require(
                all(value["kind"] == "private-use" for value in mapping.values()),
                f"{repertoire_id}: PUA mappings are not labelled private-use",
            )
        elif mapping_kind == "explicit":
            require(
                not any(PUA_FIRST <= scalar <= PUA_LAST for scalar in scalars),
                f"{repertoire_id}: explicit repertoire contains undocumented PUA",
            )
            for code in mapping:
                raw_value = record["mappings"][f"{code:03o}"]
                require(
                    mapping[code]
                    == {
                        "unicode": raw_value["unicode"],
                        "unicode_hex": raw_value["unicode_hex"],
                        "kind": "standard",
                        "label": raw_value["label"],
                        "unicode_name": raw_value["unicode_name"],
                        "status": raw_value["status"],
                    },
                    f"{repertoire_id}/{code:03o}: explicit mapping resolution changed",
                )
        else:
            base_repertoire = record["base_repertoire"]
            require(
                base_repertoire in mappings,
                f"{repertoire_id}: derived base was not resolved earlier",
            )
            private_codes = set(
                _parse_private_use_codes(
                    record.get("private_use_codes", []),
                    repertoire_id=repertoire_id,
                )
            )
            override_records = {
                int(octal, 8): value
                for octal, value in record.get("overrides", {}).items()
            }
            effective_private_codes = private_codes - set(override_records)
            if "pua_block_index" in record:
                block = record["pua_block_index"]
                require(block not in block_owners, f"PUA block {block} has two owners")
                block_owners[block] = repertoire_id
                pua_base = PUA_FIRST + block * PUA_BLOCK_SIZE
            else:
                require(
                    not effective_private_codes,
                    f"{repertoire_id}: private mappings lack a PUA block",
                )
                pua_base = None

            require(
                {
                    code
                    for code, value in mapping.items()
                    if value["kind"] == "private-use"
                }
                == effective_private_codes,
                f"{repertoire_id}: effective private-use code set changed",
            )
            for code, value in mapping.items():
                if code in override_records:
                    raw_value = override_records[code]
                    expected_value = {
                        "unicode": raw_value["unicode"],
                        "unicode_hex": raw_value["unicode_hex"],
                        "kind": "standard",
                        "label": raw_value["label"],
                        "unicode_name": raw_value["unicode_name"],
                        "status": raw_value["status"],
                    }
                    require(
                        value == expected_value,
                        f"{repertoire_id}/{code:03o}: reviewed remap changed",
                    )
                elif code in effective_private_codes:
                    require(
                        pua_base is not None
                        and int(value["unicode"]) == pua_base + code
                        and value["unicode_hex"] == f"U+{pua_base + code:04X}",
                        f"{repertoire_id}/{code:03o}: PUA allocation formula changed",
                    )
                else:
                    require(
                        value == mappings[base_repertoire][code],
                        f"{repertoire_id}/{code:03o}: inherited mapping changed",
                    )
        mappings[repertoire_id] = mapping
    require(len(block_owners) <= 50, "more than 50 BMP PUA blocks are allocated")

    assignments = manifest["assignments"]
    source_names = {record["logical_name"] for record in source_catalog["fonts"]}
    runtime_names = {
        record["artifact_name"] for record in runtime_catalog["font_artifacts"]
    }
    require(
        set(assignments["source_logical_names"]) == source_names,
        "source mapping assignments are not closed over the raw catalog",
    )
    require(
        set(assignments["runtime_artifacts"]) == runtime_names,
        "runtime mapping assignments are not closed over the raw catalog",
    )
    used = set(assignments["source_logical_names"].values()) | set(
        assignments["runtime_artifacts"].values()
    )
    require(used == set(repertoires), "mapping has unused or undeclared repertoires")

    expected = manifest["expected"]
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
    require(
        observed
        == {
            "raw_source_artifact_count": SOURCE_ARTIFACT_COUNT,
            "raw_runtime_artifact_count": RUNTIME_ARTIFACT_COUNT,
            "source_emitted_glyph_count": SOURCE_GLYPH_COUNT,
            "runtime_emitted_glyph_count": RUNTIME_GLYPH_COUNT,
        },
        f"raw profile counts changed: {observed}",
    )
    for key, value in observed.items():
        require(expected.get(key) == value, f"mapping expected count is stale: {key}")

    source_assignments = assignments["source_logical_names"]
    runtime_assignments = assignments["runtime_artifacts"]
    per_repertoire = {
        repertoire_id: {
            "raw_source_artifact_count": 0,
            "raw_runtime_artifact_count": 0,
            "source_emitted_glyph_count": 0,
            "runtime_emitted_glyph_count": 0,
        }
        for repertoire_id in repertoires
    }
    for record in source_catalog["fonts"]:
        counts = per_repertoire[source_assignments[record["logical_name"]]]
        counts["raw_source_artifact_count"] += 1
        counts["source_emitted_glyph_count"] += record["bdf"]["bdf_glyph_count"]
    for record in runtime_catalog["font_artifacts"]:
        counts = per_repertoire[runtime_assignments[record["artifact_name"]]]
        counts["raw_runtime_artifact_count"] += 1
        counts["runtime_emitted_glyph_count"] += record["bdf_profile"][
            "bdf_glyph_count"
        ]
    for repertoire_id, counts in per_repertoire.items():
        require(
            repertoires[repertoire_id].get("expected") == counts,
            f"{repertoire_id}: per-repertoire counts changed: {counts}",
        )
    return {
        "mappings": mappings,
        "allocated_pua_block_count": len(block_owners),
    }


def _parse_aliases(path: Path) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        try:
            fields = shlex.split(stripped, posix=True)
        except ValueError as error:
            raise UnicodeDistError(f"{path}:{line_number}: malformed alias") from error
        require(len(fields) == 2, f"{path}:{line_number}: alias needs two fields")
        name, target = fields
        require(name not in aliases, f"{path}:{line_number}: duplicate alias {name}")
        aliases[name] = target
    return aliases


def _parse_fonts_dir(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="ascii").splitlines()
    require(bool(lines), f"{path}: empty fonts.dir")
    entries: dict[str, str] = {}
    for line in lines[1:]:
        filename, xlfd = line.split(" ", 1)
        require(filename not in entries, f"{path}: duplicate file {filename}")
        entries[filename] = xlfd
    require(int(lines[0]) == len(entries), f"{path}: fonts.dir count mismatch")
    return entries


def _expected_source_aliases(
    artifacts: list[dict[str, object]],
    runtime_catalog: dict[str, object],
) -> dict[str, str]:
    reserved = {
        safe_filename(record["runtime_name"])
        for record in runtime_catalog["font_artifacts"]
        if record["classification"] != "legacy-compiled-version"
    } | set(RUNTIME_COMPATIBILITY_ALIASES)
    aliases: dict[str, str] = {}
    for artifact in artifacts:
        name = safe_filename(artifact["artifact_name"])
        target = artifact["unicode_xlfd_name"]
        aliases[f"cadr-unicode-source-{name}"] = target
        if name not in reserved:
            aliases[f"cadr-unicode-{name}"] = target
    return aliases


def _expected_runtime_aliases(
    artifacts: list[dict[str, object]],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    current: dict[str, dict[str, object]] = {}
    for artifact in artifacts:
        target = artifact["unicode_xlfd_name"]
        if artifact["classification"] == "legacy-compiled-version":
            name = safe_filename(artifact["artifact_name"])
            aliases[f"cadr-unicode-runtime-legacy-{name}"] = target
            continue
        name = safe_filename(artifact["runtime_name"])
        aliases[f"cadr-unicode-runtime-{name}"] = target
        aliases[f"cadr-unicode-{name}"] = target
        current[artifact["runtime_name"]] = artifact
    for alias, runtime_name in RUNTIME_COMPATIBILITY_ALIASES.items():
        require(runtime_name in current, f"runtime alias target missing: {runtime_name}")
        aliases[f"cadr-unicode-{alias}"] = current[runtime_name][
            "unicode_xlfd_name"
        ]
    return aliases


def _check_xlfd_and_properties(
    raw: dict[str, object],
    unicode: dict[str, object],
    path: Path,
) -> None:
    raw_fields = _xlfd_fields(raw["font"], path)
    unicode_fields = _xlfd_fields(unicode["font"], path)
    for index, (raw_field, unicode_field) in enumerate(
        zip(raw_fields, unicode_fields)
    ):
        if index not in {5, 12, 13}:
            require(raw_field == unicode_field, f"{path}: XLFD field {index} changed")
    expected_style = f"{raw_fields[5]} Unicode" if raw_fields[5] else "Unicode"
    require(unicode_fields[5] == expected_style, f"{path}: Unicode add-style drift")
    require(
        unicode_fields[12:] == ["ISO10646", "1"],
        f"{path}: Unicode XLFD registry drift",
    )
    raw_properties = raw["properties"]
    unicode_properties = unicode["properties"]
    require(
        set(raw_properties) == set(unicode_properties),
        f"{path}: BDF property inventory changed",
    )
    for name in raw_properties:
        if name not in {"ADD_STYLE_NAME", "CHARSET_REGISTRY", "CHARSET_ENCODING"}:
            require(
                raw_properties[name] == unicode_properties[name],
                f"{path}: property {name} changed",
            )
    require(
        (
            unicode_properties["ADD_STYLE_NAME"],
            unicode_properties["CHARSET_REGISTRY"],
            str(unicode_properties["CHARSET_ENCODING"]),
        )
        == (expected_style, "ISO10646", "1"),
        f"{path}: ISO10646 BDF properties changed",
    )
    require(raw["size"] == unicode["size"], f"{path}: SIZE changed")
    require(
        raw["font_bounding_box"] == unicode["font_bounding_box"],
        f"{path}: FONTBOUNDINGBOX changed",
    )


def _check_artifact(
    *,
    profile_root: Path,
    artifact: dict[str, object],
    expected_raw_path: Path,
    expected_raw_display: str,
    expected_repertoire: str,
    mapping: dict[int, dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
    str | None,
]:
    require(artifact["repertoire"] == expected_repertoire, "repertoire assignment drift")
    require(artifact["raw_bdf"] == expected_raw_display, "raw BDF path drift")
    raw_path = (profile_root / artifact["raw_bdf"]).resolve()
    require(raw_path == expected_raw_path.resolve(), "raw BDF target drift")
    unicode_path = profile_root / artifact["unicode_bdf"]
    require(
        artifact["unicode_bdf"] == f"bdf/{expected_raw_path.name}",
        "Unicode BDF path drift",
    )
    require(unicode_path.is_file(), f"missing Unicode BDF {unicode_path}")
    require(artifact["raw_bdf_sha256"] == sha256(raw_path), "raw BDF hash stale")
    require(
        artifact["unicode_bdf_sha256"] == sha256(unicode_path),
        "Unicode BDF hash stale",
    )
    raw = parse_bdf(raw_path)
    unicode = parse_bdf(unicode_path)
    require(artifact["raw_xlfd_name"] == raw["font"], "raw XLFD catalog drift")
    require(
        artifact["unicode_xlfd_name"] == unicode["font"],
        "Unicode XLFD catalog drift",
    )
    _check_xlfd_and_properties(raw, unicode, unicode_path)

    raw_glyphs = raw["glyphs"]
    unicode_glyphs = unicode["glyphs"]
    resolved = artifact["resolved_mappings"]
    expected_resolved = [
        {
            "cadr_code": raw_code,
            "cadr_octal": f"{raw_code:03o}",
            "unicode": int(mapping[raw_code]["unicode"]),
            "unicode_hex": mapping[raw_code]["unicode_hex"],
            "kind": mapping[raw_code]["kind"],
            "label": mapping[raw_code]["label"],
            "status": mapping[raw_code]["status"],
        }
        for raw_code in raw_glyphs
    ]
    expected_resolved.sort(key=lambda record: (record["unicode"], record["cadr_code"]))
    require(resolved == expected_resolved, "resolved mapping catalog drift")
    require(
        set(raw_glyphs) == {record["cadr_code"] for record in resolved},
        "raw glyph was omitted or added by mapping resolution",
    )
    require(
        set(unicode_glyphs) == {record["unicode"] for record in resolved},
        "Unicode BDF has an omitted or extra glyph",
    )
    require(
        list(unicode_glyphs)
        == [int(mapping[raw_code]["unicode"]) for raw_code in raw_glyphs],
        "Unicode BDF glyph blocks no longer follow raw BDF order",
    )
    require(
        len(unicode_glyphs) == len(raw_glyphs) == artifact["glyph_count"],
        "Unicode glyph count differs from raw BDF",
    )
    standard_count = sum(record["kind"] == "standard" for record in resolved)
    private_count = sum(record["kind"] == "private-use" for record in resolved)
    require(
        (artifact["standard_glyph_count"], artifact["private_use_glyph_count"])
        == (standard_count, private_count),
        "standard/private-use glyph counts changed",
    )

    geometry_records: list[dict[str, object]] = []
    for record in resolved:
        raw_code = record["cadr_code"]
        scalar = record["unicode"]
        raw_glyph = raw_glyphs[raw_code]
        unicode_glyph = unicode_glyphs[scalar]
        require(
            unicode_glyph["startchar"] == f"U{scalar:04X}_C{raw_code:03o}",
            f"{unicode_path}: STARTCHAR lost raw/Unicode identity",
        )
        for key in ("swidth", "dwidth", "bbx", "bitmap"):
            require(
                unicode_glyph[key] == raw_glyph[key],
                f"{unicode_path}: {key} changed at CADR {raw_code:03o}",
            )
        geometry_records.append(
            {
                "cadr_code": raw_code,
                "unicode": scalar,
                "swidth": raw_glyph["swidth"],
                "dwidth": raw_glyph["dwidth"],
                "bbx": raw_glyph["bbx"],
                "bitmap": raw_glyph["bitmap"],
            }
        )
    pangram_case = _check_pangram_specimen(
        profile_root=profile_root,
        artifact=artifact,
        unicode_bdf=unicode,
        bdf_filename=expected_raw_path.name,
    )
    return (
        resolved,
        geometry_records,
        {
            "size": raw["size"],
            "font_bounding_box": raw["font_bounding_box"],
            "font_ascent": raw["properties"]["FONT_ASCENT"],
            "font_descent": raw["properties"]["FONT_DESCENT"],
        },
        pangram_case,
    )


def _check_profile(
    *,
    output: Path,
    profile_name: str,
    profile_directory: str,
    raw_catalog_path: Path,
    raw_records: list[dict[str, object]],
    identity_key: str,
    mapping_manifest: dict[str, object],
    mapping_copy: Path,
    mappings: dict[str, dict[int, dict[str, object]]],
    assignments: dict[str, str],
    font_identities: dict[str, object],
    font_identities_path: Path,
    runtime_catalog: dict[str, object],
) -> dict[str, object]:
    profile_root = output / "unicode" / profile_directory
    catalog_path = profile_root / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    require(catalog["schema_version"] == 1, "unsupported Unicode catalog schema")
    require(catalog["profile"] == profile_name, "Unicode profile identity drift")
    require(catalog["mapping_id"] == mapping_manifest["mapping_id"], "mapping id drift")
    require(
        catalog.get("font_identity_mapping_id") == font_identities["mapping_id"]
        and catalog.get("font_identity_mapping_sha256")
        == sha256(font_identities_path),
        "font-identity mapping provenance drift",
    )
    require(
        catalog["unicode_version"] == mapping_manifest["unicode_version"],
        "Unicode version drift",
    )
    require(
        (catalog["charset_registry"], str(catalog["charset_encoding"]))
        == ("ISO10646", "1"),
        "Unicode catalog charset drift",
    )
    require(
        catalog["raw_catalog"]["sha256"] == sha256(raw_catalog_path),
        "raw catalog hash is stale",
    )
    expected_raw_catalog_display = (
        "../../catalog.json"
        if profile_directory == "source"
        else "../../runtime/catalog.json"
    )
    require(
        catalog["raw_catalog"]["path"] == expected_raw_catalog_display,
        "raw catalog path is stale",
    )
    require(
        catalog["mapping_manifest"]["path"] == "../UNICODE-MAPPING.json"
        and catalog["mapping_manifest"]["sha256"] == sha256(mapping_copy),
        "Unicode mapping catalog link is stale",
    )
    generator = catalog["generator"]
    require(
        generator["path"] == "scripts/build_unicode_fonts.py"
        and generator["sha256"] == sha256(ROOT / generator["path"]),
        "Unicode generator hash is stale",
    )

    artifacts = catalog["font_artifacts"]
    require(
        [record["artifact_name"] for record in artifacts]
        == [record[identity_key] for record in raw_records],
        "Unicode artifacts do not follow the closed raw catalog",
    )
    resolution_inventory: list[dict[str, object]] = []
    geometry_inventory: list[dict[str, object]] = []
    unicode_xlfds: set[str] = set()
    pangram_cases: list[str] = []
    for artifact, raw_record in zip(artifacts, raw_records):
        artifact_name = artifact["artifact_name"]
        logical_identity = artifact.get("logical_identity")
        representation = artifact.get("representation")
        require(
            isinstance(logical_identity, dict)
            and isinstance(representation, dict),
            f"{artifact_name}: logical identity or representation missing",
        )
        require(
            "representation" not in logical_identity,
            f"{artifact_name}: representation is nested in logical identity",
        )
        require(
            logical_identity == raw_record.get("logical_identity")
            and representation == raw_record.get("representation"),
            f"{artifact_name}: raw/Unicode logical metadata drift",
        )
        require(
            representation.get("profile") == profile_directory
            and representation.get("artifact_name") == artifact_name,
            f"{artifact_name}: physical representation identity drift",
        )
        if profile_directory == "source":
            assignment_key = raw_record["logical_name"]
            expected_raw_path = output / raw_record["outputs"]["bdf"]
            expected_raw_display = f'../../{raw_record["outputs"]["bdf"]}'
            require(
                artifact["logical_name"] == raw_record["logical_name"],
                f"{artifact_name}: logical name drift",
            )
            require(
                representation.get("logical_name") == raw_record["logical_name"],
                f"{artifact_name}: source representation identity drift",
            )
        else:
            assignment_key = artifact_name
            raw_relative = f'runtime/{raw_record["outputs"]["bdf"]}'
            expected_raw_path = output / raw_relative
            expected_raw_display = f"../../{raw_relative}"
            require(
                artifact["runtime_name"] == raw_record["runtime_name"]
                and artifact["classification"] == raw_record["classification"],
                f"{artifact_name}: runtime identity drift",
            )
            require(
                representation.get("runtime_name") == raw_record["runtime_name"]
                and representation.get("classification")
                == raw_record["classification"],
                f"{artifact_name}: runtime representation identity drift",
            )
        configured_logical_id = font_identities["assignments"][
            "source_logical_names"
            if profile_directory == "source"
            else "runtime_artifacts"
        ][assignment_key]
        require(
            logical_identity.get("logical_id") == configured_logical_id,
            f"{artifact_name}: configured logical-font assignment drift",
        )
        repertoire = assignments[assignment_key]
        resolved, geometry, font_geometry, pangram_case = _check_artifact(
            profile_root=profile_root,
            artifact=artifact,
            expected_raw_path=expected_raw_path,
            expected_raw_display=expected_raw_display,
            expected_repertoire=repertoire,
            mapping=mappings[repertoire],
        )
        if pangram_case is not None:
            pangram_cases.append(pangram_case)
        resolution_inventory.extend(
            {"artifact": artifact_name, "repertoire": repertoire, **record}
            for record in resolved
        )
        geometry_inventory.append(
            {
                "artifact": artifact_name,
                "font_geometry": font_geometry,
                "glyphs": geometry,
            }
        )
        xlfd = artifact["unicode_xlfd_name"]
        require(xlfd not in unicode_xlfds, f"duplicate Unicode XLFD {xlfd}")
        unicode_xlfds.add(xlfd)

    resolution_digest = canonical_sha256(resolution_inventory)
    geometry_digest = canonical_sha256(geometry_inventory)
    require(
        catalog["resolution_inventory_sha256"] == resolution_digest,
        "Unicode resolution inventory digest changed: "
        f"catalog={catalog['resolution_inventory_sha256']}, observed={resolution_digest}",
    )
    require(
        catalog["unicode_geometry_sha256"] == geometry_digest,
        "Unicode geometry inventory digest changed: "
        f"catalog={catalog['unicode_geometry_sha256']}, observed={geometry_digest}",
    )
    expected = mapping_manifest["expected"]
    oracle_prefix = "source" if profile_directory == "source" else "runtime"
    profile_oracles = {
        f"{oracle_prefix}_resolution_inventory_sha256": resolution_digest,
        f"{oracle_prefix}_unicode_geometry_sha256": geometry_digest,
    }
    require(
        set(profile_oracles).issubset(REQUIRED_SEMANTIC_ORACLES),
        "checker semantic-oracle inventory differs from the builder",
    )
    for key, digest in profile_oracles.items():
        require(expected[key] == digest, f"reviewed Unicode oracle changed: {key}")

    expected_count = (
        SOURCE_ARTIFACT_COUNT if profile_directory == "source" else RUNTIME_ARTIFACT_COUNT
    )
    expected_glyphs = (
        SOURCE_GLYPH_COUNT if profile_directory == "source" else RUNTIME_GLYPH_COUNT
    )
    require(catalog["artifact_count"] == len(artifacts) == expected_count, "artifact count drift")
    require(
        catalog["emitted_glyph_count"]
        == sum(record["glyph_count"] for record in artifacts)
        == expected_glyphs,
        "emitted Unicode glyph count drift",
    )
    require(
        catalog["standard_glyph_count"] + catalog["private_use_glyph_count"]
        == expected_glyphs,
        "standard/private-use total changed",
    )
    require(
        catalog["standard_glyph_count"]
        == sum(record["standard_glyph_count"] for record in artifacts)
        and catalog["private_use_glyph_count"]
        == sum(record["private_use_glyph_count"] for record in artifacts),
        "Unicode catalog mapping-kind counts are stale",
    )
    require(
        len(list((profile_root / "bdf").glob("*.bdf"))) == expected_count,
        "Unicode BDF directory contains missing or extra artifacts",
    )
    expected_pangram_count = (
        SOURCE_PANGRAM_SHEET_COUNT
        if profile_directory == "source"
        else RUNTIME_PANGRAM_SHEET_COUNT
    )
    expected_case_counts = (
        SOURCE_PANGRAM_CASE_COUNTS
        if profile_directory == "source"
        else RUNTIME_PANGRAM_CASE_COUNTS
    )
    observed_case_counts = {
        case: pangram_cases.count(case) for case in sorted(set(pangram_cases))
    }
    require(
        len(pangram_cases) == expected_pangram_count
        and observed_case_counts == expected_case_counts,
        f"Unicode {profile_directory} pangram selection changed: "
        f"{observed_case_counts}",
    )
    expected_pangram_catalog = {
        "sentence": PANGRAM_SENTENCE,
        "sheet_count": expected_pangram_count,
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
    }
    require(
        catalog["pangram_specimens"] == expected_pangram_catalog,
        f"Unicode {profile_directory} pangram catalog policy changed",
    )
    expected_pangram_files = {
        Path(artifact["pangram_specimen"]["path"]).name
        for artifact in artifacts
        if "pangram_specimen" in artifact
    }
    observed_pangram_entries = {
        path.name for path in (profile_root / "pangrams").iterdir()
    }
    require(
        observed_pangram_entries == expected_pangram_files,
        f"Unicode {profile_directory} pangram directory is not closed",
    )

    aliases = (
        _expected_source_aliases(artifacts, runtime_catalog)
        if profile_directory == "source"
        else _expected_runtime_aliases(artifacts)
    )
    expected_alias_count = (
        SOURCE_ALIAS_COUNT if profile_directory == "source" else RUNTIME_ALIAS_COUNT
    )
    require(len(aliases) == expected_alias_count, "Unicode alias count drift")
    alias_path = profile_root / "bdf" / "fonts.alias"
    expected_comment = (
        "! Unicode source-profile aliases; raw profiles are separate."
        if profile_directory == "source"
        else "! Unicode runtime aliases; current System 46 names win."
    )
    require(
        alias_path.read_text(encoding="ascii").splitlines()[:1]
        == [expected_comment],
        "Unicode fonts.alias policy comment changed",
    )
    require(
        _parse_aliases(alias_path) == aliases,
        "Unicode fonts.alias changed",
    )
    expected_dir = {
        Path(record["unicode_bdf"]).name: record["unicode_xlfd_name"]
        for record in artifacts
    }
    require(
        _parse_fonts_dir(profile_root / "bdf" / "fonts.dir") == expected_dir,
        "Unicode fonts.dir changed",
    )
    require(
        catalog["x_indexes"]
        == {
            "fonts_dir": "bdf/fonts.dir",
            "fonts_alias": "bdf/fonts.alias",
            "alias_count": len(aliases),
            "aliases": [
                {"name": alias, "xlfd": aliases[alias]} for alias in sorted(aliases)
            ],
        },
        "Unicode catalog X indexes are stale",
    )
    return {
        "catalog": catalog,
        "catalog_path": catalog_path,
        "aliases": aliases,
        "xlfds": unicode_xlfds,
        "resolution_digest": resolution_digest,
        "geometry_digest": geometry_digest,
    }


def _check_build_manifest(
    output: Path,
    source: dict[str, object],
    runtime: dict[str, object],
    font_identities: dict[str, object],
    font_identities_path: Path,
) -> None:
    build = json.loads((output / "BUILD-MANIFEST.json").read_text(encoding="utf-8"))
    require(build["schema_version"] == 2, "BUILD-MANIFEST is not four-profile schema 2")
    identity_assignments = font_identities["assignments"]
    expected_identity_provenance = {
        "id": font_identities["mapping_id"],
        "sha256": sha256(font_identities_path),
        "logical_identity_count": len(font_identities["logical_identities"]),
        "source_logical_name_count": len(
            identity_assignments["source_logical_names"]
        ),
        "runtime_artifact_count": len(identity_assignments["runtime_artifacts"]),
    }
    require(
        build.get("font_identities") == expected_identity_provenance,
        "BUILD-MANIFEST font-identity provenance is stale",
    )
    pairs = (
        ("unicode_authoring_source", source, "authoring_source"),
        ("unicode_system_46_runtime", runtime, "system_46_runtime"),
    )
    for name, result, raw_name in pairs:
        record = build["profiles"][name]
        catalog = result["catalog"]
        expected_catalog = (
            "unicode/source/catalog.json"
            if name == "unicode_authoring_source"
            else "unicode/runtime/catalog.json"
        )
        require(record["catalog"] == expected_catalog, f"{name}: catalog path stale")
        require(record["catalog_sha256"] == sha256(result["catalog_path"]), f"{name}: catalog hash stale")
        require(record["raw_profile"] == raw_name, f"{name}: raw profile link changed")
        for field in (
            "artifact_count",
            "emitted_glyph_count",
            "standard_glyph_count",
            "private_use_glyph_count",
        ):
            require(record[field] == catalog[field], f"{name}: {field} stale")
        require(
            record["pangram_sheet_count"]
            == catalog["pangram_specimens"]["sheet_count"],
            f"{name}: pangram sheet count stale",
        )
        require(record["alias_count"] == len(result["aliases"]), f"{name}: alias count stale")
    require(build["raw_artifact_count"] == 200, "raw artifact total changed")
    require(
        build["unicode_derivative_artifact_count"] == 200,
        "Unicode derivative total changed",
    )
    require(
        build["total_installable_artifact_count"] == 400,
        "installable artifact total changed",
    )
    require(build["total_pangram_sheet_count"] == 160, "pangram sheet total changed")


def check_unicode_distribution(
    output: Path, mapping_path: Path = DEFAULT_MAPPING
) -> dict[str, object]:
    output = output.resolve()
    mapping_path = mapping_path.resolve()
    manifest = load_mapping(mapping_path)
    mapping_copy = output / "unicode" / "UNICODE-MAPPING.json"
    require(mapping_copy.read_bytes() == mapping_path.read_bytes(), "distributed Unicode mapping is stale")
    source_catalog_path = output / "catalog.json"
    runtime_catalog_path = output / "runtime" / "catalog.json"
    font_identities_path = output / "FONT-IDENTITIES.json"
    require(font_identities_path.is_file(), "distributed font identities are missing")
    require(
        font_identities_path.read_bytes()
        == (ROOT / "config" / "font-identities.json").read_bytes(),
        "distributed font identities differ from the tracked mapping",
    )
    font_identities = json.loads(font_identities_path.read_text(encoding="utf-8"))
    require(
        font_identities.get("schema_version") == 1
        and isinstance(font_identities.get("mapping_id"), str),
        "unsupported font-identity mapping",
    )
    source_catalog = json.loads(source_catalog_path.read_text(encoding="utf-8"))
    runtime_catalog = json.loads(runtime_catalog_path.read_text(encoding="utf-8"))
    mapping_result = validate_mapping_closure(manifest, source_catalog, runtime_catalog)
    mappings = mapping_result["mappings"]
    assignments = manifest["assignments"]
    source_result = _check_profile(
        output=output,
        profile_name="unicode_authoring_source",
        profile_directory="source",
        raw_catalog_path=source_catalog_path,
        raw_records=source_catalog["fonts"],
        identity_key="name",
        mapping_manifest=manifest,
        mapping_copy=mapping_copy,
        mappings=mappings,
        assignments=assignments["source_logical_names"],
        font_identities=font_identities,
        font_identities_path=font_identities_path,
        runtime_catalog=runtime_catalog,
    )
    runtime_result = _check_profile(
        output=output,
        profile_name="unicode_system_46_runtime",
        profile_directory="runtime",
        raw_catalog_path=runtime_catalog_path,
        raw_records=runtime_catalog["font_artifacts"],
        identity_key="artifact_name",
        mapping_manifest=manifest,
        mapping_copy=mapping_copy,
        mappings=mappings,
        assignments=assignments["runtime_artifacts"],
        font_identities=font_identities,
        font_identities_path=font_identities_path,
        runtime_catalog=runtime_catalog,
    )
    require(
        not (source_result["xlfds"] & runtime_result["xlfds"]),
        "Unicode source/runtime XLFD namespaces collide",
    )
    raw_xlfds = {
        record["bdf"]["xlfd_name"] for record in source_catalog["fonts"]
    } | {
        record["bdf_profile"]["xlfd_name"]
        for record in runtime_catalog["font_artifacts"]
    }
    unicode_xlfds = source_result["xlfds"] | runtime_result["xlfds"]
    require(not (raw_xlfds & unicode_xlfds), "raw and Unicode XLFDs collide")
    require(
        len(raw_xlfds) == len(unicode_xlfds) == 200,
        "raw or Unicode XLFD inventory changed",
    )
    require(
        not (set(source_result["aliases"]) & set(runtime_result["aliases"])),
        "Unicode source/runtime aliases collide",
    )
    raw_aliases = set(_parse_aliases(output / "bdf" / "fonts.alias")) | set(
        _parse_aliases(output / "runtime" / "bdf" / "fonts.alias")
    )
    unicode_aliases = set(source_result["aliases"]) | set(runtime_result["aliases"])
    require(not (raw_aliases & unicode_aliases), "raw and Unicode aliases collide")
    _check_build_manifest(
        output,
        source_result,
        runtime_result,
        font_identities,
        font_identities_path,
    )
    return {
        "source_artifact_count": source_result["catalog"]["artifact_count"],
        "runtime_artifact_count": runtime_result["catalog"]["artifact_count"],
        "source_glyph_count": source_result["catalog"]["emitted_glyph_count"],
        "runtime_glyph_count": runtime_result["catalog"]["emitted_glyph_count"],
        "source_alias_count": len(source_result["aliases"]),
        "runtime_alias_count": len(runtime_result["aliases"]),
        "source_pangram_sheet_count": source_result["catalog"][
            "pangram_specimens"
        ]["sheet_count"],
        "runtime_pangram_sheet_count": runtime_result["catalog"][
            "pangram_specimens"
        ]["sheet_count"],
        "allocated_pua_block_count": mapping_result["allocated_pua_block_count"],
        "source_resolution_inventory_sha256": source_result["resolution_digest"],
        "source_unicode_geometry_sha256": source_result["geometry_digest"],
        "runtime_resolution_inventory_sha256": runtime_result["resolution_digest"],
        "runtime_unicode_geometry_sha256": runtime_result["geometry_digest"],
        "undefined_code_substitution": "excluded",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    args = parser.parse_args()
    try:
        result = check_unicode_distribution(args.output, args.mapping)
    except (OSError, UnicodeDistError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
