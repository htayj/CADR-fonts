#!/usr/bin/env python3
"""Independent expectations for generated CADR logical-font metadata.

This checker intentionally does not import the build-time identity resolver.
It derives the expected catalog and BDF fields directly from the distributed
closed mapping so a generator/resolver regression cannot validate itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRACKED_MAPPING = ROOT / "config" / "font-identities.json"


class IdentityCheckError(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IdentityCheckError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_distributed_mapping(output: Path) -> dict[str, object]:
    distributed = output / "FONT-IDENTITIES.json"
    require(distributed.is_file(), "distribution lacks FONT-IDENTITIES.json")
    require(
        distributed.read_bytes() == TRACKED_MAPPING.read_bytes(),
        "distributed font identities differ from the tracked mapping",
    )
    mapping = json.loads(distributed.read_text(encoding="utf-8"))
    require(mapping.get("schema_version") == 1, "unsupported font-identity schema")
    require(isinstance(mapping.get("mapping_id"), str), "font-identity mapping ID missing")
    return mapping


def _style(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part)


def _desktop_field(value: object) -> str:
    return " ".join(
        "".join(
            " " if character in '-?*,"\\' else character
            for character in str(value)
        ).split()
    )


def expected_record(
    mapping: dict[str, object],
    *,
    profile: str,
    assignment_key: str,
    artifact_name: str,
    measured_pixel_size: int,
    representation_style: str,
    logical_name: str | None = None,
    runtime_name: str | None = None,
    classification: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Independently derive expected logical and representation records."""

    assignment_table = (
        mapping["assignments"]["source_logical_names"]
        if profile == "source"
        else mapping["assignments"]["runtime_artifacts"]
    )
    logical_id = assignment_table[assignment_key]
    assignment = mapping["logical_identities"][logical_id]
    family = mapping["families"][assignment["typographic_family"]]
    face = mapping["faces"][assignment["typographic_face"]]
    disambiguators = mapping["desktop_style_disambiguators"][
        "source_artifacts" if profile == "source" else "runtime_artifacts"
    ]
    disambiguator = disambiguators.get(artifact_name)
    primary = assignment["primary"]
    selector = None
    nominal_size: int | str | None = None
    if primary is not None:
        nominal_size = (
            int(primary["size"])
            if primary["size"] is not None
            else str(primary["named_size"])
        )
        selector = "/".join(
            (str(primary["family"]), str(primary["face"]), str(nominal_size))
        )
    identity = {
        "mapping_status": assignment["mapping_status"],
        "logical_id": logical_id,
        "logical_name": selector,
        "primary": dict(primary) if primary is not None else None,
        "nominal_design_size": nominal_size,
        "measured_pixel_size": measured_pixel_size,
        "desktop_style_disambiguator": disambiguator,
        "typographic": {
            "family_name": family["family_name"],
            "family_kind": family["kind"],
            "confidence": family["confidence"],
            "weight_name": face["weight_name"],
            "slant": face["slant"],
            "setwidth_name": face["setwidth_name"],
            "base_add_style_name": face["add_style_name"],
            "add_style_name": _desktop_field(
                _style(
                    disambiguator,
                    face["add_style_name"],
                    representation_style,
                )
            ),
        },
    }
    representation: dict[str, object] = {
        "profile": profile,
        "artifact_name": artifact_name,
        "style_name": representation_style,
    }
    if profile == "source":
        representation["logical_name"] = logical_name
    else:
        representation["runtime_name"] = runtime_name
        representation["classification"] = classification
    return identity, representation


def expected_source_record(
    mapping: dict[str, object], record: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    style = (
        ""
        if record["variant_of"] is None
        else str(record["observations"]["variant_source_format"])
    )
    return expected_record(
        mapping,
        profile="source",
        assignment_key=str(record["logical_name"]),
        artifact_name=str(record["name"]),
        measured_pixel_size=int(record["character_height"]),
        representation_style=style,
        logical_name=str(record["logical_name"]),
    )


def expected_runtime_record(
    mapping: dict[str, object], record: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    artifact = str(record["artifact_name"])
    style = (
        f"System 46 Legacy {artifact}"
        if record["classification"] == "legacy-compiled-version"
        else "System 46 Runtime"
    )
    return expected_record(
        mapping,
        profile="runtime",
        assignment_key=artifact,
        artifact_name=artifact,
        measured_pixel_size=int(record["character_height"]),
        representation_style=style,
        runtime_name=str(record["runtime_name"]),
        classification=str(record["classification"]),
    )


def check_catalog_record(
    record: dict[str, object],
    expected: tuple[dict[str, object], dict[str, object]],
    *,
    context: str,
) -> dict[str, object]:
    identity, representation = expected
    require(record.get("logical_identity") == identity, f"{context}: logical identity differs")
    require(record.get("representation") == representation, f"{context}: representation differs")
    return identity


def check_bdf_profile(
    profile: dict[str, object],
    identity: dict[str, object],
    *,
    context: str,
) -> None:
    typography = identity["typographic"]
    require(profile["foundry"] == "MIT", f"{context}: foundry differs")
    for profile_key, identity_key in (
        ("family_name", "family_name"),
        ("weight_name", "weight_name"),
        ("slant", "slant"),
        ("setwidth_name", "setwidth_name"),
        ("add_style_name", "add_style_name"),
    ):
        require(
            profile[profile_key] == typography[identity_key],
            f"{context}: {profile_key} differs from logical identity",
        )
