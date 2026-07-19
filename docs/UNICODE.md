# CADR Fonts Unicode profile

This document defines **CADR Fonts Unicode Mapping version 1**, the recommended
Unicode-encoded derivative of the recovered MIT CADR System 46 bitmap fonts.
It is a project mapping for interoperable use of this distribution, not a
claim that the historical CADR files contained Unicode data.

The Unicode profile changes only character encodings and the corresponding
XLFD registry/encoding identity. It preserves each selected artifact's bitmap
rows, advance, signed bearing, line metrics, spacing classification, source or
runtime identity, and the no-op-slot omission policy. It does not trace bitmaps
into outlines, synthesize characters, or merge source and runtime
representations.

The raw preservation profiles remain authoritative and unchanged:

- `dist/bdf/` and `dist/runtime/bdf/` retain the original seven-bit CADR code
  in each BDF `ENCODING` and retain `Misc-FontSpecific` XLFD encoding fields;
- the source and runtime JSON catalogs continue to record raw CADR slots;
- Unicode BDFs are a derived, separately named view and never replace a raw
  BDF or raw alias.

## Mapping selection

Every emitted glyph is mapped by one of three closed rules:

1. The seven source logical names and 13 runtime artifacts whose represented
   slots agree with the pinned System 46 table use the
   [standard CADR character map](#standard-cadr-character-map).
2. Ordinary text families with an older or mixed code layout use a reviewed
   **hybrid map**. Proven standard positions remain ordinary Unicode;
   documented relocations are remapped; only divergent or undocumented slots
   use that family's reserved PUA block.
3. The 17 application/symbol repertoires without a proved per-code semantic
   table use one family PUA block for every raw code.

Classification is closed over all 88 source logical names and all 49 runtime
artifacts. It uses pinned loader/source evidence and reviewed positional
inventories, not an automatic bitmap recognizer. In particular, a raw code in
the ASCII numeric range is **not** mapped to ASCII when that repertoire
repurposes it. For example, SHIP raw octal `100` maps to U+E740, not U+0040,
while an Alto Latin `A` at raw `101` remains U+0041.

Only a slot represented by an emitted raw BDF glyph receives a Unicode BDF
`ENCODING`. A block reservation does not create a character for an absent or
zero-width, zero-advance, no-ink slot.

## Standard CADR character map

The standard repertoire is the Stanford/ITS extended-ASCII printing set used
by CADR. The pinned CADR
[`char.18`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmdoc/char.18#L3-L40)
lists all raw codes octal `000` through `177` as printing characters and names
the non-ASCII positions. The keyboard table in
[`kbd.123`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/kbd.123#L288-L361)
and reader names in
[`rddefs.19`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/rddefs.19#L68-L105)
provide independent code/name evidence.

The complete direct-use whitelist is deliberately small:

- source logical names: `13FG`, `13FGB`, `16FG`, `43VXMS`, `5X5`, `CPTFON`,
  and `HAFONT`;
- runtime artifacts: `13FGB`, `16FG`, `31VR`, `40VR`, `43VXMS`, `5X5`,
  `BIGVG`, `CPT-13FG`, `CPTFONT`, `MEDFNB`, `MEDFNT`, `N43XMS`, and
  `S35GER`.

The same table is also the starting point for the hybrid maps below, but only
after their explicit PUA masks and remaps are applied. An unlisted artifact
never falls back to this table implicitly.

[RFC 734, "SUPDUP Protocol"](https://www.rfc-editor.org/rfc/rfc734.html),
page 12, defines the corresponding Stanford/ITS printing repertoire. Its input
table shows the TOP bit in values `4000` through `4037` and `4177`; for display
output, the RFC specifies the low seven-bit codes. The mappings below therefore
use the raw CADR values `000` through `177`.

| Raw (octal) | Unicode | Unicode character name |
| ---: | ---: | --- |
| `000` | U+22C5 | DOT OPERATOR |
| `001` | U+2193 | DOWNWARDS ARROW |
| `002` | U+03B1 | GREEK SMALL LETTER ALPHA |
| `003` | U+03B2 | GREEK SMALL LETTER BETA |
| `004` | U+2227 | LOGICAL AND |
| `005` | U+00AC | NOT SIGN |
| `006` | U+03B5 | GREEK SMALL LETTER EPSILON |
| `007` | U+03C0 | GREEK SMALL LETTER PI |
| `010` | U+03BB | GREEK SMALL LETTER LAMDA |
| `011` | U+03B3 | GREEK SMALL LETTER GAMMA |
| `012` | U+03B4 | GREEK SMALL LETTER DELTA |
| `013` | U+2191 | UPWARDS ARROW |
| `014` | U+00B1 | PLUS-MINUS SIGN |
| `015` | U+2295 | CIRCLED PLUS |
| `016` | U+221E | INFINITY |
| `017` | U+2202 | PARTIAL DIFFERENTIAL |
| `020` | U+2282 | SUBSET OF |
| `021` | U+2283 | SUPERSET OF |
| `022` | U+2229 | INTERSECTION |
| `023` | U+222A | UNION |
| `024` | U+2200 | FOR ALL |
| `025` | U+2203 | THERE EXISTS |
| `026` | U+2297 | CIRCLED TIMES |
| `027` | U+2194 | LEFT RIGHT ARROW |
| `030` | U+2190 | LEFTWARDS ARROW |
| `031` | U+2192 | RIGHTWARDS ARROW |
| `032` | U+2260 | NOT EQUAL TO |
| `033` | U+25CA | LOZENGE |
| `034` | U+2264 | LESS-THAN OR EQUAL TO |
| `035` | U+2265 | GREATER-THAN OR EQUAL TO |
| `036` | U+2261 | IDENTICAL TO |
| `037` | U+2228 | LOGICAL OR |
| `040`-`176` | U+0020-U+007E | ASCII identity mapping |
| `177` | U+222B | INTEGRAL |

Two easily confused positions are fixed explicitly. RFC 734 calls raw `000`
"centered dot" in a mathematical repertoire; [Unicode distinguishes the
punctuation U+00B7 MIDDLE DOT from U+22C5 DOT
OPERATOR](https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-22/#G56893)
and recommends the latter for mathematical use. Raw `000` is therefore
U+22C5. RFC 734 calls raw `033` "lozenge (diamond)"; it is U+25CA LOZENGE,
not U+25C7 WHITE DIAMOND. These choices are normative for mapping version 1.

## BMP Private Use allocation

The allocation covers both whole-PUA specialty repertoires and the exceptional
slots of hybrid text repertoires. It reserves 28 aligned blocks of 128 code
points in the Unicode Basic Multilingual Plane Private Use Area.

For a family with block start `S` and a validated raw CADR code `r` in decimal
range 0 through 127, the exact mapping is:

```text
Unicode scalar = S + r
```

The numerical value of `r` is unchanged; source notation normally writes it
in octal. Thus ARROW raw `003` is U+E103 and Alto Latin raw `000` is U+E800.
A hybrid override takes precedence over the formula: Alto Latin raw `030` is
U+005F, not U+E818.

| Index | Family | Reserved range | Raw codes routed to this PUA block |
| ---: | --- | ---: | --- |
| 0 | APL14 | U+E000-U+E07F | `000-177` |
| 1 | ARR10 | U+E080-U+E0FF | `000-177` |
| 2 | ARROW | U+E100-U+E17F | `000-177` |
| 3 | BUG | U+E180-U+E1FF | `000-177` |
| 4 | CLARGK | U+E200-U+E27F | `000-177` |
| 5 | CYR12 | U+E280-U+E2FF | `000-177` |
| 6 | GATES | U+E300-U+E37F | `000-177` |
| 7 | MATH | U+E380-U+E3FF | `000-177` |
| 8 | MUSC10 | U+E400-U+E47F | `000-177` |
| 9 | PLNK16 | U+E480-U+E4FF | `000-177` |
| 10 | MOUSE | U+E500-U+E57F | `000-177` |
| 11 | TOG | U+E580-U+E5FF | `000-177` |
| 12 | SWFONT | U+E600-U+E67F | `000-177` |
| 13 | SEARCH | U+E680-U+E6FF | `000-177` |
| 14 | SHIP | U+E700-U+E77F | `000-177` |
| 15 | S30CHS | U+E780-U+E7FF | `000-177` |
| 16 | Alto Latin | U+E800-U+E87F | `000-027`, `032-037`, `177` |
| 17 | Alto Stanford display | U+E880-U+E8FF | `000-037`, `100`, `140`, `177` |
| 18 | Alto Greek/math | U+E900-U+E97F | `000-177` |
| 19 | CADR solid-zero | U+E980-U+E9FF | `000` |
| 20 | BIGFNT | U+EA00-U+EA7F | `000`, `136`, `137`, `177` |
| 21 | CM | U+EA80-U+EAFF | `000-037`, `177` |
| 22 | GLS7X9 | U+EB00-U+EB7F | `000-037`, `177` |
| 23 | METS/NON | U+EB80-U+EBFF | `000-027`, `032-037`, `177` |
| 24 | SAIL | U+EC00-U+EC7F | `013`, `177` |
| 25 | 40VSHD | U+EC80-U+ECFF | `032` |
| 26 | 20VR | U+ED00-U+ED7F | `001-032` |
| 27 | GERM35 | U+ED80-U+EDFF | `000-037`, `177` |

All 3,584 positions from U+E000 through U+EDFF are reserved. In a hybrid
block, offsets not listed in the final column remain reserved but unused; they
are not available to another family. This keeps every published
family/raw-code identity append-stable even when one representation lacks a
glyph. Reserved but absent positions and zero-width, zero-advance, no-ink
placeholders are not synthesized. U+EE00 through U+F8FF remain unallocated by
this profile, leaving 22 aligned blocks for later evidence.

Source variants, current runtime objects, and labelled legacy runtime objects
share a PUA scalar only when they have the same reviewed family and raw code.
Geometry may differ without changing that identity. A future release may
populate a reserved position when new evidence supplies a glyph, but mapping
version 1 must never move, merge, or reuse a block or raw-code position.

### Family membership and evidence limits

The source archive directory in
[`fcmp.xfile`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmfont/fcmp.xfile#L1-L73)
is evidence for historical font identity and naming. The source and runtime
manifests close the actual artifact inventory used here. Names and visual
resemblance alone are not evidence for a standardized Unicode character.

The Alto boundary has direct implementation evidence. The pinned
[`READ-AL-INTO-FONT-DESCRIPTOR`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fntcnv.28#L757-L802)
stores each unmodified Alto character index `CH` into the CADR descriptor; it
does not translate that index through `char.18`. The pinned reader also calls
raw `137` [“underline (old
leftarrow)”](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/fread.21#L78-L92).
Those sources explain the recurring old-arrow layout independently of bitmap
appearance.

#### Hybrid and alternate text repertoires

Except where the table says “whole PUA,” every code not named in the PUA or
remap columns inherits the standard CADR mapping. Remaps are chosen as a set,
so every effective repertoire remains injective: a relocated arrow's old
canonical slot is sent to PUA or exchanged with the displaced punctuation.

| Repertoire | Covered artifacts | Reviewed remaps and evidence boundary |
| --- | --- | --- |
| Alto Latin | Source logical names `CHA`, `CHAS`, `CLAR`, `CLAR12`, `CLAR14`, `CLARB`, `CLRE14`, `GACH10`, `GACH12`, `GACHA8`, all `HL*`, `PRNT10`, `PRONTO`, `PRT12B`, `TNTO14`, `TNTOB`, `TONTO`, and all `TR*`; runtime `CPT-HL10`, `CPT-HL10B`, `CPT-TR10I`, the resident `HL*`, `PRT12B`, and resident `TR*` artifacts | Raw `030` is U+005F LOW LINE, `136` is U+2191 UPWARDS ARROW, and `137` is U+2190 LEFTWARDS ARROW. Raw `000-027`, `032-037`, and `177` use PUA. The pinned Alto loader and the shared positional pattern establish one untranslated text repertoire across sizes and styles. |
| Alto Stanford display | Source `BLKF10`, `SMT10`, `SMT10A`, `SMT14`, `SMT14A`, `ST10`, `ST6`, `ST8` and their source variants | Raw `077` is U+2192, `136` is U+2191, and `137` is U+2190. Codes `000-037`, `100`, `140`, and `177` use PUA; these faces visibly share the same richer display/control positions, but those positions lack a complete semantic table. |
| Alto Greek/math | Source `HIP10A`, `HIPO10` and their source variants | Whole PUA. Greek/math forms occupy ordinary Latin positions, but no pinned per-code table proves modern Greek scalar assignments. |
| CADR solid-zero | Source `14FR3`, `25FR3`, `TVFONT`; runtime `25FR3`, `TVFONT` | The repertoire otherwise follows `char.18`, but raw `000` is a solid cell rather than a centered mathematical dot and therefore uses PUA. |
| BIGFNT | Source `BIGFNT`, `BIGFNT-KST`; runtime `BIGFNT` | Raw `000`, duplicate old-arrow positions `136`/`137`, and the full-cell `177` use PUA. Remaining represented slots follow the standard table. |
| CM | Source `CM10`, `CM12`; runtime `CPT-CM10`, `CPT-CM12` | Raw `136` is U+2191 and `137` is U+2190; the CM-specific low repertoire and `177` use PUA. |
| GLS7X9 | Source `GLS7X9` | Codes `040-176` retain their standard identities. Its nonstandard low symbol set and non-integral `177` use PUA. |
| Authored MEDFNT | Source `MEDFNT` only | No PUA block is needed: raw `030`/`137` exchange the standard left-arrow and low-line values. Runtime `MEDFNT` and `MEDFNB` use the later standard layout and remain in `standard-cadr`. |
| METS/NON | Source `METS`, `METSI`, `NONM`, `NONS`; runtime `METS`, `METSI` | Raw `030` is U+005F, `136` is U+2191, and `137` is U+2190. Raw `000-027`, `032-037`, and `177` use PUA. Shared raw `000` is the same woven ornament across the family. |
| SAIL | Source `SAIL10`; runtime `SAIL12` | Raw `030` is U+005F, `136` is U+2191, and `137` is U+2190. Raw `013` uses PUA to avoid duplicating the relocated up arrow; `177` is also unproved and uses PUA. |
| 40VSHD | Source and runtime `40VSHD` | Raw `032` is an additional shadowed arrow, not `char.18` NOT EQUAL TO, and uses PUA. Other represented positions retain the standard map. |
| 20VR | Runtime `20VR` | Raw `001-032` contain a second lowercase alphabet and use PUA; ordinary ASCII-position letters remain standard Unicode. |
| GERM35 | Runtime `GERM35` | German/blackletter material in raw `000-037` and the unproved `177` use PUA; reviewed ordinary text positions retain standard Unicode. |

#### Whole-PUA specialty repertoires

| Family | Artifacts covered by this block | Evidence and uncertainty boundary |
| --- | --- | --- |
| APL14 | Source `APL14`, `APL14-AL-AR1` | The archive name and recovered bitmaps identify an APL-oriented symbol font, but the pinned tree has no authoritative raw-code-to-APL-character table. The modern APL Unicode repertoire is not used to guess positions. |
| ARR10 | Source `ARR10`, `ARR10-AL-AR1` | The archive name and bitmaps identify the repertoire; no authoritative per-code semantic table was found. |
| ARROW | Source `ARROW`, `ARROW-KST`; runtime `ARROW` | [`lispm2/mouse.139`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lispm2/mouse.139#L164-L203) uses raw positions as mouse and rectangle-corner blinkers. This proves application-sprite use, not standardized arrow-character identities for every slot. |
| BUG | Source `BUG`, `BUG-KST` | The archive name and bitmaps prove a small specialty repertoire; no authoritative per-code semantic table was found. |
| CLARGK | Source `CLARGK`, `CLARGK-AL-AR1` | The archive name and bitmaps identify the repertoire; no authoritative per-code semantic table was found. |
| CYR12 | Source `CYR12`, `CYR12-AL-AR1` | The name and bitmaps suggest Cyrillic use, but shape-based assignment to modern Cyrillic code points would be a semantic guess. No pinned code table was found. |
| GATES | Source `GATES3`, `GATES3-AL-AR1`, `GATS3A`, `GATS3A-AL-AR1` | The related archive names and positional inventories justify one stable family block. They do not prove standardized identities for individual logic-gate-like bitmaps. |
| MATH | Source `MAT10A`, `MAT10A-AL-AR1`, `MATH10`, `MATH10-AL-AR1`, `MATH16`, `MATH16-AL-AR1` | The three logical names share the same 94 visible raw positions. Their names and shapes do not supply a complete authoritative Unicode table, so all sizes/variants share one PUA block. |
| MUSC10 | Source `MUSC10`, `MUSC10-AL-AR1` | The archive name and bitmaps indicate a music-oriented repertoire; no authoritative per-code semantic table was found. |
| PLNK16 | Source `PLNK16`, `PLNK16-AL-AR1` | The archive name and bitmaps identify the repertoire; no authoritative per-code semantic table was found. |
| MOUSE | Source `MOUSE`; runtime `MOUSE` | [`lmwin/mouse.149`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/mouse.149#L136-L214) loads positions from `FONTS:MOUSE` for mouse blinkers. This is direct sprite use. The runtime adds visible raw positions `034`-`036`, which retain the same family mapping. |
| TOG | Source `TOG`; runtime `TOG`; legacy runtime artifact `NTOG` | [`hacks.189`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/hacks.189#L307-L333) selects eight glyph states for a displayed switch register. Current TOG and legacy NTOG are display-identical but serialization-distinct and share this block. |
| SWFONT | Source `SWFONT` | [`swfont.ast`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmfont/swfont.ast#L1-L42) contains three game/sprite slots. It does not define interchangeable text characters. |
| SEARCH | Runtime `SEARCH` | This is a compiled-only runtime bitmap repertoire. Its resident name and recovered slots are authoritative; no source-level per-code semantic table was found in the pinned tree. |
| SHIP | Runtime `SHIP` | Spacewar code uses raw `000` for a torpedo, `001` for a sun, and two groups of 32 directional ship frames: [`swar.2`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/swar.2#L235-L294), [`sun use`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/swar.2#L389-L410), and [`ship bases`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/swar.2#L525-L568). These are application sprites, not text characters. |
| S30CHS | Runtime `S30CHS` | This is a compiled-only runtime bitmap repertoire. Its resident name and recovered slots are authoritative; no source-level per-code semantic table was found in the pinned tree. |

No standardized scalar is assigned to a specialty or exceptional glyph solely
because it resembles a Unicode chart glyph. That rule deliberately avoids
false identities in APL14, CYR12, GATES, MATH, the older Alto control slots,
and the other incompletely documented positions. A separately reviewed
semantic overlay could be added later, but it must not silently alter this
stable PUA profile.

The PUA allocation is a published private agreement of this project. Unicode
does not assign semantics to these positions and cannot prevent another PUA
convention from using the same values. Text containing U+E000-U+EDFF is only
interoperable when the recipient also uses this mapping and a corresponding
CADR font. Unicode normalization NFC, NFD, NFKC, and NFKD leaves PUA scalars
unchanged.

## Generated outputs and aliases

The build emits the derivative separately from the raw profiles:

```text
dist/unicode/
  UNICODE-MAPPING.json
  source/
    bdf/                  Unicode source BDFs plus fonts.dir/fonts.alias
    pangrams/             Latin-capable source artifact specimens
    catalog.json
  runtime/
    bdf/                  Unicode runtime BDFs plus fonts.dir/fonts.alias
    pangrams/             Latin-capable runtime artifact specimens
    catalog.json
```

`UNICODE-MAPPING.json` is the machine-readable release form of this mapping.
The two catalogs retain the source/runtime and current/legacy boundaries while
recording the derivative encodings. The profile-specific alias rules are:

1. `cadr-unicode-source-<artifact>` selects that exact authored source
   representation.
2. `cadr-unicode-runtime-<runtime-name>` selects the current resident runtime
   object.
3. `cadr-unicode-runtime-legacy-<artifact>` selects a labelled legacy runtime
   object and never claims a current alias.
4. `cadr-unicode-<name>` selects the current runtime object when that name is
   runtime-reserved; otherwise it selects the unambiguous source artifact.
5. Compatibility aliases `cadr-unicode-cm10`, `cadr-unicode-cm12`, and
   `cadr-unicode-cptfon` select current runtime `CPT-CM10`, `CPT-CM12`, and
   `CPTFONT`, respectively.

These names are disjoint from every raw `cadr-*` alias. Full XLFD names remain
authoritative. To expose both Unicode directories to a core X server from a
local build, use the generated indexes:

```sh
xset +fp "$PWD/dist/unicode/source/bdf"
xset +fp "$PWD/dist/unicode/runtime/bdf"
xset fp rehash
xlsfonts 'cadr-unicode-*'
```

The short names are X core font aliases; they are not Fontconfig family names.

### Latin pangram specimens

The Unicode build emits an artifact-level PNG specimen when the emitted BDF
contains a positive-advance U+0020 SPACE and visible glyphs for every capital
letter U+0041 through U+005A. This is a content predicate over reviewed Unicode
identities. It does not classify a specialty font as Latin merely because raw
slots `101-132` contain unrelated shapes.

The closed corpus currently yields 118 source specimens and 42 runtime
specimens. All authored variants remain separate, as do current and labelled
legacy runtime artifacts, so the 160 files can expose real geometry differences
that a logical-name-only gallery would hide.

The specimen sentence is the verified Lisp-themed pangram:

> The five boxing Lisp wizards jump quickly.

The mixed-case form is used only when every requested non-space character has
visible ink and U+0020 has positive advance. Otherwise the same sentence is
rendered in uppercase; this covers the uppercase-only `40VSHD` and the `TR8I`
representations whose lowercase `z` slot has advance but no ink. If an
otherwise eligible font lacks a visible U+002E FULL STOP, only that terminal
punctuation is omitted. The exact text and case decision are recorded beside
every image in the profile catalog, so no missing-character fallback
participates.

PNG generation is dependency-free and deterministic. It uses the exact
one-bit bitmap rows, advances, signed bearings, ascent, and descent of the
Unicode BDF. Lines wrap greedily at a maximum native advance of 640 pixels,
retain the CADR default `VSP = 2`, include ink outside nominal metrics, add
three native pixels of outer padding, and apply nearest-neighbor integer scale
2. The checker independently recomputes eligibility, case choice, wrapping,
bounds, baselines, dimensions, filenames, and hashes and pins the 118/42
selection closure.

The repository also commits a generated [GitHub specimen gallery](../SPECIMENS.md).
It contains those 160 pangrams plus complete raw-code glyph sheets for the 40
complementary symbols artifacts, so every generated identity can be previewed in
a browser. `scripts/update_specimen_gallery.py --check` requires the tracked
PNG bytes, paths, identities, hashes, and Markdown to match a fresh build; the
committed images are presentation derivatives and do not add Unicode evidence.

## BDF, ISO 10646, and X core constraints

Unicode derivative BDFs store the scalar value directly as decimal BDF
`ENCODING`. Their XLFD `CHARSET_REGISTRY` and `CHARSET_ENCODING` fields are
`ISO10646` and `1`, so the final XLFD fields are `ISO10646-1`, as required for
Unicode-encoded X core fonts. Raw BDFs continue to use `Misc-FontSpecific`.

All assigned values are in the Basic Multilingual Plane: the highest reserved
project PUA value is U+EDFF, and the highest standard value is U+25CA. They
therefore fit the 16-bit character matrix accepted by the X core font protocol
and the reviewed `bdftopcf` toolchain. The profile intentionally does not
allocate a supplementary-plane PUA scalar.

An application using a loaded core font must draw these encodings through a
16-bit interface such as `XDrawString16`, not the historical eight-bit
`XDrawString` path used for the raw profiles. Each BMP scalar is split into an
`XChar2b` high byte and low byte:

```c
XChar2b ch = {
    .byte1 = (codepoint >> 8) & 0xff,
    .byte2 = codepoint & 0xff,
};
XDrawString16(display, drawable, gc, x, y, &ch, 1);
```

For example, U+E103 is `{ 0xE1, 0x03 }`. A UTF-8 byte sequence must not be
passed directly to `XDrawString16`; a client must convert each BMP scalar to
`XChar2b` or use an appropriate Unicode-capable higher-level text API.

The Unicode profile changes the code used to select a glyph, not what the
glyph displays. Native-X validation must therefore compare each Unicode probe
with the same raw artifact/code geometry: bitmap pixels, advance, bearing, and
text extents must remain identical after re-encoding.

## Provenance and change control

The historical sources prove raw codes, names, bitmap geometry, and in some
cases application use. RFC 734 and the Unicode Standard support the standard
character resolution. The PUA family grouping and block numbers are new,
documented project policy; generated mapping JSON is a reproducible expression
of that policy, not independent historical evidence.

Mapping version 1 is append-stable:

- do not change a standard scalar without explicit contradictory historical
  evidence and a new mapping version;
- do not move, merge, or reuse any reserved block;
- use the same family/raw-code scalar for all source, current-runtime, and
  legacy-runtime variants;
- leave a reserved position unencoded until a recovered artifact actually
  represents that glyph;
- document new evidence and regenerate `UNICODE-MAPPING.json` and both Unicode
  catalogs together.

The test suite independently pins the complete block-index registry and the
two exact `standard-cadr` whitelists. Updating an oracle inside the mapping
manifest therefore cannot silently legitimize a repertoire reassignment.

See [Provenance and reproducibility](PROVENANCE.md) for the source, runtime,
decoder, and evidence-selection boundaries. Unicode PUA properties and their
private-agreement model are defined in
[The Unicode Standard, section 23.5](https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-23/#G19184),
and the X core XLFD convention is documented in
[Fonts in X11](https://www.x.org/archive/X11R7.5/doc/fonts/fonts.html#AEN608).
