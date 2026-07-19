#!/usr/bin/env python3
"""Build deterministic, content-partitioned CADR font release archives."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CONTENT_CLASSES = ("latin", "symbols")
LATIN_CODES = frozenset((*range(0x41, 0x5B), *range(0x61, 0x7B)))
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._+~-]+$")

# These are release boundaries, not values used to choose artifacts.  Selection
# is recomputed from the emitted ISO10646 BDFs before these reviewed counts are
# checked.
EXPECTED = {
    "latin": {
        "source": {
            "artifact_count": 118,
            "glyph_count": 12_237,
            "standard_glyph_count": 11_399,
            "private_use_glyph_count": 838,
            "alias_count": 209,
        },
        "runtime": {
            "artifact_count": 42,
            "glyph_count": 5_084,
            "standard_glyph_count": 4_355,
            "private_use_glyph_count": 729,
            "alias_count": 86,
        },
        "runtime_classification_counts": {
            "compiled-only": 14,
            "legacy-compiled-version": 1,
            "source-backed-current": 27,
        },
    },
    "symbols": {
        "source": {
            "artifact_count": 33,
            "glyph_count": 2_381,
            "standard_glyph_count": 0,
            "private_use_glyph_count": 2_381,
            "alias_count": 63,
        },
        "runtime": {
            "artifact_count": 7,
            "glyph_count": 605,
            "standard_glyph_count": 0,
            "private_use_glyph_count": 605,
            "alias_count": 13,
        },
        "runtime_classification_counts": {
            "compiled-only": 3,
            "legacy-compiled-version": 1,
            "source-backed-current": 3,
        },
    },
}


class ReleaseError(RuntimeError):
    """The requested release would not be a closed reviewed distribution."""


@dataclass(frozen=True)
class BdfSummary:
    xlfd: str
    glyph_count: int
    visible_codes: frozenset[int]

    @property
    def content_class(self) -> str:
        return "latin" if self.visible_codes & LATIN_CODES else "symbols"


@dataclass(frozen=True)
class Artifact:
    profile: str
    record: dict[str, object]
    raw_record: dict[str, object]
    raw_path: Path
    unicode_path: Path
    raw_summary: BdfSummary
    unicode_summary: BdfSummary
    content_class: str
    specimen_path: Path
    specimen_kind: str

    @property
    def name(self) -> str:
        return str(self.record["artifact_name"])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"cannot read {path}: {error}") from error
    require(isinstance(value, dict), f"{path}: expected a JSON object")
    return value


def read_bdf_summary(path: Path) -> BdfSummary:
    """Read the identity and visible encoded glyphs needed for release selection."""

    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        raise ReleaseError(f"cannot read BDF {path}: {error}") from error

    fonts = [line.removeprefix("FONT ") for line in lines if line.startswith("FONT ")]
    declarations = [line for line in lines if line.startswith("CHARS ")]
    require(len(fonts) == 1, f"{path}: expected exactly one FONT declaration")
    require(len(declarations) == 1, f"{path}: expected exactly one CHARS declaration")
    try:
        declared_count = int(declarations[0].split()[1])
    except (IndexError, ValueError) as error:
        raise ReleaseError(f"{path}: malformed CHARS declaration") from error

    encodings: set[int] = set()
    visible: set[int] = set()
    index = 0
    while index < len(lines):
        if not lines[index].startswith("STARTCHAR "):
            index += 1
            continue
        start = index
        try:
            end = lines.index("ENDCHAR", start + 1)
        except ValueError as error:
            raise ReleaseError(f"{path}:{start + 1}: unterminated glyph") from error
        block = lines[start : end + 1]
        encoding_lines = [line for line in block if line.startswith("ENCODING ")]
        require(len(encoding_lines) == 1, f"{path}:{start + 1}: malformed ENCODING")
        try:
            encoding = int(encoding_lines[0].split()[1])
        except (IndexError, ValueError) as error:
            raise ReleaseError(f"{path}:{start + 1}: malformed ENCODING") from error
        require(encoding >= 0, f"{path}:{start + 1}: unencoded glyph in release BDF")
        require(encoding not in encodings, f"{path}: duplicate encoding {encoding}")
        encodings.add(encoding)
        try:
            bitmap_start = block.index("BITMAP") + 1
        except ValueError as error:
            raise ReleaseError(f"{path}:{start + 1}: glyph lacks BITMAP") from error
        bitmap_rows = block[bitmap_start:-1]
        try:
            has_ink = any(int(row, 16) != 0 for row in bitmap_rows)
        except ValueError as error:
            raise ReleaseError(f"{path}:{start + bitmap_start + 1}: malformed bitmap") from error
        if has_ink:
            visible.add(encoding)
        index = end + 1

    require(
        len(encodings) == declared_count,
        f"{path}: CHARS declares {declared_count}, parsed {len(encodings)}",
    )
    return BdfSummary(
        xlfd=fonts[0], glyph_count=declared_count, visible_codes=frozenset(visible)
    )


def _parse_fonts_dir(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="ascii").splitlines()
    require(bool(lines), f"{path}: empty fonts.dir")
    try:
        declared = int(lines[0])
    except ValueError as error:
        raise ReleaseError(f"{path}: malformed fonts.dir count") from error
    entries: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:], 2):
        try:
            filename, xlfd = line.split(" ", 1)
        except ValueError as error:
            raise ReleaseError(f"{path}:{line_number}: malformed fonts.dir entry") from error
        require(filename not in entries, f"{path}:{line_number}: duplicate {filename}")
        entries[filename] = xlfd
    require(declared == len(entries), f"{path}: fonts.dir count mismatch")
    return entries


def _parse_fonts_alias(path: Path) -> tuple[str, dict[str, str]]:
    comment = ""
    aliases: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("!"):
            if not comment:
                comment = stripped
            continue
        try:
            fields = shlex.split(stripped)
        except ValueError as error:
            raise ReleaseError(f"{path}:{line_number}: malformed alias") from error
        require(len(fields) == 2, f"{path}:{line_number}: alias needs two fields")
        name, target = fields
        require(name not in aliases, f"{path}:{line_number}: duplicate alias {name}")
        aliases[name] = target
    return comment, aliases


def write_filtered_indexes(
    source: Path,
    destination: Path,
    selected: dict[str, str],
) -> int:
    """Write indexes whose files and alias targets are closed over ``selected``."""

    full_dir = _parse_fonts_dir(source / "fonts.dir")
    comment, full_aliases = _parse_fonts_alias(source / "fonts.alias")
    require(set(selected) <= set(full_dir), f"{source}: selected BDF missing from fonts.dir")
    for filename, expected_xlfd in selected.items():
        require(
            full_dir[filename] == expected_xlfd,
            f"{source}/{filename}: selected XLFD differs from fonts.dir",
        )
    known_targets = set(full_dir.values())
    require(
        all(target in known_targets for target in full_aliases.values()),
        f"{source}: alias target is absent from the full fonts.dir",
    )
    selected_targets = set(selected.values())
    aliases = {
        name: target
        for name, target in full_aliases.items()
        if target in selected_targets
    }
    require(
        all(target in selected_targets for target in aliases.values()),
        f"{source}: filtered alias escapes selected XLFDs",
    )
    require(
        all('"' not in target for target in aliases.values()),
        f"{source}: alias XLFD contains a quote",
    )

    destination.mkdir(parents=True, exist_ok=True)
    entries = sorted(selected.items())
    (destination / "fonts.dir").write_text(
        str(len(entries))
        + "\n"
        + "".join(f"{filename} {xlfd}\n" for filename, xlfd in entries),
        encoding="ascii",
    )
    release_comment = comment or "! CADR Fonts aliases; XLFD names remain authoritative."
    (destination / "fonts.alias").write_text(
        release_comment
        + "\n"
        + "".join(f'{name} "{aliases[name]}"\n' for name in sorted(aliases)),
        encoding="ascii",
    )
    return len(aliases)


def _artifact_inventory(distribution: Path) -> tuple[list[Artifact], dict[str, object]]:
    build_manifest_path = distribution / "BUILD-MANIFEST.json"
    build_manifest = _load_json(build_manifest_path)
    require(build_manifest.get("schema_version") == 2, "unsupported BUILD-MANIFEST schema")

    source_raw_catalog = _load_json(distribution / "catalog.json")
    runtime_raw_catalog = _load_json(distribution / "runtime" / "catalog.json")
    source_unicode_catalog = _load_json(
        distribution / "unicode" / "source" / "catalog.json"
    )
    runtime_unicode_catalog = _load_json(
        distribution / "unicode" / "runtime" / "catalog.json"
    )
    raw_records = {
        "source": {
            str(record["name"]): record for record in source_raw_catalog["fonts"]
        },
        "runtime": {
            str(record["artifact_name"]): record
            for record in runtime_raw_catalog["font_artifacts"]
        },
    }
    unicode_catalogs = {
        "source": source_unicode_catalog,
        "runtime": runtime_unicode_catalog,
    }
    artifacts: list[Artifact] = []
    seen: set[tuple[str, str]] = set()

    for profile in ("source", "runtime"):
        unicode_root = distribution / "unicode" / profile
        raw_root = distribution if profile == "source" else distribution / "runtime"
        for record in unicode_catalogs[profile]["font_artifacts"]:
            name = str(record["artifact_name"])
            identity = (profile, name)
            require(identity not in seen, f"duplicate artifact identity {identity}")
            seen.add(identity)
            require(name in raw_records[profile], f"{profile}/{name}: raw record missing")
            raw_record = raw_records[profile][name]
            raw_filename = Path(str(record["raw_bdf"])).name
            unicode_filename = Path(str(record["unicode_bdf"])).name
            require(raw_filename == unicode_filename, f"{profile}/{name}: BDF basename drift")
            raw_path = raw_root / "bdf" / raw_filename
            unicode_path = unicode_root / "bdf" / unicode_filename
            raw_summary = read_bdf_summary(raw_path)
            unicode_summary = read_bdf_summary(unicode_path)
            require(
                raw_summary.glyph_count == unicode_summary.glyph_count == record["glyph_count"],
                f"{profile}/{name}: BDF/catalog glyph count drift",
            )
            require(
                sha256(raw_path) == record["raw_bdf_sha256"],
                f"{profile}/{name}: raw BDF hash drift",
            )
            require(
                sha256(unicode_path) == record["unicode_bdf_sha256"],
                f"{profile}/{name}: Unicode BDF hash drift",
            )
            require(
                raw_summary.xlfd == record["raw_xlfd_name"]
                and unicode_summary.xlfd == record["unicode_xlfd_name"],
                f"{profile}/{name}: BDF/catalog XLFD drift",
            )
            content_class = unicode_summary.content_class
            has_pangram = "pangram_specimen" in record
            require(
                has_pangram == (content_class == "latin"),
                f"{profile}/{name}: current Latin and pangram partitions differ",
            )
            if content_class == "latin":
                specimen_path = unicode_root / str(record["pangram_specimen"]["path"])
                require(
                    sha256(specimen_path) == record["pangram_specimen"]["sha256"],
                    f"{profile}/{name}: pangram specimen hash drift",
                )
                specimen_kind = "unicode-pangram"
            else:
                specimen_path = raw_root / str(raw_record["outputs"]["sheet"])
                specimen_kind = "raw-glyph-sheet"
            require(specimen_path.is_file(), f"{profile}/{name}: specimen missing")
            artifacts.append(
                Artifact(
                    profile=profile,
                    record=record,
                    raw_record=raw_record,
                    raw_path=raw_path,
                    unicode_path=unicode_path,
                    raw_summary=raw_summary,
                    unicode_summary=unicode_summary,
                    content_class=content_class,
                    specimen_path=specimen_path,
                    specimen_kind=specimen_kind,
                )
            )

    require(len(artifacts) == 200, f"release inventory has {len(artifacts)} artifacts")
    require(len(seen) == len(artifacts), "release artifact identities are not unique")
    for profile, expected_count in (("source", 151), ("runtime", 49)):
        require(
            sum(artifact.profile == profile for artifact in artifacts) == expected_count,
            f"{profile}: release artifact count changed",
        )

    # Variants and current/legacy runtime witnesses sharing one logical identity
    # must not be split between separately installable packages.
    family_classes: dict[tuple[str, str], str] = {}
    for artifact in artifacts:
        family_name = str(
            artifact.record[
                "logical_name" if artifact.profile == "source" else "runtime_name"
            ]
        )
        key = (artifact.profile, family_name)
        previous = family_classes.setdefault(key, artifact.content_class)
        require(previous == artifact.content_class, f"{key}: family crosses release classes")
    shared_names = {
        name: content_class
        for (profile, name), content_class in family_classes.items()
        if profile == "source"
    }
    for (profile, name), content_class in family_classes.items():
        if profile == "runtime" and name in shared_names:
            require(
                shared_names[name] == content_class,
                f"{name}: source/runtime identities cross release classes",
            )

    provenance = {
        "build_manifest": {
            "path": "BUILD-MANIFEST.json",
            "sha256": sha256(build_manifest_path),
        },
        "catalogs": {
            "raw_source": {
                "path": "catalog.json",
                "sha256": sha256(distribution / "catalog.json"),
            },
            "raw_runtime": {
                "path": "runtime/catalog.json",
                "sha256": sha256(distribution / "runtime" / "catalog.json"),
            },
            "unicode_source": {
                "path": "unicode/source/catalog.json",
                "sha256": sha256(
                    distribution / "unicode" / "source" / "catalog.json"
                ),
            },
            "unicode_runtime": {
                "path": "unicode/runtime/catalog.json",
                "sha256": sha256(
                    distribution / "unicode" / "runtime" / "catalog.json"
                ),
            },
        },
        "source_revision": build_manifest["source_revision"],
    }
    return artifacts, provenance


def _validate_partition(artifacts: list[Artifact]) -> None:
    identities = {
        content_class: {
            (artifact.profile, artifact.name)
            for artifact in artifacts
            if artifact.content_class == content_class
        }
        for content_class in CONTENT_CLASSES
    }
    require(not (identities["latin"] & identities["symbols"]), "release classes overlap")
    require(
        identities["latin"] | identities["symbols"]
        == {(artifact.profile, artifact.name) for artifact in artifacts},
        "release classes do not close the artifact inventory",
    )
    for content_class in CONTENT_CLASSES:
        selected = [
            artifact for artifact in artifacts if artifact.content_class == content_class
        ]
        for profile in ("source", "runtime"):
            group = [artifact for artifact in selected if artifact.profile == profile]
            expected = EXPECTED[content_class][profile]
            observed = {
                "artifact_count": len(group),
                "glyph_count": sum(int(a.record["glyph_count"]) for a in group),
                "standard_glyph_count": sum(
                    int(a.record["standard_glyph_count"]) for a in group
                ),
                "private_use_glyph_count": sum(
                    int(a.record["private_use_glyph_count"]) for a in group
                ),
            }
            for key, value in observed.items():
                require(
                    value == expected[key],
                    f"{content_class}/{profile}: {key} is {value}, expected {expected[key]}",
                )
        runtime_counts = Counter(
            str(a.record["classification"])
            for a in selected
            if a.profile == "runtime"
        )
        require(
            dict(sorted(runtime_counts.items()))
            == EXPECTED[content_class]["runtime_classification_counts"],
            f"{content_class}: runtime classification counts changed",
        )
    require(
        all(
            int(artifact.record["standard_glyph_count"]) == 0
            for artifact in artifacts
            if artifact.content_class == "symbols"
        ),
        "current symbols partition acquired a standard Unicode mapping",
    )


def _fonttosfnt_version(executable: str) -> str:
    resolved = shutil.which(executable)
    require(resolved is not None, f"cannot find fonttosfnt executable: {executable}")
    try:
        process = subprocess.run(
            [resolved, "--version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise ReleaseError(f"cannot run {resolved} --version: {error}") from error
    except subprocess.CalledProcessError:
        # X.Org fonttosfnt releases before 1.2.5 do not implement --version.
        # Preserve an exact, reproducible tool identity instead of either
        # rejecting those releases or recording their locale-sensitive usage
        # message as a version string.
        return f"fonttosfnt executable sha256:{sha256(Path(resolved).resolve())}"
    version = (process.stdout or process.stderr).strip()
    if version:
        return version
    return f"fonttosfnt executable sha256:{sha256(Path(resolved).resolve())}"


def _convert_otb(source: Path, destination: Path, executable: str, epoch: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = str(epoch)
    try:
        process = subprocess.run(
            [executable, "-o", str(destination), str(source)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail_bytes = getattr(error, "stderr", b"") or b""
        detail = detail_bytes.decode("utf-8", "replace").strip() or str(error)
        raise ReleaseError(f"fonttosfnt failed for {source}: {detail}") from error
    require(destination.is_file() and destination.stat().st_size > 0, f"empty OTB {destination}")
    signature = destination.read_bytes()[:4]
    require(
        signature in {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"},
        f"{destination}: fonttosfnt output lacks an SFNT signature",
    )


def _copy(path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, destination)


def _write_readme(path: Path, version: str, content_class: str) -> None:
    if content_class == "latin":
        description = (
            "This archive contains every source and System 46 runtime artifact "
            "whose emitted Unicode BDF has a visible Basic Latin letter."
        )
        specimen = "The specimens are Unicode Lisp-pangram sheets."
    else:
        description = (
            "This archive contains the complementary non-Latin specialty "
            "artifacts: drawing, symbol, APL, Cyrillic, Greek, math, music, and "
            "sprite families."
        )
        specimen = "The specimens are complete raw-code glyph sheets."
    path.write_text(
        f"""# CADR Fonts {content_class} release {version}

{description}

The usable fonts are the `ISO10646-1` BDFs under `fonts/unicode/` and their
OTB conversions under `fonts/otb/`. OTB files are deterministic conversions
of the Unicode BDFs only. The raw source/runtime BDFs under `fonts/raw/` retain
CADR character codes and `Misc-FontSpecific` solely for historical
traceability; do not install them as Unicode fonts. Source and runtime
identities remain separate in every format. {specimen}

`RELEASE-MANIFEST.json` records the selection rule, exact identities, counts,
input provenance, and hashes. `SHA256SUMS` covers every other file in this
archive. Repository-authored tooling, documentation, metadata, and packaging
material are distributed under `LICENSE.project`; the recovered MIT CADR font
payload and its direct derivatives retain the separate upstream notice in
`LICENSE.source`. Both notices are BSD-3-Clause.
""",
        encoding="utf-8",
    )


def _artifact_manifest_record(
    artifact: Artifact,
    release_root: Path,
    raw_destination: Path,
    unicode_destination: Path,
    otb_destination: Path,
    specimen_destination: Path,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "profile": artifact.profile,
        "artifact_name": artifact.name,
    }
    if artifact.profile == "source":
        identity["logical_name"] = artifact.record["logical_name"]
    else:
        identity["runtime_name"] = artifact.record["runtime_name"]
        identity["classification"] = artifact.record["classification"]
    return {
        **identity,
        "repertoire": artifact.record["repertoire"],
        "glyph_count": artifact.record["glyph_count"],
        "standard_glyph_count": artifact.record["standard_glyph_count"],
        "private_use_glyph_count": artifact.record["private_use_glyph_count"],
        "raw_xlfd_name": artifact.record["raw_xlfd_name"],
        "unicode_xlfd_name": artifact.record["unicode_xlfd_name"],
        "files": {
            "raw_bdf": {
                "path": raw_destination.relative_to(release_root).as_posix(),
                "sha256": sha256(raw_destination),
            },
            "unicode_bdf": {
                "path": unicode_destination.relative_to(release_root).as_posix(),
                "sha256": sha256(unicode_destination),
            },
            "otb": {
                "path": otb_destination.relative_to(release_root).as_posix(),
                "sha256": sha256(otb_destination),
            },
            "specimen": {
                "kind": artifact.specimen_kind,
                "path": specimen_destination.relative_to(release_root).as_posix(),
                "sha256": sha256(specimen_destination),
            },
        },
    }


def _write_internal_checksums(release_root: Path) -> int:
    checksum_path = release_root / "SHA256SUMS"
    files = sorted(
        path for path in release_root.rglob("*") if path.is_file() and path != checksum_path
    )
    checksum_path.write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(release_root).as_posix()}\n"
            for path in files
        ),
        encoding="ascii",
    )
    return len(files)


def write_deterministic_archive(root: Path, archive: Path, epoch: int) -> None:
    require(0 <= epoch <= 0xFFFFFFFF, "SOURCE_DATE_EPOCH is outside gzip range")
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(f".{archive.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with temporary.open("wb") as raw_stream:
            with gzip.GzipFile(fileobj=raw_stream, mode="wb", filename="", mtime=epoch) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
                    paths = [
                        root,
                        *sorted(
                            root.rglob("*"),
                            key=lambda path: path.relative_to(root).as_posix(),
                        ),
                    ]
                    for path in paths:
                        arcname = (
                            root.name
                            if path == root
                            else f"{root.name}/{path.relative_to(root).as_posix()}"
                        )
                        require(not path.is_symlink(), f"release staging contains symlink {path}")
                        info = tar.gettarinfo(str(path), arcname=arcname)
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = epoch
                        info.mode = 0o755 if path.is_dir() else 0o644
                        info.pax_headers = {}
                        if path.is_file():
                            with path.open("rb") as stream:
                                tar.addfile(info, stream)
                        else:
                            tar.addfile(info)
        os.replace(temporary, archive)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_one(
    *,
    distribution: Path,
    destination_directory: Path,
    version: str,
    epoch: int,
    content_class: str,
    artifacts: list[Artifact],
    provenance: dict[str, object],
    fonttosfnt: str,
    converter_version: str,
) -> tuple[Path, Path]:
    package_name = f"CADR-fonts-{content_class}-{version}"
    selected = sorted(
        (artifact for artifact in artifacts if artifact.content_class == content_class),
        key=lambda artifact: (artifact.profile, artifact.name),
    )
    with tempfile.TemporaryDirectory(prefix="cadr-fonts-release-") as temporary:
        release_root = Path(temporary) / package_name
        release_root.mkdir()
        _write_readme(release_root / "README.release.md", version, content_class)
        _copy(ROOT / "LICENSE", release_root / "LICENSE.project")
        _copy(distribution / "LICENSE.source", release_root / "LICENSE.source")
        metadata_sources = {
            "SOURCE-MANIFEST.json": distribution / "SOURCE-MANIFEST.json",
            "runtime-source-manifest.json": distribution
            / "runtime"
            / "runtime-source-manifest.json",
            "UNICODE-MAPPING.json": distribution / "unicode" / "UNICODE-MAPPING.json",
        }
        metadata_records: dict[str, dict[str, str]] = {}
        for name, source in metadata_sources.items():
            destination = release_root / "metadata" / name
            _copy(source, destination)
            metadata_records[name] = {
                "path": destination.relative_to(release_root).as_posix(),
                "sha256": sha256(destination),
            }

        manifest_artifacts: list[dict[str, object]] = []
        alias_counts: dict[str, dict[str, int]] = {"raw": {}, "unicode": {}}
        for profile in ("source", "runtime"):
            group = [artifact for artifact in selected if artifact.profile == profile]
            raw_index_source = (
                distribution / "bdf"
                if profile == "source"
                else distribution / "runtime" / "bdf"
            )
            unicode_index_source = distribution / "unicode" / profile / "bdf"
            raw_index_destination = release_root / "fonts" / "raw" / profile
            unicode_index_destination = release_root / "fonts" / "unicode" / profile
            raw_selected = {
                artifact.raw_path.name: artifact.raw_summary.xlfd for artifact in group
            }
            unicode_selected = {
                artifact.unicode_path.name: artifact.unicode_summary.xlfd
                for artifact in group
            }
            alias_counts["raw"][profile] = write_filtered_indexes(
                raw_index_source, raw_index_destination, raw_selected
            )
            alias_counts["unicode"][profile] = write_filtered_indexes(
                unicode_index_source, unicode_index_destination, unicode_selected
            )
            expected_aliases = EXPECTED[content_class][profile]["alias_count"]
            require(
                alias_counts["raw"][profile]
                == alias_counts["unicode"][profile]
                == expected_aliases,
                f"{content_class}/{profile}: filtered alias count changed",
            )

            for artifact in group:
                raw_destination = raw_index_destination / artifact.raw_path.name
                unicode_destination = unicode_index_destination / artifact.unicode_path.name
                otb_destination = (
                    release_root
                    / "fonts"
                    / "otb"
                    / profile
                    / f"{artifact.unicode_path.stem}.otb"
                )
                specimen_destination = (
                    release_root
                    / "specimens"
                    / profile
                    / artifact.specimen_path.name
                )
                _copy(artifact.raw_path, raw_destination)
                _copy(artifact.unicode_path, unicode_destination)
                _convert_otb(
                    artifact.unicode_path, otb_destination, fonttosfnt, epoch
                )
                _copy(artifact.specimen_path, specimen_destination)
                manifest_artifacts.append(
                    _artifact_manifest_record(
                        artifact,
                        release_root,
                        raw_destination,
                        unicode_destination,
                        otb_destination,
                        specimen_destination,
                    )
                )

        profile_counts = {}
        for profile in ("source", "runtime"):
            group = [artifact for artifact in selected if artifact.profile == profile]
            profile_counts[profile] = {
                "artifact_count": len(group),
                "raw_bdf_count": len(group),
                "unicode_bdf_count": len(group),
                "otb_count": len(group),
                "specimen_count": len(group),
                "glyph_count_per_encoding": sum(
                    int(artifact.record["glyph_count"]) for artifact in group
                ),
                "standard_glyph_count": sum(
                    int(artifact.record["standard_glyph_count"]) for artifact in group
                ),
                "private_use_glyph_count": sum(
                    int(artifact.record["private_use_glyph_count"]) for artifact in group
                ),
                "raw_alias_count": alias_counts["raw"][profile],
                "unicode_alias_count": alias_counts["unicode"][profile],
            }
        artifact_count = len(selected)
        total_file_count = 4 * artifact_count + 16
        release_manifest = {
            "schema_version": 1,
            "name": package_name,
            "version": version,
            "content_class": content_class,
            "content_class_policy": {
                "latin": (
                    "at least one emitted Unicode BDF glyph in U+0041-U+005A or "
                    "U+0061-U+007A has visible ink"
                ),
                "symbols": "the closed complement of the latin artifact set",
                "selection_input": (
                    "emitted Unicode BDF content; names, repertoire labels, and "
                    "specimen presence do not select release membership"
                ),
                "glyph_preservation": (
                    "classification selects whole artifacts; no glyph is removed "
                    "from a selected raw or Unicode BDF"
                ),
            },
            "source_revision": provenance["source_revision"],
            "source_date_epoch": epoch,
            "generator": {
                "path": "scripts/build_release.py",
                "sha256": sha256(Path(__file__).resolve()),
                "fonttosfnt": converter_version,
                "otb_input": "selected ISO10646-1 BDF",
            },
            "source_distribution": {
                "build_manifest": provenance["build_manifest"],
                "catalogs": provenance["catalogs"],
            },
            "licenses": {
                "project": {
                    "path": "LICENSE.project",
                    "spdx": "BSD-3-Clause",
                    "sha256": sha256(release_root / "LICENSE.project"),
                    "applies_to": (
                        "repository-authored tooling, metadata, documentation, "
                        "and packaging material"
                    ),
                },
                "source": {
                    "path": "LICENSE.source",
                    "spdx": "BSD-3-Clause",
                    "sha256": sha256(release_root / "LICENSE.source"),
                    "applies_to": (
                        "recovered MIT CADR font payload and direct derivatives"
                    ),
                },
            },
            "metadata": metadata_records,
            "counts": {
                "artifact_count": artifact_count,
                "profiles": profile_counts,
                "raw_bdf_count": artifact_count,
                "unicode_bdf_count": artifact_count,
                "bdf_count": 2 * artifact_count,
                "otb_count": artifact_count,
                "specimen_count": artifact_count,
                "raw_alias_count": sum(alias_counts["raw"].values()),
                "unicode_alias_count": sum(alias_counts["unicode"].values()),
                "alias_count": sum(alias_counts["raw"].values())
                + sum(alias_counts["unicode"].values()),
                "glyph_count_per_encoding": sum(
                    int(artifact.record["glyph_count"]) for artifact in selected
                ),
                "bdf_glyph_instances": 2
                * sum(int(artifact.record["glyph_count"]) for artifact in selected),
                "total_file_count": total_file_count,
                "checksum_covered_file_count": total_file_count - 1,
            },
            "artifacts": sorted(
                manifest_artifacts,
                key=lambda record: (record["profile"], record["artifact_name"]),
            ),
        }
        manifest_path = release_root / "RELEASE-MANIFEST.json"
        manifest_path.write_text(
            json.dumps(release_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pre_checksum_files = sum(path.is_file() for path in release_root.rglob("*"))
        require(
            pre_checksum_files == total_file_count - 1,
            f"{content_class}: staged file count is {pre_checksum_files}, "
            f"expected {total_file_count - 1}",
        )
        covered = _write_internal_checksums(release_root)
        require(covered == total_file_count - 1, f"{content_class}: checksum closure changed")
        require(
            sum(path.is_file() for path in release_root.rglob("*")) == total_file_count,
            f"{content_class}: final staged file count changed",
        )

        archive = destination_directory / f"{package_name}.tar.gz"
        write_deterministic_archive(release_root, archive, epoch)
        checksum = archive.with_name(f"{archive.name}.sha256")
        checksum.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="ascii")
        return archive, checksum


def build_release(
    *,
    distribution: Path,
    release_dir: Path,
    version: str,
    source_date_epoch: int,
    fonttosfnt: str = "fonttosfnt",
) -> list[Path]:
    require(VERSION_PATTERN.fullmatch(version) is not None, "unsafe release version")
    require(0 <= source_date_epoch <= 0xFFFFFFFF, "invalid SOURCE_DATE_EPOCH")
    distribution = distribution.resolve()
    release_dir = release_dir.resolve()
    require(distribution.is_dir(), f"distribution directory does not exist: {distribution}")
    require((ROOT / "LICENSE").is_file(), "project LICENSE is missing")
    require((ROOT / "LICENSE.source").is_file(), "tracked source license is missing")
    require(
        (ROOT / "LICENSE.source").read_bytes()
        == (distribution / "LICENSE.source").read_bytes(),
        "tracked and generated source licenses differ",
    )
    artifacts, provenance = _artifact_inventory(distribution)
    _validate_partition(artifacts)
    converter_version = _fonttosfnt_version(fonttosfnt)

    release_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    with tempfile.TemporaryDirectory(prefix=".cadr-fonts-assets-", dir=release_dir) as temp:
        temporary_assets = Path(temp)
        for content_class in CONTENT_CLASSES:
            archive, checksum = _build_one(
                distribution=distribution,
                destination_directory=temporary_assets,
                version=version,
                epoch=source_date_epoch,
                content_class=content_class,
                artifacts=artifacts,
                provenance=provenance,
                fonttosfnt=fonttosfnt,
                converter_version=converter_version,
            )
            for source in (archive, checksum):
                destination = release_dir / source.name
                os.replace(source, destination)
                outputs.append(destination)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument(
        "--fonttosfnt",
        default="fonttosfnt",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    try:
        outputs = build_release(
            distribution=args.distribution,
            release_dir=args.release_dir,
            version=args.version,
            source_date_epoch=args.source_date_epoch,
            fonttosfnt=args.fonttosfnt,
        )
    except ReleaseError as error:
        parser.exit(1, f"release build failed: {error}\n")
    print(json.dumps({"release_assets": [str(path) for path in outputs]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
