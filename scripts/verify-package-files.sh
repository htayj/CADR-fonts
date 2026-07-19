#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
usage: scripts/verify-package-files.sh --group latin|symbols [--prefix PATH]
       [--allow-missing-doc] [--skip-fontconfig]

Verify one installed CADR-fonts group, including exact profile counts, BDF
indexes and aliases, metadata, documentation, and OTB fontconfig visibility.
USAGE
}

fail() {
    echo "verify-package-files: $*" >&2
    exit 1
}

group=
prefix=/
skip_fontconfig=false
allow_missing_doc=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --group) [[ $# -ge 2 ]] || fail "--group requires a value"; group=$2; shift 2 ;;
        --group=*) group=${1#--group=}; shift ;;
        --prefix) [[ $# -ge 2 ]] || fail "--prefix requires a path"; prefix=$2; shift 2 ;;
        --prefix=*) prefix=${1#--prefix=}; shift ;;
        --allow-missing-doc) allow_missing_doc=true; shift ;;
        --skip-fontconfig) skip_fontconfig=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done
case "$group" in latin|symbols) ;; *) fail "--group must be latin or symbols" ;; esac

join_path() {
    local base=${1%/}
    local rest=${2#/}
    if [[ -z "$base" || "$base" == / ]]; then printf '/%s' "$rest"; else printf '%s/%s' "$base" "$rest"; fi
}
need_tool() { command -v "$1" >/dev/null 2>&1 || fail "missing required tool: $1"; }
for tool in python3 find grep sort; do need_tool "$tool"; done

case "$group" in
    latin) expected_source=118; expected_runtime=42 ;;
    symbols) expected_source=33; expected_runtime=7 ;;
esac

font_root=$(join_path "$prefix" "/usr/share/fonts/cadr-fonts/$group")
data_root=$(join_path "$prefix" "/usr/share/cadr-fonts/$group")
doc_root=$(join_path "$prefix" "/usr/share/doc/cadr-fonts-$group")
config_name="75-cadr-fonts-$group.conf"
config_available=$(join_path "$prefix" "/usr/share/fontconfig/conf.avail/$config_name")
config_enabled=$(join_path "$prefix" "/etc/fonts/conf.d/$config_name")

for file in \
    "$data_root/RELEASE-MANIFEST.json" \
    "$data_root/SHA256SUMS" \
    "$data_root/metadata/SOURCE-MANIFEST.json" \
    "$data_root/metadata/runtime-source-manifest.json" \
    "$data_root/metadata/UNICODE-MAPPING.json"; do
    [[ -s "$file" ]] || fail "missing or empty installed file: $file"
done
for file in \
    "$doc_root/README.release.md" \
    "$doc_root/LICENSE.project" \
    "$doc_root/LICENSE.source"; do
    if [[ -s "$file" ]]; then
        continue
    fi
    [[ $allow_missing_doc == true ]] || fail "missing or empty installed file: $file"
    echo "documentation omitted by package-manager policy: $file"
done

check_bdf_profile() {
    local directory=$1
    local expected=$2
    python3 - "$directory" "$expected" <<'PY'
from pathlib import Path
import shlex
import sys

directory = Path(sys.argv[1])
expected = int(sys.argv[2])
if not directory.is_dir():
    raise SystemExit(f"missing BDF profile: {directory}")
bdfs = sorted(directory.glob("*.bdf"))
if len(bdfs) != expected:
    raise SystemExit(f"{directory}: expected {expected} BDFs, found {len(bdfs)}")

font_names = {}
for path in bdfs:
    name = None
    with path.open(encoding="ascii") as source:
        for line in source:
            if line.startswith("FONT "):
                name = line[5:].rstrip("\n")
                break
    if not name:
        raise SystemExit(f"{path}: missing FONT record")
    if not name.endswith("-ISO10646-1"):
        raise SystemExit(f"{path}: installed BDF is not Unicode encoded: {name}")
    if name in font_names:
        raise SystemExit(f"{directory}: duplicate FONT name {name!r}")
    font_names[name] = path.name

index_path = directory / "fonts.dir"
lines = index_path.read_text(encoding="utf-8").splitlines()
if not lines or not lines[0].isdigit() or int(lines[0]) != expected:
    raise SystemExit(f"{index_path}: expected count {expected}")
records = lines[1:]
if len(records) != expected:
    raise SystemExit(f"{index_path}: expected {expected} records, found {len(records)}")
indexed = {}
for line in records:
    filename, separator, xlfd = line.partition(" ")
    if not separator or not filename or not xlfd:
        raise SystemExit(f"{index_path}: malformed record {line!r}")
    if filename in indexed:
        raise SystemExit(f"{index_path}: duplicate filename {filename!r}")
    indexed[filename] = xlfd
if set(indexed) != {path.name for path in bdfs}:
    raise SystemExit(f"{index_path}: filename closure mismatch")
for xlfd, filename in font_names.items():
    if indexed.get(filename) != xlfd:
        raise SystemExit(f"{index_path}: XLFD mismatch for {filename}")

aliases_path = directory / "fonts.alias"
alias_lines = aliases_path.read_text(encoding="utf-8").splitlines()
aliases = {}
for line in alias_lines:
    if not line or line.startswith("!"):
        continue
    fields = shlex.split(line)
    if len(fields) != 2:
        raise SystemExit(f"{aliases_path}: malformed alias {line!r}")
    alias, target = fields
    if alias in aliases:
        raise SystemExit(f"{aliases_path}: duplicate alias {alias!r}")
    if target not in font_names:
        raise SystemExit(f"{aliases_path}: alias target is not in fonts.dir: {target!r}")
    aliases[alias] = target
if not aliases:
    raise SystemExit(f"{aliases_path}: no aliases")
PY
}

check_bdf_profile "$font_root/bdf/source" "$expected_source"
check_bdf_profile "$font_root/bdf/runtime" "$expected_runtime"

if find "$font_root/bdf" -mindepth 1 -maxdepth 1 -type d \
        ! -name source ! -name runtime -print -quit | grep -q .; then
    fail "installed BDF tree contains an unexpected profile"
fi

python3 - "$font_root" "$expected_source" "$expected_runtime" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for profile, expected in (("source", int(sys.argv[2])), ("runtime", int(sys.argv[3]))):
    directory = root / "otb" / profile
    files = sorted(directory.glob("*.otb")) if directory.is_dir() else []
    if len(files) != expected:
        raise SystemExit(f"{directory}: expected {expected} OTBs, found {len(files)}")
    bdf_stems = {p.stem for p in (root / "bdf" / profile).glob("*.bdf")}
    if {p.stem for p in files} != bdf_stems:
        raise SystemExit(f"{directory}: OTB/Unicode-BDF filename closure mismatch")
PY

if [[ "$skip_fontconfig" == true ]]; then
    echo "fontconfig checks skipped for cadr-fonts-$group"
    exit 0
fi

for file in "$config_available" "$config_enabled"; do
    [[ -s "$file" ]] || fail "missing installed fontconfig file: $file"
done
for tool in fc-cache fc-query fc-list fc-match mktemp; do need_tool "$tool"; done

first_otb=$(find "$font_root/otb" -type f -name '*.otb' | sort | head -n 1)
[[ -n "$first_otb" ]] || fail "no OTB font found under $font_root"
query_family=$(fc-query --format '%{family[0]}\n' "$first_otb" | head -n 1)
[[ -n "$query_family" ]] || fail "fc-query returned no family for $first_otb"

fontconfig_tmp=$(mktemp -d)
trap 'rm -rf "$fontconfig_tmp"' EXIT
mkdir -p "$fontconfig_tmp/cache"
cat > "$fontconfig_tmp/fonts.conf" <<XML
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>$font_root/otb/source</dir>
  <dir>$font_root/otb/runtime</dir>
  <include ignore_missing="no">$config_available</include>
  <cachedir>$fontconfig_tmp/cache</cachedir>
</fontconfig>
XML
fontconfig_env=(env FONTCONFIG_FILE="$fontconfig_tmp/fonts.conf" XDG_CACHE_HOME="$fontconfig_tmp/cache")
"${fontconfig_env[@]}" fc-cache -f "$font_root/otb" >/dev/null

listed_files=$("${fontconfig_env[@]}" fc-list --format '%{file}\n' | sort -u)
listed_count=$(printf '%s\n' "$listed_files" | grep -Fc "$font_root/otb/" || true)
expected_otb=$((expected_source + expected_runtime))
[[ $listed_count -eq $expected_otb ]] || fail "fc-list exposed $listed_count packaged OTBs, expected $expected_otb"

matched_file=$("${fontconfig_env[@]}" fc-match --format '%{file}\n' "$query_family" | head -n 1)
case "$matched_file" in "$font_root"/otb/*) ;; *) fail "fc-match did not resolve $query_family to cadr-fonts-$group: $matched_file" ;; esac

echo "cadr-fonts-$group installed-file verification passed"
