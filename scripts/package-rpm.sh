#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
usage: scripts/package-rpm.sh [--version VERSION] [--release-dir DIR]
       [--archive FILE ...] [--output-dir DIR] [--no-fontconfig]

Build co-installable cadr-fonts-latin and cadr-fonts-symbols noarch RPMs.
SOURCE_DATE_EPOCH must be set to the release epoch.
USAGE
}

fail() { echo "package-rpm: $*" >&2; exit 1; }
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
raw_version=${VERSION:-}
release_dir=${RELEASE_DIR:-dist/release}
output_dir=${RPM_PACKAGE_DIR:-${DIST_PACKAGE_DIR:-dist/packages}/rpm}
install_fontconfig=true
archive_inputs=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) [[ $# -ge 2 ]] || fail "--version requires a value"; raw_version=$2; shift 2 ;;
        --version=*) raw_version=${1#--version=}; shift ;;
        --release-dir) [[ $# -ge 2 ]] || fail "--release-dir requires a directory"; release_dir=$2; shift 2 ;;
        --release-dir=*) release_dir=${1#--release-dir=}; shift ;;
        --archive) [[ $# -ge 2 ]] || fail "--archive requires a file"; archive_inputs+=("$2"); shift 2 ;;
        --archive=*) archive_inputs+=("${1#--archive=}"); shift ;;
        --output-dir|--package-dir) [[ $# -ge 2 ]] || fail "$1 requires a directory"; output_dir=$2; shift 2 ;;
        --output-dir=*|--package-dir=*) output_dir=${1#*=}; shift ;;
        --fontconfig) install_fontconfig=true; shift ;;
        --no-fontconfig) install_fontconfig=false; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

[[ -n "$raw_version" ]] || raw_version=$(git -C "$repo_root" describe --tags --always --dirty 2>/dev/null || echo dev)
[[ $raw_version =~ ^[A-Za-z0-9._+~-]+$ ]] || fail "unsafe VERSION: $raw_version"
[[ ${SOURCE_DATE_EPOCH:-} =~ ^[0-9]+$ ]] || fail "SOURCE_DATE_EPOCH must be a non-negative integer"
export SOURCE_DATE_EPOCH
for tool in rpmbuild sha256sum mktemp cp mkdir; do command -v "$tool" >/dev/null 2>&1 || fail "missing required tool: $tool"; done

declare -A archives=()
archive_dir=$release_dir
for archive in "${archive_inputs[@]}"; do
    [[ -f "$archive" ]] || fail "missing release archive: $archive"
    archive=$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")
    case $(basename "$archive") in
        "CADR-fonts-latin-$raw_version.tar.gz") group=latin ;;
        "CADR-fonts-symbols-$raw_version.tar.gz") group=symbols ;;
        *) fail "archive name does not match VERSION $raw_version: $archive" ;;
    esac
    [[ -z ${archives[$group]:-} ]] || fail "duplicate $group archive"
    archives[$group]=$archive
    archive_dir=$(dirname "$archive")
done
for group in latin symbols; do
    archives[$group]=${archives[$group]:-"$archive_dir/CADR-fonts-$group-$raw_version.tar.gz"}
    [[ -f ${archives[$group]} ]] || fail "missing $group release archive: ${archives[$group]}"
done

package_version=$("$script_dir/package-version.sh" --format rpm "$raw_version")
mkdir -p "$output_dir"
output_dir=$(cd "$output_dir" && pwd)
workdir=$(mktemp -d "$output_dir/.rpmbuild.XXXXXX")
trap 'rm -rf "$workdir"' EXIT

for group in latin symbols; do
    package="cadr-fonts-$group"
    staged="$workdir/$group-root"
    stage_args=(--format rpm --group "$group" --destdir "$staged" --version "$raw_version" --archive "${archives[$group]}")
    [[ $install_fontconfig == true ]] || stage_args+=(--no-fontconfig)
    "$script_dir/stage-linux-package.sh" "${stage_args[@]}"
    "$script_dir/verify-package-files.sh" --group "$group" --prefix "$staged" --skip-fontconfig

    topdir="$workdir/$group-rpmbuild"
    mkdir -p "$topdir/BUILD" "$topdir/BUILDROOT" "$topdir/RPMS" "$topdir/SOURCES" "$topdir/SPECS" "$topdir/SRPMS"
    spec="$topdir/SPECS/$package.spec"
    if [[ $group == latin ]]; then
        summary="MIT CADR bitmap fonts with visible Latin alphabets"
    else
        summary="MIT CADR bitmap symbol and drawing fonts"
    fi
    cat > "$spec" <<SPEC
%global debug_package %{nil}
Name: $package
Version: $package_version
Release: 1
Summary: $summary
License: BSD-3-Clause
URL: https://github.com/htayj/CADR-fonts
BuildArch: noarch
Requires: fontconfig
AutoReqProv: no

%description
Unicode-encoded bitmap-font profiles recovered from MIT CADR source and the
reviewed System 46 runtime, with Unicode OTB conversions for modern clients.

%prep

%build

%install
rm -rf "%{buildroot}"
mkdir -p "%{buildroot}"
cp -a "$staged"/. "%{buildroot}"/

%files
/usr/share/fonts/cadr-fonts/$group
/usr/share/cadr-fonts/$group
%doc /usr/share/doc/$package/README.release.md
%license /usr/share/doc/$package/LICENSE.project
%license /usr/share/doc/$package/LICENSE.source
SPEC
    if [[ $install_fontconfig == true ]]; then
        cat >> "$spec" <<SPEC
/usr/share/fontconfig/conf.avail/75-cadr-fonts-$group.conf
%config(noreplace) /etc/fonts/conf.d/75-cadr-fonts-$group.conf
SPEC
    fi

    rpmbuild -bb "$spec" \
        --define "_topdir $topdir" \
        --define "_build_id_links none" \
        --define "use_source_date_epoch_as_buildtime 1" \
        --define "_buildhost reproducible.cadr-fonts.invalid"
    built="$topdir/RPMS/noarch/$package-$package_version-1.noarch.rpm"
    [[ -f "$built" ]] || fail "rpmbuild did not produce expected RPM: $built"
    package_path="$output_dir/$(basename "$built")"
    checksum_path="$package_path.sha256"
    rm -f "$package_path" "$checksum_path"
    cp -f "$built" "$package_path"
    (cd "$output_dir" && sha256sum "$(basename "$package_path")" > "$(basename "$checksum_path")")
    echo "wrote $package_path"
    echo "wrote $checksum_path"
done
