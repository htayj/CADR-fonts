# CADR fonts

This repository reproducibly recovers the public MIT CADR System 46 bitmap-font
sources as inspectable JSON and PNG specimens plus installable BDF 2.1 fonts
with complete X Logical Font Description (XLFD) names.

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
```

`make check-external` builds `dist/`, runs the unit and corpus checks, compiles
all BDFs to PCF with `bdftopcf`, independently indexes them with `mkfontdir`,
and loads every generated alias in a private Xvfb server. It requires those
three X11 tools; the build itself needs only Python 3.10 or newer and its
standard library. `make reproducible` performs two isolated builds and compares
every output byte.

When the sibling `../genera-emu` checkout is present, `make compare-genera`
repeats the compatibility audit against its published BDF artifacts. It
compares represented glyph repertoires, advances, x bearings, and every
baseline-relative set pixel after normalizing the zero-width no-op slots
described below, while deliberately ignoring transparent storage padding and
the new XLFD metadata.

`make audit-runtime-names` uses the separately pinned, inert QFASL parser from
that sibling checkout to reproduce the three `FONTS:` bindings used as runtime
family/alias evidence. Neither optional lineage audit is needed to build from
the source submodule; both make the migration and naming review repeatable.

The current reviewed result is:

- 151 BDFs from 88 authored logical names;
- 63 preserved source-representation variants;
- 134 proportional, 15 character-cell, and two monospace XLFD classifications;
- 1,855 zero-width, zero-advance, no-ink Alto slots retained in JSON and
  omitted from 62 installable BDFs;
- six explicitly partial Alto pointer recoveries;
- 45 Alto fonts with 142 glyphs whose observed pixels exceed declared extents;
- zero rejected selected sources.

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

## What is in `dist/`

```text
dist/
  bdf/                 BDF fonts, fonts.dir, and fonts.alias
  json/                lossless normalized source metrics and bitmap rows
  sheets/              deterministic octal-labelled PNG specimens
  catalog.json         artifact, recovery, metric, XLFD, and generator records
  SOURCE-MANIFEST.json closed source filename/size/SHA-256 manifest
  LICENSE.source       upstream three-clause BSD license
  SHA256SUMS            digest of every other distributed file
```

Convenience aliases are `cadr-<artifact-name>`; for example, `cadr-hl10` and
`cadr-tvfont`. The full XLFD names remain authoritative.

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
- Alto's zero-width, zero-advance slots with no set pixels remain in the
  lossless JSON but are omitted from BDF. Xorg's PCF renderer rejects a font
  containing such a glyph with `BadAlloc`; omission changes neither ink nor
  escapement and lets the complete font load through the X core protocol.
- The sources do not authoritatively classify weight, slant, setwidth, or
  physical DPI. XLFD uses `Unknown-OT-Unknown`, while 72 dpi is documented as
  an interchange convention that preserves one source pixel as one nominal
  point.

See [the font model](docs/FONT-MODEL.md) and
[the provenance chain](docs/PROVENANCE.md) for the evidence and exact
transformations. The output follows the official
[BDF 2.1 standard](https://www.x.org/releases/X11R7.0/doc/PDF/bdf.pdf) and
[XLFD conventions](https://www.x.org/releases/X11R7.6/doc/xorg-docs/specs/XLFD/xlfd.html).

## Release status

There is no `.github/workflows` file yet. [RELEASING.md](docs/RELEASING.md)
records the proposed tag pipeline and the decisions still needed before it is
safe to publish releases.
