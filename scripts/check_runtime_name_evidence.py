#!/usr/bin/env python3
"""Reproduce the three runtime FONT bindings with the pinned inert parser."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "source-manifest.json"
SOURCE = ROOT / "sources" / "mit-cadr-system-software"
DEFAULT_PARSER = ROOT.parent / "genera-emu" / "scripts" / "extract-cadr-qfasl-fonts.py"


class EvidenceError(AssertionError):
    """Pinned QFASL name evidence does not reproduce."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_qfasl_parser(path: Path, expected_sha256: str):
    if not path.is_file():
        raise EvidenceError(f"pinned inert QFASL parser is missing: {path}")
    observed = digest(path.read_bytes())
    if observed != expected_sha256:
        raise EvidenceError(
            f"QFASL parser hash changed: expected={expected_sha256}, observed={observed}"
        )
    specification = importlib.util.spec_from_file_location(
        "_cadr_runtime_name_qfasl_parser", path
    )
    if specification is None or specification.loader is None:
        raise EvidenceError(f"cannot load QFASL parser module from {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parser", type=Path, default=DEFAULT_PARSER)
    args = parser.parse_args()

    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        findings = manifest["reviewed_findings"]
        parser_record = findings["runtime_name_qfasl_parser"]
        qfasl = load_qfasl_parser(
            args.parser.resolve(), parser_record["sha256"]
        )
        if qfasl.SOURCE_REVISION != manifest["revision"]:
            raise EvidenceError("QFASL parser targets a different source revision")

        results = []
        for logical_name, record in sorted(
            findings["runtime_name_qfasl_evidence"].items()
        ):
            path = SOURCE / record["path"]
            raw = path.read_bytes()
            if len(raw) != record["byte_size"] or digest(raw) != record["sha256"]:
                raise EvidenceError(f"QFASL witness changed for {logical_name}")
            words = qfasl.evacuated_words(raw)
            canonical_words = b"".join(word.to_bytes(5, "big") for word in words)
            if len(words) != record["decoded_pdp10_word_count"] or digest(
                canonical_words
            ) != record["decoded_pdp10_word_sha256"]:
                raise EvidenceError(f"PDP-10 word decode changed for {logical_name}")
            nibbles = qfasl.qfasl_nibbles(words)
            decoded = qfasl.FontQfaslParser(nibbles)
            bindings = decoded.parse()
            symbol, _font_array = qfasl._serialized_font_binding(bindings)
            if symbol.qualified_name != record["runtime_name"]:
                raise EvidenceError(
                    f"runtime binding changed for {logical_name}: "
                    f"{symbol.qualified_name}"
                )
            if (
                len(nibbles) != record["decoded_qfasl_nibble_count"]
                or decoded.position != len(nibbles)
                or decoded.whack_count != record["end_of_whack_count"]
            ):
                raise EvidenceError(f"QFASL consumption changed for {logical_name}")
            results.append(
                {
                    "logical_name": logical_name,
                    "binding": symbol.qualified_name,
                    "pdp10_word_count": len(words),
                    "qfasl_nibble_count": len(nibbles),
                }
            )
    except (EvidenceError, KeyError, OSError, ValueError) as error:
        parser.error(str(error))

    print(json.dumps({"status": "ok", "bindings": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
