#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
usage: scripts/stage-linux-package.sh --format deb|rpm|arch|gentoo|guix|void \
       --group latin|symbols --destdir DIR --version VERSION \
       [--archive FILE | --release-dir DIR] [--no-fontconfig]

Safely extract one deterministic CADR-fonts release archive and stage its
group-specific files into a Linux package root.
USAGE
}

fail() {
    echo "stage-linux-package: $*" >&2
    exit 1
}

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/.." && pwd)
format=
group=
destdir=
raw_version=${VERSION:-}
archive=
release_dir=${RELEASE_DIR:-dist/release}
install_fontconfig=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --format) [[ $# -ge 2 ]] || fail "--format requires a value"; format=$2; shift 2 ;;
        --format=*) format=${1#--format=}; shift ;;
        --group) [[ $# -ge 2 ]] || fail "--group requires a value"; group=$2; shift 2 ;;
        --group=*) group=${1#--group=}; shift ;;
        --destdir) [[ $# -ge 2 ]] || fail "--destdir requires a directory"; destdir=$2; shift 2 ;;
        --destdir=*) destdir=${1#--destdir=}; shift ;;
        --version) [[ $# -ge 2 ]] || fail "--version requires a value"; raw_version=$2; shift 2 ;;
        --version=*) raw_version=${1#--version=}; shift ;;
        --archive) [[ $# -ge 2 ]] || fail "--archive requires a file"; archive=$2; shift 2 ;;
        --archive=*) archive=${1#--archive=}; shift ;;
        --release-dir) [[ $# -ge 2 ]] || fail "--release-dir requires a directory"; release_dir=$2; shift 2 ;;
        --release-dir=*) release_dir=${1#--release-dir=}; shift ;;
        --fontconfig) install_fontconfig=true; shift ;;
        --no-fontconfig) install_fontconfig=false; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

case "$format" in
    deb|rpm|arch|gentoo|guix|void) ;;
    *) fail "--format must be deb, rpm, arch, gentoo, guix, or void" ;;
esac
case "$group" in latin|symbols) ;; *) fail "--group must be latin or symbols" ;; esac
for tool in python3 sha256sum install find sort mktemp cp chmod grep mkdir awk; do
    command -v "$tool" >/dev/null 2>&1 || fail "missing required tool: $tool"
done
[[ -n "$destdir" ]] || fail "--destdir is required"
[[ "$destdir" != / ]] || fail "refusing to stage directly into /"
[[ ! -L "$destdir" ]] || fail "--destdir must not be a symbolic link"
if [[ -e "$destdir" ]]; then
    [[ -d "$destdir" ]] || fail "--destdir exists and is not a directory: $destdir"
    if find "$destdir" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
        fail "--destdir must be a fresh empty package root: $destdir"
    fi
else
    mkdir -p "$destdir"
fi
destdir=$(cd "$destdir" && pwd -P)
[[ -n "$raw_version" ]] || fail "--version is required"
[[ $raw_version =~ ^[A-Za-z0-9._+~-]+$ ]] || fail "unsafe VERSION for archive name: $raw_version"

if [[ -z "$archive" ]]; then
    archive="$release_dir/CADR-fonts-$group-$raw_version.tar.gz"
fi
[[ -f "$archive" ]] || fail "missing release archive: $archive"
archive=$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")
expected_basename="CADR-fonts-$group-$raw_version.tar.gz"
[[ $(basename "$archive") == "$expected_basename" ]] || \
    fail "archive must be named $expected_basename: $archive"

checksum="$archive.sha256"
[[ -f "$checksum" ]] || fail "missing archive checksum: $checksum"
read -r expected_digest checksum_name checksum_extra < "$checksum" || fail "cannot read $checksum"
[[ -z ${checksum_extra:-} ]] || fail "checksum must contain exactly one record: $checksum"
[[ $expected_digest =~ ^[0-9a-fA-F]{64}$ ]] || fail "invalid SHA-256 in $checksum"
checksum_name=${checksum_name#\*}
[[ $checksum_name == "$expected_basename" ]] || fail "checksum names $checksum_name, expected $expected_basename"
actual_digest=$(sha256sum "$archive" | awk '{print $1}')
[[ ${actual_digest,,} == ${expected_digest,,} ]] || fail "archive checksum mismatch: $archive"

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
expected_root="CADR-fonts-$group-$raw_version"

# Do not delegate path safety to tar implementation defaults.  Reject links,
# devices, duplicate names, absolute paths, and parent traversal, then extract
# regular files ourselves beneath the expected single top-level directory.
python3 - "$archive" "$workdir" "$expected_root" <<'PY'
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

archive = Path(sys.argv[1])
destination = Path(sys.argv[2])
expected_root = sys.argv[3]
seen: set[str] = set()

with tarfile.open(archive, "r:gz") as source:
    members = source.getmembers()
    if not members:
        raise SystemExit("release archive is empty")
    for member in members:
        name = member.name.rstrip("/")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe archive path: {member.name!r}")
        if path.parts[0] != expected_root:
            raise SystemExit(f"archive member is outside {expected_root!r}: {member.name!r}")
        normalized = str(path)
        if normalized in seen:
            raise SystemExit(f"duplicate archive member: {normalized}")
        seen.add(normalized)
        if not (member.isdir() or member.isfile()):
            raise SystemExit(f"unsupported archive member type: {member.name!r}")

    for member in members:
        relative = PurePosixPath(member.name.rstrip("/"))
        target = destination.joinpath(*relative.parts)
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            target.chmod(0o755)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        extracted = source.extractfile(member)
        if extracted is None:
            raise SystemExit(f"cannot read archive member: {member.name!r}")
        with target.open("xb") as output:
            shutil.copyfileobj(extracted, output)
        target.chmod(0o644)
PY

payload="$workdir/$expected_root"
[[ -d "$payload" ]] || fail "archive did not contain $expected_root"
for required in \
    README.release.md \
    LICENSE.project \
    LICENSE.source \
    RELEASE-MANIFEST.json \
    SHA256SUMS \
    metadata/FONT-IDENTITIES.json \
    metadata/SOURCE-MANIFEST.json \
    metadata/runtime-source-manifest.json \
    metadata/UNICODE-MAPPING.json; do
    [[ -s "$payload/$required" ]] || fail "archive is missing required file: $required"
done

(cd "$payload" && sha256sum -c SHA256SUMS >/dev/null) || fail "internal release checksums failed"

python3 - "$payload/RELEASE-MANIFEST.json" "$group" "$raw_version" "$expected_root" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
group, version, expected_name = sys.argv[2:]
manifest = json.loads(path.read_text(encoding="utf-8"))
expected = {
    "schema_version": 1,
    "content_class": group,
    "version": version,
    "name": expected_name,
}
observed = {key: manifest.get(key) for key in expected}
if observed != expected:
    raise SystemExit(
        f"release identity differs: observed={observed!r}, expected={expected!r}"
    )
expected_licenses = {
    "project": "LICENSE.project",
    "source": "LICENSE.source",
}
licenses = manifest.get("licenses")
if not isinstance(licenses, dict) or set(licenses) != set(expected_licenses):
    raise SystemExit(f"release license manifest differs: {licenses!r}")
for key, expected_path in expected_licenses.items():
    record = licenses[key]
    if not isinstance(record, dict) or {
        "path": record.get("path"),
        "spdx": record.get("spdx"),
    } != {"path": expected_path, "spdx": "BSD-3-Clause"}:
        raise SystemExit(f"release {key} license record differs: {record!r}")

metadata = manifest.get("metadata")
expected_metadata = {
    "FONT-IDENTITIES.json",
    "SOURCE-MANIFEST.json",
    "runtime-source-manifest.json",
    "UNICODE-MAPPING.json",
}
if not isinstance(metadata, dict) or set(metadata) != expected_metadata:
    raise SystemExit(f"release metadata manifest differs: {metadata!r}")
source_distribution = manifest.get("source_distribution")
if not isinstance(source_distribution, dict):
    raise SystemExit("release source-distribution provenance is missing")
identity_provenance = source_distribution.get("font_identities")
if not isinstance(identity_provenance, dict) or not identity_provenance.get("id"):
    raise SystemExit("release font-identity provenance is missing")
identities_path = path.parent / "metadata" / "FONT-IDENTITIES.json"
identities_bytes = identities_path.read_bytes()
identities = json.loads(identities_bytes)
identity_digest = hashlib.sha256(identities_bytes).hexdigest()
if identity_provenance != {
    "path": "FONT-IDENTITIES.json",
    "id": identities.get("mapping_id"),
    "sha256": identity_digest,
}:
    raise SystemExit("release font-identity provenance differs")
for name, record in metadata.items():
    metadata_path = path.parent / "metadata" / name
    if not isinstance(record, dict) or record != {
        "path": f"metadata/{name}",
        "sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
    }:
        raise SystemExit(f"release metadata provenance differs for {name}")
for artifact in manifest.get("artifacts", []):
    if not isinstance(artifact, dict):
        raise SystemExit("release artifact record is malformed")
    logical_identity = artifact.get("logical_identity")
    representation = artifact.get("representation")
    if not isinstance(logical_identity, dict) or not isinstance(representation, dict):
        raise SystemExit("release artifact identity is missing")
    if "representation" in logical_identity:
        raise SystemExit("release artifact representation is nested in logical identity")
    if (
        representation.get("profile") != artifact.get("profile")
        or representation.get("artifact_name") != artifact.get("artifact_name")
    ):
        raise SystemExit("release artifact representation identity differs")
PY

case "$group" in
    latin) expected_source=118; expected_runtime=42 ;;
    symbols) expected_source=33; expected_runtime=7 ;;
esac

check_profile() {
    local directory=$1
    local extension=$2
    local expected=$3
    [[ -d "$directory" ]] || fail "missing archive directory: ${directory#"$payload/"}"
    local actual
    actual=$(find "$directory" -maxdepth 1 -type f -name "*.$extension" -printf . | wc -c)
    [[ $actual -eq $expected ]] || fail "${directory#"$payload/"}: expected $expected .$extension files, found $actual"
}

for profile in raw/source unicode/source; do
    check_profile "$payload/fonts/$profile" bdf "$expected_source"
done
for profile in raw/runtime unicode/runtime; do
    check_profile "$payload/fonts/$profile" bdf "$expected_runtime"
done
check_profile "$payload/fonts/otb/source" otb "$expected_source"
check_profile "$payload/fonts/otb/runtime" otb "$expected_runtime"

for profile in raw/source raw/runtime unicode/source unicode/runtime; do
    [[ -s "$payload/fonts/$profile/fonts.dir" ]] || fail "$profile is missing fonts.dir"
    [[ -s "$payload/fonts/$profile/fonts.alias" ]] || fail "$profile is missing fonts.alias"
done

cd "$repo_root"
umask 022
font_root="$destdir/usr/share/fonts/cadr-fonts/$group"
data_root="$destdir/usr/share/cadr-fonts/$group"
doc_root="$destdir/usr/share/doc/cadr-fonts-$group"

copy_tree() {
    local source=$1
    local destination=$2
    mkdir -p "$destination"
    cp -a "$source"/. "$destination"/
}

# Packages expose only the Unicode-encoded BDF profiles as fonts.  The raw
# CADR-code BDFs remain in the generic archive as provenance material, but
# installing them beside the Unicode profiles would make the historical
# encoding too easy to select accidentally in modern applications.
copy_tree "$payload/fonts/unicode/source" "$font_root/bdf/source"
copy_tree "$payload/fonts/unicode/runtime" "$font_root/bdf/runtime"
copy_tree "$payload/fonts/otb/source" "$font_root/otb/source"
copy_tree "$payload/fonts/otb/runtime" "$font_root/otb/runtime"

install -D -m 0644 "$payload/RELEASE-MANIFEST.json" "$data_root/RELEASE-MANIFEST.json"
install -D -m 0644 "$payload/SHA256SUMS" "$data_root/SHA256SUMS"
copy_tree "$payload/metadata" "$data_root/metadata"
if [[ -d "$payload/specimens" ]]; then
    copy_tree "$payload/specimens" "$data_root/specimens"
fi
install -D -m 0644 "$payload/README.release.md" "$doc_root/README.release.md"
install -D -m 0644 "$payload/LICENSE.project" "$doc_root/LICENSE.project"
install -D -m 0644 "$payload/LICENSE.source" "$doc_root/LICENSE.source"

if [[ "$install_fontconfig" == true ]]; then
    config_name="75-cadr-fonts-$group.conf"
    config_available="$destdir/usr/share/fontconfig/conf.avail/$config_name"
    config_enabled="$destdir/etc/fonts/conf.d/$config_name"
    mkdir -p "$(dirname "$config_available")" "$(dirname "$config_enabled")"
    python3 - "$group" > "$config_available" <<'PY'
import sys
group = sys.argv[1]
root = f"/usr/share/fonts/cadr-fonts/{group}/otb"
print('<?xml version="1.0"?>')
print('<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">')
print('<fontconfig>')
print(f'  <description>MIT CADR {group} bitmap fonts</description>')
print(f'  <dir>{root}/source</dir>')
print(f'  <dir>{root}/runtime</dir>')
print('</fontconfig>')
PY
    cp -p "$config_available" "$config_enabled"
fi

find "$destdir" -type d -exec chmod 0755 {} +
find "$destdir" -type f -exec chmod 0644 {} +

# A group package may own shared parent directories, but never a file belonging
# to the other group.
other_group=latin
[[ $group == latin ]] && other_group=symbols
[[ ! -e "$destdir/usr/share/fonts/cadr-fonts/$other_group" ]] || fail "staging leaked $other_group font paths"
[[ ! -e "$destdir/usr/share/cadr-fonts/$other_group" ]] || fail "staging leaked $other_group data paths"
[[ ! -e "$destdir/usr/share/doc/cadr-fonts-$other_group" ]] || fail "staging leaked $other_group documentation paths"
[[ ! -e "$destdir/etc/fonts/conf.d/75-cadr-fonts-$other_group.conf" ]] || fail "staging leaked $other_group fontconfig paths"

echo "staged cadr-fonts-$group $format package root at $destdir"
