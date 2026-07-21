#!/usr/bin/env python3
"""Validate a generated CADR font distribution and its X-facing metadata."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from lisp_machine_fonts import safe_filename
from check_font_identities import (
    IdentityCheckError,
    check_bdf_profile,
    check_catalog_record,
    expected_source_record,
    load_distributed_mapping,
)


ROOT = Path(__file__).resolve().parents[1]


class CheckError(AssertionError):
    """A generated artifact violates a reviewed invariant."""


class XErrorEvent(ctypes.Structure):
    """The stable prefix of Xlib's XErrorEvent used by the validation hook."""

    _fields_ = [
        ("type", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("resource_id", ctypes.c_ulong),
        ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte),
        ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def round_ratio(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def parse_bdf(path: Path) -> dict[str, object]:
    lines = path.read_text(encoding="ascii").splitlines()
    require(lines and lines[0] == "STARTFONT 2.1", f"{path}: not BDF 2.1")
    require(lines[-1] == "ENDFONT", f"{path}: missing ENDFONT")

    def one(prefix: str) -> str:
        values = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
        require(len(values) == 1, f"{path}: expected one {prefix.strip()}")
        return values[0]

    font_name = one("FONT ")
    size = tuple(map(int, one("SIZE ").split()))
    font_box = tuple(map(int, one("FONTBOUNDINGBOX ").split()))
    property_start = next(
        index for index, line in enumerate(lines) if line.startswith("STARTPROPERTIES ")
    )
    property_count = int(lines[property_start].split()[1])
    property_end = lines.index("ENDPROPERTIES", property_start + 1)
    property_lines = lines[property_start + 1 : property_end]
    require(
        len(property_lines) == property_count,
        f"{path}: STARTPROPERTIES count mismatch",
    )
    properties: dict[str, str | int] = {}
    for line in property_lines:
        key, value = line.split(" ", 1)
        if value.startswith('"'):
            require(value.endswith('"'), f"{path}: unterminated property {key}")
            parsed: str | int = value[1:-1]
        else:
            parsed = int(value)
        require(key not in properties, f"{path}: duplicate property {key}")
        properties[key] = parsed

    declared_chars = int(one("CHARS "))
    glyphs = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("STARTCHAR "):
            index += 1
            continue
        start = index
        end = lines.index("ENDCHAR", start + 1)
        segment = lines[start : end + 1]

        def glyph_one(prefix: str) -> str:
            values = [line[len(prefix) :] for line in segment if line.startswith(prefix)]
            require(len(values) == 1, f"{path}: glyph missing {prefix.strip()}")
            return values[0]

        encoding_tokens = glyph_one("ENCODING ").split()
        require(
            len(encoding_tokens) == 1,
            f"{path}: glyph must use a direct primary CADR encoding",
        )
        encoding = int(encoding_tokens[0])
        swidth = tuple(map(int, glyph_one("SWIDTH ").split()))
        dwidth = tuple(map(int, glyph_one("DWIDTH ").split()))
        box = tuple(map(int, glyph_one("BBX ").split()))
        bitmap_index = segment.index("BITMAP")
        bitmap = segment[bitmap_index + 1 : -1]
        width, height, x_offset, y_offset = box
        require(len(bitmap) == height, f"{path}: bitmap height mismatch at {encoding}")
        byte_width = max(1, (width + 7) // 8)
        padding = byte_width * 8 - width
        rows = []
        for row in bitmap:
            require(
                len(row) == byte_width * 2,
                f"{path}: bitmap row width mismatch at {encoding}",
            )
            value = int(row, 16)
            require(
                padding == 0 or value & ((1 << padding) - 1) == 0,
                f"{path}: nonzero BDF row padding at {encoding}",
            )
            rows.append(value >> padding)
        glyphs.append(
            {
                "name": segment[0].split(" ", 1)[1],
                "encoding": encoding,
                "swidth": swidth,
                "dwidth": dwidth,
                "box": box,
                "rows": rows,
            }
        )
        index = end + 1

    require(len(glyphs) == declared_chars, f"{path}: CHARS count mismatch")
    require(
        len({glyph["encoding"] for glyph in glyphs}) == len(glyphs),
        f"{path}: duplicate encoding",
    )
    return {
        "font_name": font_name,
        "size": size,
        "font_box": font_box,
        "properties": properties,
        "glyphs": glyphs,
    }


def expected_spacing(bdf: dict[str, object]) -> str:
    glyphs = bdf["glyphs"]
    advances = {glyph["dwidth"][0] for glyph in glyphs}
    if len(advances) != 1:
        return "P"
    advance = next(iter(advances))
    ascent = bdf["properties"]["FONT_ASCENT"]
    descent = bdf["properties"]["FONT_DESCENT"]
    charcell = all(
        box[2] >= 0
        and box[2] + box[0] <= advance
        and box[3] >= -descent
        and box[3] + box[1] <= ascent
        for box in (glyph["box"] for glyph in glyphs)
    )
    return "C" if charcell else "M"


def check_bdf(
    path: Path,
    record: dict[str, object],
    normalized_root: Path,
    font_identities: dict[str, object],
) -> dict[str, object]:
    bdf = parse_bdf(path)
    profile = record["bdf"]
    require(bdf["font_name"] == profile["xlfd_name"], f"{path}: XLFD drift")
    fields = bdf["font_name"][1:].split("-")
    require(
        bdf["font_name"].startswith("-") and len(fields) == 14,
        f"{path}: incomplete XLFD name",
    )
    properties = bdf["properties"]
    field_properties = (
        "FOUNDRY",
        "FAMILY_NAME",
        "WEIGHT_NAME",
        "SLANT",
        "SETWIDTH_NAME",
        "ADD_STYLE_NAME",
        "PIXEL_SIZE",
        "POINT_SIZE",
        "RESOLUTION_X",
        "RESOLUTION_Y",
        "SPACING",
        "AVERAGE_WIDTH",
        "CHARSET_REGISTRY",
        "CHARSET_ENCODING",
    )
    for field, property_name in zip(fields, field_properties):
        require(
            str(properties[property_name]).casefold() == field.casefold(),
            f"{path}: XLFD field/property disagreement for {property_name}",
        )
    require(
        bdf["size"]
        == (
            profile["pixel_size"],
            profile["resolution_x"],
            profile["resolution_y"],
        ),
        f"{path}: SIZE/profile mismatch",
    )

    # These assertions derive the reviewed packaging policy from source-facing
    # catalog fields, not from the generated BDF profile.  That makes a shared
    # bdf_profile/catalog regression visible instead of merely self-consistent.
    character_height = record["character_height"]
    baseline = record["baseline"]
    logical_identity = check_catalog_record(
        record,
        expected_source_record(font_identities, record),
        context=str(path),
    )
    check_bdf_profile(profile, logical_identity, context=str(path))
    require(bdf["size"] == (character_height, 72, 72), f"{path}: wrong SIZE policy")
    require(properties["FOUNDRY"] == "MIT", f"{path}: wrong foundry policy")
    typography = logical_identity["typographic"]
    require(properties["FAMILY_NAME"] == typography["family_name"], f"{path}: wrong logical family")
    require(properties["WEIGHT_NAME"] == typography["weight_name"], f"{path}: wrong logical weight")
    require(properties["SLANT"] == typography["slant"], f"{path}: wrong logical slant")
    require(properties["SETWIDTH_NAME"] == typography["setwidth_name"], f"{path}: wrong logical setwidth")
    require(properties["ADD_STYLE_NAME"] == typography["add_style_name"], f"{path}: wrong representation style")
    require(properties["PIXEL_SIZE"] == character_height, f"{path}: wrong pixel size")
    require(
        properties["POINT_SIZE"] == character_height * 10,
        f"{path}: wrong 72 dpi point-size convention",
    )
    require(properties["RESOLUTION_X"] == 72, f"{path}: wrong horizontal DPI")
    require(properties["RESOLUTION_Y"] == 72, f"{path}: wrong vertical DPI")
    require(properties["FONT_ASCENT"] == baseline, f"{path}: wrong source baseline")
    require(
        properties["FONT_DESCENT"] == max(0, character_height - baseline),
        f"{path}: wrong source line descent",
    )
    require(
        profile["source_glyph_count"] == record["glyph_count"],
        f"{path}: source glyph count drift",
    )
    require(
        profile["bdf_glyph_count"] == len(bdf["glyphs"]),
        f"{path}: BDF glyph count drift",
    )
    require(
        profile["omitted_nonrendering_placeholder_count"]
        == record["glyph_count"] - len(bdf["glyphs"]),
        f"{path}: placeholder count drift",
    )
    require(properties["CHARSET_REGISTRY"] == "Misc", f"{path}: wrong registry")
    require(
        properties["CHARSET_ENCODING"] == "FontSpecific",
        f"{path}: false modern character-set identity",
    )
    require(
        all(0 <= glyph["encoding"] <= 0o177 for glyph in bdf["glyphs"]),
        f"{path}: character code outside the recovered seven-bit repertoire",
    )

    spacing = expected_spacing(bdf)
    require(properties["SPACING"] == spacing, f"{path}: wrong SPACING")
    average_width = round_ratio(
        sum(abs(glyph["dwidth"][0]) for glyph in bdf["glyphs"]) * 10,
        len(bdf["glyphs"]),
    )
    require(
        properties["AVERAGE_WIDTH"] == average_width,
        f"{path}: wrong AVERAGE_WIDTH",
    )
    for glyph in bdf["glyphs"]:
        expected_swidth = round_ratio(
            abs(glyph["dwidth"][0]) * 1000, character_height
        ) * (-1 if glyph["dwidth"][0] < 0 else 1)
        require(
            glyph["swidth"] == (expected_swidth, 0),
            f"{path}: SWIDTH mismatch at {glyph['encoding']}",
        )

    boxes = [glyph["box"] for glyph in bdf["glyphs"]]
    min_x = min(box[2] for box in boxes)
    max_x = max(box[2] + box[0] for box in boxes)
    min_y = min(box[3] for box in boxes)
    max_y = max(box[3] + box[1] for box in boxes)
    require(
        bdf["font_box"] == (max_x - min_x, max_y - min_y, min_x, min_y),
        f"{path}: FONTBOUNDINGBOX mismatch",
    )

    json_relative = record["outputs"].get("json")
    if json_relative is not None:
        normalized = json.loads((normalized_root / json_relative).read_text(encoding="utf-8"))
        placeholders = [
            glyph
            for glyph in normalized["glyphs"]
            if glyph["advance"] == 0
            and glyph["bitmap_width"] == 0
            and not any(int(row, 16) for row in glyph["rows"])
        ]
        require(
            len(placeholders) == profile["omitted_nonrendering_placeholder_count"],
            f"{path}: normalized placeholder inventory drift",
        )
        placeholder_codes = {glyph["code"] for glyph in placeholders}
        source_glyphs = {
            glyph["code"]: glyph
            for glyph in normalized["glyphs"]
            if glyph["code"] not in placeholder_codes
        }
        require(
            set(source_glyphs) == {glyph["encoding"] for glyph in bdf["glyphs"]},
            f"{path}: normalized/BDF repertoire mismatch",
        )
        for glyph in bdf["glyphs"]:
            source = source_glyphs[glyph["encoding"]]
            require(glyph["dwidth"] == (source["advance"], 0), f"{path}: DWIDTH drift")
            require(
                glyph["box"]
                == (
                    source["bitmap_width"],
                    len(source["rows"]),
                    source["x_offset"],
                    source["y_offset"],
                ),
                f"{path}: bearing/raster metric drift at {glyph['encoding']}",
            )
            require(
                glyph["rows"] == [int(row, 16) for row in source["rows"]],
                f"{path}: set pixels drift at {glyph['encoding']}",
            )
    return bdf


def semantic_inventory_digest(inventory: list[dict[str, object]]) -> str:
    """Hash reviewed line metrics and exact represented glyph geometry."""

    payload = json.dumps(
        sorted(inventory, key=lambda font: font["artifact"]),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def expected_aliases(
    catalog: dict[str, object],
    reserved_convenience_names: set[str] | frozenset[str] = frozenset(),
) -> dict[str, str]:
    aliases: dict[str, str] = {}

    def add(alias: str, xlfd: str) -> None:
        require(
            alias not in aliases or aliases[alias] == xlfd,
            f"alias collision for {alias}",
        )
        aliases[alias] = xlfd

    for record in catalog["fonts"]:
        xlfd = record["bdf"]["xlfd_name"]
        add(f'cadr-source-{safe_filename(record["name"])}', xlfd)
        convenience_name = safe_filename(record["name"])
        if convenience_name not in reserved_convenience_names:
            add(f"cadr-{convenience_name}", xlfd)
    return aliases


def check_checksums(output: Path) -> None:
    checksum_path = output / "SHA256SUMS"
    lines = checksum_path.read_text(encoding="ascii").splitlines()
    expected_paths = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path != checksum_path
    }
    observed_paths = set()
    for line in lines:
        digest, relative = line.split("  ", 1)
        path = output / relative
        require(path.is_file(), f"SHA256SUMS names missing file {relative}")
        require(sha256(path) == digest, f"checksum mismatch for {relative}")
        observed_paths.add(relative)
    require(observed_paths == expected_paths, "SHA256SUMS coverage mismatch")


def check_external_tools(
    output: Path,
    catalog: dict[str, object],
    reserved_convenience_names: set[str] | frozenset[str],
) -> dict[str, int | bool]:
    bdftopcf = shutil.which("bdftopcf")
    mkfontdir = shutil.which("mkfontdir")
    require(bdftopcf is not None, "bdftopcf is required for external validation")
    require(mkfontdir is not None, "mkfontdir is required for external validation")

    with tempfile.TemporaryDirectory(prefix="cadr-font-check-") as directory:
        temporary = Path(directory)
        for record in catalog["fonts"]:
            source = output / record["outputs"]["bdf"]
            destination = temporary / (source.stem + ".pcf")
            subprocess.run(
                [bdftopcf, str(source), "-o", str(destination)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        entries = sorted(
            (
                Path(record["outputs"]["bdf"]).stem + ".pcf",
                record["bdf"]["xlfd_name"],
            )
            for record in catalog["fonts"]
        )
        subprocess.run(
            [mkfontdir, str(temporary)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        generated_lines = (temporary / "fonts.dir").read_text(encoding="ascii").splitlines()
        require(int(generated_lines[0]) == len(entries), "mkfontdir PCF count changed")
        generated_entries = {
            filename: xlfd.casefold()
            for filename, xlfd in (line.split(" ", 1) for line in generated_lines[1:])
        }
        require(
            generated_entries
            == {filename: xlfd.casefold() for filename, xlfd in entries},
            "mkfontdir PCF names differ from reviewed XLFD names",
        )
        shutil.copyfile(output / "bdf" / "fonts.alias", temporary / "fonts.alias")

        xvfb = shutil.which("Xvfb")
        require(xvfb is not None, "Xvfb is required for external validation")
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XLoadQueryFont.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        x11.XLoadQueryFont.restype = ctypes.c_void_p
        x11.XFreeFont.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        error_handler_type = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent)
        )
        x_errors = []

        @error_handler_type
        def record_x_error(_display, event):
            x_errors.append(
                (
                    event.contents.error_code,
                    event.contents.request_code,
                    event.contents.minor_code,
                )
            )
            return 0

        x11.XSetErrorHandler.argtypes = [error_handler_type]
        x11.XSetErrorHandler(record_x_error)

        # Some desktop X servers leave a live Unix socket without the legacy
        # /tmp/.X<N>-lock file.  Xvfb -displayfd can then report that occupied
        # number before failing, and a client may accidentally connect to the
        # user's real display.  Allocate from a private high range, skip both
        # socket and lock witnesses, and require the spawned process to stay
        # alive before accepting the connection.
        server = None
        display = None
        display_number = None
        for candidate in range(1000, 1100):
            if Path(f"/tmp/.X{candidate}-lock").exists() or Path(
                f"/tmp/.X11-unix/X{candidate}"
            ).exists():
                continue
            candidate_server = subprocess.Popen(
                [
                    xvfb,
                    f":{candidate}",
                    "-screen",
                    "0",
                    "640x480x8",
                    "-nolisten",
                    "tcp",
                    "-fp",
                    str(temporary),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            deadline = time.monotonic() + 5
            candidate_display = None
            while time.monotonic() < deadline:
                if candidate_server.poll() is not None:
                    break
                candidate_display = x11.XOpenDisplay(f":{candidate}".encode("ascii"))
                if candidate_display:
                    break
                time.sleep(0.05)
            if candidate_display and candidate_server.poll() is None:
                server = candidate_server
                display = candidate_display
                display_number = candidate
                break
            if candidate_display:
                x11.XCloseDisplay(candidate_display)
            candidate_server.terminate()
            try:
                candidate_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                candidate_server.kill()
                candidate_server.wait(timeout=5)

        require(server is not None, "cannot start an isolated validation Xvfb")
        require(display is not None, "cannot connect to validation Xvfb")
        require(display_number is not None, "validation Xvfb has no display number")
        aliases = expected_aliases(catalog, reserved_convenience_names)
        try:
            for alias in sorted(aliases):
                encoded_alias = alias.encode("ascii")
                x_errors.clear()
                font = x11.XLoadQueryFont(display, encoded_alias)
                x11.XSync(display, 0)
                require(not x_errors, f"X error loading alias {alias}: {x_errors}")
                require(bool(font), f"X cannot load alias {alias}")
                x11.XFreeFont(display, font)
        finally:
            x11.XCloseDisplay(display)
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        return {
            "pcf_count": len(entries),
            "mkfontdir_indexed": True,
            "xvfb_alias_count": len(aliases),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--external-tools",
        action="store_true",
        help="compile/index every BDF as PCF and load every alias in Xvfb",
    )
    args = parser.parse_args()
    output = args.output.resolve()

    try:
        font_identities = load_distributed_mapping(output)
        catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
        runtime_catalog = json.loads(
            (output / "runtime" / "catalog.json").read_text(encoding="utf-8")
        )
        reserved_convenience_names = {
            safe_filename(record["runtime_name"])
            for record in runtime_catalog["font_artifacts"]
            if record["classification"] != "legacy-compiled-version"
        } | {"cm10", "cm12", "cptfon"}
        manifest = json.loads((ROOT / "config/source-manifest.json").read_text())
        require(
            (output / "SOURCE-MANIFEST.json").read_bytes()
            == (ROOT / "config/source-manifest.json").read_bytes(),
            "distribution source manifest is stale",
        )
        expected = manifest["expected_output"]
        for key in (
            "font_count",
            "logical_font_count",
            "variant_count",
            "character_pointer_partial_recovery_count",
            "extent_recovery_font_count",
            "extent_recovery_glyph_count",
        ):
            require(catalog[key] == expected[key], f"catalog {key} changed")
        require(
            len(catalog["rejected_sources"]) == expected["rejected_source_count"],
            "rejected source count changed",
        )

        xlfd_names = set()
        spacing_counts = {"C": 0, "M": 0, "P": 0}
        semantic_inventory = []
        normalized_semantic_inventory = []
        placeholder_count = 0
        placeholder_font_count = 0
        for record in catalog["fonts"]:
            path = output / record["outputs"]["bdf"]
            bdf = check_bdf(path, record, output, font_identities)
            semantic_inventory.append(
                {
                    "artifact": Path(record["outputs"]["bdf"]).name,
                    "size": bdf["size"],
                    "font_box": bdf["font_box"],
                    "font_ascent": bdf["properties"]["FONT_ASCENT"],
                    "font_descent": bdf["properties"]["FONT_DESCENT"],
                    "glyphs": [
                        {
                            "encoding": glyph["encoding"],
                            "dwidth": glyph["dwidth"],
                            "box": glyph["box"],
                            "rows": glyph["rows"],
                        }
                        for glyph in bdf["glyphs"]
                    ],
                }
            )
            json_relative = record["outputs"].get("json")
            require(
                json_relative is not None,
                "normalized JSON is required for the full semantic gate",
            )
            normalized = json.loads(
                (output / json_relative).read_text(encoding="utf-8")
            )
            normalized_semantic_inventory.append(
                {
                    "artifact": Path(json_relative).name,
                    "character_height": normalized["character_height"],
                    "raster_height": normalized["raster_height"],
                    "baseline": normalized["baseline"],
                    "glyphs": [
                        {
                            "code": glyph["code"],
                            "bitmap_width": glyph["bitmap_width"],
                            "advance": glyph["advance"],
                            "x_offset": glyph["x_offset"],
                            "y_offset": glyph["y_offset"],
                            "rows": [int(row, 16) for row in glyph["rows"]],
                        }
                        for glyph in normalized["glyphs"]
                    ],
                }
            )
            xlfd = record["bdf"]["xlfd_name"].casefold()
            require(xlfd not in xlfd_names, f"duplicate XLFD {xlfd}")
            xlfd_names.add(xlfd)
            spacing_counts[record["bdf"]["spacing"]] += 1
            omitted_placeholders = record["bdf"][
                "omitted_nonrendering_placeholder_count"
            ]
            placeholder_count += omitted_placeholders
            placeholder_font_count += omitted_placeholders > 0
            adjustment = record["observations"].get("column_position_adjustment")
            require(
                adjustment in (None, 0),
                f"unmodeled tracking in {record['name']}: {adjustment}",
            )
        require(
            spacing_counts == expected["spacing_counts"],
            f"spacing inventory changed: {spacing_counts}",
        )

        findings = manifest["reviewed_findings"]
        require(
            {
                "font_count": placeholder_font_count,
                "slot_count": placeholder_count,
            }
            == findings["bdf_omitted_nonrendering_placeholders"],
            "BDF placeholder omission inventory changed",
        )
        semantic_digest = semantic_inventory_digest(semantic_inventory)
        normalized_semantic_digest = semantic_inventory_digest(
            normalized_semantic_inventory
        )
        require(
            semantic_digest == findings["bdf_semantic_inventory"]["sha256"],
            f"reviewed BDF semantic inventory changed: {semantic_digest}",
        )
        require(
            normalized_semantic_digest
            == findings["normalized_semantic_inventory"]["sha256"],
            "reviewed normalized semantic inventory changed: "
            f"{normalized_semantic_digest}",
        )
        records_by_name = {record["name"]: record for record in catalog["fonts"]}
        for name, heights in findings["ast_raster_heights"].items():
            record = records_by_name[name]
            require(
                {
                    "character_height": record["character_height"],
                    "raster_height": record["raster_height"],
                }
                == heights,
                f"AST raster-height recovery changed for {name}",
            )
        actual_partial = {
            recovery["logical_name"]: recovery["omitted_character_codes"]
            for recovery in catalog["character_pointer_partial_recoveries"]
        }
        require(
            actual_partial == findings["character_pointer_partial_recoveries"],
            f"partial recovery inventory changed: {actual_partial}",
        )
        actual_runtime = {
            record["logical_name"]: record["runtime_name"]
            for record in catalog["fonts"]
            if record["runtime_name"] != record["logical_name"]
        }
        require(
            actual_runtime == findings["runtime_name_overrides"],
            f"runtime-name evidence mapping changed: {actual_runtime}",
        )

        expected_fonts_dir = sorted(
            (
                Path(record["outputs"]["bdf"]).name,
                record["bdf"]["xlfd_name"],
            )
            for record in catalog["fonts"]
        )
        fonts_dir_lines = (output / "bdf" / "fonts.dir").read_text().splitlines()
        require(int(fonts_dir_lines[0]) == len(expected_fonts_dir), "fonts.dir count")
        require(
            fonts_dir_lines[1:]
            == [f"{name} {xlfd}" for name, xlfd in expected_fonts_dir],
            "fonts.dir mappings changed",
        )
        aliases = expected_aliases(catalog, reserved_convenience_names)
        fonts_alias_lines = (output / "bdf" / "fonts.alias").read_text().splitlines()
        require(
            fonts_alias_lines
            == ["! Source-profile aliases; XLFD names remain authoritative."]
            + [
                f'{alias} "{aliases[alias]}"'
                for alias in sorted(aliases)
            ],
            "fonts.alias mappings changed",
        )
        check_checksums(output)
        for generator in catalog["generator"]["files"]:
            require(
                sha256(ROOT / generator["path"]) == generator["sha256"],
                f"stale generator hash for {generator['path']}",
            )
        external_result = (
            check_external_tools(
                output, catalog, reserved_convenience_names
            )
            if args.external_tools
            else None
        )
    except (
        CheckError,
        IdentityCheckError,
        KeyError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(output),
                "font_count": catalog["font_count"],
                "spacing_counts": spacing_counts,
                "external_tools": args.external_tools,
                "external_result": external_result,
                "semantic_inventory_sha256": semantic_digest,
                "normalized_semantic_inventory_sha256": (
                    normalized_semantic_digest
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
