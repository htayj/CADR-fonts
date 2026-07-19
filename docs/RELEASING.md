# Release plan

GitHub Actions and release publication are deliberately not enabled yet. The
local build is the authority while release contents, project code license, and
versioning policy are still being settled.

The public upstream repository is
[`htayj/CADR-fonts`](https://github.com/htayj/CADR-fonts), its `origin` uses
SSH, and its default branch is `master`.

## Proposed tag workflow

For tags matching `v*`, a future workflow should:

1. check out the repository with submodules;
2. assert the submodule gitlink, the 31-file authoring-source manifest, and the
   49-file runtime-QFASL manifest;
3. run the repository's pinned-lineage inert QFASL decoder; no external parser
   checkout or executable target environment participates in the build;
4. run `make check-external`, including the native defined-glyph framebuffer
   gate for the raw source/runtime profiles and both Unicode derivatives;
5. run `make reproducible` in a clean environment;
6. rebuild the intended smaller release profile if normalized JSON or specimen
   sheets are to be omitted;
7. create a deterministic tar archive with sorted entries, numeric owner/group,
   and an mtime derived from `SOURCE_DATE_EPOCH`;
8. publish the archive, `SHA256SUMS`, `BUILD-MANIFEST.json`, all four profile
   catalogs, both closed raw manifests, `unicode/UNICODE-MAPPING.json`, and
   `LICENSE.source` on the tag's GitHub Release.

The workflow must call the same scripts as local development. It should not
contain a second implementation of font selection, naming, or checksumming.

## Decisions required first

- Project-tooling license; the recovered source payload itself is BSD-3-Clause.
- Whether releases include normalized JSON and PNG sheets or only BDF plus
  catalogs, indexes, license, and checksums.
- Versioning and whether a tag is allowed to change the pinned System 46 source
  revision.
- Whether PCF files should be shipped or remain reproducible derived output.

## Required release gates

- No dirty or wrong-revision source submodule.
- Exact 31-file source-profile manifest and exact 49-file runtime manifest at
  the pinned submodule revision.
- Runtime classification remains 30 source-backed current, 17 compiled-only,
  and two explicitly legacy objects, representing 47 current runtime logical
  names.
- The inert decoder reproduces every reviewed resident symbol, stream
  checkpoint, and serialized `FONT` object without evaluating compiled code.
- Reviewed source corpus, spacing, partial-recovery, and extent-recovery
  invariants, plus 151 source and 49 runtime raw BDF artifacts containing
  20,307 emitted glyphs.
- The 151 source and 49 runtime Unicode derivatives preserve those same 20,307
  bitmap, advance, bearing, and line-metric instances, yielding four profiles,
  400 BDFs, and 40,614 emitted glyph instances overall.
- Unicode catalogs and release contents include exactly 118 source and 42
  runtime Latin pangram PNGs. Eligibility, mixed/uppercase choice, wrapping,
  bitmap bounds, dimensions, paths, and hashes must be recomputed without
  missing-character fallback.
- Exact reviewed normalized and BDF semantic-inventory digests for both
  profiles: all source slots, all 6,170 runtime slots, and every emitted
  source/runtime glyph geometry and line metric.
- The 30 source-backed runtime comparisons remain exact, including the
  reviewed `ARROW-KST`, `BIGFNT-KST`, current `MEDFNT`, and runtime `MOUSE`
  distinctions; `N43XMS` and `NTOG` remain non-current legacy identities.
- Unique, complete XLFD names and exact `fonts.dir`/`fonts.alias` indexes for
  all four profiles. Unicode XLFDs must retain `ISO10646-1`, remain distinct
  from raw `Misc-FontSpecific` XLFDs, and preserve raw spacing classifications.
- Exact alias namespaces: 151 `cadr-source-*`, 47 `cadr-runtime-*`, two
  `cadr-runtime-legacy-*`, and collision-checked `cadr-*` current convenience
  names. Current runtime aliases must resolve to runtime-distinct XLFDs, not to
  a source font with an accidentally identical XLFD. The reviewed split is 272
  aliases in the source index and 99 in the runtime index, 371 raw aliases in
  total. The corresponding disjoint `cadr-unicode-*` indexes must contain the
  same 272/99 split, for 371 Unicode aliases and 742 aliases overall.
- The closed mapping assigns every one of the 88 source logical names and all
  49 runtime artifact names without a default. Its standard CADR map, reviewed
  hybrid remaps, and 28 fixed 128-code-point BMP PUA reservations remain
  exactly as documented in [UNICODE.md](UNICODE.md). The independently pinned
  block registry and exact standard-repertoire whitelists must also pass.
- All BDFs compile with `bdftopcf` and `mkfontdir` independently recovers the
  expected PCF-to-XLFD index.
- Every generated alias loads in an isolated Xvfb server; the release image
  must install Xvfb rather than silently skipping this gate.
- For every code defined by every source and runtime BDF, native raw-eight-bit
  `XDrawString` produces the independently predicted one-bit framebuffer,
  advance, and text extents. Every Unicode derivative is also drawn as BMP
  `XChar2b` values with `XDrawString16` and must reproduce its corresponding
  raw artifact/code geometry exactly. Undefined-code/default-character
  substitution is explicitly outside this gate.
- The independent CADR layout model proves default `VSP = 2`, maximum
  font-map baseline, maximum font-map character height, and per-font baseline
  adjustment for mixed-font lines.
- Two isolated builds are byte-identical.
- All distributed files are covered by `SHA256SUMS`.
