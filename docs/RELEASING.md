# Release plan

GitHub Actions and release publication are deliberately not enabled yet. The
local build is the authority while output contents, repository naming, project
code license, and versioning policy are still being settled.

## Proposed tag workflow

For tags matching `v*`, a future workflow should:

1. check out the repository with submodules;
2. assert the submodule gitlink, the 31-file authoring-source manifest, and the
   49-file runtime-QFASL manifest;
3. run the repository's pinned-lineage inert QFASL decoder; no external parser
   checkout or executable target environment participates in the build;
4. run `make check-external`, including the native defined-glyph framebuffer
   gate for both source and runtime BDFs;
5. run `make reproducible` in a clean environment;
6. rebuild the intended smaller release profile if normalized JSON or specimen
   sheets are to be omitted;
7. create a deterministic tar archive with sorted entries, numeric owner/group,
   and an mtime derived from `SOURCE_DATE_EPOCH`;
8. publish the archive, `SHA256SUMS`, `BUILD-MANIFEST.json`, both profile
   catalogs, both closed manifests, and `LICENSE.source` on the tag's GitHub
   Release.

The workflow must call the same scripts as local development. It should not
contain a second implementation of font selection, naming, or checksumming.

## Decisions required first

- GitHub owner/repository, remote, and intended default branch.
- Project-tooling license; the recovered source payload itself is BSD-3-Clause.
- Whether releases include normalized JSON and PNG sheets or only BDF plus
  catalogs, indexes, license, and checksums.
- Versioning and whether a tag is allowed to change the pinned System 46 source
  revision.
- Whether PCF files should be shipped or remain reproducible derived output.
- Whether a later Unicode-mapped profile belongs in this repository; it must
  remain distinct from the raw CADR code profile.

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
  invariants, plus 151 source and 49 runtime BDF artifacts containing 20,307
  emitted glyphs.
- Exact reviewed normalized and BDF semantic-inventory digests for both
  profiles: all source slots, all 6,170 runtime slots, and every emitted
  source/runtime glyph geometry and line metric.
- The 30 source-backed runtime comparisons remain exact, including the
  reviewed `ARROW-KST`, `BIGFNT-KST`, current `MEDFNT`, and runtime `MOUSE`
  distinctions; `N43XMS` and `NTOG` remain non-current legacy identities.
- Unique, complete XLFD names and exact `fonts.dir`/`fonts.alias` indexes.
- Exact alias namespaces: 151 `cadr-source-*`, 47 `cadr-runtime-*`, two
  `cadr-runtime-legacy-*`, and collision-checked `cadr-*` current convenience
  names. Current runtime aliases must resolve to runtime-distinct XLFDs, not to
  a source font with an accidentally identical XLFD. The reviewed split is 272
  aliases in the source index and 99 in the runtime index, 371 in total.
- All BDFs compile with `bdftopcf` and `mkfontdir` independently recovers the
  expected PCF-to-XLFD index.
- Every generated alias loads in an isolated Xvfb server; the release image
  must install Xvfb rather than silently skipping this gate.
- For every code defined by every source and runtime BDF, native raw-eight-bit
  X drawing produces the independently predicted one-bit framebuffer,
  advances, and text extents. Undefined-code/default-character substitution is
  explicitly outside this gate.
- The independent CADR layout model proves default `VSP = 2`, maximum
  font-map baseline, maximum font-map character height, and per-font baseline
  adjustment for mixed-font lines.
- Two isolated builds are byte-identical.
- All distributed files are covered by `SHA256SUMS`.
