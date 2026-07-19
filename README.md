# CADR fonts

This repository reproducibly recovers two complementary public MIT CADR System
46 bitmap-font profiles as inspectable JSON and PNG specimens plus installable
BDF 2.1 fonts with complete X Logical Font Description (XLFD) names:

- the **source profile** preserves 151 authored AST, KST, Alto, and archive
  representations, including meaningful source variants;
- the **runtime profile** inertly decompiles all 49 reviewed font QFASLs into
  the serialized `FONT` arrays that System 46 would draw when loaded: 47
  current logical fonts and two explicitly legacy compiled versions.

Each raw profile also has a separately named Unicode derivative. The raw BDFs
retain CADR codes and `Misc-FontSpecific`; the derivatives re-encode the same
glyphs under `ISO10646-1` using the reviewed standard-character map and fixed
BMP Private Use Area allocation documented in [UNICODE.md](docs/UNICODE.md).
The result is four installable profiles and 400 BDFs. The Unicode profiles also
include pangram PNGs for every artifact with a complete visible Latin alphabet.

All 200 generated artifacts can be inspected without installing anything in
the tracked [font specimen gallery](SPECIMENS.md): Latin fonts use the
Lisp-themed pangram and specialty fonts use complete glyph sheets. A fresh
build must reproduce every committed PNG and the gallery index exactly.

The source and runtime identities are deliberately not collapsed. The source
profiles answer “what surviving authoring representations contain”; the
runtime profiles answer “what this System 46 snapshot would display for a
defined character.” Unicode derivation changes addressing, not that boundary
or any displayed geometry.

The source witness is a pinned Git submodule. Generated files stay under the
ignored `dist/` directory for now; a GitHub release workflow is intentionally
deferred until the local build and release contents are agreed.

## Build and verify

```sh
git submodule update --init
make check-external
make reproducible
make compare-genera
make audit-runtime-names
make specimens
make check-specimens
```

`make check-external` builds all four profiles under `dist/`, runs the unit and
corpus checks, compiles every BDF to PCF with `bdftopcf`, independently indexes
the result with `mkfontdir`, and uses a private Xvfb server for alias-load and
native rendering checks. For every character actually defined by an emitted
BDF, the rendering gate compares framebuffer pixels, advances, and
`XTextExtents` with an independent BDF renderer. Raw CADR encodings are drawn
through eight-bit `XDrawString`; Unicode `ISO10646-1` encodings are drawn as BMP
scalars through `XDrawString16` and must reproduce the corresponding raw glyph
exactly. No scaling or antialiasing is involved. It requires `bdftopcf`,
`mkfontdir`, Xvfb, and Xlib; the build itself needs only Python 3.10 or newer
and its standard library. `make reproducible` performs two isolated builds and
compares every output byte. The reviewed build passes this gate for 371 raw
aliases and 371 Unicode aliases across the four font paths, 742 aliases total,
and for every emitted glyph.

`make specimens` refreshes the tracked GitHub gallery from the reviewed build;
`make check-specimens` is the non-mutating gate. It closes the gallery over
160 Latin pangrams and 40 symbols glyph sheets and verifies every PNG byte,
path, identity, and digest against the generated distribution.

When the sibling `../genera-emu` checkout is present, `make compare-genera`
repeats the compatibility audit against its published BDF artifacts. It
compares represented glyph repertoires, advances, x bearings, and every
baseline-relative set pixel after normalizing the zero-width no-op slots
described below, while deliberately ignoring transparent storage padding and
the new XLFD metadata.

The runtime build uses the repository's strict, non-evaluating QFASL decoder.
It accepts only the serialized-object operations observed in the closed
49-file manifest, rejects every unsupported operation, and never executes Lisp
forms or target-machine code. `make audit-runtime-names` remains an optional
lineage cross-check against the separately pinned ancestor in the sibling
checkout; it is not a source of unpinned build data.

The current reviewed result is:

- 151 source BDFs from 88 authored logical names;
- 63 preserved source-representation variants;
- 134 proportional, 15 character-cell, and two monospace XLFD classifications;
- 1,855 zero-width, zero-advance, no-ink Alto slots retained in JSON and
  omitted from 62 installable BDFs;
- six explicitly partial Alto pointer recoveries;
- 45 Alto fonts with 142 glyphs whose observed pixels exceed declared extents;
- zero rejected selected sources;
- 49 runtime BDFs: 30 current source-backed objects, 17 compiled-only current
  fonts, and two legacy compiled versions representing 47 current runtime
  logical names;
- 6,170 normalized runtime slots, of which 5,689 are installable BDF glyphs
  after omitting 481 zero-width, zero-advance, no-ink runtime placeholders;
- 200 raw BDF artifacts containing 20,307 emitted glyphs across the source and
  runtime profiles;
- 200 Unicode derivative BDFs preserving those same 20,307 bitmap, advance,
  bearing, and line-metric instances exactly;
- 400 BDFs and 40,614 emitted glyph instances across all four profiles;
- 272 source-path and 99 runtime-path aliases in the raw profiles, 371 total,
  mirrored by 371 disjoint `cadr-unicode-*` aliases for 742 aliases overall.
- 160 Unicode Latin pangram specimens: 118 source artifacts and 42 runtime
  artifacts, retaining distinct authored, current-runtime, and legacy-runtime
  representations rather than collapsing them by logical name.

The earlier `genera-emu` extraction produced 150 artifacts. This repository
corrects its AST raster-height model: `BUG` has a 32-row authored AST raster but
a 33-row KST raster, so `BUG-KST` is now retained as a real 151st source
variant. The set pixels, bearings, and advances of the existing artifacts are
otherwise retained for every represented glyph; `make compare-genera` proves
that result over all 150 common BDFs.

The permanent corpus gate checks two committed SHA-256 oracles: one over the
complete normalized source model, including every JSON-only no-op slot, and
one over the installable BDF line metrics and emitted glyph geometry. This
prevents a deterministic decoder regression from blessing its own changed JSON
and BDF output.

The runtime profile has its own pair of reviewed semantic oracles over all
6,170 decoded `FONT` slots and all 5,689 installable runtime glyphs. The 30
source-backed QFASLs are also compared with the source profile. Most resident
fonts preserve the surviving authored display geometry, but four distinctions
matter for actual screen output:

- resident `ARROW` includes visible codes octal `003` and `006`; the source
  `ARROW-KST` variant matches it;
- resident `BIGFNT` is matched by `BIGFNT-KST`; the source-profile canonical
  differs at `155` and lacks six visible runtime codes;
- current `MEDFNT` changes 57 previously visible glyphs and makes six formerly
  blank slots visible relative to the surviving older/source-backed form;
- resident `MOUSE` adds visible codes `034` through `036`.

The runtime profile carries those resident shapes directly rather than
silently rewriting the source artifacts.

## What is in `dist/`

```text
dist/
  bdf/                    source BDFs plus source fonts.dir/fonts.alias
  json/                   lossless normalized source metrics and bitmap rows
  sheets/                 deterministic source PNG specimens
  catalog.json            source artifact/recovery/XLFD catalog
  runtime/
    bdf/                  49 runtime BDFs plus runtime fonts.dir/fonts.alias
    json/                 all normalized resident FONT slots
    sheets/               deterministic runtime PNG specimens
    catalog.json          runtime classification, metrics, and provenance
    runtime-source-manifest.json
  unicode/
    UNICODE-MAPPING.json  release copy of the reviewed mapping contract
    source/
      bdf/                Unicode source BDFs plus fonts.dir/fonts.alias
      pangrams/           Latin-capable source artifact sentence specimens
      catalog.json        resolved source encodings and geometry digest
    runtime/
      bdf/                Unicode runtime BDFs plus fonts.dir/fonts.alias
      pangrams/           Latin-capable runtime artifact sentence specimens
      catalog.json        resolved runtime encodings and geometry digest
  BUILD-MANIFEST.json     four-profile counts, catalogs, aliases, and specimens
  SOURCE-MANIFEST.json    closed authoring-source manifest
  LICENSE.source          upstream three-clause BSD license
  SHA256SUMS              digest of every other distributed file
```

Aliases make the profile boundary explicit:

- `cadr-source-<artifact>` always selects that exact authored artifact;
- `cadr-runtime-<runtime-name>` selects the current System 46 resident object;
- `cadr-runtime-legacy-n43xms` and `cadr-runtime-legacy-ntog` select the two
  older compiled objects and are never current defaults;
- `cadr-<name>` is a convenience alias for the current runtime font when that
  name is resident, otherwise for the unambiguous source artifact.

Current runtime names win intentional collisions such as `cadr-arrow`; the
source form remains available as `cadr-source-arrow`. Compatibility spellings
such as `CM10`/`CPT-CM10`, `CM12`/`CPT-CM12`, and `CPTFON`/`CPTFONT` resolve to
the same current resident font, while their exact source forms remain under
`cadr-source-*`. Full XLFD names remain authoritative.

The Unicode aliases preserve the same selection rules under the disjoint
`cadr-unicode-source-*`, `cadr-unicode-runtime-*`,
`cadr-unicode-runtime-legacy-*`, and `cadr-unicode-*` namespaces. See
[the Unicode profile](docs/UNICODE.md) for the exact map, complete repertoire
allocation, and X core usage.

The Unicode catalogs select pangram specimens from emitted content, not font
names or raw slot numbers. A font qualifies only when U+0020 has positive
advance and U+0041-U+005A are all present with visible ink. The specimen is the
compact Lisp-themed pangram “The five boxing Lisp wizards jump quickly.” Fonts
where a non-space glyph requested by the mixed-case sentence is blank or
missing use the same text in uppercase; an unavailable terminal full stop is
explicitly omitted and recorded. The dependency-free renderer uses the
recovered one-bit pixels and metrics directly, wraps at a 640-source-pixel
advance, adds three native pixels of padding, and scales each pixel to a 2-by-2
block without interpolation.

## Metric and identity boundaries

These are one-bit bitmap fonts, not vectors or outlines. The build does not
trace, scale, hint, or synthesize glyph shapes.

- BDF `DWIDTH` is the historical per-character advance.
- The source's “left kern” is a signed per-glyph bearing, not pair kerning; the
  historical renderer draws at `X - kern`, so BDF `BBX` x-offset is `-kern`.
- There is no pair-kerning table. All AST/KST column-position adjustments are
  zero, so no tracking adjustment is added.
- `SPACING` is calculated under the XLFD `P`, `M`, and `C` definitions from
  advances and represented raster boxes.
- Raw CADR codes are direct BDF encodings under `Misc-FontSpecific`. They are
  not labelled Unicode or ISO-8859.
- Unicode derivatives retain the same bitmaps and metrics but use
  `ISO10646-1`. Artifacts proven to follow the System 46 table use its explicit
  Unicode map. Older Alto/SAIL and mixed text repertoires use hybrid maps that
  keep proven ordinary characters at standard Unicode scalars while routing
  divergent or undocumented slots to family PUA blocks. Twenty-eight fixed
  128-code-point blocks are reserved from U+E000 through U+EDFF, including 17
  whole-PUA families: the 16 specialty repertoires plus Alto Greek/math. This
  is a documented project private agreement, not a Unicode assignment inferred
  from bitmap resemblance.
- Alto's zero-width, zero-advance slots with no set pixels remain in the
  lossless JSON but are omitted from BDF. Xorg's PCF renderer rejects a font
  containing such a glyph with `BadAlloc`; omission changes neither ink nor
  escapement and lets the complete font load through the X core protocol.
- The sources do not authoritatively classify weight, slant, setwidth, or
  physical DPI. XLFD uses `Unknown-OT-Unknown`, while 72 dpi is documented as
  an interchange convention that preserves one source pixel as one nominal
  point.

System 46 sheet layout adds two pixels of vertical spacing by default. For a
mixed-font map, the sheet baseline is the greatest font baseline and the line
height is the greatest character height plus that two-pixel VSP; changing font
adds the difference between the sheet and font baselines. BDF preserves each
font's metrics but cannot encode this sheet-level policy, so the independent
render model tests it separately.

The conformance claim is intentionally limited to native rendering of defined
glyphs in both raw and Unicode profiles. What an X server substitutes for a
code absent from a BDF is outside the project gate, as requested; no fallback
behavior is presented as CADR behavior.

See [the font model](docs/FONT-MODEL.md),
[the Unicode profile](docs/UNICODE.md), and
[the provenance chain](docs/PROVENANCE.md) for the evidence and exact
transformations. The output follows the official
[BDF 2.1 standard](https://www.x.org/releases/X11R7.0/doc/PDF/bdf.pdf) and
[XLFD conventions](https://www.x.org/releases/X11R7.6/doc/xorg-docs/specs/XLFD/xlfd.html).

## Release status

There is no `.github/workflows` file yet. [RELEASING.md](docs/RELEASING.md)
records the proposed tag pipeline and the decisions still needed before it is
safe to publish releases.
