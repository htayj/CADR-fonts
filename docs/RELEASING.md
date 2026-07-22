# Releasing

The public upstream repository is
[`htayj/CADR-fonts`](https://github.com/htayj/CADR-fonts), its `origin` uses
SSH, and its default branch is `master`. The release workflow is
`.github/workflows/release-packaging.yml`.

The workflow runs its build and packaging gates for branches and pull
requests. A tag matching `v*` additionally creates a GitHub Release, but only
when the tag resolves to the workflow commit and that commit is an ancestor of
`origin/master`. Publication is immutable: if a release for the tag already
exists, the workflow fails instead of replacing assets.

## Published collections

Release membership is a literal predicate over each emitted Unicode BDF:

- **Latin** means that at least one encoded glyph in U+0041-U+005A or
  U+0061-U+007A has visible ink;
- **symbols** is the exact complement.

The symbols name is deliberately broader than “drawing fonts.” It includes
drawing and application sprites plus Greek, Cyrillic, APL, mathematics, and
music repertoires whose Unicode identities are wholly or partly represented by
the documented project PUA mapping. Names, raw slot numbers, and specimen
presence do not determine collection membership.

The closed current inventory is:

| Collection | Source artifacts | Runtime artifacts | Total |
| --- | ---: | ---: | ---: |
| Latin | 118 | 42 | 160 |
| Symbols | 33 | 7 | 40 |

Every one of the 151 source artifacts and 49 runtime artifacts occurs in
exactly one collection. The build also rejects a source/runtime logical family
that crosses the content boundary.

## Generic archives

`make release VERSION=<version> SOURCE_DATE_EPOCH=<epoch>` writes exactly two
generic payloads and two adjacent checksum files to `dist/release/`:

```text
CADR-fonts-latin-<version>.tar.gz
CADR-fonts-latin-<version>.tar.gz.sha256
CADR-fonts-symbols-<version>.tar.gz
CADR-fonts-symbols-<version>.tar.gz.sha256
```

Each archive has one versioned root and contains:

```text
README.release.md
LICENSE.project
LICENSE.source
RELEASE-MANIFEST.json
SHA256SUMS
metadata/
  SOURCE-MANIFEST.json
  runtime-source-manifest.json
  UNICODE-MAPPING.json
fonts/
  unicode/{source,runtime}/   usable ISO10646-1 BDF plus closed indexes
  otb/{source,runtime}/       OTB conversions of Unicode BDF only
  raw/{source,runtime}/       historical CADR-code BDF, clearly separated
specimens/{source,runtime}/
```

The Unicode BDFs and their OTB conversions are the usable release fonts. The
raw `Misc-FontSpecific` BDFs are included only so the transformation remains
traceable to CADR code positions; users should not install them as Unicode
fonts. Source and current/legacy runtime identities remain separate in every
format.

The Latin archive has 160 Unicode BDFs and 160 OTBs representing 17,321
glyphs, plus 160 Lisp-pangram sheets. The symbols archive has 40 Unicode BDFs
and 40 OTBs representing 2,986 glyphs, plus 40 full raw-code glyph sheets. Both
archives contain a second, raw BDF representation of the same selected
artifacts for traceability.

OTB is a one-bit bitmap OpenType container, not an outline conversion. The
release checker proves that all 20,307 encoded glyphs converted from the
Unicode BDFs have exactly their repertoire, advance, and baseline-relative set
pixels. Each OTB also has an unencoded `.notdef`, which is outside that claim.
`fonttosfnt` is allowed
to trim transparent rows and columns from stored bitmap boxes because that
does not alter the displayed image. The Unicode BDF remains authoritative for
the derivative's explicit metrics and provenance.

`RELEASE-MANIFEST.json` records the selection rule, exact artifact identities,
profile and glyph counts, input provenance, generator identity, and hashes. It
records the converter's reported version, or the executable SHA-256 for older
`fonttosfnt` releases that do not implement `--version`.
The internal `SHA256SUMS` covers every other archive file. The adjacent
`.sha256` covers the compressed archive itself. Archive entries are sorted,
have numeric owner and group zero, fixed file modes, and the supplied
`SOURCE_DATE_EPOCH`; gzip uses that epoch too.

`LICENSE.project` is the repository's BSD-3-Clause text governing authored
tooling, documentation, metadata, and packaging material. `LICENSE.source` is
the distinct upstream BSD-3-Clause text retained with the recovered MIT CADR
font payload and its direct derivatives. The manifest records the path, SPDX
identifier, scope, and digest of both notices.

## Published packages

For each collection, the workflow builds one package in each of four formats:

| Platform | Release suffix | Package architecture |
| --- | --- | --- |
| Debian/Ubuntu | `.deb` | `all` |
| Fedora/RHEL/openSUSE-style RPM | `.rpm` | `noarch` |
| Arch Linux | `.pkg.tar.zst` | `any` |
| Void Linux | `.xbps` | `noarch` |

Every package has an adjacent `.sha256`, and every package is installed and
checked in a native distribution container before publication. The two
collection packages are co-installable. They install only the Unicode BDFs
and Unicode-derived OTBs—not the raw CADR-encoded BDFs—under
`/usr/share/fonts/cadr-fonts/<collection>/`, with source/runtime identity kept
in separate subdirectories. Fontconfig is configured to discover the OTB
trees.

The repository's locked Nix flake independently builds and checks
`cadr-fonts-latin` and `cadr-fonts-symbols` on x86_64 and AArch64 Linux. Manual
package recipes and their validation commands are documented in
[PACKAGING.md](PACKAGING.md).

One tagged GitHub Release therefore contains an explicit allowlist of ten
payload assets—two generic archives and eight native packages—and ten adjacent
SHA-256 files. Repository metadata, temporary build products, signatures, and
package-manager repository indexes are not uploaded implicitly.

## Updating the AUR package

The AUR package base `cadr-fonts` is a separate, source-only Git repository.
Update it after the corresponding GitHub tag and release are immutable:

1. bump `pkgver` and reset `pkgrel` in `packaging/aur/cadr-fonts/PKGBUILD`;
2. replace the project tag object, project commit, release timestamp, and any
   changed CADR revision with the exact reviewed identities;
3. regenerate both source hashes with `makepkg --geninteg`, then regenerate
   `.SRCINFO` with `makepkg --printsrcinfo`;
4. run `pkgctl license check`, `namcap` on the recipe and both packages, a
   clean Arch build, co-installation, and Fontconfig discovery; and
5. copy only `PKGBUILD`, `.SRCINFO`, `.gitignore`, `LICENSE`,
   `LICENSES/0BSD.txt`, and `REUSE.toml` to the AUR `master` branch, commit a
   meaningful release update, and push.

Do not upload built packages, file lists, generated font trees, or GitHub
release assets to the AUR repository. AUR commit authorship is effectively
permanent, so confirm the public Git name and email before every push.

## Required gates

The tag workflow invokes the same generators and checkers used locally. Its
release-critical gates are:

- clean checkout at the pinned CADR submodule revision, with the exact
  31-file authoring and 49-file runtime-QFASL manifests;
- strict inert QFASL decoding, all reviewed source/runtime classification and
  semantic-inventory oracles, and the exceptional display comparisons for
  `ARROW`, `BIGFNT`, current `MEDFNT`, and runtime `MOUSE`;
- the GERM35-only 16-bit structural signature, pinned compiler/screen
  evidence (with later `FCMP-16` as the reference implementation), complete
  display-geometry oracle, and proof that no other runtime font receives its
  raster-word normalization;
- 151 source and 49 runtime artifacts, 20,307 emitted glyphs per encoding, and
  byte-for-byte raw-to-Unicode geometry preservation;
- exact 118/42 Latin and 33/7 symbols partition, with complete and disjoint
  artifact identities and collection-specific closed indexes;
- unique XLFDs, the reviewed raw and Unicode alias closures, BDF compilation,
  isolated Xvfb loads, and native raw/Unicode framebuffer equivalence for
  every defined glyph;
- exact CADR sheet-layout checks for `VSP = 2`, font-map baseline and height,
  and per-font baseline adjustment;
- deterministic archives, complete internal and external checksums, and a
  second isolated byte-for-byte build comparison;
- exact Unicode-to-OTB repertoire, advance, and baseline-relative pixel
  equivalence for every glyph;
- two packages per native format, checksum closure, co-installable path
  boundaries, native-container installation, expected Unicode BDF/OTB counts,
  and Fontconfig discovery;
- locked Nix checks for both collections; and
- the final ten-payload/twenty-file GitHub Release allowlist.

Substitution for a character absent from a font remains outside the rendering
claim. No release checker interprets X or Fontconfig fallback as CADR output.

## Local rehearsal

Use the tag spelling intended for the release and the commit timestamp as the
archive epoch:

```sh
git submodule update --init --recursive
version=v0.1.2
epoch=$(git show -s --format=%ct HEAD)
make ci VERSION="$version" SOURCE_DATE_EPOCH="$epoch"
export SOURCE_DATE_EPOCH="$epoch"
scripts/package-deb.sh --version "$version"
scripts/package-rpm.sh --version "$version"
scripts/package-arch.sh --version "$version"
scripts/package-void.sh --version "$version"
make test-nix-flake-container
```

The native packaging scripts expect the two archive files and their checksum
sidecars in `dist/release/`. See [PACKAGING.md](PACKAGING.md) for prerequisites
and individual installation checks.
