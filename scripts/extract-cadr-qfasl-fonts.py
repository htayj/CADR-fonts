#!/usr/bin/env python3
"""Recover all reviewed MIT CADR System 46 runtime fonts from QFASL.

This is deliberately separate from ``extract-cadr-fonts.py``.  That program
recovers authored AST, KST, Alto, and CLDFNT representations; this one reads a
narrow, verified subset of the QFASL object language and reconstructs the
runtime FONT arrays stored by the historical font compiler or array dumper.

The inputs are the 49 public ``src/lmfont/*.qfasl`` files at the pinned CADR
revision, not a load band and not licensed Symbolics media.  The parser
implements only opcodes observed in that closed corpus and rejects all other
operations; it never evaluates Lisp forms or loads target-machine code.

The inert parser and FONT-array reconstruction were ported from
``lisp-machine-container-museum`` commit
``d62ad48fbf879fb09c7bc17c49735116cc13e143``.  That exact ancestor and its
SHA-256 are recorded in ``config/runtime-source-manifest.json``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
from typing import Iterable

from font_identities import (
    DEFAULT_FONT_IDENTITIES,
    bdf_profile_arguments,
    load_font_identities,
    resolve_font_identity,
)
from lisp_machine_fonts import (
    BitmapFont,
    Glyph,
    bdf_profile,
    prepare_output_directory,
    write_font_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "sources" / "mit-cadr-system-software" / "src" / "lmfont"
DEFAULT_MANIFEST = ROOT / "config" / "runtime-source-manifest.json"
SOURCE_REPOSITORY = "https://github.com/mietek/mit-cadr-system-software.git"
SOURCE_REVISION = "8e978d7d1704096a63edd4386a3b8326a2e584af"
SOURCE_LICENSE_SHA256 = "05b8de7c86c946cc747ab71a9aaa7dd56e37365278b5585ab685156eaa90fb92"
DECODER_ANCESTOR_REPOSITORY = (
    "https://github.com/htayj/lisp-machine-container-museum.git"
)
DECODER_ANCESTOR_REVISION = "d62ad48fbf879fb09c7bc17c49735116cc13e143"
DECODER_ANCESTOR_SHA256 = (
    "184d886477086e583c660209de1265a2ce79dec5b813494858cefc6d014ace88"
)
CLASSIFICATIONS = {
    "source-backed-current",
    "compiled-only",
    "legacy-compiled-version",
}
MASK36 = (1 << 36) - 1
MAX_NIBBLES = 2_000_000
MAX_TABLE_ENTRIES = 100_000
MAX_ARRAY_ELEMENTS = 20_000_000
MAX_INITIALIZATION_VALUES = 2_000_000
MAX_NESTING = 128
RASTER_ORDER_OVERRIDE_ARTIFACTS = {"GERM35"}
RASTER_ORDER_EVIDENCE_PATHS = {
    "src/lmio1/fcmp.66",
    "src/lmio/tvdefs.52",
    "src/lmio/tv.347",
    "src/moon/wall.3",
}
FCMP_16_SERIALIZED_ORDER = "16-bit-screen"
FCMP_16_NORMALIZATION = "reverse-each-serialized-32-bit-raster-word"


class QfaslError(ValueError):
    """The input cannot be decoded under the reviewed inert-QFASL grammar."""


@dataclass(frozen=True)
class RuntimeArtifactSpec:
    artifact_name: str
    source_file: str
    runtime_name: str
    runtime_symbol: str
    classification: str
    byte_size: int
    sha256: str
    decoded_pdp10_word_count: int
    decoded_pdp10_word_sha256: str
    decoded_qfasl_nibble_count: int
    end_of_whack_count: int
    source_reference_artifact: str | None = None
    expected_source_relation: str | None = None
    expected_source_relation_details: dict[str, object] | None = None


@dataclass(frozen=True)
class DecodedRuntimeFont:
    spec: RuntimeArtifactSpec
    font: BitmapFont
    parser: "FontQfaslParser"
    words: tuple[int, ...]
    source_sha256: str


def _validate_raster_order_overrides(
    manifest: dict, specs: tuple[RuntimeArtifactSpec, ...]
) -> dict[str, dict[str, object]]:
    """Validate the closed, historical exceptions to normal raster decoding."""

    overrides = manifest.get("raster_order_overrides")
    if not isinstance(overrides, dict):
        raise QfaslError("runtime manifest lacks raster-order overrides")
    if set(overrides) != RASTER_ORDER_OVERRIDE_ARTIFACTS:
        raise QfaslError("runtime manifest raster-order override set changed")
    if not set(overrides) <= {spec.artifact_name for spec in specs}:
        raise QfaslError("raster-order override names an unknown artifact")

    profile = overrides["GERM35"]
    if not isinstance(profile, dict) or set(profile) != {
        "display_normalization",
        "historical_evidence",
        "historical_screen_mode",
        "reference_compiler_entrypoint",
        "reviewed_display_oracle",
        "serialized_raster_order",
        "structural_signature",
    }:
        raise QfaslError("GERM35 raster-order override schema changed")
    if (
        profile["historical_screen_mode"] != "16-bit"
        or profile["reference_compiler_entrypoint"] != "FCMP-16"
        or profile["serialized_raster_order"] != FCMP_16_SERIALIZED_ORDER
        or profile["display_normalization"] != FCMP_16_NORMALIZATION
        or profile["structural_signature"]
        != {
            "indexing_table": True,
            "raster_width": 16,
            "rasters_per_word": 2,
        }
    ):
        raise QfaslError("GERM35 raster-order contract changed")

    evidence = profile["historical_evidence"]
    if not isinstance(evidence, list) or len(evidence) != len(
        RASTER_ORDER_EVIDENCE_PATHS
    ):
        raise QfaslError("GERM35 raster-order evidence set changed")
    evidence_paths = set()
    for record in evidence:
        if not isinstance(record, dict) or set(record) != {
            "byte_size",
            "line_ranges",
            "observation",
            "path",
            "sha256",
        }:
            raise QfaslError("GERM35 raster-order evidence schema changed")
        evidence_path = PurePosixPath(str(record["path"]))
        if (
            evidence_path.is_absolute()
            or ".." in evidence_path.parts
            or not evidence_path.parts
            or evidence_path.parts[0] != "src"
        ):
            raise QfaslError("GERM35 raster-order evidence path is unsafe")
        evidence_paths.add(evidence_path.as_posix())
        if (
            not isinstance(record["byte_size"], int)
            or record["byte_size"] < 1
            or not isinstance(record["sha256"], str)
            or len(record["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in record["sha256"])
            or not isinstance(record["line_ranges"], list)
            or not record["line_ranges"]
            or not all(isinstance(value, str) and value for value in record["line_ranges"])
            or not isinstance(record["observation"], str)
            or not record["observation"]
        ):
            raise QfaslError("GERM35 raster-order evidence record is invalid")
    if evidence_paths != RASTER_ORDER_EVIDENCE_PATHS:
        raise QfaslError("GERM35 raster-order evidence paths changed")

    oracle = profile["reviewed_display_oracle"]
    if not isinstance(oracle, dict) or set(oracle) != {
        "canonicalization",
        "ink_bearing_glyph_count",
        "sha256",
    }:
        raise QfaslError("GERM35 display oracle schema changed")
    if (
        not isinstance(oracle["canonicalization"], str)
        or not oracle["canonicalization"]
        or oracle["ink_bearing_glyph_count"] != 74
        or not isinstance(oracle["sha256"], str)
        or len(oracle["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in oracle["sha256"])
    ):
        raise QfaslError("GERM35 display oracle is invalid")
    return overrides


def load_runtime_manifest(
    path: Path = DEFAULT_MANIFEST,
) -> tuple[dict, tuple[RuntimeArtifactSpec, ...]]:
    """Load and structurally validate the closed 49-file runtime manifest."""

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1:
            raise QfaslError("unsupported runtime source manifest schema")
        if manifest["repository"] != SOURCE_REPOSITORY:
            raise QfaslError("runtime manifest names an unexpected source repository")
        if manifest["revision"] != SOURCE_REVISION:
            raise QfaslError("runtime manifest names an unexpected source revision")
        license_record = manifest["license"]
        if license_record["sha256"] != SOURCE_LICENSE_SHA256:
            raise QfaslError("runtime manifest names an unexpected source license")
        lineage = manifest["decoder_lineage"]
        expected_lineage = (
            DECODER_ANCESTOR_REPOSITORY,
            DECODER_ANCESTOR_REVISION,
            DECODER_ANCESTOR_SHA256,
        )
        if (
            lineage["repository"],
            lineage["revision"],
            lineage["sha256"],
        ) != expected_lineage:
            raise QfaslError("runtime manifest decoder lineage changed")
        specs = tuple(RuntimeArtifactSpec(**record) for record in manifest["artifacts"])
        expected = manifest["expected"]
    except (KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        raise QfaslError(f"cannot load runtime source manifest {path}: {error}") from error

    source_files = [spec.source_file for spec in specs]
    artifact_names = [spec.artifact_name for spec in specs]
    if len(specs) != expected["artifact_count"] or len(specs) != 49:
        raise QfaslError("runtime manifest must contain exactly 49 artifacts")
    if len(set(source_files)) != len(source_files):
        raise QfaslError("runtime manifest repeats a source file")
    if len(set(artifact_names)) != len(artifact_names):
        raise QfaslError("runtime manifest repeats an artifact name")
    if any(not name.endswith(".qfasl") for name in source_files):
        raise QfaslError("runtime manifest includes a non-.qfasl input")
    counts = Counter(spec.classification for spec in specs)
    if set(counts) != CLASSIFICATIONS or dict(counts) != expected["classification_counts"]:
        raise QfaslError("runtime manifest classification counts changed")
    if len({spec.runtime_name for spec in specs}) != expected["runtime_logical_name_count"]:
        raise QfaslError("runtime manifest logical-name count changed")
    for spec in specs:
        has_reference = (
            spec.source_reference_artifact is not None
            and spec.expected_source_relation is not None
        )
        if has_reference != (spec.classification == "source-backed-current"):
            raise QfaslError(
                "only source-backed current artifacts may name source references"
            )
        if (
            spec.expected_source_relation == "exact-runtime-visible"
            and spec.expected_source_relation_details is not None
        ):
            raise QfaslError("exact source relations must not carry difference details")
    _validate_raster_order_overrides(manifest, specs)
    return manifest, specs


def _text_byte(byte: int) -> tuple[int, ...]:
    """Undo one byte of the ITS tape extractor's evacuated representation."""

    if 0 <= byte <= 0o11:
        return (byte,)
    if byte == 0o12:
        return (0o15, 0o12)
    if 0o13 <= byte <= 0o14:
        return (byte,)
    if byte == 0o15:
        return (0o12,)
    if 0o16 <= byte <= 0o176:
        return (byte,)
    if byte == 0o177:
        return (0o177, 0o7)
    if 0o200 <= byte <= 0o206:
        return (0o177, byte - 0o200)
    if byte == 0o207:
        return (0o177, 0o177)
    if 0o210 <= byte <= 0o211:
        return (0o177, byte - 0o200)
    if byte == 0o212:
        return (0o177, 0o15)
    if 0o213 <= byte <= 0o214:
        return (0o177, byte - 0o200)
    if byte == 0o215:
        return (0o177, 0o12)
    if 0o216 <= byte <= 0o355:
        return (0o177, byte - 0o200)
    if byte == 0o356:
        return (0o15,)
    if byte == 0o357:
        return (0o177,)
    raise QfaslError(f"invalid evacuated text byte {byte:#o}")


def evacuated_words(raw: bytes) -> list[int]:
    """Reconstruct the historical PDP-10 36-bit words from host bytes."""

    words: list[int] = []
    characters: list[int] = []
    position = 0

    def flush() -> None:
        nonlocal characters
        if len(characters) == 5:
            words.append(
                sum(
                    character << shift
                    for character, shift in zip(characters, (29, 22, 15, 8, 1))
                )
            )
            characters = []

    while position < len(raw):
        byte = raw[position]
        position += 1
        if byte >= 0o360:
            if characters:
                raise QfaslError("quoted binary word occurs inside a text word")
            if position + 4 > len(raw):
                raise QfaslError("truncated quoted binary word")
            byte1, byte2, byte3, byte4 = raw[position : position + 4]
            position += 4
            left = ((byte & 0o17) << 14) | (byte1 << 6) | (byte2 >> 2)
            right = ((byte2 & 0o3) << 16) | (byte3 << 8) | byte4
            words.append((left << 18) | right)
            continue
        for character in _text_byte(byte):
            characters.append(character)
            flush()

    if characters:
        characters.extend([0o3] * (5 - len(characters)))
        flush()
    return words


def qfasl_nibbles(words: Iterable[int]) -> list[int]:
    """Return the two 16-bit QFASL nibbles stored in each PDP-10 word."""

    result = []
    for word in words:
        if not 0 <= word <= MASK36:
            raise QfaslError("PDP-10 word is outside 36-bit range")
        if word & 0xF:
            raise QfaslError("QFASL PDP-10 word has nonzero low padding bits")
        result.extend(((word >> 20) & 0xFFFF, (word >> 4) & 0xFFFF))
    return result


@dataclass(frozen=True)
class Symbol:
    name: str
    package: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return ":".join((*self.package, self.name))


@dataclass
class SerializedArray:
    element_type: str
    dimensions: tuple[int, ...]
    leader: dict[int, object] = field(default_factory=dict)
    initialization: list[object] | None = None
    initialization_opcode: str | None = None
    declared_leader_length: int | None = None

    @property
    def length(self) -> int:
        result = 1
        for dimension in self.dimensions:
            result *= dimension
        return result

    def values(self) -> list[int]:
        """Decode the initialized array in Lisp Machine storage order."""

        if self.initialization is None:
            raise QfaslError("array was never initialized")
        if any(not isinstance(value, int) for value in self.initialization):
            raise QfaslError(f"{self.element_type} array has non-integer data")
        raw = [int(value) for value in self.initialization]

        packed_counts = {
            "ART-Q": self.length,
            "ART-1B": (self.length + 15) // 16,
            "ART-8B": (self.length + 1) // 2,
            "ART-16B": self.length,
            "ART-32B": self.length * 2,
        }
        if self.element_type not in packed_counts:
            raise QfaslError(f"unsupported serialized array type {self.element_type}")
        expected_count = packed_counts[self.element_type]
        if len(raw) != expected_count:
            raise QfaslError(
                f"{self.element_type} initialization has {len(raw)} halfwords or "
                f"values, expected exactly {expected_count}"
            )

        if self.element_type == "ART-Q":
            result = raw
        elif self.element_type == "ART-1B":
            result = [(word >> bit) & 1 for word in raw for bit in range(16)]
        elif self.element_type == "ART-8B":
            result = [
                (word >> shift) & 0xFF for word in raw for shift in (0, 8)
            ]
        elif self.element_type == "ART-16B":
            result = raw
        elif self.element_type == "ART-32B":
            if len(raw) % 2:
                raise QfaslError("ART-32B array has an odd halfword count")
            result = []
            for index in range(0, len(raw), 2):
                # System 46's ART-32B access supplies a FIXNUM data type and
                # exposes 24 payload bits.  The dumped upper byte is the Q tag,
                # not part of a signed left-kern value.
                raw32 = raw[index] | (raw[index + 1] << 16)
                tag = (raw32 >> 24) & 0xFF
                if raw32 != 0 and tag != 0xC5:
                    raise QfaslError(
                        f"ART-32B element has unsupported Q tag {tag:#04x}"
                    )
                value = raw32 & 0xFFFFFF
                if value & 0x800000:
                    value -= 1 << 24
                result.append(value)
        if any(result[self.length :]):
            raise QfaslError(f"nonzero packing padding in {self.element_type} array")
        return result[: self.length]


@dataclass
class _Group:
    opcode: int
    flag: bool
    remaining: int
    offset: int


OPCODE_NAMES = {
    0o02: "INDEX",
    0o03: "SYMBOL",
    0o04: "LIST",
    0o05: "TEMP-LIST",
    0o06: "FIXED",
    0o10: "ARRAY",
    0o16: "STOREIN-SYMBOL-VALUE",
    0o25: "END-OF-WHACK",
    0o26: "END-OF-FILE",
    0o44: "INITIALIZE-ARRAY",
    0o54: "STRING",
    0o55: "STOREIN-ARRAY-LEADER",
    0o56: "INITIALIZE-NUMERIC-ARRAY",
    0o60: "PACKAGE-SYMBOL",
}


class FontQfaslParser:
    """A non-evaluating parser for the reviewed font serialization subset."""

    def __init__(self, nibbles: list[int]):
        if len(nibbles) > MAX_NIBBLES:
            raise QfaslError(f"QFASL exceeds the {MAX_NIBBLES}-nibble safety limit")
        self.nibbles = nibbles
        self.position = 0
        self.table: list[object] = []
        self.bindings: dict[Symbol, object] = {}
        self.opcode_counts: Counter[int] = Counter()
        self.whack_count = 0
        self._finished = False
        self._reset_table()

    def _reset_table(self) -> None:
        # Only FASL-NIL (index zero) is semantically required by these files.
        # Unknown parameter slots are sentinels so an unexpected dependency is
        # rejected instead of silently assigned a made-up host value.
        self.table = [None] + [_UNSET] * 31

    def _raw(self) -> int:
        if self.position >= len(self.nibbles):
            raise QfaslError("unexpected end of QFASL nibble stream")
        value = self.nibbles[self.position]
        self.position += 1
        return value

    @staticmethod
    def _operation_name(opcode: int) -> str:
        return OPCODE_NAMES[opcode]

    def _direct(self, group: _Group) -> int:
        if group.remaining == 0:
            raise QfaslError(
                f"opcode {self._operation_name(group.opcode)} "
                "consumed too many direct nibbles"
            )
        group.remaining -= 1
        return self._raw()

    def _enter(self, value: object) -> int:
        if len(self.table) >= MAX_TABLE_ENTRIES:
            raise QfaslError("QFASL table exceeds its safety limit")
        self.table.append(value)
        return len(self.table) - 1

    def _lookup(self, index: int) -> object:
        if not 0 <= index < len(self.table):
            raise QfaslError(f"FASL table index {index} is out of range")
        value = self.table[index]
        if value is _UNSET:
            raise QfaslError(f"FASL table parameter index {index} is unsupported")
        return value

    def _value(self, depth: int) -> object:
        return self._lookup(self._parse_group(depth + 1))

    @staticmethod
    def _symbol_name(value: object, field_name: str) -> str:
        if not isinstance(value, Symbol):
            raise QfaslError(f"{field_name} is not a symbol")
        return value.name

    def _parse_group(self, depth: int = 0) -> int:
        if depth > MAX_NESTING:
            raise QfaslError("QFASL value nesting exceeds its safety limit")
        offset = self.position
        header = self._raw()
        if not header & 0o100000:
            raise QfaslError(
                f"group at nibble {offset} lacks the QFASL check bit: {header:#o}"
            )
        opcode = header & 0o77
        if opcode not in OPCODE_NAMES:
            raise QfaslError(
                f"unsupported opcode {opcode:#o} at nibble {offset}; "
                "QFASLs are never evaluated"
            )
        length = (header & 0o37700) >> 6
        if length == 0o377:
            length = self._raw()
        group = _Group(opcode, bool(header & 0o40000), length, offset)
        self.opcode_counts[opcode] += 1

        if opcode == 0o02:  # INDEX
            result = self._direct(group)
            self._lookup(result)
        elif opcode in {0o03, 0o54}:  # SYMBOL or STRING
            characters: list[int] = []
            for nibble_number in range(length):
                packed = self._direct(group)
                characters.append(packed & 0xFF)
                second = (packed >> 8) & 0xFF
                if second == 0x80:
                    if nibble_number != length - 1:
                        raise QfaslError("symbol padding occurs before its last nibble")
                else:
                    characters.append(second)
            try:
                name = bytes(characters).decode("ascii")
            except UnicodeDecodeError as error:
                raise QfaslError("font QFASL contains a non-ASCII symbol") from error
            if opcode == 0o03:
                value: object = None if name == "NIL" else Symbol(name)
            else:
                value = name
            result = self._enter(value)
        elif opcode in {0o04, 0o05}:  # LIST or TEMP-LIST
            count = self._direct(group)
            if count > MAX_INITIALIZATION_VALUES:
                raise QfaslError("QFASL list exceeds its safety limit")
            values = [self._value(depth) for _ in range(count)]
            if group.flag:
                raise QfaslError("dotted lists are outside the font QFASL subset")
            result = self._enter(values)
        elif opcode == 0o06:  # FIXED
            magnitude = 0
            for _ in range(length):
                magnitude = (magnitude << 16) | self._direct(group)
            result = self._enter(-magnitude if group.flag else magnitude)
        elif opcode == 0o10:  # ARRAY
            area = self._value(depth)
            element_type = self._symbol_name(
                self._value(depth), "array element type"
            )
            dimensions_value = self._value(depth)
            displaced = self._value(depth)
            leader_value = self._value(depth)
            index_offset = self._value(depth)
            if group.flag:
                named_structure = self._value(depth)
                if named_structure not in {Symbol("T"), Symbol("FONT")}:
                    # Historical generic dumps use T; FCMP supplies FONT via
                    # the leader and does not set this flag.
                    raise QfaslError("unexpected ARRAY named-structure marker")
            if not isinstance(area, Symbol):
                raise QfaslError("array area is not a symbol")
            if displaced is not None or index_offset is not None:
                raise QfaslError("displaced font arrays are unsupported")
            if not isinstance(dimensions_value, list) or not dimensions_value:
                raise QfaslError("array dimensions are not a nonempty list")
            if any(
                not isinstance(value, int) or value < 0
                for value in dimensions_value
            ):
                raise QfaslError("array has an invalid dimension")
            element_count = 1
            for dimension in dimensions_value:
                element_count *= dimension
                if element_count > MAX_ARRAY_ELEMENTS:
                    raise QfaslError("array dimensions exceed the safety limit")
            if isinstance(leader_value, int):
                raise QfaslError("array leader initializer is not a list")
            elif leader_value is None:
                leader = {}
                declared_leader_length = 0
            elif isinstance(leader_value, list):
                leader = dict(enumerate(reversed(leader_value)))
                declared_leader_length = len(leader_value)
            else:
                raise QfaslError("array leader initializer is neither a list nor a length")
            result = self._enter(
                SerializedArray(
                    element_type,
                    tuple(dimensions_value),
                    leader,
                    declared_leader_length=declared_leader_length,
                )
            )
        elif opcode == 0o16:  # STOREIN-SYMBOL-VALUE
            source_index = self._direct(group)
            destination = self._value(depth)
            if not isinstance(destination, Symbol):
                raise QfaslError("symbol-value destination is not a symbol")
            self.bindings[destination] = self._lookup(source_index)
            result = 0
        elif opcode == 0o25:  # END-OF-WHACK
            if group.flag:
                raise QfaslError("END-OF-WHACK has an unexpected flag")
            self.whack_count += 1
            result = _END_WHACK
        elif opcode == 0o26:  # END-OF-FILE
            if group.flag:
                raise QfaslError("END-OF-FILE has an unexpected flag")
            result = _END_FILE
        elif opcode in {0o44, 0o56}:  # array initialization
            array_index = self._parse_group(depth + 1)
            array = self._lookup(array_index)
            count = self._value(depth)
            if not isinstance(array, SerializedArray):
                raise QfaslError("array initialization target is not an array")
            if array.initialization is not None:
                raise QfaslError("array is initialized more than once")
            if not isinstance(count, int) or count < 0:
                raise QfaslError("array initialization count is invalid")
            if count > MAX_INITIALIZATION_VALUES:
                raise QfaslError("array initialization exceeds its safety limit")
            if opcode == 0o44:
                initialization = [self._value(depth) for _ in range(count)]
                operation = "INITIALIZE-ARRAY"
            else:
                # The historical format explicitly excludes these halfwords
                # from the group-length field.
                initialization = [self._raw() for _ in range(count)]
                operation = "INITIALIZE-NUMERIC-ARRAY"
            array.initialization = initialization
            array.initialization_opcode = operation
            result = array_index
        elif opcode == 0o55:  # STOREIN-ARRAY-LEADER
            array = self._lookup(self._direct(group))
            subscript = self._lookup(self._direct(group))
            value = self._lookup(self._direct(group))
            if not isinstance(array, SerializedArray):
                raise QfaslError("leader store target is not an array")
            if not isinstance(subscript, int) or subscript < 0:
                raise QfaslError("leader store subscript is invalid")
            if (
                array.declared_leader_length is not None
                and subscript >= array.declared_leader_length
            ):
                raise QfaslError("leader store subscript is outside the declared leader")
            array.leader[subscript] = value
            result = 0
        elif opcode == 0o60:  # PACKAGE-SYMBOL
            component_count = self._direct(group)
            if component_count > MAX_NESTING:
                raise QfaslError("package name has too many components")
            components = [self._value(depth) for _ in range(component_count)]
            if not components or any(
                not isinstance(component, str) for component in components
            ):
                raise QfaslError("package symbol has invalid name components")
            result = self._enter(
                Symbol(str(components[-1]), tuple(str(x) for x in components[:-1]))
            )
        else:  # pragma: no cover - guarded by OPCODE_NAMES
            raise AssertionError(opcode)

        if group.remaining:
            raise QfaslError(
                f"opcode {self._operation_name(opcode)} left {group.remaining} "
                "direct nibbles unconsumed"
            )
        return result

    def parse(self) -> dict[Symbol, object]:
        if self._finished:
            raise QfaslError("parser instances are single-use")
        if self._raw() != 0o143150 or self._raw() != 0o071660:
            raise QfaslError("not a System 46 QFASL file (bad SIXBIT/QFASL magic)")
        while True:
            result = self._parse_group()
            if result is _END_FILE:
                break
            if result is _END_WHACK:
                self._reset_table()
        trailing = self.nibbles[self.position :]
        if len(trailing) > 1 or any(trailing):
            raise QfaslError(f"unexpected data after END-OF-FILE: {trailing!r}")
        self._finished = True
        return self.bindings


_UNSET = object()
_END_WHACK = -2
_END_FILE = -3


def _require_int(leader: dict[int, object], index: int, name: str) -> int:
    value = leader.get(index)
    if not isinstance(value, int):
        raise QfaslError(f"FONT leader {name} ({index:o}) is not an integer")
    return value


def _optional_array(
    leader: dict[int, object], index: int, expected_type: str, length: int, name: str
) -> list[int] | None:
    value = leader.get(index)
    if value is None:
        return None
    if not isinstance(value, SerializedArray):
        raise QfaslError(f"FONT leader {name} ({index:o}) is not an array")
    if value.element_type not in {expected_type, "ART-Q"}:
        raise QfaslError(
            f"FONT {name} table uses {value.element_type}, expected {expected_type}"
        )
    values = value.values()
    if len(values) != length:
        raise QfaslError(f"FONT {name} table has {len(values)} entries, expected {length}")
    return values


def _serialized_font_binding(
    bindings: dict[Symbol, object],
) -> tuple[Symbol, SerializedArray]:
    font_bindings = [
        (symbol, value)
        for symbol, value in bindings.items()
        if isinstance(value, SerializedArray)
        and isinstance(value.leader.get(1), Symbol)
        and value.leader[1].name == "FONT"
    ]
    if len(font_bindings) != 1:
        raise QfaslError(f"expected one serialized FONT binding, found {len(font_bindings)}")
    return font_bindings[0]


def _normalize_serialized_raster_bits(
    raster_bits: list[int], raster_order_profile: dict[str, object] | None
) -> list[int]:
    """Convert a reviewed serialized raster order to display coordinates."""

    if raster_order_profile is None:
        return raster_bits
    if (
        raster_order_profile["serialized_raster_order"]
        != FCMP_16_SERIALIZED_ORDER
        or raster_order_profile["display_normalization"]
        != FCMP_16_NORMALIZATION
    ):
        raise QfaslError("unsupported reviewed raster-order normalization")
    if len(raster_bits) % 32:
        raise QfaslError("16-bit-screen raster is not composed of complete words")
    return [
        bit
        for offset in range(0, len(raster_bits), 32)
        for bit in reversed(raster_bits[offset : offset + 32])
    ]


def font_from_binding(
    artifact_name: str,
    expected_runtime_name: str,
    source_name: str,
    bindings: dict[Symbol, object],
    *,
    expected_runtime_symbol: str | None = None,
    raster_order_profile: dict[str, object] | None = None,
) -> BitmapFont:
    symbol, array = _serialized_font_binding(bindings)
    expected_symbol = expected_runtime_symbol or f"FONTS:{expected_runtime_name}"
    if symbol.qualified_name != expected_symbol or symbol.name != expected_runtime_name:
        raise QfaslError(
            f"QFASL binds {symbol.qualified_name}, expected "
            f"{expected_symbol}"
        )
    if array.element_type != "ART-1B" or len(array.dimensions) != 1:
        raise QfaslError("serialized FONT raster is not a one-dimensional ART-1B array")

    leader = array.leader
    character_height = _require_int(leader, 0o3, "character height")
    fixed_width = _require_int(leader, 0o4, "character width")
    raster_height = _require_int(leader, 0o5, "raster height")
    raster_width = _require_int(leader, 0o6, "raster width")
    rasters_per_word = _require_int(leader, 0o7, "rasters per word")
    words_per_character = _require_int(leader, 0o10, "words per character")
    baseline = _require_int(leader, 0o11, "baseline")
    if not 1 <= character_height <= 256:
        raise QfaslError("FONT character height is outside the supported range")
    if not 1 <= raster_height <= character_height:
        raise QfaslError("FONT raster height is inconsistent with character height")
    if not 0 <= baseline <= character_height:
        raise QfaslError("FONT baseline is outside the character cell")
    if not 1 <= raster_width <= 32:
        raise QfaslError("FONT raster width is outside 1..32")
    if rasters_per_word != 32 // raster_width:
        raise QfaslError("FONT rasters-per-word is inconsistent with raster width")
    expected_words = (raster_height + rasters_per_word - 1) // rasters_per_word
    if words_per_character != expected_words:
        raise QfaslError("FONT words-per-character is inconsistent with raster height")

    widths = _optional_array(leader, 0o12, "ART-8B", 128, "character width")
    kerns = _optional_array(leader, 0o13, "ART-32B", 128, "left kern")
    indexes = _optional_array(leader, 0o14, "ART-16B", 129, "indexing")
    if leader.get(0o15) is not None:
        raise QfaslError("FONT next-plane pointer is unsupported")
    exists = _optional_array(leader, 0o20, "ART-1B", 128, "characters-exist")
    if indexes is not None:
        if indexes[0] != 0:
            raise QfaslError("FONT indexing table does not start at zero")
        if any(indexes[index] > indexes[index + 1] for index in range(128)):
            raise QfaslError("FONT indexing table is not monotonic")
    storage_characters = indexes[-1] if indexes is not None else 128
    if raster_order_profile is not None:
        observed_signature = {
            "indexing_table": indexes is not None,
            "raster_width": raster_width,
            "rasters_per_word": rasters_per_word,
        }
        if observed_signature != raster_order_profile["structural_signature"]:
            raise QfaslError(
                "reviewed raster-order structural signature changed: "
                f"{observed_signature}"
            )
    expected_raster_bits = 32 * words_per_character * storage_characters
    if array.length != expected_raster_bits:
        raise QfaslError(
            f"FONT raster has {array.length} bits, expected {expected_raster_bits}"
        )
    raster_bits = _normalize_serialized_raster_bits(
        array.values(), raster_order_profile
    )
    if array.initialization is None or len(array.initialization) % 2:
        raise QfaslError("FONT raster does not contain complete 32-bit words")
    raster_qs = [
        int(array.initialization[index])
        | (int(array.initialization[index + 1]) << 16)
        for index in range(0, len(array.initialization), 2)
    ]
    raster_q_bytes = b"".join(value.to_bytes(4, "big") for value in raster_qs)

    glyphs = []
    represented_codes = [
        code for code in range(128) if exists is None or exists[code] != 0
    ]
    for code in represented_codes:
        if indexes is None:
            bitmap_width = raster_width
        else:
            bitmap_width = (indexes[code + 1] - indexes[code]) * raster_width
        rows = []
        for row in range(raster_height):
            packed_row = 0
            for column in range(bitmap_width):
                storage_code = (
                    code
                    if indexes is None
                    else indexes[code] + column // raster_width
                )
                in_column = column % raster_width
                word_index = (
                    words_per_character * storage_code + row // rasters_per_word
                )
                bit_index = (
                    32 * word_index
                    + raster_width * (row % rasters_per_word)
                    + in_column
                )
                packed_row = (packed_row << 1) | raster_bits[bit_index]
            rows.append(packed_row)
        glyphs.append(
            Glyph(
                code=code,
                bitmap_width=bitmap_width,
                advance=widths[code] if widths is not None else fixed_width,
                x_offset=-(kerns[code] if kerns is not None else 0),
                y_offset=baseline - raster_height,
                rows=tuple(rows),
            )
        )

    leader_name = leader.get(0o2)
    serialized_leader_name = (
        leader_name.qualified_name if isinstance(leader_name, Symbol) else None
    )
    if raster_order_profile is None:
        raster_order_metadata = {
            "historical_screen_mode": None,
            "raster_order_reference": None,
            "serialized_raster_order": None,
            "display_raster_normalization": "none",
            "controller_mode_provenance": (
                "not encoded in the FONT leader; no artifact-specific "
                "raster-order override is assigned"
            ),
        }
    else:
        raster_order_metadata = {
            "historical_screen_mode": raster_order_profile[
                "historical_screen_mode"
            ],
            "raster_order_reference": (
                raster_order_profile["reference_compiler_entrypoint"]
                + " in pinned fcmp.66"
            ),
            "serialized_raster_order": raster_order_profile[
                "serialized_raster_order"
            ],
            "display_raster_normalization": raster_order_profile[
                "display_normalization"
            ],
            "controller_mode_provenance": (
                "reviewed as 16-bit screen order from the unique 16-pixel "
                "wide-font structural signature and pinned historical "
                "evidence; the later FCMP-16 entry point is the reference "
                "implementation, not a claimed 1978 invocation"
            ),
        }

    return BitmapFont(
        name=artifact_name,
        character_height=character_height,
        raster_height=raster_height,
        baseline=baseline,
        glyphs=tuple(glyphs),
        source_format="MIT CADR System 46 serialized QFASL FONT object",
        source_name=source_name,
        metadata={
            "runtime_name": symbol.name,
            "runtime_symbol": symbol.qualified_name,
            "serialized_leader_name": serialized_leader_name,
            "fixed_character_width": fixed_width,
            "raster_width": raster_width,
            "rasters_per_word": rasters_per_word,
            "words_per_character": words_per_character,
            "leader_length": max(leader, default=-1) + 1,
            "blinker_width": _require_int(leader, 0o16, "blinker width"),
            "blinker_height": _require_int(leader, 0o17, "blinker height"),
            "storage_character_count": storage_characters,
            "raster_q_count": len(raster_qs),
            "raster_q_sha256": hashlib.sha256(raster_q_bytes).hexdigest(),
            "character_width_table": widths is not None,
            "left_kern_table": kerns is not None,
            "indexing_table": indexes is not None,
            "next_plane_present": False,
            "characters_exist_table": exists is not None,
            "explicit_existing_code_count": (
                sum(value != 0 for value in exists) if exists is not None else None
            ),
            "explicit_existing_codes": (
                [code for code, value in enumerate(exists) if value != 0]
                if exists is not None
                else None
            ),
            "existence_semantics": (
                "explicit characters-exist table"
                if exists is not None
                else "no table; runtime treats all 128 character slots as existing"
            ),
            "bitmap_width_semantics": (
                "runtime storage/draw width; compiler padding is retained"
            ),
        }
        | raster_order_metadata,
    )


def _decode_bytes(
    raw: bytes,
    source_name: str,
    artifact_name: str,
    runtime_name: str,
    runtime_symbol: str | None = None,
    raster_order_profile: dict[str, object] | None = None,
) -> tuple[BitmapFont, FontQfaslParser, tuple[int, ...]]:
    words = tuple(evacuated_words(raw))
    nibbles = qfasl_nibbles(words)
    parser = FontQfaslParser(nibbles)
    bindings = parser.parse()
    font = font_from_binding(
        artifact_name,
        runtime_name,
        source_name,
        bindings,
        expected_runtime_symbol=runtime_symbol,
        raster_order_profile=raster_order_profile,
    )
    return font, parser, words


def _decode_file(
    path: Path,
    artifact_name: str,
    runtime_name: str,
    runtime_symbol: str | None = None,
    raster_order_profile: dict[str, object] | None = None,
) -> tuple[BitmapFont, FontQfaslParser, tuple[int, ...]]:
    return _decode_bytes(
        path.read_bytes(),
        path.name,
        artifact_name,
        runtime_name,
        runtime_symbol,
        raster_order_profile,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reviewed_bytes(
    path: Path, expected_size: int, expected_sha256: str
) -> bytes:
    if not path.is_file():
        raise QfaslError(f"missing reviewed input: {path}")
    raw = path.read_bytes()
    if len(raw) != expected_size:
        raise QfaslError(
            f"{path.name}: expected {expected_size} bytes, found {len(raw)}"
        )
    digest = _sha256(raw)
    if digest != expected_sha256:
        raise QfaslError(
            f"{path.name}: SHA-256 {digest} does not match reviewed input"
        )
    return raw


def _canonical_word_bytes(words: Iterable[int]) -> bytes:
    return b"".join(word.to_bytes(5, "big") for word in words)


def decode_reviewed_fonts(
    source: Path = DEFAULT_SOURCE,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> tuple[dict, tuple[DecodedRuntimeFont, ...]]:
    """Decode all closed-manifest inputs to inert in-memory font objects."""

    manifest, specs = load_runtime_manifest(manifest_path)
    raster_order_overrides = _validate_raster_order_overrides(manifest, specs)
    if not source.is_dir():
        raise QfaslError(f"runtime font source is not a directory: {source}")

    expected_files = {spec.source_file for spec in specs}
    observed_files = {
        path.name for path in source.glob("*.qfasl") if path.is_file()
    }
    if observed_files != expected_files:
        missing = sorted(expected_files - observed_files)
        extra = sorted(observed_files - expected_files)
        raise QfaslError(
            "runtime QFASL selection is not closed: "
            f"missing={missing}, extra={extra}"
        )

    license_record = manifest["license"]
    license_path = source.parent / "LICENSE"
    _reviewed_bytes(
        license_path,
        int(license_record["byte_size"]),
        str(license_record["sha256"]),
    )

    source_checkout = source.parent.parent
    for profile in raster_order_overrides.values():
        for evidence in profile["historical_evidence"]:
            relative = PurePosixPath(str(evidence["path"]))
            _reviewed_bytes(
                source_checkout.joinpath(*relative.parts),
                int(evidence["byte_size"]),
                str(evidence["sha256"]),
            )

    decoded = []
    for spec in specs:
        raster_order_profile = raster_order_overrides.get(spec.artifact_name)
        raw = _reviewed_bytes(
            source / spec.source_file,
            spec.byte_size,
            spec.sha256,
        )
        try:
            font, qfasl, words = _decode_bytes(
                raw,
                spec.source_file,
                spec.artifact_name,
                spec.runtime_name,
                spec.runtime_symbol,
                raster_order_profile,
            )
        except QfaslError as error:
            raise QfaslError(f"{spec.source_file}: {error}") from error

        canonical_words = _canonical_word_bytes(words)
        checkpoints = (
            len(words) == spec.decoded_pdp10_word_count,
            _sha256(canonical_words) == spec.decoded_pdp10_word_sha256,
            len(qfasl.nibbles) == spec.decoded_qfasl_nibble_count,
            qfasl.whack_count == spec.end_of_whack_count,
        )
        if not all(checkpoints):
            raise QfaslError(
                f"{spec.source_file}: decoded stream checkpoints changed"
            )

        font = BitmapFont(
            name=font.name,
            character_height=font.character_height,
            raster_height=font.raster_height,
            baseline=font.baseline,
            glyphs=font.glyphs,
            source_format=font.source_format,
            source_name=font.source_name,
            metadata=font.metadata
            | {
                "runtime_corpus_classification": spec.classification,
                "source_reference_artifact": spec.source_reference_artifact,
                "expected_source_relation": spec.expected_source_relation,
                "expected_source_relation_details": (
                    spec.expected_source_relation_details
                ),
                "runtime_source_sha256": spec.sha256,
                "runtime_source_revision": SOURCE_REVISION,
                "decoder_safety": (
                    "strict inert reviewed subset; no QFASL operation evaluated"
                ),
            },
        )
        if raster_order_profile is not None:
            _validate_reviewed_display_oracle(font, raster_order_profile)
        decoded.append(
            DecodedRuntimeFont(
                spec=spec,
                font=font,
                parser=qfasl,
                words=words,
                source_sha256=_sha256(raw),
            )
        )
    decoded_fonts = tuple(decoded)
    expected_inventories = manifest.get("semantic_inventories")
    if expected_inventories is not None:
        observed_inventories = runtime_semantic_inventory_digests(decoded_fonts)
        for name, observed in observed_inventories.items():
            if observed != expected_inventories[name]["sha256"]:
                raise QfaslError(
                    f"reviewed {name} semantic inventory changed: {observed}"
                )
    return manifest, decoded_fonts


def _semantic_glyph(glyph: Glyph) -> dict[str, object]:
    return {
        "code": glyph.code,
        "bitmap_width": glyph.bitmap_width,
        "advance": glyph.advance,
        "x_offset": glyph.x_offset,
        "y_offset": glyph.y_offset,
        "rows": list(glyph.rows),
    }


def _normalized_font_semantic_record(
    artifact_name: str, font: BitmapFont
) -> dict[str, object]:
    return {
        "artifact_name": artifact_name,
        "character_height": font.character_height,
        "raster_height": font.raster_height,
        "baseline": font.baseline,
        "glyphs": [
            _semantic_glyph(glyph)
            for glyph in sorted(font.glyphs, key=lambda glyph: glyph.code)
        ],
    }


def _validate_reviewed_display_oracle(
    font: BitmapFont, raster_order_profile: dict[str, object]
) -> None:
    oracle = raster_order_profile["reviewed_display_oracle"]
    visible_count = sum(any(glyph.rows) for glyph in font.glyphs)
    if visible_count != oracle["ink_bearing_glyph_count"]:
        raise QfaslError(
            f"{font.name}: reviewed ink-bearing glyph count changed: "
            f"{visible_count}"
        )
    observed = _semantic_digest(
        _normalized_font_semantic_record(font.name, font)
    )
    if observed != oracle["sha256"]:
        raise QfaslError(
            f"{font.name}: reviewed display geometry changed: {observed}"
        )


def _bdf_semantic_glyphs(font: BitmapFont) -> tuple[Glyph, ...]:
    """Mirror the shared writer's documented no-op placeholder policy."""

    return tuple(
        glyph
        for glyph in font.glyphs
        if not (
            glyph.advance == 0
            and glyph.bitmap_width == 0
            and not any(glyph.rows)
        )
    )


def runtime_normalized_semantic_inventory(
    decoded: Iterable[DecodedRuntimeFont],
) -> list[dict[str, object]]:
    """Canonical lossless runtime FONT geometry for regression oracles."""

    return [
        _normalized_font_semantic_record(item.spec.artifact_name, item.font)
        for item in sorted(decoded, key=lambda item: item.spec.artifact_name)
    ]


def runtime_bdf_semantic_inventory(
    decoded: Iterable[DecodedRuntimeFont],
) -> list[dict[str, object]]:
    """Canonical geometry represented by the installable BDF profile."""

    records = []
    for item in sorted(decoded, key=lambda item: item.spec.artifact_name):
        font = item.font
        glyphs = _bdf_semantic_glyphs(font)
        minimum_x = min(glyph.x_offset for glyph in glyphs)
        maximum_x = max(
            glyph.x_offset + glyph.bitmap_width for glyph in glyphs
        )
        minimum_y = min(glyph.y_offset for glyph in glyphs)
        maximum_y = max(glyph.y_offset + len(glyph.rows) for glyph in glyphs)
        records.append(
            {
                "artifact_name": item.spec.artifact_name,
                "size": font.character_height,
                "font_bounding_box": [
                    maximum_x - minimum_x,
                    maximum_y - minimum_y,
                    minimum_x,
                    minimum_y,
                ],
                "font_ascent": font.baseline,
                "font_descent": max(
                    0, font.character_height - font.baseline
                ),
                "glyphs": [_semantic_glyph(glyph) for glyph in glyphs],
            }
        )
    return records


def _semantic_digest(records: object) -> str:
    canonical = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(canonical)


def runtime_semantic_inventory_digests(
    decoded: Iterable[DecodedRuntimeFont],
) -> dict[str, str]:
    """Return independent reviewed-oracle digests for runtime and BDF geometry."""

    decoded = tuple(decoded)
    return {
        "normalized_runtime_font_geometry": _semantic_digest(
            runtime_normalized_semantic_inventory(decoded)
        ),
        "bdf_geometry": _semantic_digest(runtime_bdf_semantic_inventory(decoded)),
    }


def _runtime_add_style(spec: RuntimeArtifactSpec) -> str:
    if spec.classification == "legacy-compiled-version":
        return f"System 46 Legacy {spec.artifact_name}"
    return "System 46 Runtime"


def write_runtime_distribution(
    decoded: Iterable[DecodedRuntimeFont],
    *,
    font_identities: dict[str, object],
    manifest: dict,
    manifest_path: Path,
    source: Path,
    output: Path,
    clean: bool,
    sheet_columns: int,
    sheet_scale: int,
    include_json: bool = True,
) -> dict:
    """Write BDF/JSON/specimen outputs and a traceable runtime catalog."""

    owned = {
        "bdf",
        "json",
        "sheets",
        "catalog.json",
        "runtime-source-manifest.json",
        "LICENSE.source",
    }
    prepare_output_directory(output, clean=clean, owned_names=owned)

    decoded = tuple(decoded)
    records = []
    for item in decoded:
        spec = item.spec
        font = item.font
        logical_identity = resolve_font_identity(
            font_identities,
            profile="runtime",
            physical_assignment=spec.artifact_name,
            artifact_name=spec.artifact_name,
            measured_pixel_size=font.character_height,
            representation_style=_runtime_add_style(spec),
            runtime_name=spec.runtime_name,
            classification=spec.classification,
        )
        representation = logical_identity.pop("representation")
        profile = bdf_profile(font, **bdf_profile_arguments(logical_identity))
        outputs = write_font_outputs(
            font,
            output,
            foundry="Misc",
            sheet_columns=sheet_columns,
            sheet_scale=sheet_scale,
            include_json=include_json,
            sheet_label_radix=8,
            bdf_metadata=profile,
        )
        records.append(
            {
                "artifact_name": spec.artifact_name,
                "runtime_name": spec.runtime_name,
                "runtime_symbol": spec.runtime_symbol,
                "classification": spec.classification,
                "source_reference_artifact": spec.source_reference_artifact,
                "expected_source_relation": spec.expected_source_relation,
                "expected_source_relation_details": (
                    spec.expected_source_relation_details
                ),
                "raster_order_override": manifest[
                    "raster_order_overrides"
                ].get(spec.artifact_name),
                "source_file": f"src/lmfont/{spec.source_file}",
                "source_byte_size": spec.byte_size,
                "source_sha256": item.source_sha256,
                "decoded_pdp10_word_count": len(item.words),
                "decoded_pdp10_word_sha256": _sha256(
                    _canonical_word_bytes(item.words)
                ),
                "decoded_qfasl_nibble_count": len(item.parser.nibbles),
                "consumed_qfasl_nibble_count": item.parser.position,
                "padding_nibble_count": (
                    len(item.parser.nibbles) - item.parser.position
                ),
                "end_of_whack_count": item.parser.whack_count,
                "fasl_table_segment_count": item.parser.whack_count + 1,
                "opcode_counts": {
                    OPCODE_NAMES[opcode]: count
                    for opcode, count in sorted(
                        item.parser.opcode_counts.items()
                    )
                },
                "character_height": font.character_height,
                "raster_height": font.raster_height,
                "baseline": font.baseline,
                "glyph_count": len(font.glyphs),
                "logical_identity": logical_identity,
                "representation": representation,
                "observations": font.metadata,
                "bdf_profile": profile,
                "outputs": outputs,
            }
        )

    manifest_bytes = manifest_path.read_bytes()
    if json.loads(manifest_bytes) != manifest:
        raise QfaslError("runtime source manifest changed after decoding")
    license_path = source.parent / "LICENSE"
    shutil.copyfile(license_path, output / "LICENSE.source")
    shutil.copyfile(manifest_path, output / "runtime-source-manifest.json")

    classification_counts = dict(
        sorted(Counter(record["classification"] for record in records).items())
    )
    catalog = {
        "schema_version": 1,
        "method": (
            "strict non-evaluating decode of the reviewed System 46 font-QFASL "
            "object subset into runtime FONT arrays"
        ),
        "safety": (
            "serialized objects only; no Lisp form, machine instruction, or "
            "QFASL operation is evaluated"
        ),
        "display_layout_policy": {
            "bitmap": (
                "native one-bit runtime bitmap; no outline conversion, "
                "scaling, hinting, or synthesized pixels"
            ),
            "horizontal_placement": (
                "each glyph retains its runtime advance and fixed x bearing; "
                "no pair kerning or tracking is added"
            ),
            "system_46_sheet_default_vertical_spacing_pixels": 2,
            "system_46_mixed_font_line_map": (
                "maximum baseline and maximum character height across fonts "
                "in the sheet font map"
            ),
            "bdf_scope": (
                "encodes glyph bitmaps and metrics only; sheet-level vertical "
                "spacing and mixed-font line-map behavior remain application policy"
            ),
        },
        "xlfd_profile_policy": {
            "representation_add_style_name": "System 46 Runtime",
            "legacy_representation_add_style_name_pattern": (
                "System 46 Legacy <artifact>"
            ),
            "purpose": (
                "compose runtime provenance with reviewed logical family/face "
                "metadata and keep legacy versions distinct from current fonts"
            ),
        },
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": SOURCE_REVISION,
        "source_directory": "src/lmfont",
        "source_license": "src/LICENSE (BSD-3-Clause)",
        "source_license_copy": "LICENSE.source",
        "runtime_manifest": "runtime-source-manifest.json",
        "runtime_manifest_sha256": _sha256(manifest_bytes),
        "raster_order_overrides": manifest["raster_order_overrides"],
        "semantic_inventory_digests": runtime_semantic_inventory_digests(
            decoded
        ),
        "generator": {
            "path": "scripts/extract-cadr-qfasl-fonts.py",
            "sha256": _sha256(Path(__file__).read_bytes()),
            "shared_writer_path": "scripts/lisp_machine_fonts.py",
            "shared_writer_sha256": _sha256(
                (ROOT / "scripts" / "lisp_machine_fonts.py").read_bytes()
            ),
            "ancestor_repository": DECODER_ANCESTOR_REPOSITORY,
            "ancestor_revision": DECODER_ANCESTOR_REVISION,
            "ancestor_path": "scripts/extract-cadr-qfasl-fonts.py",
            "ancestor_sha256": DECODER_ANCESTOR_SHA256,
        },
        "artifact_count": len(records),
        "runtime_logical_name_count": len(
            {record["runtime_name"] for record in records}
        ),
        "classification_counts": classification_counts,
        "font_artifacts": records,
    }
    expected = manifest["expected"]
    if (
        catalog["artifact_count"] != expected["artifact_count"]
        or catalog["runtime_logical_name_count"]
        != expected["runtime_logical_name_count"]
        or classification_counts != expected["classification_counts"]
    ):
        raise QfaslError("generated runtime catalog counts changed")
    (output / "catalog.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return catalog


def positive_integer(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recover all 49 reviewed public MIT CADR runtime-font QFASLs "
            "without executing them."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_SOURCE,
        help="public System 46 src/lmfont (defaults to the pinned submodule)",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="closed runtime QFASL source manifest",
    )
    parser.add_argument(
        "--font-identities",
        type=Path,
        default=DEFAULT_FONT_IDENTITIES,
        help="closed reviewed logical-font identity mapping",
    )
    parser.add_argument("--sheet-columns", type=positive_integer, default=16)
    parser.add_argument("--sheet-scale", type=positive_integer, default=2)
    parser.add_argument(
        "--omit-json",
        action="store_true",
        help="omit per-font normalized JSON while retaining BDF/PNG/catalog",
    )
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    try:
        source = args.source.resolve()
        manifest_path = args.manifest.resolve()
        font_identities = load_font_identities(
            args.font_identities.resolve(),
            source_repository=source.parents[1],
        )
        manifest, decoded = decode_reviewed_fonts(source, manifest_path)
        catalog = write_runtime_distribution(
            decoded,
            font_identities=font_identities,
            manifest=manifest,
            manifest_path=manifest_path,
            source=source,
            output=args.output.resolve(),
            clean=args.clean,
            sheet_columns=args.sheet_columns,
            sheet_scale=args.sheet_scale,
            include_json=not args.omit_json,
        )
    except (OSError, QfaslError, ValueError) as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "artifact_count": catalog["artifact_count"],
                "runtime_logical_name_count": catalog[
                    "runtime_logical_name_count"
                ],
                "classification_counts": catalog["classification_counts"],
                "catalog": str(args.output.resolve() / "catalog.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.stderr.close()
