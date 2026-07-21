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
    "$data_root/metadata/FONT-IDENTITIES.json" \
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

python3 - "$font_root" "$data_root" "$expected_source" "$expected_runtime" <<'PY'
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys

font_root = Path(sys.argv[1])
data_root = Path(sys.argv[2])
profile_counts = {"source": int(sys.argv[3]), "runtime": int(sys.argv[4])}
manifest = json.loads((data_root / "RELEASE-MANIFEST.json").read_text(encoding="utf-8"))
identity_path = data_root / "metadata" / "FONT-IDENTITIES.json"
identity_bytes = identity_path.read_bytes()
identities = json.loads(identity_bytes)
identity_digest = hashlib.sha256(identity_bytes).hexdigest()
source_distribution = manifest.get("source_distribution")
if not isinstance(source_distribution, dict) or source_distribution.get("font_identities") != {
    "path": "FONT-IDENTITIES.json",
    "id": identities.get("mapping_id"),
    "sha256": identity_digest,
}:
    raise SystemExit("installed font-identity provenance differs")

metadata = manifest.get("metadata")
expected_metadata = {
    "FONT-IDENTITIES.json",
    "SOURCE-MANIFEST.json",
    "runtime-source-manifest.json",
    "UNICODE-MAPPING.json",
}
if not isinstance(metadata, dict) or set(metadata) != expected_metadata:
    raise SystemExit("installed release metadata set differs")
for name, record in metadata.items():
    installed = data_root / "metadata" / name
    expected_record = {
        "path": f"metadata/{name}",
        "sha256": hashlib.sha256(installed.read_bytes()).hexdigest(),
    }
    if record != expected_record:
        raise SystemExit(f"{installed}: metadata provenance differs")

assignments = identities.get("assignments")
if not isinstance(assignments, dict):
    raise SystemExit("installed font-identity assignments are missing")
source_assignments = assignments.get("source_logical_names")
runtime_assignments = assignments.get("runtime_artifacts")
if not isinstance(source_assignments, dict) or not isinstance(runtime_assignments, dict):
    raise SystemExit("installed font-identity physical assignments are missing")

expected_bdfs = set()
expected_otbs = set()
artifact_counts = {"source": 0, "runtime": 0}
physical_identities = set()
for artifact in manifest.get("artifacts", []):
    if not isinstance(artifact, dict):
        raise SystemExit("installed release artifact is malformed")
    profile = artifact.get("profile")
    artifact_name = artifact.get("artifact_name")
    if profile not in profile_counts or not isinstance(artifact_name, str):
        raise SystemExit("installed release artifact identity is malformed")
    physical = (profile, artifact_name)
    if physical in physical_identities:
        raise SystemExit(f"duplicate installed artifact identity: {physical}")
    physical_identities.add(physical)
    artifact_counts[profile] += 1

    logical_identity = artifact.get("logical_identity")
    representation = artifact.get("representation")
    if not isinstance(logical_identity, dict) or not isinstance(representation, dict):
        raise SystemExit(f"{physical}: installed logical identity is missing")
    if "representation" in logical_identity:
        raise SystemExit(f"{physical}: representation is nested in logical identity")
    if (
        representation.get("profile") != profile
        or representation.get("artifact_name") != artifact_name
    ):
        raise SystemExit(f"{physical}: installed representation identity differs")
    if profile == "source":
        logical_name = artifact.get("logical_name")
        if representation.get("logical_name") != logical_name:
            raise SystemExit(f"{physical}: installed source representation differs")
        assigned_logical_id = source_assignments.get(logical_name)
    else:
        runtime_name = artifact.get("runtime_name")
        classification = artifact.get("classification")
        if (
            representation.get("runtime_name") != runtime_name
            or representation.get("classification") != classification
        ):
            raise SystemExit(f"{physical}: installed runtime representation differs")
        assigned_logical_id = runtime_assignments.get(artifact_name)
    if assigned_logical_id != logical_identity.get("logical_id"):
        raise SystemExit(f"{physical}: installed configured logical assignment differs")

    files = artifact.get("files")
    if not isinstance(files, dict):
        raise SystemExit(f"{physical}: installed artifact files are missing")
    for kind, release_prefix, installed_kind, expected_paths in (
        ("unicode_bdf", ("fonts", "unicode", profile), "bdf", expected_bdfs),
        ("otb", ("fonts", "otb", profile), "otb", expected_otbs),
    ):
        record = files.get(kind)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise SystemExit(f"{physical}: installed {kind} record is malformed")
        relative = PurePosixPath(record["path"])
        if (
            relative.parts[:3] != release_prefix
            or len(relative.parts) != 4
            or relative.suffix != (".bdf" if kind == "unicode_bdf" else ".otb")
        ):
            raise SystemExit(f"{physical}: installed {kind} path escaped its profile")
        installed = font_root / installed_kind / profile / relative.name
        if installed in expected_paths or not installed.is_file():
            raise SystemExit(f"{physical}: installed {kind} file closure differs")
        expected_paths.add(installed)
        digest = hashlib.sha256(installed.read_bytes()).hexdigest()
        if digest != record.get("sha256"):
            raise SystemExit(f"{installed}: release hash differs")

if artifact_counts != profile_counts:
    raise SystemExit(
        f"installed artifact profile counts differ: {artifact_counts!r} != {profile_counts!r}"
    )
actual_bdfs = set(font_root.glob("bdf/*/*.bdf"))
actual_otbs = set(font_root.glob("otb/*/*.otb"))
if actual_bdfs != expected_bdfs or actual_otbs != expected_otbs:
    raise SystemExit("installed BDF/OTB manifest path closure differs")
if {path.relative_to(font_root / "bdf").with_suffix("") for path in actual_bdfs} != {
    path.relative_to(font_root / "otb").with_suffix("") for path in actual_otbs
}:
    raise SystemExit("installed OTB/Unicode-BDF profile and filename closure differs")
PY

if [[ "$skip_fontconfig" == true ]]; then
    echo "fontconfig checks skipped for cadr-fonts-$group"
    exit 0
fi

for file in "$config_available" "$config_enabled"; do
    [[ -s "$file" ]] || fail "missing installed fontconfig file: $file"
done
for tool in fc-cache fc-query fc-list fc-match mktemp; do need_tool "$tool"; done

python3 - "$font_root" "$data_root/RELEASE-MANIFEST.json" <<'PY'
from pathlib import Path, PurePosixPath
import json
import subprocess
import sys

font_root = Path(sys.argv[1])
manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))


def unicode_add_style(typographic):
    composed = " ".join(
        part for part in (typographic["add_style_name"], "Unicode") if part
    )
    normalized = "".join(
        " " if character in '-?*,"\\' else character for character in composed
    )
    return " ".join(normalized.split())


def expected_style(typographic):
    parts = []
    parts.append(unicode_add_style(typographic).replace(" ", "-"))
    if typographic["weight_name"] == "Bold":
        parts.append("Bold")
    if typographic["slant"] == "I":
        parts.append("Italic")
    if typographic["setwidth_name"] != "Normal":
        parts.append(typographic["setwidth_name"])
    return " ".join(parts) or "Regular"


expected_weights = {"Medium": 80, "Bold": 200}
expected_slants = {"R": 0, "I": 100}
expected_widths = {"Condensed": 75, "Normal": 100, "Expanded": 125}
expected_identities = {}
observed_identities = {}
for artifact in manifest["artifacts"]:
    profile = artifact["profile"]
    name = artifact["artifact_name"]
    label = f"{profile}/{name}"
    identity = artifact["logical_identity"]
    typographic = identity["typographic"]
    otb_relative = PurePosixPath(artifact["files"]["otb"]["path"])
    bdf_relative = PurePosixPath(artifact["files"]["unicode_bdf"]["path"])
    otb = font_root / "otb" / Path(
        *otb_relative.relative_to("fonts/otb").parts
    )
    bdf = font_root / "bdf" / Path(
        *bdf_relative.relative_to("fonts/unicode").parts
    )
    pixel_values = [
        line.split()[1]
        for line in bdf.read_text(encoding="ascii").splitlines()
        if line.startswith("PIXEL_SIZE ")
    ]
    if len(pixel_values) != 1:
        raise SystemExit(f"{bdf}: expected one PIXEL_SIZE")
    expected_add_style = unicode_add_style(typographic)
    add_style_values = [
        line.removeprefix('ADD_STYLE_NAME "').removesuffix('"')
        for line in bdf.read_text(encoding="ascii").splitlines()
        if line.startswith('ADD_STYLE_NAME "')
    ]
    if add_style_values != [expected_add_style]:
        raise SystemExit(f"{bdf}: Unicode BDF add style differs from logical identity")
    try:
        expected = (
            typographic["family_name"],
            expected_style(typographic),
            expected_weights[typographic["weight_name"]],
            expected_slants[typographic["slant"]],
            expected_widths[typographic["setwidth_name"]],
            float(pixel_values[0]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"{label}: unsupported logical typography: {error}") from error
    if expected in expected_identities:
        raise SystemExit(
            f"desktop identity collision: {expected_identities[expected]} and {label}"
        )
    expected_identities[expected] = label
    process = subprocess.run(
        [
            "fc-query",
            "--format",
            "%{family[0]}\t%{style[0]}\t%{weight}\t%{slant}\t%{width}\t%{pixelsize}\n",
            str(otb),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    fields = process.stdout.rstrip("\n").split("\t")
    if len(fields) != 6:
        raise SystemExit(f"{otb}: fc-query returned malformed identity")
    try:
        observed = (
            fields[0],
            fields[1],
            int(fields[2]),
            int(fields[3]),
            int(fields[4]),
            float(fields[5]),
        )
    except ValueError as error:
        raise SystemExit(f"{otb}: fc-query returned non-numeric identity fields") from error
    if observed in observed_identities:
        raise SystemExit(
            f"observed Fontconfig identity collision: "
            f"{observed_identities[observed]} and {label}"
        )
    observed_identities[observed] = label
    if observed != expected:
        raise SystemExit(
            f"{otb}: Fontconfig identity differs for {label}: "
            f"expected={expected!r}, observed={observed!r}"
        )
PY

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
