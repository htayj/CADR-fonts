# Font model and X conversion

## Two normalized models

The distribution keeps source identity and resident runtime identity separate.
Neither profile is treated as a disposable intermediate for the other.

### Authored-source model

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

### System 46 runtime model

Every reviewed `.qfasl` in `src/lmfont` is decoded into the serialized resident
`FONT` array it would install. The runtime model retains:

- the exact bound symbol and serialized leader name;
- character height, raster height, baseline, and fixed width;
- optional 128-entry advance, left-kern, and existence tables;
- the optional 129-entry indexing table used by wide characters;
- every represented character code, storage width, advance, bearing, and
  one-bit raster row.

This is an inert object decode, not execution or emulation. The decoder accepts
only the reviewed QFASL serialization operations, verifies each input's size,
SHA-256, decoded PDP-10-word digest, nibble count, and complete consumption,
and rejects all other operations. It does not evaluate a Lisp form or execute
a Lisp Machine instruction.

The closed runtime corpus contains 49 compiled objects:

- 30 current objects with surviving source-profile counterparts;
- 17 current compiled-only fonts: `20VR`, `31VR`, `40VR`, `BIGVG`,
  `CPT-13FG`, `CPT-HL10`, `CPT-HL10B`, `CPT-TR10I`, `GERM35`, `HL12BI`,
  `MEDFNB`, `S30CHS`, `S35GER`, `SAIL12`, `SEARCH`, `SHIP`, and `TR12B1`;
- two explicitly older objects, `N43XMS` and `NTOG`, whose resident names
  collide with current `43VXMS` and `TOG` respectively.

There are therefore 47 current runtime logical names, not 49. A legacy object
never displaces the current object sharing its resident name.

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

The runtime `FONT` arrays make the same display distinction explicit: their
width table is escapement and their left-kern table is a fixed bearing. They
contain no pair-keyed table and the runtime exporter adds no tracking.

## Source/runtime display comparison

For the 30 source-backed runtime objects, the comparison is performed in
baseline-relative display coordinates: character advance, fixed x bearing,
and every set pixel. Compiler storage padding is not a visible difference.

The reviewed source reference is exact for 28 of the 30 source-backed runtime
objects. `ARROW` and `BIGFNT` reach that exact result through their KST variants
rather than the source-profile canonical artifacts; current `MEDFNT` is
genuinely divergent, and source `MOUSE` represents only a visible subset. Four
names therefore require care when the question is what all defined resident
codes display:

| Runtime name | Source-profile observation | Runtime-correct result |
| --- | --- | --- |
| `ARROW` | Canonical `ARROW` lacks visible codes `003` and `006`. | `ARROW-KST` and the QFASL object contain both and match for all 16 visible glyphs. |
| `BIGFNT` | Canonical `BIGFNT` differs at `155` and lacks visible `000`, `006`, `022`, `023`, `033`, and `036`. | `BIGFNT-KST` matches the resident object across all 128 slots. |
| `MEDFNT` | The authored form matches the older `medfnt.oqfasl`. | Current `medfnt.qfasl` changes 57 previously visible glyphs and makes `000`, `011`, `012`, `014`, `015`, and `177` visible. |
| `MOUSE` | The KST source lacks three resident images. | The QFASL adds visible `034`, `035`, and `036`. |

The runtime BDFs carry the decompiled objects directly. Source BDFs retain the
authored observations, including `ARROW-KST` and `BIGFNT-KST`, instead of being
rewritten to resemble a later compiled file.

`N43XMS` is a genuinely different older `43VXMS`: 69 glyphs have different set
pixels from the current object. `NTOG` is display-identical to current `TOG`
and differs only in serialized leader layout. Both remain provenance-labelled
legacy artifacts rather than alternate current aliases.

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

### Zero-width no-op slots

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

The runtime model applies the same lossless/installable boundary. Its 49
objects contain 6,170 normalized slots. Exactly 481 slots have zero width, zero
advance, and no ink; they remain in runtime JSON but are omitted from BDF,
leaving 5,689 installable runtime glyphs. No zero-width glyph with ink or
nonzero advance is silently discarded. Together with the source profile's
14,618 emitted glyphs, the 200 BDFs contain 20,307 glyphs.

## CADR sheet-level vertical layout

Per-font BDF metrics are necessary but not sufficient to reproduce a complete
CADR text layout. System 46's [`SHEET :INIT`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/sheet.383#L397-L426)
defaults vertical spacing (`VSP`) to two pixels. Its
[`SHEET-NEW-FONT-MAP`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/sheet.383#L507-L539)
sets:

```text
sheet baseline = maximum FONT baseline in the font map
line height    = maximum FONT character height in the font map + VSP
```

When the current font changes,
[`SHEET-SET-FONT`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/shwarm.162#L80-L83)
sets `BASELINE-ADJ` to the sheet baseline minus that font's baseline. Mixed
fonts on one line therefore share the font-map baseline even when their own
ascents differ, and successive default lines are separated by two pixels more
than the tallest character height.

BDF has no field for a sheet's font map or VSP. The distribution preserves
each font's ascent/descent in BDF and tests the default VSP and mixed-baseline
rules in an independent layout model; applications seeking CADR-like whole-line
layout must apply that policy themselves.

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
- `ADD_STYLE_NAME` distinguishes source variants (`KST`, `AL AR1`), current
  resident objects (`System 46 Runtime`), and the two explicitly named legacy
  compiled objects (`System 46 Legacy N43XMS` and `System 46 Legacy NTOG`).
  This keeps all 200 full XLFD names collision-free.
- Pixel size is the source character height.
- Point size is ten times pixel size in decipoints at a packaging resolution of
  72 dpi. This is an interchange convention, not a historical display-DPI
  claim.
- `AVERAGE_WIDTH` is the rounded arithmetic mean of absolute advances in tenths
  of pixels, as XLFD specifies.

The official [XLFD conventions](https://www.x.org/releases/X11R7.6/doc/xorg-docs/specs/XLFD/xlfd.html)
define `P` as variable advance, `M` as constant advance, and `C` as constant
advance with every represented character box inside the common cell. The
reviewed source profile is 134 `P`, two `M` (`APL14` and its Alto variant), and
15 `C` artifacts. The additional character-cell result is the `GACHA8` Alto
variant; once its no-op slots are excluded, all emitted glyphs have the same
advance and fit the cell. The newly preserved `BUG-KST` is also `C`. The
runtime profile is independently classified as 37 `P`, five `M`, and seven
`C`; combined, the 200 BDFs are 171 `P`, seven `M`, and 22 `C`.

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

The native X rendering gate intentionally constructs probes only from codes
defined in each emitted BDF. Every defined raw eight-bit code is drawn through
the X core protocol at 1x and compared pixel-for-pixel with an independent BDF
renderer; advances and text extents are checked at the same time. Behavior for
an absent code—including X default-character or fallback substitution—is
explicitly outside the conformance claim and is not treated as evidence of a
CADR display difference.

The output syntax and `SWIDTH`/`DWIDTH` conversion follow the official
[BDF 2.1 standard](https://www.x.org/releases/X11R7.0/doc/PDF/bdf.pdf).
