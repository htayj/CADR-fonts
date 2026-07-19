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


def artifact_inventory(distribution: Path) -> tuple[list[dict[str, object]], str]:
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
    return artifacts, source_revision


def build_gallery(distribution: Path) -> tuple[dict[str, bytes], bytes, bytes]:
    artifacts, source_revision = artifact_inventory(distribution.resolve())
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
        profile = str(artifact["profile"])
        record_data = artifact["record"]
        label_key = "logical_name" if profile == "source" else "runtime_name"
        record: dict[str, object] = {
            "content_class": artifact["content_class"],
            "profile": profile,
            "artifact_name": artifact["name"],
            label_key: record_data[label_key],
            "specimen_kind": artifact["specimen_kind"],
            "path": relative,
            "sha256": sha256_bytes(data),
        }
        if artifact["specimen_kind"] == "unicode-pangram":
            record["text"] = record_data["pangram_specimen"]["text"]
        records.append(record)

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
                lines.extend(
                    [
                        f"#### `{artifact_name}`{suffix}",
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
