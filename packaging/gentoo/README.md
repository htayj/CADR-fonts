# Gentoo overlay

This local live overlay exposes two independent packages:

- `media-fonts/cadr-fonts-latin`
- `media-fonts/cadr-fonts-symbols`

Both `-9999` ebuilds clone CADR Fonts and its pinned submodule, build the
deterministic release payloads from source, and install only Unicode BDF and
Unicode OTB fonts. They intentionally have no stable keywords until a tagged
source release and Manifest are available.

Add `packaging/gentoo` as a local repository with `eselect repository` or a
matching `repos.conf` entry, then emerge either package.
