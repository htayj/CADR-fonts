# Void Linux local templates

These are local `xbps-src` templates for the independent
`cadr-fonts-latin` and `cadr-fonts-symbols` packages. They intentionally do not
name a remote `distfiles` URL or placeholder checksum before the first release
exists.

Build and check the local release first:

```sh
make release check-release VERSION=v0.1.1
```

Make this checkout visible inside the Void packages tree (placing it below
`srcpkgs/_sources/` is convenient), copy or symlink the two template
directories into `void-packages/srcpkgs`, and put paths visible *inside the
chroot* in `void-packages/etc/conf`:

```sh
CADR_FONTS_SOURCE_DIR=/void-packages/srcpkgs/_sources/cadr-fonts
CADR_FONTS_RELEASE_DIR=/void-packages/srcpkgs/_sources/cadr-fonts/dist/release
```

Then build either package:

```sh
./xbps-src pkg cadr-fonts-latin
./xbps-src pkg cadr-fonts-symbols
```

The templates consume the checked local archive and adjacent SHA-256 file via
the repository's safe staging helper. They install only Unicode BDF and Unicode
OTB fonts; raw CADR-code BDFs are never installed.
