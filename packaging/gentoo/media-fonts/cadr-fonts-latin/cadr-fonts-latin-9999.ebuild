EAPI=8

PYTHON_COMPAT=( python3_{11..14} )
inherit font git-r3 python-any-r1

DESCRIPTION="Unicode-encoded MIT CADR bitmap fonts containing Latin letters"
HOMEPAGE="https://github.com/htayj/CADR-fonts"
EGIT_REPO_URI="https://github.com/htayj/CADR-fonts.git"
EGIT_SUBMODULES=( '*' )

# Gentoo's BSD entry covers both the project work and recovered upstream font
# payload; their distinct LICENSE.project and LICENSE.source files are installed.
LICENSE="BSD"
SLOT="0"
KEYWORDS=""

BDEPEND="
	${PYTHON_DEPS}
	x11-apps/fonttosfnt
"
RDEPEND="media-libs/fontconfig"

src_compile() {
	local epoch version
	version=$(git describe --tags --always) || die
	epoch=$(git show -s --format=%ct HEAD) || die
	printf '%s\n' "${version}" > "${T}/cadr-release-version" || die

	emake release \
		PYTHON="${EPYTHON}" \
		VERSION="${version}" \
		SOURCE_DATE_EPOCH="${epoch}"
}

src_install() {
	local version
	version=$(<"${T}/cadr-release-version") || die
	docompress -x /usr/share/doc/cadr-fonts-latin
	"${S}"/scripts/stage-linux-package.sh \
		--format gentoo \
		--group latin \
		--destdir "${D}" \
		--version "${version}" || die
}
