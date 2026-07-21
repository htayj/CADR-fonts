#!/usr/bin/env python3
"""Write or verify the tracked GitHub specimen gallery from a fresh build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from check_unicode_dist import UnicodeDistError, _glyph_visible, parse_bdf
from lisp_machine_fonts import prepare_output_directory


ROOT = Path(__file__).resolve().parents[1]
LATIN_CODES = frozenset((*range(0x41, 0x5B), *range(0x61, 0x7B)))
PROJECT_LICENSE_SHA256 = (
    "64b21e556cd37bb07b437113db1c8c98058b684705aacacd608564172723c449"
)
SOURCE_LICENSE_SHA256 = (
    "05b8de7c86c946cc747ab71a9aaa7dd56e37365278b5585ab685156eaa90fb92"
)


class GalleryError(RuntimeError):
    """The tracked gallery differs from the reviewed generated specimens."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GalleryError(f"{path}: expected a JSON object")
    return value


def _mapping_provenance(
    unicode_catalogs: dict[str, dict[str, object]],
) -> dict[str, str]:
    """Require both Unicode profiles to name the same reviewed identity map."""

    values: dict[str, tuple[object, object]] = {
        profile: (
            catalog.get("font_identity_mapping_id"),
            catalog.get("font_identity_mapping_sha256"),
        )
        for profile, catalog in unicode_catalogs.items()
    }
    source = values.get("source")
    runtime = values.get("runtime")
    if source is None or runtime is None or source != runtime:
        raise GalleryError(
            "Unicode source/runtime font-identity mapping provenance differs"
        )
    mapping_id, mapping_sha256 = source
    if not isinstance(mapping_id, str) or not mapping_id:
        raise GalleryError("Unicode catalogs lack a font-identity mapping ID")
    if not (
        isinstance(mapping_sha256, str)
        and len(mapping_sha256) == 64
        and all(character in "0123456789abcdef" for character in mapping_sha256)
    ):
        raise GalleryError("Unicode catalogs lack a valid font-identity mapping SHA-256")
    return {"id": mapping_id, "sha256": mapping_sha256}


def _validated_logical_identity(
    value: object,
    *,
    profile: str,
    artifact_name: str,
) -> dict[str, object]:
    """Validate the identity fields needed by the public gallery contract."""

    if not isinstance(value, dict):
        raise GalleryError(f"{profile}/{artifact_name}: logical identity is missing")
    status = value.get("mapping_status")
    if status not in {"mapped", "role-mapped", "unmapped"}:
        raise GalleryError(
            f"{profile}/{artifact_name}: invalid logical mapping status {status!r}"
        )
    logical_name = value.get("logical_name")
    if logical_name is not None and (
        not isinstance(logical_name, str) or not logical_name
    ):
        raise GalleryError(f"{profile}/{artifact_name}: invalid logical selector")
    if status == "mapped" and not isinstance(logical_name, str):
        raise GalleryError(f"{profile}/{artifact_name}: mapped identity lacks a selector")
    if status == "unmapped" and logical_name is not None:
        raise GalleryError(f"{profile}/{artifact_name}: unmapped identity has a selector")

    typography = value.get("typographic")
    if not isinstance(typography, dict):
        raise GalleryError(f"{profile}/{artifact_name}: logical typography is missing")
    family_name = typography.get("family_name")
    if not isinstance(family_name, str) or not family_name:
        raise GalleryError(f"{profile}/{artifact_name}: desktop family name is missing")

    return value


def _validated_representation(
    value: object,
    *,
    profile: str,
    artifact_name: str,
) -> dict[str, object]:
    """Validate the sibling physical-representation record."""

    representation = value
    if not isinstance(representation, dict):
        raise GalleryError(f"{profile}/{artifact_name}: representation is missing")
    if (
        representation.get("profile") != profile
        or representation.get("artifact_name") != artifact_name
    ):
        raise GalleryError(
            f"{profile}/{artifact_name}: representation physical identity differs"
        )
    style_name = representation.get("style_name")
    if not isinstance(style_name, str):
        raise GalleryError(f"{profile}/{artifact_name}: representation style is invalid")
    if profile == "runtime" and representation.get("classification") not in {
        "source-backed-current",
        "compiled-only",
        "legacy-compiled-version",
    }:
        raise GalleryError(
            f"{profile}/{artifact_name}: representation classification is invalid"
        )
    return representation


def logical_identity_label(identity: dict[str, object]) -> str:
    """Describe the reviewed selector without replacing physical identity."""

    status = identity.get("mapping_status")
    logical_name = identity.get("logical_name")
    typography = identity.get("typographic")
    if not isinstance(typography, dict):
        raise GalleryError("logical identity lacks typography")
    family_name = typography.get("family_name")
    if not isinstance(family_name, str) or not family_name:
        raise GalleryError("logical identity lacks a desktop family")
    if status == "unmapped":
        return f"{family_name} (unmapped)"
    if status == "role-mapped":
        parts: list[str] = []
        if logical_name is not None:
            if not isinstance(logical_name, str) or not logical_name:
                raise GalleryError("role-mapped identity has an invalid selector")
            primary = identity.get("primary")
            if not isinstance(primary, dict):
                raise GalleryError("role-mapped selector lacks primary metadata")
            character_set = primary.get("character_set")
            if not isinstance(character_set, str) or not character_set:
                raise GalleryError("role-mapped selector lacks a character set")
            parts.append(f"{logical_name} [{character_set}]")
        parts.append(f"{family_name} (role-mapped)")
        return " · ".join(parts)
    if status != "mapped" or not isinstance(logical_name, str) or not logical_name:
        raise GalleryError("mapped logical identity lacks a selector")
    return logical_name


def representation_label(representation: dict[str, object]) -> str:
    """Describe the authored/current/legacy representation on its own line."""

    profile = representation.get("profile")
    style_name = representation.get("style_name")
    if not isinstance(style_name, str):
        raise GalleryError("representation style is invalid")
    if profile == "source":
        return "Authored source" + (f" · {style_name}" if style_name else "")
    if profile != "runtime":
        raise GalleryError(f"invalid representation profile {profile!r}")
    classification = representation.get("classification")
    classification_labels = {
        "source-backed-current": "source-backed current object",
        "compiled-only": "compiled-only current object",
        "legacy-compiled-version": "legacy compiled version",
    }
    try:
        classification_label = classification_labels[classification]
    except KeyError as error:
        raise GalleryError(
            f"invalid runtime representation classification {classification!r}"
        ) from error
    base = style_name or "System 46 runtime"
    return f"{base} · {classification_label}"


def artifact_inventory(
    distribution: Path,
) -> tuple[list[dict[str, object]], str, dict[str, str]]:
    """Resolve specimens directly from the normal generated distribution."""

    build_manifest = load_json(distribution / "BUILD-MANIFEST.json")
    if build_manifest.get("schema_version") != 2:
        raise GalleryError("unsupported BUILD-MANIFEST schema")

    raw_catalogs = {
        "source": load_json(distribution / "catalog.json"),
        "runtime": load_json(distribution / "runtime" / "catalog.json"),
    }
    unicode_catalogs = {
        profile: load_json(distribution / "unicode" / profile / "catalog.json")
        for profile in ("source", "runtime")
    }
    identity_mapping = _mapping_provenance(unicode_catalogs)
    raw_records = {
        "source": {
            str(record["name"]): record
            for record in raw_catalogs["source"]["fonts"]
        },
        "runtime": {
            str(record["artifact_name"]): record
            for record in raw_catalogs["runtime"]["font_artifacts"]
        },
    }

    artifacts: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for profile in ("source", "runtime"):
        raw_root = distribution if profile == "source" else distribution / "runtime"
        unicode_root = distribution / "unicode" / profile
        for record in unicode_catalogs[profile]["font_artifacts"]:
            name = str(record["artifact_name"])
            identity = (profile, name)
            if identity in identities:
                raise GalleryError(f"duplicate artifact identity: {profile}/{name}")
            identities.add(identity)
            raw_record = raw_records[profile].get(name)
            if raw_record is None:
                raise GalleryError(f"{profile}/{name}: raw catalog record missing")
            logical_identity = _validated_logical_identity(
                record.get("logical_identity"),
                profile=profile,
                artifact_name=name,
            )
            representation = _validated_representation(
                record.get("representation"),
                profile=profile,
                artifact_name=name,
            )
            if raw_record.get("logical_identity") != logical_identity:
                raise GalleryError(
                    f"{profile}/{name}: raw and Unicode logical identities differ"
                )
            if raw_record.get("representation") != representation:
                raise GalleryError(
                    f"{profile}/{name}: raw and Unicode representations differ"
                )
            label_key = "logical_name" if profile == "source" else "runtime_name"
            if record.get(label_key) != raw_record.get(label_key):
                raise GalleryError(
                    f"{profile}/{name}: raw and Unicode {label_key} values differ"
                )
            if representation.get(label_key) != record.get(label_key):
                raise GalleryError(
                    f"{profile}/{name}: representation {label_key} differs"
                )
            if profile == "runtime" and (
                record.get("classification") != raw_record.get("classification")
                or representation.get("classification") != record.get("classification")
            ):
                raise GalleryError(
                    f"{profile}/{name}: runtime classification metadata differs"
                )

            unicode_bdf = unicode_root / str(record["unicode_bdf"])
            if sha256_file(unicode_bdf) != record["unicode_bdf_sha256"]:
                raise GalleryError(f"{profile}/{name}: Unicode BDF hash drift")
            glyphs = parse_bdf(unicode_bdf)["glyphs"]
            content_class = (
                "latin"
                if any(code in glyphs and _glyph_visible(glyphs[code]) for code in LATIN_CODES)
                else "symbols"
            )
            has_pangram = "pangram_specimen" in record
            if has_pangram != (content_class == "latin"):
                raise GalleryError(
                    f"{profile}/{name}: current Latin and pangram partitions differ"
                )
            if has_pangram:
                specimen_kind = "unicode-pangram"
                specimen = unicode_root / str(record["pangram_specimen"]["path"])
                if sha256_file(specimen) != record["pangram_specimen"]["sha256"]:
                    raise GalleryError(f"{profile}/{name}: pangram specimen hash drift")
            else:
                specimen_kind = "raw-glyph-sheet"
                specimen = raw_root / str(raw_record["outputs"]["sheet"])
            if not specimen.is_file():
                raise GalleryError(f"{profile}/{name}: specimen missing: {specimen}")
            artifacts.append(
                {
                    "content_class": content_class,
                    "profile": profile,
                    "name": name,
                    "record": record,
                    "raw_record": raw_record,
                    "specimen_kind": specimen_kind,
                    "specimen_path": specimen,
                }
            )

    if len(artifacts) != 200:
        raise GalleryError(f"specimen inventory has {len(artifacts)} artifacts")
    if len(identities) != len(artifacts):
        raise GalleryError("specimen artifact identities are not unique")
    source_revision = build_manifest.get("source_revision")
    if not isinstance(source_revision, str):
        raise GalleryError("BUILD-MANIFEST source revision is missing")
    return artifacts, source_revision, identity_mapping


def specimen_manifest_record(
    artifact: dict[str, object],
    *,
    relative: str,
    specimen_sha256: str,
) -> dict[str, object]:
    """Build one additive manifest record without collapsing its artifact key."""

    profile = str(artifact["profile"])
    record_data = artifact["record"]
    raw_record = artifact["raw_record"]
    label_key = "logical_name" if profile == "source" else "runtime_name"
    logical_identity = record_data["logical_identity"]
    record: dict[str, object] = {
        "content_class": artifact["content_class"],
        "profile": profile,
        "artifact_name": artifact["name"],
        label_key: record_data[label_key],
        "logical_identity": logical_identity,
        "representation": record_data["representation"],
        "specimen_kind": artifact["specimen_kind"],
        "path": relative,
        "sha256": specimen_sha256,
    }
    if profile == "source":
        record["variant_of"] = raw_record.get("variant_of")
    else:
        record["classification"] = record_data["classification"]
    if artifact["specimen_kind"] == "unicode-pangram":
        record["text"] = record_data["pangram_specimen"]["text"]
    return record


def build_gallery(distribution: Path) -> tuple[dict[str, bytes], bytes, bytes]:
    artifacts, source_revision, identity_mapping = artifact_inventory(
        distribution.resolve()
    )
    project_license = ROOT / "LICENSE"
    tracked_license = ROOT / "LICENSE.source"
    generated_license = distribution / "LICENSE.source"
    if (
        sha256_file(project_license) != PROJECT_LICENSE_SHA256
        or sha256_file(tracked_license) != SOURCE_LICENSE_SHA256
        or tracked_license.read_bytes() != generated_license.read_bytes()
    ):
        raise GalleryError("tracked project/source license closure differs")
    image_files: dict[str, bytes] = {}
    records: list[dict[str, object]] = []

    for artifact in sorted(
        artifacts,
        key=lambda item: (
            item["content_class"],
            item["profile"],
            str(item["name"]).casefold(),
            item["name"],
        ),
    ):
        relative = (
            Path(str(artifact["content_class"]))
            / str(artifact["profile"])
            / Path(artifact["specimen_path"]).name
        ).as_posix()
        if relative in image_files:
            raise GalleryError(f"specimen destination collision: {relative}")
        data = Path(artifact["specimen_path"]).read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise GalleryError(
                f"generated specimen is not PNG: {artifact['specimen_path']}"
            )
        image_files[relative] = data
        records.append(
            specimen_manifest_record(
                artifact,
                relative=relative,
                specimen_sha256=sha256_bytes(data),
            )
        )

    counts = {
        content_class: {
            profile: sum(
                record["content_class"] == content_class
                and record["profile"] == profile
                for record in records
            )
            for profile in ("source", "runtime")
        }
        for content_class in ("latin", "symbols")
    }
    if counts != {
        "latin": {"source": 118, "runtime": 42},
        "symbols": {"source": 33, "runtime": 7},
    }:
        raise GalleryError(f"specimen selection changed: {counts}")

    manifest = {
        "schema_version": 1,
        "source_revision": source_revision,
        "font_identity_mapping_id": identity_mapping["id"],
        "font_identity_mapping_sha256": identity_mapping["sha256"],
        "project_license": {
            "path": "LICENSE",
            "sha256": PROJECT_LICENSE_SHA256,
        },
        "source_license": {
            "path": "LICENSE.source",
            "sha256": SOURCE_LICENSE_SHA256,
        },
        "selection": {
            "latin": (
                "at least one visible emitted Unicode BDF glyph in "
                "U+0041-U+005A or U+0061-U+007A"
            ),
            "symbols": "closed complement of the Latin artifact set",
        },
        "counts": {
            "total": len(records),
            "latin": sum(record["content_class"] == "latin" for record in records),
            "symbols": sum(record["content_class"] == "symbols" for record in records),
            "profiles": counts,
        },
        "specimens": records,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    lines = [
        "# CADR font specimens",
        "",
        "<!-- Generated by scripts/update_specimen_gallery.py; do not edit by hand. -->",
        "",
        "These are the exact one-bit specimens generated from the pinned CADR source",
        "and reviewed System 46 runtime fonts. They let GitHub visitors inspect every",
        "published artifact without installing it. The Latin collection uses the",
        "Lisp-themed pangram; the symbols collection uses complete raw-code glyph",
        "sheets because those repertoires are not sentences.",
        "",
        "Repository-authored gallery tooling, metadata, and documentation use the project",
        "[BSD-3-Clause license](LICENSE). The recovered bitmap payload and direct",
        "specimens retain the pinned upstream [source license](LICENSE.source).",
        "",
        "Gallery grouping is content-derived: a font is Latin when at least one",
        "visible emitted Unicode glyph is a Basic Latin letter; `symbols` is the",
        "closed complement. See [the Unicode mapping](docs/UNICODE.md) and",
        "[font model](docs/FONT-MODEL.md).",
        "Artifact names remain the physical source/runtime identities. Each entry",
        "shows its reviewed logical selector separately from its authored, current",
        "runtime, or legacy runtime representation.",
        "",
    ]
    for content_class, title in (("latin", "Latin fonts"), ("symbols", "Symbols and drawing fonts")):
        total = sum(record["content_class"] == content_class for record in records)
        lines.extend([f"## {title} ({total})", ""])
        for profile, profile_title in (("source", "Authored source profile"), ("runtime", "System 46 runtime profile")):
            selected = [
                record
                for record in records
                if record["content_class"] == content_class
                and record["profile"] == profile
            ]
            lines.extend([f"### {profile_title} ({len(selected)})", ""])
            for record in selected:
                identity_key = "logical_name" if profile == "source" else "runtime_name"
                identity = str(record[identity_key])
                artifact_name = str(record["artifact_name"])
                suffix = "" if identity == artifact_name else f" — `{identity}`"
                path = f"specimens/{record['path']}"
                logical_label = logical_identity_label(record["logical_identity"])
                physical_label = representation_label(record["representation"])
                lines.extend(
                    [
                        f"#### `{artifact_name}`{suffix}",
                        "",
                        f"**Logical selector:** `{logical_label}`",
                        "",
                        f"**Representation:** `{physical_label}`",
                        "",
                        f"![{artifact_name} {content_class} {profile} specimen]({path})",
                        "",
                    ]
                )
    markdown_bytes = ("\n".join(lines).rstrip() + "\n").encode("utf-8")
    return image_files, manifest_bytes, markdown_bytes


def check_gallery(
    output: Path,
    markdown: Path,
    image_files: dict[str, bytes],
    manifest_bytes: bytes,
    markdown_bytes: bytes,
) -> None:
    expected = set(image_files) | {"MANIFEST.json"}
    observed = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    } if output.is_dir() else set()
    if observed != expected:
        raise GalleryError(
            f"tracked specimen file set differs: missing={sorted(expected - observed)}, "
            f"unexpected={sorted(observed - expected)}"
        )
    expected_bytes = {**image_files, "MANIFEST.json": manifest_bytes}
    changed = [
        name for name, data in expected_bytes.items() if (output / name).read_bytes() != data
    ]
    if changed:
        raise GalleryError(f"tracked specimens changed: {changed}")
    if not markdown.is_file() or markdown.read_bytes() != markdown_bytes:
        raise GalleryError(f"tracked gallery Markdown differs: {markdown}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, default=ROOT / "specimens")
    parser.add_argument("--markdown", type=Path, default=ROOT / "SPECIMENS.md")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        images, manifest, markdown = build_gallery(args.distribution)
        if args.check:
            check_gallery(args.output, args.markdown, images, manifest, markdown)
        else:
            prepare_output_directory(
                args.output,
                clean=True,
                owned_names={"latin", "symbols", "MANIFEST.json"},
            )
            for relative, data in images.items():
                destination = args.output / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            (args.output / "MANIFEST.json").write_bytes(manifest)
            args.markdown.write_bytes(markdown)
    except (OSError, ValueError, GalleryError, UnicodeDistError) as error:
        parser.error(str(error))
    action = "verified" if args.check else "wrote"
    print(f"{action} {len(images)} tracked CADR font specimens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
