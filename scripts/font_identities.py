#!/usr/bin/env python3
"""Closed logical-font identities for the recovered MIT CADR font corpus.

Physical source artifacts, source variants, and resident runtime objects remain
separate records.  This module resolves those records to a reviewed logical
family/face/size identity and composes a distinct desktop representation style
without deriving typography from an opaque filename at build time.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FONT_IDENTITIES = ROOT / "config" / "font-identities.json"
SOURCE_REPOSITORY = ROOT / "sources" / "mit-cadr-system-software"


class FontIdentityError(ValueError):
    """The logical-font mapping is malformed or not closed over the corpus."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FontIdentityError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _exact_keys(value: object, keys: set[str], context: str) -> dict[str, object]:
    require(isinstance(value, dict), f"{context}: expected an object")
    observed = set(value)
    require(
        observed == keys,
        f"{context}: schema keys differ; missing={sorted(keys - observed)}, "
        f"unexpected={sorted(observed - keys)}",
    )
    return value


def _string(
    value: object,
    context: str,
    *,
    allow_empty: bool = False,
    limit: int = 512,
) -> str:
    require(isinstance(value, str), f"{context}: expected a string")
    require(allow_empty or bool(value), f"{context}: empty string")
    require(len(value) <= limit, f"{context}: string is too long")
    require(all(character.isprintable() for character in value), f"{context}: non-printable text")
    return value


def _integer(value: object, context: str, *, minimum: int = 0) -> int:
    require(type(value) is int, f"{context}: expected an integer")
    result = int(value)
    require(result >= minimum, f"{context}: value is below {minimum}")
    return result


def _sha256(value: object, context: str) -> str:
    require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{context}: expected a lowercase SHA-256",
    )
    return value


def _safe_source_path(value: object, context: str) -> str:
    relative = _string(value, context, limit=256)
    path = Path(relative)
    require(
        not path.is_absolute()
        and path.as_posix() == relative
        and "\\" not in relative
        and "." not in path.parts
        and ".." not in path.parts,
        f"{context}: unsafe path",
    )
    return relative


def _join_style(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part)


def _desktop_field(value: object) -> str:
    """Normalize one value exactly as an XLFD text field is normalized."""

    return " ".join(
        "".join(
            " " if character in '-?*,"\\' else character
            for character in str(value)
        ).split()
    )


def load_font_identities(
    path: Path = DEFAULT_FONT_IDENTITIES,
    *,
    verify_evidence: bool = True,
    source_repository: Path = SOURCE_REPOSITORY,
) -> dict[str, object]:
    """Load, schema-check, and optionally verify the pinned evidence mapping.

    ``source_repository`` must be the same checkout or hash-closed snapshot
    used for extraction.  Keeping it explicit prevents an alternate source
    build from accidentally verifying evidence in the default submodule.
    """

    try:
        mapping = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FontIdentityError(f"cannot read {path}: {error}") from error
    mapping = _exact_keys(
        mapping,
        {
            "schema_version",
            "mapping_id",
            "profile",
            "source",
            "policy",
            "families",
            "faces",
            "logical_identities",
            "assignments",
            "desktop_style_disambiguators",
            "expected",
        },
        "font identities",
    )
    require(mapping["schema_version"] == 1, "unsupported font-identity schema")
    _string(mapping["mapping_id"], "font identities.mapping_id", limit=128)
    _string(mapping["profile"], "font identities.profile", limit=160)

    source = _exact_keys(
        mapping["source"],
        {"repository", "revision", "evidence"},
        "font identities.source",
    )
    _string(source["repository"], "font identities.source.repository", limit=256)
    revision = _string(source["revision"], "font identities.source.revision", limit=40)
    require(
        len(revision) == 40
        and all(character in "0123456789abcdef" for character in revision),
        "font identities.source.revision: invalid Git commit",
    )
    evidence = source["evidence"]
    require(isinstance(evidence, dict) and evidence, "font identities.source.evidence is empty")
    for evidence_id, value in evidence.items():
        _string(evidence_id, "font evidence ID", limit=96)
        record = _exact_keys(
            value, {"path", "sha256", "scope"}, f"font evidence {evidence_id}"
        )
        relative = _safe_source_path(record["path"], f"font evidence {evidence_id}.path")
        digest = _sha256(record["sha256"], f"font evidence {evidence_id}.sha256")
        _string(record["scope"], f"font evidence {evidence_id}.scope")
        if verify_evidence:
            evidence_path = source_repository / relative
            require(evidence_path.is_file(), f"font evidence is missing: {relative}")
            require(sha256(evidence_path) == digest, f"font evidence changed: {relative}")
    if verify_evidence and (source_repository / ".git").exists():
        # The superproject already pins this submodule.  Avoid invoking Git here;
        # build.py independently verifies the exact revision before extraction.
        require(bool(revision), "font identity source revision is missing")

    policy = _exact_keys(
        mapping["policy"],
        {
            "physical_identity",
            "logical_identity",
            "desktop_identity",
            "representation_identity",
            "size_identity",
            "specialty_identity",
            "uncertainty",
        },
        "font identities.policy",
    )
    for key, value in policy.items():
        _string(value, f"font identities.policy.{key}")

    families = mapping["families"]
    require(isinstance(families, dict) and families, "font identities.families is empty")
    desktop_names: set[str] = set()
    for family_id, value in families.items():
        _string(family_id, "font family ID", limit=64)
        record = _exact_keys(
            value,
            {"family_name", "kind", "confidence"},
            f"font family {family_id}",
        )
        family_name = _string(
            record["family_name"], f"font family {family_id}.family_name", limit=128
        )
        require(
            record["kind"] in {"text", "specialty", "unmapped"},
            f"font family {family_id}: invalid kind",
        )
        require(
            record["confidence"] in {"direct", "inferred", "neutral"},
            f"font family {family_id}: invalid confidence",
        )
        require(family_name not in desktop_names, f"duplicate desktop family: {family_name}")
        desktop_names.add(family_name)

    faces = mapping["faces"]
    require(isinstance(faces, dict) and faces, "font identities.faces is empty")
    for face_id, value in faces.items():
        _string(face_id, "font face ID", limit=64)
        record = _exact_keys(
            value,
            {"weight_name", "slant", "setwidth_name", "add_style_name"},
            f"font face {face_id}",
        )
        require(
            record["weight_name"] in {"Medium", "Bold", "Unknown"},
            f"font face {face_id}: unsupported weight",
        )
        require(record["slant"] in {"R", "I", "OT"}, f"font face {face_id}: invalid slant")
        require(
            record["setwidth_name"] in {"Condensed", "Normal", "Expanded", "Unknown"},
            f"font face {face_id}: unsupported set width",
        )
        _string(
            record["add_style_name"],
            f"font face {face_id}.add_style_name",
            allow_empty=True,
            limit=64,
        )

    logical_identities = mapping["logical_identities"]
    require(
        isinstance(logical_identities, dict) and logical_identities,
        "font identities.logical_identities is empty",
    )
    status_counts: Counter[str] = Counter()
    primary_count = 0
    used_families: set[str] = set()
    for logical_id, value in logical_identities.items():
        _string(logical_id, "logical font ID", limit=64)
        record = _exact_keys(
            value,
            {"mapping_status", "primary", "typographic_family", "typographic_face"},
            f"logical font {logical_id}",
        )
        status = record["mapping_status"]
        require(
            status in {"mapped", "role-mapped", "unmapped"},
            f"logical font {logical_id}: invalid mapping status",
        )
        status_counts[str(status)] += 1
        family_id = record["typographic_family"]
        face_id = record["typographic_face"]
        require(family_id in families, f"logical font {logical_id}: unknown family")
        require(face_id in faces, f"logical font {logical_id}: unknown face")
        used_families.add(str(family_id))
        if status == "unmapped":
            require(
                families[family_id]["kind"] == "unmapped",
                f"logical font {logical_id}: unmapped status needs an unmapped family",
            )
        else:
            require(
                families[family_id]["kind"] != "unmapped",
                f"logical font {logical_id}: mapped status uses an unmapped family",
            )
        primary = record["primary"]
        if primary is not None:
            primary_count += 1
            selector = _exact_keys(
                primary,
                {"family", "face", "size", "named_size", "character_set"},
                f"logical font {logical_id}.primary",
            )
            require(selector["family"] in families, f"logical font {logical_id}: unknown primary family")
            require(selector["face"] in faces, f"logical font {logical_id}: unknown primary face")
            require(selector["face"] == face_id, f"logical font {logical_id}: primary face differs")
            size = selector["size"]
            named_size = selector["named_size"]
            require(
                (size is None) != (named_size is None),
                f"logical font {logical_id}: specify exactly one numeric or named size",
            )
            if size is not None:
                _integer(size, f"logical font {logical_id}.primary.size", minimum=1)
            if named_size is not None:
                _string(named_size, f"logical font {logical_id}.primary.named_size", limit=64)
            _string(selector["character_set"], f"logical font {logical_id}.primary.character_set", limit=64)
            if status == "mapped":
                require(
                    selector["family"] == family_id,
                    f"logical font {logical_id}: primary and desktop family differ",
                )
        require(
            status != "mapped" or primary is not None,
            f"logical font {logical_id}: mapped identity lacks a primary selector",
        )
        require(
            status != "unmapped" or primary is None,
            f"logical font {logical_id}: unmapped identity has a primary selector",
        )

    assignments = _exact_keys(
        mapping["assignments"],
        {"source_logical_names", "runtime_artifacts"},
        "font identities.assignments",
    )
    for profile_key in ("source_logical_names", "runtime_artifacts"):
        profile_assignments = assignments[profile_key]
        require(isinstance(profile_assignments, dict), f"{profile_key}: expected an object")
        for physical_id, logical_id in profile_assignments.items():
            _string(physical_id, f"{profile_key} key", limit=64)
            require(
                logical_id in logical_identities,
                f"{profile_key}/{physical_id}: unknown logical identity {logical_id!r}",
            )
    used_logical = set(assignments["source_logical_names"].values()) | set(
        assignments["runtime_artifacts"].values()
    )
    require(
        used_logical == set(logical_identities),
        "logical identities are unused or absent from physical assignments",
    )

    disambiguators = _exact_keys(
        mapping["desktop_style_disambiguators"],
        {"source_artifacts", "runtime_artifacts"},
        "font identities.desktop_style_disambiguators",
    )
    for profile_key in ("source_artifacts", "runtime_artifacts"):
        values = disambiguators[profile_key]
        require(isinstance(values, dict), f"desktop disambiguators.{profile_key}: expected object")
        for artifact, qualifier in values.items():
            _string(artifact, f"desktop disambiguators.{profile_key} key", limit=96)
            _string(qualifier, f"desktop disambiguator for {profile_key}/{artifact}", limit=64)

    expected = _exact_keys(
        mapping["expected"],
        {
            "logical_identity_count",
            "source_logical_name_count",
            "runtime_artifact_count",
            "mapped_logical_identity_count",
            "role_mapped_logical_identity_count",
            "unmapped_logical_identity_count",
            "primary_selector_count",
            "typographic_family_count",
            "desktop_style_disambiguator_count",
        },
        "font identities.expected",
    )
    for key, value in expected.items():
        _integer(value, f"font identities.expected.{key}")
    observed = {
        "logical_identity_count": len(logical_identities),
        "source_logical_name_count": len(assignments["source_logical_names"]),
        "runtime_artifact_count": len(assignments["runtime_artifacts"]),
        "mapped_logical_identity_count": status_counts["mapped"],
        "role_mapped_logical_identity_count": status_counts["role-mapped"],
        "unmapped_logical_identity_count": status_counts["unmapped"],
        "primary_selector_count": primary_count,
        "typographic_family_count": len(used_families),
        "desktop_style_disambiguator_count": sum(
            len(disambiguators[key]) for key in disambiguators
        ),
    }
    require(expected == observed, f"font identity expected counts differ: observed={observed}")
    require(len(used_families) == len(families), "typographic family registry is not closed")
    return mapping


def validate_assignment_closure(
    mapping: dict[str, object],
    *,
    source_logical_names: Iterable[str],
    runtime_artifacts: Iterable[tuple[str, str]],
) -> None:
    """Require exact physical corpus closure and runtime-name cross-checks."""

    assignments = mapping["assignments"]
    source_names = set(source_logical_names)
    require(
        set(assignments["source_logical_names"]) == source_names,
        "font identities are not closed over source logical names",
    )
    runtime_items = tuple(runtime_artifacts)
    runtime = dict(runtime_items)
    require(
        len(runtime) == len(runtime_items),
        "duplicate runtime artifact passed to identity closure",
    )
    require(
        set(assignments["runtime_artifacts"]) == set(runtime),
        "font identities are not closed over runtime artifacts",
    )
    for artifact, runtime_name in runtime.items():
        logical_id = assignments["runtime_artifacts"][artifact]
        require(
            logical_id == runtime_name,
            f"runtime assignment {artifact}->{logical_id} differs from serialized name {runtime_name}",
        )


def resolve_font_identity(
    mapping: dict[str, object],
    *,
    profile: str,
    physical_assignment: str,
    artifact_name: str,
    measured_pixel_size: int,
    representation_style: str = "",
    logical_name: str | None = None,
    runtime_name: str | None = None,
    classification: str | None = None,
) -> dict[str, object]:
    """Resolve one physical artifact to logical typography and representation."""

    require(profile in {"source", "runtime"}, f"invalid identity profile: {profile}")
    _integer(measured_pixel_size, "measured pixel size", minimum=1)
    assignment_key = "source_logical_names" if profile == "source" else "runtime_artifacts"
    try:
        logical_id = mapping["assignments"][assignment_key][physical_assignment]
        assignment = mapping["logical_identities"][logical_id]
        family = mapping["families"][assignment["typographic_family"]]
        face = mapping["faces"][assignment["typographic_face"]]
    except KeyError as error:
        raise FontIdentityError(
            f"{profile}/{physical_assignment}: missing logical-font assignment"
        ) from error
    disambiguator_key = "source_artifacts" if profile == "source" else "runtime_artifacts"
    disambiguator = mapping["desktop_style_disambiguators"][disambiguator_key].get(
        artifact_name
    )
    add_style = _desktop_field(
        _join_style(
            disambiguator,
            face["add_style_name"],
            representation_style,
        )
    )
    primary = assignment["primary"]
    selector = None
    nominal_design_size: int | str | None = None
    if primary is not None:
        size_label = (
            str(primary["size"])
            if primary["size"] is not None
            else str(primary["named_size"])
        )
        selector = "/".join((primary["family"], primary["face"], size_label))
        nominal_design_size = (
            int(primary["size"])
            if primary["size"] is not None
            else str(primary["named_size"])
        )
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
    return {
        "mapping_status": assignment["mapping_status"],
        "logical_id": logical_id,
        "logical_name": selector,
        "primary": dict(primary) if primary is not None else None,
        "nominal_design_size": nominal_design_size,
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
            "add_style_name": add_style,
        },
        "representation": representation,
    }


def bdf_profile_arguments(identity: dict[str, object]) -> dict[str, object]:
    """Return reviewed bdf_profile keyword arguments for one resolved identity."""

    typography = identity["typographic"]
    return {
        "foundry": "MIT",
        "family_name": typography["family_name"],
        "add_style_name": typography["add_style_name"],
        "weight_name": typography["weight_name"],
        "slant": typography["slant"],
        "setwidth_name": typography["setwidth_name"],
        "typographic_classification_policy": (
            "reviewed CADR logical-font identity mapping; nominal design size "
            "is recorded separately from recovered raster line height"
        ),
    }


def verify_desktop_identity_uniqueness(
    records: Iterable[tuple[str, dict[str, object]]],
) -> int:
    """Reject physical strikes that desktop clients cannot distinguish."""

    seen: dict[tuple[object, ...], str] = {}
    count = 0
    for label, identity in records:
        typography = identity["typographic"]
        key = (
            typography["family_name"],
            typography["weight_name"],
            typography["slant"],
            typography["setwidth_name"],
            typography["add_style_name"],
            identity["measured_pixel_size"],
        )
        require(
            key not in seen,
            f"desktop font identity collision: {seen.get(key)} and {label}",
        )
        seen[key] = label
        count += 1
    return count
