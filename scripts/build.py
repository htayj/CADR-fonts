#!/usr/bin/env python3
"""Build the pinned MIT CADR bitmap-font distribution deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lisp_machine_fonts import safe_filename


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = ROOT / "sources" / "mit-cadr-system-software"
SOURCE_MANIFEST = ROOT / "config" / "source-manifest.json"
RUNTIME_SOURCE_MANIFEST = ROOT / "config" / "runtime-source-manifest.json"
EXTRACTOR = ROOT / "scripts" / "extract-cadr-fonts.py"
RUNTIME_EXTRACTOR = ROOT / "scripts" / "extract-cadr-qfasl-fonts.py"
GENERATOR_FILES = (
    "config/source-manifest.json",
    "config/runtime-source-manifest.json",
    "scripts/build.py",
    "scripts/extract-cadr-fonts.py",
    "scripts/extract-cadr-qfasl-fonts.py",
    "scripts/lisp_machine_fonts.py",
)
RUNTIME_COMPATIBILITY_ALIASES = {
    "cm10": "CPT-CM10",
    "cm12": "CPT-CM12",
    "cptfon": "CPTFONT",
}


class BuildError(RuntimeError):
    """The requested build would not match the pinned source witness."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*arguments: str) -> str:
    try:
        process = subprocess.run(
            ["git", "-C", str(SOURCE_REPOSITORY), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise BuildError(f"cannot inspect source submodule: {detail.strip()}") from error
    return process.stdout.strip()


def load_and_verify_source() -> tuple[dict[str, object], Path]:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise BuildError("unsupported source-manifest schema")
    if not SOURCE_REPOSITORY.is_dir():
        raise BuildError(
            "source submodule is missing; run: git submodule update --init --recursive"
        )

    revision = git("rev-parse", "HEAD")
    expected_revision = manifest["revision"]
    if revision != expected_revision:
        raise BuildError(
            f"source revision is {revision}, expected {expected_revision}; "
            "run: git submodule update --init"
        )
    dirty = git("status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise BuildError("source submodule is dirty; refusing a non-reproducible build")

    source_root = SOURCE_REPOSITORY / str(manifest["source_root"])
    expected_files = {str(record["path"]): record for record in manifest["files"]}
    actual_names = {
        path.name
        for path in source_root.iterdir()
        if path.name.casefold() in {"arc.ast's", "ar1.1"}
        or path.suffix.casefold() in {".ast", ".kst", ".al"}
    }
    if actual_names != set(expected_files):
        missing = sorted(set(expected_files) - actual_names)
        unexpected = sorted(actual_names - set(expected_files))
        raise BuildError(
            f"source corpus differs from closed manifest; missing={missing}, "
            f"unexpected={unexpected}"
        )

    for name, record in expected_files.items():
        path = source_root / name
        size = path.stat().st_size
        digest = sha256(path)
        if size != record["byte_size"] or digest != record["sha256"]:
            raise BuildError(
                f"source mismatch for {name}: size={size}, sha256={digest}"
            )

    license_record = manifest["license"]
    license_path = SOURCE_REPOSITORY / str(license_record["path"])
    if (
        license_path.stat().st_size != license_record["byte_size"]
        or sha256(license_path) != license_record["sha256"]
    ):
        raise BuildError("source license does not match the pinned manifest")
    runtime_evidence = manifest["reviewed_findings"]["runtime_name_qfasl_evidence"]
    for logical_name, record in runtime_evidence.items():
        path = SOURCE_REPOSITORY / str(record["path"])
        if (
            path.stat().st_size != record["byte_size"]
            or sha256(path) != record["sha256"]
        ):
            raise BuildError(f"runtime-name QFASL evidence changed for {logical_name}")
    return manifest, source_root


def extend_catalog(
    output: Path, manifest: dict[str, object]
) -> dict[str, object]:
    catalog_path = output / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    expected = manifest["expected_output"]
    observed = {
        "font_count": catalog["font_count"],
        "logical_font_count": catalog["logical_font_count"],
        "variant_count": catalog["variant_count"],
        "rejected_source_count": len(catalog["rejected_sources"]),
        "character_pointer_partial_recovery_count": catalog[
            "character_pointer_partial_recovery_count"
        ],
        "extent_recovery_font_count": catalog["extent_recovery_font_count"],
        "extent_recovery_glyph_count": catalog["extent_recovery_glyph_count"],
        "spacing_counts": {
            code: sum(font["bdf"]["spacing"] == code for font in catalog["fonts"])
            for code in ("C", "M", "P")
        },
    }
    if observed != expected:
        raise BuildError(f"output invariants changed: expected={expected}, observed={observed}")

    manifest_copy = output / "SOURCE-MANIFEST.json"
    shutil.copyfile(SOURCE_MANIFEST, manifest_copy)
    catalog["source_repository"] = {
        "url": manifest["repository"],
        "revision": manifest["revision"],
        "submodule_path": "sources/mit-cadr-system-software",
        "source_root": manifest["source_root"],
        "license": manifest["license"],
        "closed_manifest": "SOURCE-MANIFEST.json",
        "closed_manifest_sha256": sha256(manifest_copy),
        "physical_input_count": len(manifest["files"]),
        "runtime_name_evidence_count": len(
            manifest["reviewed_findings"]["runtime_name_qfasl_evidence"]
        ),
    }
    catalog["generator"] = {
        "name": "cadr-fonts",
        "language": "Python 3 standard library",
        "origin": {
            "repository": "genera-emu",
            "revision": "2602eab2ef1bea4800312f71f9185e9261c6fa6c",
            "note": "source decoder ported, then adapted for pinned XLFD output",
        },
        "files": [
            {
                "path": relative,
                "sha256": sha256(ROOT / relative),
            }
            for relative in GENERATOR_FILES
        ],
    }
    catalog_path.write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return catalog


def write_x_indexes(
    output: Path,
    catalog: dict[str, object],
    *,
    reserved_convenience_names: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str]:
    """Write source-profile indexes without claiming runtime-owned names."""

    bdf_directory = output / "bdf"
    entries = sorted(
        (
            Path(record["outputs"]["bdf"]).name,
            record["bdf"]["xlfd_name"],
            record,
        )
        for record in catalog["fonts"]
    )
    (bdf_directory / "fonts.dir").write_text(
        str(len(entries))
        + "\n"
        + "".join(f"{filename} {xlfd}\n" for filename, xlfd, _record in entries),
        encoding="ascii",
    )

    aliases: dict[str, str] = {}

    def add_alias(alias: str, xlfd: str) -> None:
        previous = aliases.get(alias)
        if previous is not None and previous != xlfd:
            raise BuildError(f"X font alias collision for {alias}")
        aliases[alias] = xlfd

    for _filename, xlfd, record in entries:
        add_alias(f'cadr-source-{safe_filename(record["name"])}', xlfd)
        convenience_name = safe_filename(record["name"])
        if convenience_name not in reserved_convenience_names:
            add_alias(f"cadr-{convenience_name}", xlfd)
    (bdf_directory / "fonts.alias").write_text(
        "! Source-profile aliases; XLFD names remain authoritative.\n"
        + "".join(f'{alias} "{aliases[alias]}"\n' for alias in sorted(aliases)),
        encoding="ascii",
    )
    return aliases


def write_runtime_x_indexes(
    output: Path,
    catalog: dict[str, object],
    *,
    compatibility_aliases: dict[str, str] = RUNTIME_COMPATIBILITY_ALIASES,
) -> dict[str, str]:
    """Write current-runtime and explicit-legacy X core-font aliases."""

    bdf_directory = output / "bdf"
    entries = sorted(
        (
            Path(record["outputs"]["bdf"]).name,
            record["bdf_profile"]["xlfd_name"],
            record,
        )
        for record in catalog["font_artifacts"]
    )
    (bdf_directory / "fonts.dir").write_text(
        str(len(entries))
        + "\n"
        + "".join(f"{filename} {xlfd}\n" for filename, xlfd, _ in entries),
        encoding="ascii",
    )

    aliases: dict[str, str] = {}

    def add_alias(alias: str, xlfd: str) -> None:
        previous = aliases.get(alias)
        if previous is not None and previous != xlfd:
            raise BuildError(f"X font alias collision for {alias}")
        aliases[alias] = xlfd

    current_by_name: dict[str, dict[str, object]] = {}
    for _filename, xlfd, record in entries:
        artifact = safe_filename(record["artifact_name"])
        if record["classification"] == "legacy-compiled-version":
            add_alias(f"cadr-runtime-legacy-{artifact}", xlfd)
            continue
        runtime_name = safe_filename(record["runtime_name"])
        add_alias(f"cadr-runtime-{runtime_name}", xlfd)
        add_alias(f"cadr-{runtime_name}", xlfd)
        current_by_name[str(record["runtime_name"])] = record

    for alias_name, runtime_name in compatibility_aliases.items():
        record = current_by_name.get(runtime_name)
        if record is None:
            raise BuildError(
                f"runtime compatibility alias target is absent: {runtime_name}"
            )
        add_alias(f"cadr-{alias_name}", record["bdf_profile"]["xlfd_name"])

    (bdf_directory / "fonts.alias").write_text(
        "! Runtime-profile aliases; unqualified names select current System 46.\n"
        + "".join(f'{alias} "{aliases[alias]}"\n' for alias in sorted(aliases)),
        encoding="ascii",
    )
    return aliases


def write_build_manifest(
    output: Path,
    source_catalog: dict[str, object],
    runtime_catalog: dict[str, object],
    source_aliases: dict[str, str],
    runtime_aliases: dict[str, str],
) -> None:
    """Record the two non-interchangeable artifact profiles in one index."""

    source_catalog_path = output / "catalog.json"
    runtime_catalog_path = output / "runtime" / "catalog.json"
    record = {
        "schema_version": 1,
        "source_revision": source_catalog["source_repository"]["revision"],
        "profiles": {
            "authoring_source": {
                "catalog": "catalog.json",
                "catalog_sha256": sha256(source_catalog_path),
                "artifact_count": source_catalog["font_count"],
                "logical_font_count": source_catalog["logical_font_count"],
                "alias_count": len(source_aliases),
                "alias_policy": (
                    "cadr-source-<artifact> always; cadr-<artifact> only when "
                    "the name is not reserved for a current runtime font"
                ),
            },
            "system_46_runtime": {
                "catalog": "runtime/catalog.json",
                "catalog_sha256": sha256(runtime_catalog_path),
                "artifact_count": runtime_catalog["artifact_count"],
                "runtime_logical_name_count": runtime_catalog[
                    "runtime_logical_name_count"
                ],
                "classification_counts": runtime_catalog["classification_counts"],
                "alias_count": len(runtime_aliases),
                "alias_policy": (
                    "cadr-<runtime-name> and cadr-runtime-<runtime-name> select "
                    "current System 46; legacy artifacts are explicit only"
                ),
            },
        },
        "total_artifact_count": (
            source_catalog["font_count"] + runtime_catalog["artifact_count"]
        ),
        "undefined_character_policy": (
            "not normalized across CADR and X; rendering conformance covers only "
            "character codes defined by each emitted BDF"
        ),
    }
    (output / "BUILD-MANIFEST.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_checksums(output: Path) -> None:
    checksum_path = output / "SHA256SUMS"
    files = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path != checksum_path
    )
    checksum_path.write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(output).as_posix()}\n"
            for path in files
        ),
        encoding="ascii",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--omit-json",
        action="store_true",
        help="omit normalized per-font JSON; intended for smaller later releases",
    )
    args = parser.parse_args()
    output = args.output.resolve()

    try:
        manifest, source_root = load_and_verify_source()
        command = [
            sys.executable,
            str(EXTRACTOR),
            str(source_root),
            "--output",
            str(output),
            "--clean",
            "--strict",
        ]
        if args.omit_json:
            command.append("--omit-json")
        subprocess.run(command, check=True)
        catalog = extend_catalog(output, manifest)

        runtime_output = output / "runtime"
        runtime_command = [
            sys.executable,
            str(RUNTIME_EXTRACTOR),
            str(source_root),
            "--output",
            str(runtime_output),
            "--manifest",
            str(RUNTIME_SOURCE_MANIFEST),
            "--clean",
        ]
        if args.omit_json:
            runtime_command.append("--omit-json")
        subprocess.run(runtime_command, check=True)
        runtime_catalog_path = runtime_output / "catalog.json"
        runtime_catalog = json.loads(
            runtime_catalog_path.read_text(encoding="utf-8")
        )

        current_runtime_names = {
            safe_filename(record["runtime_name"])
            for record in runtime_catalog["font_artifacts"]
            if record["classification"] != "legacy-compiled-version"
        }
        reserved_source_convenience_names = current_runtime_names | set(
            RUNTIME_COMPATIBILITY_ALIASES
        )
        source_aliases = write_x_indexes(
            output,
            catalog,
            reserved_convenience_names=reserved_source_convenience_names,
        )
        runtime_aliases = write_runtime_x_indexes(
            runtime_output, runtime_catalog
        )
        runtime_catalog["x_indexes"] = {
            "fonts_dir": "bdf/fonts.dir",
            "fonts_alias": "bdf/fonts.alias",
            "alias_count": len(runtime_aliases),
            "aliases": [
                {"name": alias, "xlfd": runtime_aliases[alias]}
                for alias in sorted(runtime_aliases)
            ],
        }
        runtime_catalog["packager"] = {
            "path": "scripts/build.py",
            "sha256": sha256(Path(__file__)),
        }
        runtime_catalog_path.write_text(
            json.dumps(runtime_catalog, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_build_manifest(
            output,
            catalog,
            runtime_catalog,
            source_aliases,
            runtime_aliases,
        )
        write_checksums(output)
    except (BuildError, OSError, subprocess.CalledProcessError, ValueError) as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "output": str(output),
                "font_count": catalog["font_count"],
                "runtime_artifact_count": runtime_catalog["artifact_count"],
                "total_artifact_count": (
                    catalog["font_count"] + runtime_catalog["artifact_count"]
                ),
                "logical_font_count": catalog["logical_font_count"],
                "runtime_logical_name_count": runtime_catalog[
                    "runtime_logical_name_count"
                ],
                "variant_count": catalog["variant_count"],
                "source_revision": manifest["revision"],
                "checksums": str(output / "SHA256SUMS"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
