# Arch User Repository recipe

`cadr-fonts/PKGBUILD` is the stable AUR split-package recipe. It builds the
tagged source release and installs either `cadr-fonts-latin` or
`cadr-fonts-symbols`; the two packages do not share installed files.

Both packages install only the Unicode BDF source/runtime profiles and their
Unicode OTB conversions. The raw CADR-code BDFs remain provenance material in
the generic release archives and are not installed as fonts.

For local testing:

```sh
cd packaging/aur/cadr-fonts
makepkg --syncdeps --install
```

`makepkg` asks which split packages to install when appropriate. The declared
second Git source lets `makepkg` acquire the CADR submodule during source
acquisition; both the CADR Fonts tag and historical CADR revision are immutable
source identities. `prepare()` redirects the submodule to that local checkout.

The AUR Git repository contains only `PKGBUILD`, generated `.SRCINFO`,
`.gitignore`, `LICENSE`, its `LICENSES/0BSD.txt` compatibility symlink, and
`REUSE.toml`. The licensing files cover the packaging recipe itself under
0BSD; the built font packages retain and install the two upstream
BSD-3-Clause notices separately.
