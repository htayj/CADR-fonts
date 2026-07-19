# Release plan

GitHub Actions and release publication are deliberately not enabled yet. The
local build is the authority while output contents, repository naming, project
code license, and versioning policy are still being settled.

## Proposed tag workflow

For tags matching `v*`, a future workflow should:

1. check out the repository with submodules;
2. assert the submodule gitlink and closed source manifest;
3. fetch the separately pinned inert QFASL parser and run
   `make audit-runtime-names` against it;
4. run `make check-external`;
5. run `make reproducible` in a clean environment;
6. rebuild the intended smaller release profile if normalized JSON or specimen
   sheets are to be omitted;
7. create a deterministic tar archive with sorted entries, numeric owner/group,
   and an mtime derived from `SOURCE_DATE_EPOCH`;
8. publish the archive, `SHA256SUMS`, `catalog.json`,
   `SOURCE-MANIFEST.json`, and `LICENSE.source` on the tag's GitHub Release.

The workflow must call the same scripts as local development. It should not
contain a second implementation of font selection, naming, or checksumming.

## Decisions required first

- GitHub owner/repository and default branch (`master` is currently unborn).
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
- Exact 31-file input manifest plus three metadata-only runtime-name QFASLs.
- The three runtime names reproduce with the exact inert QFASL parser pinned in
  the manifest; compiled code is never evaluated.
- Reviewed corpus, spacing, partial-recovery, and extent-recovery invariants.
- Exact reviewed normalized and BDF semantic-inventory digests covering every
  source slot plus installable line/glyph metrics, encodings, boxes, and rows.
- Unique, complete XLFD names and exact `fonts.dir`/`fonts.alias` indexes.
- All BDFs compile with `bdftopcf` and `mkfontdir` independently recovers the
  expected PCF-to-XLFD index.
- Every generated alias loads in an isolated Xvfb server; the release image
  must install Xvfb rather than silently skipping this gate.
- Two isolated builds are byte-identical.
- All distributed files are covered by `SHA256SUMS`.
