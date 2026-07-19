# Packaging and installation

CADR Fonts publishes two independently installable collections. `latin`
contains every artifact with at least one visible Basic Latin letter;
`symbols` is the closed complement and includes drawing/sprite, Greek,
Cyrillic, APL, mathematics, and music repertoires. The current split is 160
Latin artifacts and 40 symbols artifacts.

## Which files to install

The usable release fonts are Unicode encoded:

- `fonts/unicode/{source,runtime}` contains `ISO10646-1` BDFs and closed
  `fonts.dir`/`fonts.alias` indexes for X core-font clients;
- `fonts/otb/{source,runtime}` contains one-bit OpenType Bitmap conversions of
  those Unicode BDFs for Fontconfig and modern desktop clients.

The generic archives also contain `fonts/raw/`. Those BDFs use historical CADR
codes and `Misc-FontSpecific`; they are retained only for provenance and must
not be installed or advertised as Unicode fonts. All native packages and the
Nix/Guix recipes install only Unicode BDF and OTB files.

Source and runtime remain separate directories because they answer different
questions. The source profile preserves authored representations and variants;
the runtime profile preserves the 49 reviewed System 46 compiled objects,
including two explicitly legacy versions. Installing both does not collapse
those identities.

## GitHub Release assets

A `v*` tag publishes these generic archives and adjacent SHA-256 files:

```text
CADR-fonts-latin-<version>.tar.gz
CADR-fonts-latin-<version>.tar.gz.sha256
CADR-fonts-symbols-<version>.tar.gz
CADR-fonts-symbols-<version>.tar.gz.sha256
```

It also publishes separate `cadr-fonts-latin` and `cadr-fonts-symbols`
packages for:

| Platform | Format | Architecture marker |
| --- | --- | --- |
| Debian and Ubuntu | `.deb` | `all` |
| RPM distributions | `.rpm` | `noarch` |
| Arch Linux | `.pkg.tar.zst` | `any` |
| Void Linux | `.xbps` | `noarch` |

Every concrete package is installed and queried in a native distribution
container before the tag job can create a release. Every payload has its own
adjacent `.sha256`; the release job accepts exactly ten payloads and ten
checksums and refuses to mutate an existing release.

The binary packages use this co-installable layout:

```text
/usr/share/fonts/cadr-fonts/<collection>/bdf/{source,runtime}/
/usr/share/fonts/cadr-fonts/<collection>/otb/{source,runtime}/
/usr/share/cadr-fonts/<collection>/
/usr/share/doc/cadr-fonts-<collection>/
```

Their Fontconfig snippets expose only the OTB directories. The BDF indexes are
available for an X core server when that interface is specifically required.

Install either collection or both downloaded packages with the native package
manager (replace `*` with the release's exact filenames):

```sh
# Debian or Ubuntu
sudo apt install ./cadr-fonts-latin_*.deb ./cadr-fonts-symbols_*.deb

# Fedora or another RPM distribution using DNF
sudo dnf install ./cadr-fonts-latin-*.rpm ./cadr-fonts-symbols-*.rpm

# Arch Linux
sudo pacman -U ./cadr-fonts-latin-*.pkg.tar.zst ./cadr-fonts-symbols-*.pkg.tar.zst

# Void Linux: make the downloaded directory a local XBPS repository first
xbps-rindex -a ./cadr-fonts-latin-*.xbps ./cadr-fonts-symbols-*.xbps
sudo xbps-install --repository="$PWD" cadr-fonts-latin cadr-fonts-symbols
```

Check the adjacent `.sha256` files before installation. Omitting either
collection's filename/package name installs only the other collection.

## Local generic and binary builds

Build and independently verify both generic archives with a version string and
the source commit timestamp:

```sh
version=v0.1.1
epoch=$(git show -s --format=%ct HEAD)
make check-release VERSION="$version" SOURCE_DATE_EPOCH="$epoch"
make release-reproducible VERSION="$version" SOURCE_DATE_EPOCH="$epoch"
```

The build requires Python 3.10 or newer and `fonttosfnt`; OTB validation also
requires Python FontTools. The full `make ci` gate additionally needs
`bdftopcf`, `mkfontdir`, Xvfb, and Xlib.

After the generic archives exist, the release-package builders are:

```sh
export SOURCE_DATE_EPOCH="$epoch"
scripts/package-deb.sh --version "$version"
scripts/package-rpm.sh --version "$version"
scripts/package-arch.sh --version "$version"
scripts/package-void.sh --version "$version"
```

The scripts require `SOURCE_DATE_EPOCH`; this prevents a package build from
silently embedding wall-clock metadata instead of the release epoch.

Each command emits two packages plus checksums beneath
`dist/packages/<format>/`. The DEB builder needs `dpkg-deb`; RPM needs
`rpmbuild`; Arch needs `makepkg`; and Void needs `xbps-create` or a Docker or
Podman runtime for its Void-container fallback. Concrete package install tests
can be repeated with:

```sh
scripts/test-linux-package-container.sh \
  --runtime docker --format deb \
  --package dist/packages/deb/cadr-fonts-latin_0.1.1-1_all.deb \
  --package dist/packages/deb/cadr-fonts-symbols_0.1.1-1_all.deb
```

Use the matching format and files for the other package systems. Passing both
packages proves they are co-installable in one clean native container.

## Nix flake

The locked flake exposes both packages on x86_64 and AArch64 Linux:

```sh
nix profile install .#cadr-fonts-latin
nix profile install .#cadr-fonts-symbols
nix flake check
```

The flake fetches the exact CADR source revision independently, presents it to
the generator as a hash-closed source snapshot, rebuilds both release archives,
checks all 20,307 encoded BDF-derived OTB glyphs, and installs only Unicode
BDF/OTB trees. GitHub Actions
runs the checks on native x86_64 and AArch64 hosted runners. For a clean local
container check, use `make test-nix-flake-container`.

## Guix packages

The local Guix module exposes the same two independently installable outputs.
Load it directly from this checkout:

```sh
guix lint -L packaging/guix cadr-fonts-latin cadr-fonts-symbols
guix build -L packaging/guix cadr-fonts-latin cadr-fonts-symbols
guix install -L packaging/guix cadr-fonts-latin cadr-fonts-symbols
```

The recipe's source closure contains the generator, mapping/manifests, pinned
font payload, and the seven exact CADR files whose hashes support the Unicode
mapping and GERM35 raster-order evidence. It installs neither raw CADR-code
BDFs nor unrelated CADR source files.

## Manual source-package recipes

The following recipes mirror the additional platforms maintained by the
sibling DEC Fonts project:

- `packaging/aur/cadr-fonts-git/` is an AUR-style VCS split `PKGBUILD` for
  `cadr-fonts-latin-git` and `cadr-fonts-symbols-git`; its separately declared
  CADR Git source is redirected into the pinned submodule checkout.
- `packaging/gentoo/` is a local live overlay containing independent
  `media-fonts/cadr-fonts-latin` and `media-fonts/cadr-fonts-symbols` ebuilds.
- `packaging/guix/` is a local channel module exporting `cadr-fonts-latin` and
  `cadr-fonts-symbols`; it closes a local source snapshot over the generator,
  manifests, and pinned CADR inputs.
- `packaging/void/` contains explicit local `xbps-src` templates. They avoid a
  dead release URL or invented checksum and consume a locally verified release
  directory visible inside the build chroot.

Each directory contains platform-specific usage notes where needed. These are
source recipes, distinct from the concrete DEB/RPM/Arch/Void binaries attached
to tagged GitHub Releases.

## Format boundary

These are bitmap fonts. OTB is an embedded-bitmap SFNT container, not a vector
or outline conversion. The release does not ship PCF because it is a native X
server cache derivative that can be compiled locally from BDF. It does not ship
PSF because the corpus contains many proportional and non-character-cell fonts
and is not a Linux-console font set.

Repository-authored build, packaging, metadata, and documentation material is
governed by the root BSD-3-Clause `LICENSE` and is installed by packages as
`LICENSE.project`. The recovered font payload and its direct derivatives retain
the pinned upstream BSD-3-Clause text installed as `LICENSE.source`. Package
metadata uses each platform's BSD-3-Clause identifier (`BSD` in Gentoo), while
both distinct notices are shipped so neither attribution chain is collapsed.
