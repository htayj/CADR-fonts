# Font model and X conversion

## Historical normalized model

Every selected source becomes a one-bit `BitmapFont` with:

- character/line height;
- authored raster height;
- baseline;
- original CADR character code;
- glyph raster width and rows;
- signed per-character advance;
- signed per-character left bearing.

AST's line height and raster height are distinct. The historical compiler
computes raster height as the greatest number of rows actually authored in any
glyph, then stores shorter glyphs with blank lower rows. Four primary artifacts
make the distinction observable:

| Font | Character height | Raster height |
| --- | ---: | ---: |
| `APL14` | 15 | 14 |
| `BUG` | 33 | 32 |
| `GLS7X9` | 16 | 14 |
| `SWFONT` | 32 | 22 |

The old sibling converter padded these to line height. Correcting the model
also exposes `BUG-KST`: its KST raster is 33 rows, so it is no longer suppressed
as identical to the 32-row AST representation.

## Bearings, advance, kerning, and tracking

The CADR renderer looks up the current character width, draws at
`cursor-x - left-kern`, and then moves the cursor by the width. Consequently:

| CADR value | BDF value |
| --- | --- |
| character width | `DWIDTH x` |
| negative left-kern | positive `BBX xoff` |
| positive left-kern | negative `BBX xoff` |
| baseline | `FONT_ASCENT` |
| character height minus baseline | `FONT_DESCENT` |

“Left kern” is historical terminology for a glyph-specific bearing. It is not
a previous/next-character pair adjustment. No pair-kerning data exists in
these representations.

AST and KST contain a field called column-position adjustment. Historical
`RD-AST` reads and discards the AST value, while the historical KST converter
explicitly rejects a nonzero value because its meaning was unknown. All
selected AST and KST values are zero. This decoder conservatively rejects a
nonzero value in either representation instead of guessing that it is
tracking; no additional letter spacing is applied.

## Bitmap and vertical overflow policy

BDF bitmap rows preserve every decoded set pixel and, for emitted glyphs, the
represented source raster box; the writer does not crop transparent storage
columns or rows. Character advance remains independent of raster width, so
overhangs survive.

XLFD permits individual glyphs to extend beyond the recommended font ascent or
descent. `PRT12B-AL-AR1` code octal `030` has a recovered row below its declared
line height, so its glyph and font bounding boxes extend one row below
`FONT_DESCENT`. The build preserves and tests this fact instead of changing the
declared interline metric or clipping the pixel.

### Zero-width source slots

The historical Alto reader constructs all 128 character-descriptor slots.
Across 62 recovered Alto fonts, 1,855 of those slots have zero raster width,
zero advance, and no set pixels. They are real source-table observations and
remain in normalized JSON and specimen generation, but they have no rendering
effect.

`bdftopcf` accepts a BDF containing those zero-width glyphs, but Xorg's bitmap
font renderer rejects the resulting PCF at `OpenFont` with `BadAlloc`. The
installable BDF profile therefore omits exactly those no-op slots. It does not
omit zero-advance glyphs that have raster width or ink. The corpus validator
checks the per-font omission inventory against JSON, the committed total, and
an actual all-alias Xvfb load.

## XLFD profile

Each BDF `FONT` has all fourteen XLFD fields:

```text
-Misc-MIT CADR HL10-Unknown-OT-Unknown--12-120-72-72-P-70-Misc-FontSpecific
```

- `Misc` is the conservative X foundry/charset namespace.
- Family is `MIT CADR <proven runtime name>` where runtime evidence exists,
  otherwise `MIT CADR <authored logical name>`.
- Weight, slant, and setwidth remain `Unknown`, `OT`, and `Unknown`. Opaque
  historical filename suffixes are not treated as authoritative typography.
- `ADD_STYLE_NAME` distinguishes source variants (`KST`, `AL AR1`).
- Pixel size is the source character height.
- Point size is ten times pixel size in decipoints at a packaging resolution of
  72 dpi. This is an interchange convention, not a historical display-DPI
  claim.
- `AVERAGE_WIDTH` is the rounded arithmetic mean of absolute advances in tenths
  of pixels, as XLFD specifies.

The official [XLFD conventions](https://www.x.org/releases/X11R7.6/doc/xorg-docs/specs/XLFD/xlfd.html)
define `P` as variable advance, `M` as constant advance, and `C` as constant
advance with every represented character box inside the common cell. The
reviewed installable output is 134 `P`, two `M` (`APL14` and its Alto variant),
and 15 `C` artifacts. The additional character-cell result is the `GACHA8`
Alto variant; once its no-op slots are excluded, all emitted glyphs have the
same advance and fit the cell. The newly preserved `BUG-KST` is also `C`.

## Character encoding boundary

The original codes occupy octal `000` through `177`, but they are Lisp Machine
codes—not a Unicode or ISO-8859 claim. For every emitted glyph, BDF `ENCODING`
uses the original numeric value directly, while XLFD declares
`Misc-FontSpecific`. This makes the fonts addressable by the X core-font
protocol without falsely relabelling the repertoire. Normalized JSON retains
the no-op Alto slots that the installable profile cannot emit.

The per-font normalized JSON is the archival record of raw source codes,
metrics, and rows. A future Unicode mapping, if desired, must be a separate,
reviewed derivative rather than a silent change to this profile.

The output syntax and `SWIDTH`/`DWIDTH` conversion follow the official
[BDF 2.1 standard](https://www.x.org/releases/X11R7.0/doc/PDF/bdf.pdf).
