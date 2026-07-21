#!/usr/bin/env python3
"""Independently validate the two closed CADR Fonts release archives."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import struct
import tarfile


ROOT = Path(__file__).resolve().parents[1]
LATIN_CODES = frozenset((*range(0x41, 0x5B), *range(0x61, 0x7B)))
EXPECTED = {
    "latin": {
        "source": (118, 12_237, 209),
        "runtime": (42, 5_084, 86),
        "artifacts": 160,
        "files": 657,
        "aliases": 590,
        "runtime_classes": {
            "compiled-only": 14,
            "legacy-compiled-version": 1,
            "source-backed-current": 27,
        },
    },
    "symbols": {
        "source": (33, 2_381, 63),
        "runtime": (7, 605, 13),
        "artifacts": 40,
        "files": 177,
        "aliases": 152,
        "runtime_classes": {
            "compiled-only": 3,
            "legacy-compiled-version": 1,
            "source-backed-current": 3,
        },
    },
}


class ReleaseDistError(AssertionError):
    """A release asset violates the reviewed split or file contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseDistError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _parse_bdf(data: bytes, label: str) -> dict[str, object]:
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise ReleaseDistError(f"{label}: BDF is not ASCII") from error
    fonts = [line[5:] for line in lines if line.startswith("FONT ")]
    declarations = [line for line in lines if line.startswith("CHARS ")]
    require(len(fonts) == 1, f"{label}: expected one FONT")
    require(len(declarations) == 1, f"{label}: expected one CHARS")
    try:
        declared = int(declarations[0].split()[1])
    except (IndexError, ValueError) as error:
        raise ReleaseDistError(f"{label}: malformed CHARS") from error
    encodings: set[int] = set()
    visible: set[int] = set()
    index = 0
    while index < len(lines):
        if not lines[index].startswith("STARTCHAR "):
            index += 1
            continue
        try:
            end = lines.index("ENDCHAR", index + 1)
        except ValueError as error:
            raise ReleaseDistError(f"{label}: unterminated glyph") from error
        block = lines[index : end + 1]
        encoding_lines = [line for line in block if line.startswith("ENCODING ")]
        require(len(encoding_lines) == 1, f"{label}: malformed ENCODING")
        try:
            encoding = int(encoding_lines[0].split()[1])
            bitmap_index = block.index("BITMAP")
            has_ink = any(int(row, 16) for row in block[bitmap_index + 1 : -1])
        except (IndexError, ValueError) as error:
            raise ReleaseDistError(f"{label}: malformed glyph") from error
        require(encoding >= 0, f"{label}: unencoded release glyph")
        require(encoding not in encodings, f"{label}: duplicate U+{encoding:04X}")
        encodings.add(encoding)
        if has_ink:
            visible.add(encoding)
        index = end + 1
    require(len(encodings) == declared, f"{label}: CHARS count mismatch")
    return {
        "xlfd": fonts[0],
        "glyph_count": declared,
        "codes": encodings,
        "visible": visible,
        "class": "latin" if visible & LATIN_CODES else "symbols",
    }


def _parse_indexes(
    files: dict[str, bytes], directory: str, expected_files: set[str], label: str
) -> int:
    dir_path = f"{directory}/fonts.dir"
    alias_path = f"{directory}/fonts.alias"
    require(dir_path in files and alias_path in files, f"{label}: missing X indexes")
    dir_lines = files[dir_path].decode("ascii").splitlines()
    require(bool(dir_lines), f"{label}: empty fonts.dir")
    try:
        declared = int(dir_lines[0])
    except ValueError as error:
        raise ReleaseDistError(f"{label}: malformed fonts.dir count") from error
    entries: dict[str, str] = {}
    for line in dir_lines[1:]:
        try:
            filename, xlfd = line.split(" ", 1)
        except ValueError as error:
            raise ReleaseDistError(f"{label}: malformed fonts.dir") from error
        require(filename not in entries, f"{label}: duplicate fonts.dir filename")
        entries[filename] = xlfd
    require(declared == len(entries), f"{label}: fonts.dir count mismatch")
    require(set(entries) == expected_files, f"{label}: fonts.dir is not closed")

    aliases: dict[str, str] = {}
    for line in files[alias_path].decode("ascii").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("!"):
            continue
        try:
            fields = shlex.split(stripped)
        except ValueError as error:
            raise ReleaseDistError(f"{label}: malformed fonts.alias") from error
        require(len(fields) == 2, f"{label}: malformed fonts.alias")
        name, target = fields
        require(name not in aliases, f"{label}: duplicate alias")
        require(target in set(entries.values()), f"{label}: dangling alias target")
        aliases[name] = target
    return len(aliases)


def _read_archive(path: Path) -> tuple[list[tarfile.TarInfo], dict[str, bytes]]:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            files: dict[str, bytes] = {}
            names: set[str] = set()
            for member in members:
                require(
                    member.name not in names,
                    f"{path}: duplicate archive member {member.name!r}",
                )
                names.add(member.name)
                member_path = PurePosixPath(member.name)
                require(
                    not member_path.is_absolute() and ".." not in member_path.parts,
                    f"{path}: unsafe archive path {member.name!r}",
                )
                require(
                    member.isdir() or member.isfile(),
                    f"{path}: links and special files are forbidden",
                )
                if member.isfile():
                    stream = archive.extractfile(member)
                    require(stream is not None, f"{path}: unreadable {member.name}")
                    files[member.name] = stream.read()
            return members, files
    except (OSError, tarfile.TarError) as error:
        raise ReleaseDistError(f"cannot read {path}: {error}") from error


def check_archive(path: Path, content_class: str) -> dict[str, object]:
    expected = EXPECTED[content_class]
    sidecar = path.with_name(f"{path.name}.sha256")
    require(sidecar.is_file(), f"{path}: missing external checksum")
    expected_sidecar = f"{file_digest(path)}  {path.name}\n"
    require(
        sidecar.read_text(encoding="ascii") == expected_sidecar,
        f"{path}: external checksum differs",
    )
    raw_gzip = path.read_bytes()
    require(raw_gzip[:2] == b"\x1f\x8b", f"{path}: not gzip")
    gzip_mtime = struct.unpack("<I", raw_gzip[4:8])[0]
    members, archived_files = _read_archive(path)
    require(bool(members), f"{path}: empty archive")
    root = f"CADR-fonts-{content_class}-"
    roots = {PurePosixPath(member.name).parts[0] for member in members}
    require(len(roots) == 1, f"{path}: expected one archive root")
    root_name = next(iter(roots))
    require(root_name.startswith(root), f"{path}: wrong archive root {root_name}")
    version = root_name.removeprefix(root)
    require(path.name == f"{root_name}.tar.gz", f"{path}: filename/root mismatch")
    names = [member.name for member in members]
    require(names == sorted(names), f"{path}: tar members are not sorted")

    relative_files = {
        str(PurePosixPath(name).relative_to(root_name)): data
        for name, data in archived_files.items()
    }
    require(
        "RELEASE-MANIFEST.json" in relative_files and "SHA256SUMS" in relative_files,
        f"{path}: release metadata missing",
    )
    try:
        manifest = json.loads(relative_files["RELEASE-MANIFEST.json"])
    except json.JSONDecodeError as error:
        raise ReleaseDistError(f"{path}: malformed RELEASE-MANIFEST") from error
    require(manifest["schema_version"] == 1, f"{path}: manifest schema changed")
    require(manifest["name"] == root_name, f"{path}: manifest name changed")
    require(manifest["version"] == version, f"{path}: manifest version changed")
    require(
        manifest["content_class"] == content_class,
        f"{path}: manifest class changed",
    )
    epoch = int(manifest["source_date_epoch"])
    require(gzip_mtime == epoch, f"{path}: gzip timestamp differs from manifest")
    for member in members:
        require(
            (member.uid, member.gid, member.uname, member.gname)
            == (0, 0, "", ""),
            f"{path}:{member.name}: non-reproducible ownership",
        )
        require(member.mtime == epoch, f"{path}:{member.name}: timestamp drift")
        require(
            member.mode == (0o755 if member.isdir() else 0o644),
            f"{path}:{member.name}: mode drift",
        )

    checksum_lines = relative_files["SHA256SUMS"].decode("ascii").splitlines()
    checksums: dict[str, str] = {}
    for line in checksum_lines:
        fields = line.split("  ", 1)
        require(len(fields) == 2, f"{path}: malformed internal checksum")
        checksum, name = fields
        require(name not in checksums, f"{path}: duplicate internal checksum")
        checksums[name] = checksum
    covered = set(relative_files) - {"SHA256SUMS"}
    require(set(checksums) == covered, f"{path}: internal checksum set is not closed")
    for name in sorted(covered):
        require(checksums[name] == digest(relative_files[name]), f"{path}:{name}: hash drift")

    artifacts = manifest["artifacts"]
    require(len(artifacts) == expected["artifacts"], f"{path}: artifact count changed")
    identities: set[tuple[str, str]] = set()
    desktop_identities: dict[tuple[object, ...], tuple[str, str]] = {}
    glyph_counts = Counter()
    runtime_classes = Counter()
    expected_paths = {
        "README.release.md",
        "LICENSE.project",
        "LICENSE.source",
        "RELEASE-MANIFEST.json",
        "SHA256SUMS",
        "metadata/FONT-IDENTITIES.json",
        "metadata/SOURCE-MANIFEST.json",
        "metadata/runtime-source-manifest.json",
        "metadata/UNICODE-MAPPING.json",
    }
    require(
        expected_paths <= set(relative_files),
        f"{path}: required release files are missing",
    )
    try:
        font_identities = json.loads(relative_files["metadata/FONT-IDENTITIES.json"])
    except json.JSONDecodeError as error:
        raise ReleaseDistError(f"{path}: malformed font-identity mapping") from error
    require(
        isinstance(font_identities, dict)
        and font_identities.get("schema_version") == 1,
        f"{path}: unsupported font-identity mapping",
    )
    identity_mapping_id = font_identities.get("mapping_id")
    require(
        isinstance(identity_mapping_id, str) and identity_mapping_id,
        f"{path}: font-identity mapping ID is missing",
    )
    identity_assignments = font_identities.get("assignments")
    require(
        isinstance(identity_assignments, dict),
        f"{path}: font-identity assignments are missing",
    )
    source_assignments = identity_assignments.get("source_logical_names")
    runtime_assignments = identity_assignments.get("runtime_artifacts")
    require(
        isinstance(source_assignments, dict) and isinstance(runtime_assignments, dict),
        f"{path}: font-identity physical assignments are missing",
    )
    identity_digest = digest(relative_files["metadata/FONT-IDENTITIES.json"])
    source_distribution = manifest.get("source_distribution")
    require(
        isinstance(source_distribution, dict),
        f"{path}: source-distribution provenance is missing",
    )
    require(
        source_distribution.get("font_identities")
        == {
            "path": "FONT-IDENTITIES.json",
            "id": identity_mapping_id,
            "sha256": identity_digest,
        },
        f"{path}: source font-identity provenance differs",
    )
    metadata_names = {
        "FONT-IDENTITIES.json",
        "SOURCE-MANIFEST.json",
        "runtime-source-manifest.json",
        "UNICODE-MAPPING.json",
    }
    metadata = manifest.get("metadata")
    require(
        isinstance(metadata, dict) and set(metadata) == metadata_names,
        f"{path}: release metadata set changed",
    )
    for name in sorted(metadata_names):
        packaged_path = f"metadata/{name}"
        record = metadata[name]
        require(isinstance(record, dict), f"{path}:{packaged_path}: malformed record")
        require(
            record.get("path") == packaged_path
            and record.get("sha256") == digest(relative_files[packaged_path]),
            f"{path}:{packaged_path}: metadata provenance differs",
        )
    license_sources = {
        "project": ("LICENSE.project", ROOT / "LICENSE"),
        "source": ("LICENSE.source", ROOT / "LICENSE.source"),
    }
    licenses = manifest.get("licenses")
    require(isinstance(licenses, dict), f"{path}: license manifest missing")
    require(set(licenses) == set(license_sources), f"{path}: license set changed")
    for key, (archive_name, repository_path) in license_sources.items():
        require(repository_path.is_file(), f"{path}: repository license missing")
        require(archive_name in relative_files, f"{path}:{archive_name}: license missing")
        expected_bytes = repository_path.read_bytes()
        require(
            relative_files[archive_name] == expected_bytes,
            f"{path}:{archive_name}: license text differs from repository",
        )
        record = licenses[key]
        require(isinstance(record, dict), f"{path}:{key}: malformed license record")
        require(record["path"] == archive_name, f"{path}:{key}: license path changed")
        require(
            record["spdx"] == "BSD-3-Clause",
            f"{path}:{key}: license identifier changed",
        )
        require(
            record["sha256"] == digest(expected_bytes),
            f"{path}:{key}: license hash changed",
        )
        require(
            isinstance(record.get("applies_to"), str) and record["applies_to"],
            f"{path}:{key}: license scope missing",
        )
    readme = relative_files["README.release.md"].decode("utf-8")
    require(
        "LICENSE.project" in readme and "LICENSE.source" in readme,
        f"{path}: release README does not explain both licenses",
    )
    index_expectations: list[tuple[str, str, set[str], int]] = []
    for profile in ("source", "runtime"):
        selected = [record for record in artifacts if record["profile"] == profile]
        artifact_count, glyph_count, alias_count = expected[profile]
        require(len(selected) == artifact_count, f"{path}: {profile} count changed")
        raw_names: set[str] = set()
        unicode_names: set[str] = set()
        for record in selected:
            identity = (profile, str(record["artifact_name"]))
            require(identity not in identities, f"{path}: duplicate artifact identity")
            identities.add(identity)
            logical_identity = record.get("logical_identity")
            representation = record.get("representation")
            require(
                isinstance(logical_identity, dict),
                f"{path}:{identity}: logical identity is missing",
            )
            require(
                isinstance(representation, dict),
                f"{path}:{identity}: representation is missing",
            )
            require(
                "representation" not in logical_identity,
                f"{path}:{identity}: representation is nested in logical identity",
            )
            typographic = logical_identity.get("typographic")
            require(
                isinstance(typographic, dict)
                and isinstance(typographic.get("family_name"), str)
                and bool(typographic["family_name"]),
                f"{path}:{identity}: logical typography is malformed",
            )
            require(
                representation.get("profile") == profile
                and representation.get("artifact_name") == identity[1],
                f"{path}:{identity}: representation physical identity differs",
            )
            if profile == "source":
                logical_name = str(record["logical_name"])
                require(
                    representation.get("logical_name") == logical_name,
                    f"{path}:{identity}: representation logical name differs",
                )
                assigned_logical_id = source_assignments.get(logical_name)
            else:
                runtime_name = str(record["runtime_name"])
                classification = str(record["classification"])
                require(
                    representation.get("runtime_name") == runtime_name
                    and representation.get("classification") == classification,
                    f"{path}:{identity}: representation runtime identity differs",
                )
                assigned_logical_id = runtime_assignments.get(identity[1])
            require(
                assigned_logical_id == logical_identity.get("logical_id"),
                f"{path}:{identity}: configured logical assignment differs",
            )
            desktop_identity = (
                typographic.get("family_name"),
                typographic.get("weight_name"),
                typographic.get("slant"),
                typographic.get("setwidth_name"),
                typographic.get("add_style_name"),
                logical_identity.get("measured_pixel_size"),
            )
            require(
                all(value is not None for value in desktop_identity),
                f"{path}:{identity}: desktop identity is incomplete",
            )
            require(
                desktop_identity not in desktop_identities,
                f"{path}: desktop identity collision between "
                f"{desktop_identities.get(desktop_identity)} and {identity}",
            )
            desktop_identities[desktop_identity] = identity
            if profile == "runtime":
                runtime_classes[str(record["classification"])] += 1
            files = record["files"]
            required_file_keys = {"raw_bdf", "unicode_bdf", "otb", "specimen"}
            require(set(files) == required_file_keys, f"{path}:{identity}: file map changed")
            for file_record in files.values():
                packaged_path = str(file_record["path"])
                require(packaged_path in relative_files, f"{path}: missing {packaged_path}")
                require(
                    file_record["sha256"] == digest(relative_files[packaged_path]),
                    f"{path}:{packaged_path}: manifest hash changed",
                )
                expected_paths.add(packaged_path)
            raw_path = str(files["raw_bdf"]["path"])
            unicode_path = str(files["unicode_bdf"]["path"])
            otb_path = str(files["otb"]["path"])
            require(
                raw_path.startswith(f"fonts/raw/{profile}/")
                and unicode_path.startswith(f"fonts/unicode/{profile}/")
                and otb_path.startswith(f"fonts/otb/{profile}/"),
                f"{path}:{identity}: profile path escaped",
            )
            require(
                PurePosixPath(raw_path).stem
                == PurePosixPath(unicode_path).stem
                == PurePosixPath(otb_path).stem,
                f"{path}:{identity}: font-format basenames differ",
            )
            raw_names.add(PurePosixPath(raw_path).name)
            unicode_names.add(PurePosixPath(unicode_path).name)
            raw_bdf = _parse_bdf(relative_files[raw_path], f"{path}:{raw_path}")
            unicode_bdf = _parse_bdf(
                relative_files[unicode_path], f"{path}:{unicode_path}"
            )
            require(
                raw_bdf["glyph_count"]
                == unicode_bdf["glyph_count"]
                == record["glyph_count"],
                f"{path}:{identity}: glyph count differs",
            )
            require(
                unicode_bdf["class"] == content_class,
                f"{path}:{identity}: content classification differs",
            )
            require(
                raw_bdf["xlfd"] == record["raw_xlfd_name"]
                and unicode_bdf["xlfd"] == record["unicode_xlfd_name"],
                f"{path}:{identity}: XLFD differs",
            )
            require(
                str(raw_bdf["xlfd"]).endswith("-Misc-FontSpecific"),
                f"{path}:{identity}: raw BDF lost its historical encoding label",
            )
            require(
                str(unicode_bdf["xlfd"]).endswith("-ISO10646-1"),
                f"{path}:{identity}: usable BDF is not Unicode encoded",
            )
            glyph_counts[profile] += int(record["glyph_count"])
        require(glyph_counts[profile] == glyph_count, f"{path}: {profile} glyph total")
        for encoding, names in (("raw", raw_names), ("unicode", unicode_names)):
            directory = f"fonts/{encoding}/{profile}"
            expected_paths.update({f"{directory}/fonts.dir", f"{directory}/fonts.alias"})
            index_expectations.append((encoding, profile, names, alias_count))

    alias_total = 0
    for encoding, profile, names, expected_aliases in index_expectations:
        count = _parse_indexes(
            relative_files,
            f"fonts/{encoding}/{profile}",
            names,
            f"{path}:{encoding}/{profile}",
        )
        require(count == expected_aliases, f"{path}: {encoding}/{profile} alias count")
        alias_total += count
    require(alias_total == expected["aliases"], f"{path}: total alias count changed")
    require(
        dict(sorted(runtime_classes.items())) == expected["runtime_classes"],
        f"{path}: runtime classification closure changed",
    )
    require(set(relative_files) == expected_paths, f"{path}: release file set is not closed")
    require(len(relative_files) == expected["files"], f"{path}: file count changed")
    counts = manifest["counts"]
    require(counts["artifact_count"] == expected["artifacts"], f"{path}: stale manifest")
    require(counts["total_file_count"] == expected["files"], f"{path}: stale file count")
    require(counts["alias_count"] == expected["aliases"], f"{path}: stale alias count")
    return {
        "archive": str(path),
        "version": version,
        "content_class": content_class,
        "artifact_count": len(artifacts),
        "glyph_count": sum(glyph_counts.values()),
        "file_count": len(relative_files),
        "alias_count": alias_total,
    }


def check_release_directory(directory: Path) -> list[dict[str, object]]:
    expected_names: set[str] = set()
    archives: dict[str, Path] = {}
    for content_class in EXPECTED:
        matches = sorted(directory.glob(f"CADR-fonts-{content_class}-*.tar.gz"))
        require(len(matches) == 1, f"{directory}: expected one {content_class} archive")
        archives[content_class] = matches[0]
        expected_names.update({matches[0].name, f"{matches[0].name}.sha256"})
    observed_names = {path.name for path in directory.iterdir()}
    require(observed_names == expected_names, f"{directory}: release asset set is not closed")
    results = [
        check_archive(archives[content_class], content_class)
        for content_class in EXPECTED
    ]
    require(
        len({str(result["version"]) for result in results}) == 1,
        "release archives have different versions",
    )
    identities = []
    desktop_identities: dict[tuple[object, ...], tuple[str, str, str]] = {}
    for content_class, archive_path in archives.items():
        _members, files = _read_archive(archive_path)
        root = next(iter({PurePosixPath(name).parts[0] for name in files}))
        manifest = json.loads(files[f"{root}/RELEASE-MANIFEST.json"])
        for record in manifest["artifacts"]:
            release_identity = (
                content_class,
                str(record["profile"]),
                str(record["artifact_name"]),
            )
            identities.append(release_identity)
            logical_identity = record.get("logical_identity")
            require(
                isinstance(logical_identity, dict),
                f"{archive_path}:{release_identity}: logical identity is missing",
            )
            typographic = logical_identity.get("typographic")
            require(
                isinstance(typographic, dict),
                f"{archive_path}:{release_identity}: logical typography is missing",
            )
            desktop_identity = (
                typographic.get("family_name"),
                typographic.get("weight_name"),
                typographic.get("slant"),
                typographic.get("setwidth_name"),
                typographic.get("add_style_name"),
                logical_identity.get("measured_pixel_size"),
            )
            require(
                desktop_identity not in desktop_identities,
                "combined release desktop identity collision between "
                f"{desktop_identities.get(desktop_identity)} and {release_identity}",
            )
            desktop_identities[desktop_identity] = release_identity
    require(len(identities) == 200, "combined release does not contain 200 artifacts")
    unclassified = [(profile, name) for _class, profile, name in identities]
    require(len(set(unclassified)) == 200, "release archives overlap artifact identities")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        results = check_release_directory(args.release_dir.resolve())
    except (OSError, ReleaseDistError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"status": "ok", "archives": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
