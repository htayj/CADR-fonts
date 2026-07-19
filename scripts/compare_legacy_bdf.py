#!/usr/bin/env python3
"""Compare current BDF geometry with the earlier genera-emu artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEGACY = ROOT.parent / "genera-emu" / "docs" / "assets" / "mit-cadr-fonts" / "bdf"


class ComparisonError(AssertionError):
    """The current distribution is not geometrically legacy-compatible."""


@dataclass(frozen=True)
class GlyphGeometry:
    advance: tuple[int, int]
    bitmap_width: int
    x_offset: int
    pixels: frozenset[tuple[int, int]]


def parse_geometry(path: Path) -> dict[int, GlyphGeometry]:
    lines = path.read_text(encoding="ascii").splitlines()
    glyphs: dict[int, GlyphGeometry] = {}
    index = 0
    while index < len(lines):
        if not lines[index].startswith("STARTCHAR "):
            index += 1
            continue
        end = lines.index("ENDCHAR", index + 1)
        segment = lines[index : end + 1]

        def one(prefix: str) -> str:
            values = [line[len(prefix) :] for line in segment if line.startswith(prefix)]
            if len(values) != 1:
                raise ComparisonError(f"{path}: expected one glyph {prefix.strip()}")
            return values[0]

        encoding = one("ENCODING ").split()
        if len(encoding) == 1:
            code = int(encoding[0])
        elif len(encoding) == 2 and encoding[0] == "-1":
            code = int(encoding[1])
        else:
            raise ComparisonError(f"{path}: unsupported BDF encoding {encoding!r}")
        advance = tuple(map(int, one("DWIDTH ").split()))
        width, height, x_offset, y_offset = map(int, one("BBX ").split())
        bitmap_index = segment.index("BITMAP")
        rows = segment[bitmap_index + 1 : -1]
        if len(rows) != height:
            raise ComparisonError(f"{path}: bitmap height mismatch at code {code}")
        byte_width = max(1, (width + 7) // 8)
        pixels = set()
        for row_index, row in enumerate(rows):
            if len(row) != byte_width * 2:
                raise ComparisonError(f"{path}: bitmap width mismatch at code {code}")
            value = int(row, 16)
            for column in range(width):
                mask = 1 << (byte_width * 8 - 1 - column)
                if value & mask:
                    # BDF rows run top-to-bottom; compare in baseline-relative
                    # coordinates so transparent AST padding is immaterial.
                    pixels.add(
                        (x_offset + column, y_offset + height - 1 - row_index)
                    )
        # The new installable profile omits source slots that have no advance,
        # no width, and no ink because Xorg rejects zero-width PCF glyphs.  The
        # normalized JSON remains the lossless record.  Apply the same no-op
        # normalization to the legacy side before comparing visible geometry.
        if width == 0 and advance == (0, 0) and not pixels:
            index = end + 1
            continue
        if code in glyphs:
            raise ComparisonError(f"{path}: duplicate glyph code {code}")
        glyphs[code] = GlyphGeometry(
            advance=(advance[0], advance[1]),
            bitmap_width=width,
            x_offset=x_offset,
            pixels=frozenset(pixels),
        )
        index = end + 1
    return glyphs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--current", type=Path, default=ROOT / "dist" / "bdf")
    parser.add_argument(
        "--expected-added",
        nargs="*",
        default=["bug-kst.bdf"],
        help="current-only BDF basenames expected from reviewed converter fixes",
    )
    args = parser.parse_args()
    legacy_root = args.legacy.resolve()
    current_root = args.current.resolve()

    try:
        if not legacy_root.is_dir():
            raise ComparisonError(f"legacy BDF directory is missing: {legacy_root}")
        if not current_root.is_dir():
            raise ComparisonError(f"current BDF directory is missing: {current_root}")
        legacy = {path.name: path for path in legacy_root.glob("*.bdf")}
        current = {path.name: path for path in current_root.glob("*.bdf")}
        removed = sorted(legacy.keys() - current.keys())
        added = sorted(current.keys() - legacy.keys())
        if removed:
            raise ComparisonError(f"legacy artifacts removed: {removed}")
        if added != sorted(args.expected_added):
            raise ComparisonError(
                f"current-only artifacts changed: expected={sorted(args.expected_added)}, "
                f"observed={added}"
            )

        changed = []
        for name in sorted(legacy.keys() & current.keys()):
            old_glyphs = parse_geometry(legacy[name])
            new_glyphs = parse_geometry(current[name])
            if old_glyphs != new_glyphs:
                codes = sorted(
                    code
                    for code in old_glyphs.keys() | new_glyphs.keys()
                    if old_glyphs.get(code) != new_glyphs.get(code)
                )
                changed.append({"font": name, "character_codes": codes})
        if changed:
            raise ComparisonError(
                "glyph repertoire, advance, bearing, or set-pixel changes: "
                + json.dumps(changed[:20], sort_keys=True)
            )
    except (ComparisonError, OSError, ValueError) as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "status": "ok",
                "legacy_font_count": len(legacy),
                "current_font_count": len(current),
                "common_geometry_matches": len(legacy),
                "added": added,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
