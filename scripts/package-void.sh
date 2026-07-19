#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
usage: scripts/package-void.sh [--version VERSION] [--release-dir DIR]
       [--archive FILE ...] [--output-dir DIR] [--runtime docker|podman]
       [--image IMAGE] [--no-container] [--no-fontconfig]

Build co-installable cadr-fonts-latin and cadr-fonts-symbols noarch XBPS
packages.  If xbps-create is unavailable, re-run in a Void container.
SOURCE_DATE_EPOCH must be set to the release epoch.
USAGE
}

fail() { echo "package-void: $*" >&2; exit 1; }
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
raw_version=${VERSION:-}
release_dir=${RELEASE_DIR:-dist/release}
output_dir=${VOID_PACKAGE_DIR:-${DIST_PACKAGE_DIR:-dist/packages}/void}
runtime=${CONTAINER_RUNTIME:-docker}
image=${VOID_CONTAINER_IMAGE:-docker.io/voidlinux/voidlinux:latest@sha256:26ba972f0c06beadcec4796ec3037e0bec32af4d255edb68a528bd98304c74f4}
allow_container=true
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
        --runtime) [[ $# -ge 2 ]] || fail "--runtime requires docker or podman"; runtime=$2; shift 2 ;;
        --runtime=*) runtime=${1#--runtime=}; shift ;;
        --image) [[ $# -ge 2 ]] || fail "--image requires a value"; image=$2; shift 2 ;;
        --image=*) image=${1#--image=}; shift ;;
        --no-container) allow_container=false; shift ;;
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
case "$runtime" in docker|podman) ;; *) fail "--runtime must be docker or podman: $runtime" ;; esac

if ! command -v xbps-create >/dev/null 2>&1; then
    [[ $allow_container == true ]] || fail "missing required tool: xbps-create"
    command -v "$runtime" >/dev/null 2>&1 || fail "missing container runtime: $runtime"
    # The standard CI invocation keeps releases and outputs beneath the checkout;
    # refusing external paths avoids silently writing somewhere not mounted.
    for path in "$release_dir" "$output_dir" "${archive_inputs[@]}"; do
        [[ -z "$path" ]] && continue
        resolved=$(realpath -m "$path")
        case "$resolved" in "$repo_root"|"$repo_root"/*) ;; *) fail "container fallback requires paths under $repo_root: $path" ;; esac
    done
    relative_release=${release_dir#"$repo_root"/}
    relative_output=${output_dir#"$repo_root"/}
    [[ $relative_release != "$release_dir" || $release_dir != /* ]] || fail "cannot map release directory into container"
    [[ $relative_output != "$output_dir" || $output_dir != /* ]] || fail "cannot map output directory into container"
    cmd=(./scripts/package-void.sh --version "$raw_version" --release-dir "$relative_release" --output-dir "$relative_output" --no-container)
    [[ $install_fontconfig == true ]] || cmd+=(--no-fontconfig)
    for archive in "${archive_inputs[@]}"; do
        archive_abs=$(realpath -m "$archive")
        cmd+=(--archive "${archive_abs#"$repo_root"/}")
    done
    volume_suffix=:rw
    [[ $runtime == podman ]] && volume_suffix=:rw,Z
    printf 'xbps-create not found; building Void packages in %s with %s\n' "$image" "$runtime"
    "$runtime" run --rm -i -e "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH" \
        -v "$repo_root:/repo$volume_suffix" -w /repo "$image" sh -lc '
        set -eu
        mkdir -p /etc/xbps.d
        printf "%s\n" "repository=https://repo-default.voidlinux.org/current" > /etc/xbps.d/00-repository-main.conf
        xbps-install -Syu -y xbps || xbps-install -Syu -y xbps
        xbps-install -S -y bash python3
        exec bash -s
    ' <<CONTAINER_COMMAND
set -euo pipefail
$(printf ' %q' "${cmd[@]}")
CONTAINER_COMMAND
    exit $?
fi

for tool in xbps-create sha256sum mktemp cp find sort python3 touch; do command -v "$tool" >/dev/null 2>&1 || fail "missing required tool: $tool"; done

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

package_version=$("$script_dir/package-version.sh" --format void "$raw_version")
revision=1
mkdir -p "$output_dir"
output_dir=$(cd "$output_dir" && pwd)
workdir=$(mktemp -d "$output_dir/.voidbuild.XXXXXX")
trap 'rm -rf "$workdir"' EXIT

for group in latin symbols; do
    package="cadr-fonts-$group"
    root="$workdir/$group-root"
    stage_args=(--format void --group "$group" --destdir "$root" --version "$raw_version" --archive "${archives[$group]}")
    [[ $install_fontconfig == true ]] || stage_args+=(--no-fontconfig)
    "$script_dir/stage-linux-package.sh" "${stage_args[@]}"
    "$script_dir/verify-package-files.sh" --group "$group" --prefix "$root" --skip-fontconfig
    find "$root" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
    if [[ $group == latin ]]; then
        summary="MIT CADR bitmap fonts with visible Latin alphabets"
    else
        summary="MIT CADR bitmap symbol and drawing fonts"
    fi
    pkgver="$package-${package_version}_${revision}"
    expected_name="$pkgver.noarch.xbps"
    rm -f "$output_dir/$expected_name" "$output_dir/$expected_name.sha256"
    xbps_args=(
        -A noarch
        -n "$pkgver"
        -s "$summary"
        -S "Unicode-encoded MIT CADR bitmap fonts, with Unicode OTB conversions for modern clients."
        -D "fontconfig>=0"
        -H "https://github.com/htayj/CADR-fonts"
        # Project work and the upstream font payload are both BSD-3-Clause;
        # their distinct license texts are installed with the package.
        -l BSD-3-Clause
        -m "CADR-fonts maintainers <noreply@example.invalid>"
        -t fonts
    )
    [[ $install_fontconfig == true ]] && xbps_args+=(-F "/etc/fonts/conf.d/75-cadr-fonts-$group.conf")
    (cd "$output_dir" && xbps-create "${xbps_args[@]}" "$root" >/dev/null)
    [[ -f "$output_dir/$expected_name" ]] || fail "xbps-create did not produce $expected_name"
    (cd "$output_dir" && sha256sum "$expected_name" > "$expected_name.sha256")
    echo "wrote $output_dir/$expected_name"
    echo "wrote $output_dir/$expected_name.sha256"
done
