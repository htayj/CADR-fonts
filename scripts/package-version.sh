#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
usage: scripts/package-version.sh [--format generic|deb|rpm|arch|void] [VERSION]

Normalize a release tag or git-describe string for package metadata.  A leading
"v" on a numeric version is removed. SemVer prereleases use each package
manager's ordering form so that they sort before the corresponding final
release; post-tag Git snapshots sort after their base tag.
USAGE
}

fail() {
    echo "package-version: $*" >&2
    exit 1
}

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
format=generic
raw_version=

while [[ $# -gt 0 ]]; do
    case "$1" in
        --format)
            [[ $# -ge 2 ]] || fail "--format requires a value"
            format=$2
            shift 2
            ;;
        --format=*)
            format=${1#--format=}
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --*)
            fail "unknown option: $1"
            ;;
        *)
            [[ -z "$raw_version" ]] || fail "only one VERSION may be supplied"
            raw_version=$1
            shift
            ;;
    esac
done

case "$format" in
    generic|deb|rpm|arch|void) ;;
    *) fail "--format must be generic, deb, rpm, arch, or void: $format" ;;
esac

if [[ -z "$raw_version" ]]; then
    raw_version=${VERSION:-}
fi
if [[ -z "$raw_version" ]]; then
    raw_version=$(git -C "$repo_root" describe --tags --always --dirty 2>/dev/null || echo dev)
fi

dirty_suffix=
if [[ $raw_version == *-dirty ]]; then
    raw_version=${raw_version%-dirty}
    dirty_suffix=dirty
fi

# `git describe` appends `-<distance>-g<commit>` to the nearest tag.  That is
# not a SemVer prerelease: it is a later development snapshot.  Separate the
# suffix before normalizing the tag, then express it as build metadata accepted
# by all four package managers.
git_distance=
git_revision=
if [[ $raw_version =~ ^(.+)-([0-9]+)-g([0-9A-Fa-f]+)$ ]]; then
    raw_version=${BASH_REMATCH[1]}
    git_distance=${BASH_REMATCH[2]}
    git_revision=${BASH_REMATCH[3],,}
fi

if [[ $raw_version =~ ^[vV][0-9] ]]; then
    raw_version=${raw_version:1}
fi

# Preserve stable versions exactly. For SemVer-style prereleases, use the
# package-manager-specific form that sorts before the final release. Pacman's
# vercmp treats tilde as newer, so Arch uses an alphabetic `pre.` suffix.
if [[ $raw_version =~ ^([0-9]+(\.[0-9]+)*)(-([0-9A-Za-z][0-9A-Za-z.-]*))?(\+([0-9A-Za-z][0-9A-Za-z.-]*))?$ ]]; then
    base=${BASH_REMATCH[1]}
    prerelease=${BASH_REMATCH[4]:-}
    build=${BASH_REMATCH[6]:-}
    version=$base
    if [[ -n "$prerelease" ]]; then
        case "$format" in
            generic) version+="-$prerelease" ;;
            arch) version+="pre.$prerelease" ;;
            deb|rpm|void) version+="~$prerelease" ;;
        esac
    fi
    [[ -z "$build" ]] || version+="+$build"
else
    version=$(printf '%s' "$raw_version" | LC_ALL=C sed -E \
        -e 's/[^A-Za-z0-9.+~]+/./g' \
        -e 's/[.]+/./g' \
        -e 's/^[.]+//' \
        -e 's/[.]+$//')
    [[ -n "$version" ]] || version=unknown
    [[ $version =~ ^[0-9] ]] || version="0+git.$version"
fi

metadata=()
if [[ -n "$git_distance" ]]; then
    metadata+=("git" "$git_distance" "g$git_revision")
fi
[[ -z "$dirty_suffix" ]] || metadata+=("$dirty_suffix")
if [[ ${#metadata[@]} -gt 0 ]]; then
    suffix=$(IFS=.; printf '%s' "${metadata[*]}")
    if [[ $version == *+* ]]; then
        version+=".$suffix"
    else
        version+="+$suffix"
    fi
fi

case "$format" in
    generic)
        [[ $version =~ ^[A-Za-z0-9.+~-]+$ ]] || fail "invalid generic version: $version"
        ;;
    deb|rpm|arch|void)
        [[ $version != *-* ]] || fail "$format version must not contain '-': $version"
        [[ $version =~ ^[A-Za-z0-9.+~]+$ ]] || fail "invalid $format version: $version"
        ;;
esac

printf '%s\n' "$version"
