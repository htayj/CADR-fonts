#!/usr/bin/env python3
"""Prove that packaged OTB strikes display every Unicode BDF glyph exactly."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

try:
    from fontTools.ttLib import TTFont
except ImportError as error:  # pragma: no cover - exercised by release hosts
    raise SystemExit(
        "check_otb.py requires fontTools (for example python3-fonttools)"
    ) from error

from check_unicode_dist import parse_bdf


class OtbCheckError(AssertionError):
    """A packaged OTB does not preserve its Unicode BDF display geometry."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OtbCheckError(message)


def _safe_archive_members(archive: tarfile.TarFile) -> tuple[tarfile.TarInfo, ...]:
    members = tuple(archive.getmembers())
    require(bool(members), f"{archive.name}: empty archive")
    roots: set[str] = set()
    names: set[str] = set()
    for member in members:
        normalized = member.name.rstrip("/")
        require(
            normalized and normalized not in names,
            f"{archive.name}: duplicate archive member",
        )
        names.add(normalized)
        path = PurePosixPath(normalized)
        require(
            not path.is_absolute() and ".." not in path.parts,
            f"{archive.name}: unsafe archive path {member.name!r}",
        )
        require(
            normalized == path.as_posix(),
            f"{archive.name}: non-canonical archive path {member.name!r}",
        )
        require(
            member.isdir() or member.isfile(),
            f"{archive.name}: links and special files are not permitted",
        )
        require(bool(path.parts), f"{archive.name}: empty archive path")
        roots.add(path.parts[0])
    require(len(roots) == 1, f"{archive.name}: expected one archive root")
    return members


def _bitmap_metrics(bitmap: object, subtable: object) -> tuple[int, int, int, int, int, object]:
    try:
        metrics = bitmap.metrics
    except AttributeError:
        metrics = subtable.metrics
    if hasattr(metrics, "BearingX"):
        values = (
            metrics.width,
            metrics.height,
            metrics.BearingX,
            metrics.BearingY,
            metrics.Advance,
        )
    else:
        values = (
            metrics.width,
            metrics.height,
            metrics.horiBearingX,
            metrics.horiBearingY,
            metrics.horiAdvance,
        )
    return (*map(int, values), metrics)


def _bdf_ink(glyph: dict[str, object]) -> tuple[int, set[tuple[int, int]]]:
    width, height, x_offset, y_offset = map(int, str(glyph["bbx"]).split())
    advance_fields = tuple(map(int, str(glyph["dwidth"]).split()))
    require(
        len(advance_fields) == 2 and advance_fields[1] == 0,
        "packaged BDF has a non-horizontal advance",
    )
    ink: set[tuple[int, int]] = set()
    for row_number, row_hex in enumerate(glyph["bitmap"]):
        storage_width = len(row_hex) * 4
        row = int(row_hex, 16) >> (storage_width - width)
        for column in range(width):
            if row & (1 << (width - column - 1)):
                ink.add(
                    (
                        x_offset + column,
                        y_offset + height - row_number - 1,
                    )
                )
    return advance_fields[0], ink


def _otb_ink(
    bitmap: object,
    subtable: object,
) -> tuple[int, set[tuple[int, int]]]:
    width, height, bearing_x, bearing_y, advance, metrics = _bitmap_metrics(
        bitmap, subtable
    )
    ink: set[tuple[int, int]] = set()
    for row_number in range(height):
        row_bytes = bitmap.getRow(row_number, 1, metrics=metrics)
        row = int.from_bytes(row_bytes, "big") >> (len(row_bytes) * 8 - width)
        for column in range(width):
            if row & (1 << (width - column - 1)):
                ink.add((bearing_x + column, bearing_y - row_number - 1))
    return advance, ink


def _unicode_add_style(typographic: dict[str, object]) -> str:
    composed = " ".join(
        part for part in (str(typographic.get("add_style_name") or ""), "Unicode") if part
    )
    normalized = "".join(
        " " if character in '-?*,"\\' else character for character in composed
    )
    return " ".join(normalized.split())


def _expected_style(typographic: dict[str, object]) -> str:
    parts: list[str] = []
    parts.append(_unicode_add_style(typographic).replace(" ", "-"))
    if typographic.get("weight_name") == "Bold":
        parts.append("Bold")
    if typographic.get("slant") == "I":
        parts.append("Italic")
    setwidth = typographic.get("setwidth_name")
    if setwidth != "Normal":
        parts.append(str(setwidth))
    return " ".join(parts) or "Regular"


def _check_identity(
    font: TTFont, otb_path: Path, logical_identity: dict[str, object]
) -> None:
    typographic = logical_identity.get("typographic")
    require(isinstance(typographic, dict), f"{otb_path}: logical typography is missing")
    family = typographic.get("family_name")
    require(isinstance(family, str) and family, f"{otb_path}: logical family is missing")
    style = _expected_style(typographic)
    name_table = font["name"]
    require(name_table.getDebugName(1) == family, f"{otb_path}: OTB family name differs")
    require(name_table.getDebugName(2) == style, f"{otb_path}: OTB style name differs")
    expected_full_name = family if style == "Regular" else f"{family} {style}"
    require(
        name_table.getDebugName(4) == expected_full_name,
        f"{otb_path}: OTB full name differs",
    )

    os2 = font["OS/2"]
    expected_weight = {"Medium": 400, "Bold": 700}.get(
        typographic.get("weight_name")
    )
    expected_width = {"Condensed": 3, "Normal": 5, "Expanded": 7}.get(
        typographic.get("setwidth_name")
    )
    require(expected_weight is not None, f"{otb_path}: unsupported expected weight")
    require(expected_width is not None, f"{otb_path}: unsupported expected width")
    require(os2.usWeightClass == expected_weight, f"{otb_path}: OS/2 weight differs")
    require(os2.usWidthClass == expected_width, f"{otb_path}: OS/2 width differs")
    selection = int(os2.fsSelection)
    italic = typographic.get("slant") == "I"
    bold = typographic.get("weight_name") == "Bold"
    require(bool(selection & 0x01) == italic, f"{otb_path}: OS/2 italic bit differs")
    require(bool(selection & 0x20) == bold, f"{otb_path}: OS/2 bold bit differs")
    require(
        bool(selection & 0x40) == (not italic and not bold),
        f"{otb_path}: OS/2 regular bit differs",
    )


def check_pair(
    bdf_path: Path,
    otb_path: Path,
    logical_identity: dict[str, object],
) -> int:
    bdf = parse_bdf(bdf_path)
    typographic = logical_identity.get("typographic")
    require(isinstance(typographic, dict), f"{bdf_path}: logical typography is missing")
    expected_add_style = _unicode_add_style(typographic)
    require(
        bdf["properties"].get("ADD_STYLE_NAME") == expected_add_style,
        f"{bdf_path}: Unicode BDF add style differs from logical identity",
    )
    font = TTFont(otb_path, lazy=False)
    try:
        require("name" in font and "OS/2" in font, f"{otb_path}: identity tables missing")
        _check_identity(font, otb_path, logical_identity)
        require("EBLC" in font and "EBDT" in font, f"{otb_path}: no EBDT strike")
        strikes = font["EBLC"].strikes
        strike_data = font["EBDT"].strikeData
        require(
            len(strikes) == 1 and len(strike_data) == 1,
            f"{otb_path}: expected exactly one embedded bitmap strike",
        )
        size = strikes[0].bitmapSizeTable
        require(size.bitDepth == 1, f"{otb_path}: strike is not one-bit")
        cmap = font.getBestCmap() or {}
        bdf_codes = set(bdf["glyphs"])
        require(
            set(cmap) == bdf_codes,
            f"{otb_path}: Unicode repertoire differs from BDF "
            f"(missing={sorted(bdf_codes - set(cmap))}, "
            f"extra={sorted(set(cmap) - bdf_codes)})",
        )
        name_to_subtable = {
            name: subtable
            for subtable in strikes[0].indexSubTables
            for name in subtable.names
        }
        bitmaps = strike_data[0]
        for code in sorted(bdf_codes):
            name = cmap[code]
            require(name in bitmaps, f"{otb_path}: U+{code:04X} lacks bitmap data")
            require(
                name in name_to_subtable,
                f"{otb_path}: U+{code:04X} lacks an EBLC locator",
            )
            expected_advance, expected_ink = _bdf_ink(bdf["glyphs"][code])
            observed_advance, observed_ink = _otb_ink(
                bitmaps[name], name_to_subtable[name]
            )
            require(
                observed_advance == expected_advance,
                f"{otb_path}: U+{code:04X} advance changed "
                f"from {expected_advance} to {observed_advance}",
            )
            require(
                observed_ink == expected_ink,
                f"{otb_path}: U+{code:04X} baseline-relative ink changed "
                f"(missing={len(expected_ink - observed_ink)}, "
                f"extra={len(observed_ink - expected_ink)})",
            )
        return len(bdf_codes)
    finally:
        font.close()


def check_archive(path: Path) -> dict[str, object]:
    with tarfile.open(path, "r:gz") as archive:
        members = _safe_archive_members(archive)
        files = {member.name: member for member in members if member.isfile()}
        bdfs = sorted(
            name
            for name in files
            if "/fonts/unicode/" in name and name.endswith(".bdf")
        )
        require(bool(bdfs), f"{path}: no packaged Unicode BDFs")
        manifests = [name for name in files if name.endswith("/RELEASE-MANIFEST.json")]
        require(len(manifests) == 1, f"{path}: expected one release manifest")
        manifest_name = manifests[0]
        manifest_stream = archive.extractfile(files[manifest_name])
        require(manifest_stream is not None, f"{path}: cannot read release manifest")
        manifest = json.loads(manifest_stream.read())
        artifacts = manifest.get("artifacts")
        require(isinstance(artifacts, list), f"{path}: release artifacts are missing")
        archive_root = PurePosixPath(manifest_name).parts[0]
        artifacts_by_bdf: dict[
            str, tuple[str, dict[str, object], dict[str, object]]
        ] = {}
        for artifact in artifacts:
            require(isinstance(artifact, dict), f"{path}: malformed release artifact")
            artifact_files = artifact.get("files")
            logical_identity = artifact.get("logical_identity")
            representation = artifact.get("representation")
            require(isinstance(artifact_files, dict), f"{path}: artifact files are missing")
            require(
                isinstance(logical_identity, dict),
                f"{path}: artifact logical identity is missing",
            )
            require(
                isinstance(representation, dict),
                f"{path}: artifact representation is missing",
            )
            bdf_record = artifact_files.get("unicode_bdf")
            otb_record = artifact_files.get("otb")
            require(isinstance(bdf_record, dict), f"{path}: artifact BDF record is missing")
            require(isinstance(otb_record, dict), f"{path}: artifact OTB record is missing")
            bdf_relative = bdf_record.get("path")
            otb_relative = otb_record.get("path")
            require(isinstance(bdf_relative, str), f"{path}: artifact BDF path is missing")
            require(isinstance(otb_relative, str), f"{path}: artifact OTB path is missing")
            bdf_path = PurePosixPath(bdf_relative)
            otb_path = PurePosixPath(otb_relative)
            profile = artifact.get("profile")
            require(profile in {"source", "runtime"}, f"{path}: invalid artifact profile")
            require(
                representation.get("profile") == profile
                and representation.get("artifact_name") == artifact.get("artifact_name"),
                f"{path}: artifact representation identity differs",
            )
            require(
                "representation" not in logical_identity,
                f"{path}: representation is nested in logical identity",
            )
            require(
                bdf_path.parts[:3] == ("fonts", "unicode", profile)
                and otb_path.parts[:3] == ("fonts", "otb", profile)
                and len(bdf_path.parts) == len(otb_path.parts) == 4
                and bdf_path.suffix == ".bdf"
                and otb_path.suffix == ".otb",
                f"{path}: artifact font path escaped its profile",
            )
            require(
                bdf_path.stem == otb_path.stem,
                f"{path}: artifact BDF/OTB basenames differ",
            )
            bdf_name = str(PurePosixPath(archive_root) / bdf_path)
            otb_name = str(PurePosixPath(archive_root) / otb_path)
            require(
                bdf_name not in artifacts_by_bdf,
                f"{path}: duplicate artifact BDF path {bdf_relative}",
            )
            artifacts_by_bdf[bdf_name] = (
                otb_name,
                logical_identity,
                representation,
            )

        require(
            set(artifacts_by_bdf) == set(bdfs),
            f"{path}: release manifest is not closed over packaged Unicode BDF paths",
        )
        pair_bytes: list[
            tuple[str, bytes, bytes, dict[str, object]]
        ] = []
        for bdf_name in bdfs:
            otb_name, logical_identity, _representation = artifacts_by_bdf[bdf_name]
            require(otb_name in files, f"{path}: missing {otb_name}")
            bdf_stream = archive.extractfile(files[bdf_name])
            otb_stream = archive.extractfile(files[otb_name])
            require(
                bdf_stream is not None and otb_stream is not None,
                f"{path}: cannot read packaged font pair",
            )
            pair_bytes.append(
                (bdf_name, bdf_stream.read(), otb_stream.read(), logical_identity)
            )

    import tempfile

    glyph_count = 0
    with tempfile.TemporaryDirectory(prefix="cadr-fonts-otb-check-") as directory:
        temporary = Path(directory)
        for index, (name, bdf_data, otb_data, logical_identity) in enumerate(pair_bytes):
            bdf_path = temporary / f"{index}.bdf"
            otb_path = temporary / f"{index}.otb"
            bdf_path.write_bytes(bdf_data)
            otb_path.write_bytes(otb_data)
            try:
                glyph_count += check_pair(bdf_path, otb_path, logical_identity)
            except OtbCheckError as error:
                raise OtbCheckError(f"{path}:{name}: {error}") from error
    return {
        "archive": str(path),
        "font_count": len(pair_bytes),
        "glyph_count": glyph_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        results = [check_archive(path.resolve()) for path in args.archives]
    except (OSError, OtbCheckError, tarfile.TarError) as error:
        parser.error(str(error))
    print(json.dumps({"status": "ok", "archives": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
