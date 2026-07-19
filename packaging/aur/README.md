# Arch User Repository recipe

`cadr-fonts-git/PKGBUILD` is a local/AUR VCS split-package recipe. It builds
and installs either `cadr-fonts-latin-git` or `cadr-fonts-symbols-git`; the two
packages do not share installed files.

Both packages install only the Unicode BDF source/runtime profiles and their
Unicode OTB conversions. The raw CADR-code BDFs remain provenance material in
the generic release archives and are not installed as fonts.

For local testing:

```sh
cd packaging/aur/cadr-fonts-git
makepkg --syncdeps --install
```

`makepkg` asks which split packages to install when appropriate. The declared
second Git source lets `makepkg` fetch the CADR submodule during source
acquisition; `prepare()` checks out the exact revision pinned by CADR Fonts.
