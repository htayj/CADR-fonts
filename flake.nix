{
  description = "Reproducibly recovered MIT CADR System 46 bitmap fonts";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    cadr-source = {
      url = "github:mietek/mit-cadr-system-software/8e978d7d1704096a63edd4386a3b8326a2e584af";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, cadr-source }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python3.withPackages (packages: [
            packages.fonttools
          ]);
          version = "0+git.${self.shortRev or self.dirtyShortRev or "local"}";
          sourceDateEpoch = self.lastModified or 1;

          releaseAssets = pkgs.stdenvNoCC.mkDerivation {
            pname = "cadr-fonts-release-assets";
            inherit version;
            src = self;
            strictDeps = true;
            nativeBuildInputs = [
              pkgs.coreutils
              pkgs.findutils
              pkgs.fonttosfnt
              pkgs.gnutar
              pkgs.gzip
              python
            ];
            dontConfigure = true;

            buildPhase = ''
              runHook preBuild
              export HOME="$TMPDIR"
              export LC_ALL=C.UTF-8
              export PYTHONDONTWRITEBYTECODE=1
              export SOURCE_DATE_EPOCH=${toString sourceDateEpoch}

              ${python}/bin/python3 scripts/build.py \
                --output dist \
                --source-repository ${cadr-source} \
                --allow-source-snapshot
              ${python}/bin/python3 scripts/build_release.py \
                --distribution dist \
                --release-dir dist/release \
                --version ${version} \
                --source-date-epoch "$SOURCE_DATE_EPOCH" \
                --fonttosfnt ${pkgs.fonttosfnt}/bin/fonttosfnt

              (cd dist/release && sha256sum -c ./*.tar.gz.sha256)
              ${python}/bin/python3 scripts/check_otb.py \
                dist/release/CADR-fonts-latin-${version}.tar.gz \
                dist/release/CADR-fonts-symbols-${version}.tar.gz
              runHook postBuild
            '';

            installPhase = ''
              runHook preInstall
              install -d "$out"
              install -m 0644 \
                dist/release/CADR-fonts-latin-${version}.tar.gz \
                dist/release/CADR-fonts-latin-${version}.tar.gz.sha256 \
                dist/release/CADR-fonts-symbols-${version}.tar.gz \
                dist/release/CADR-fonts-symbols-${version}.tar.gz.sha256 \
                "$out/"
              runHook postInstall
            '';
          };

          mkCadrFonts = {
            group,
            sourceCount,
            runtimeCount,
          }:
            pkgs.stdenvNoCC.mkDerivation {
              pname = "cadr-fonts-${group}";
              inherit version;
              src = releaseAssets;
              strictDeps = true;
              nativeBuildInputs = [
                pkgs.coreutils
                pkgs.findutils
                pkgs.fontconfig
                pkgs.gnugrep
                pkgs.gnutar
                pkgs.gzip
                python
              ];
              dontUnpack = true;
              dontConfigure = true;
              dontBuild = true;

              installPhase = ''
                runHook preInstall
                archive="$src/CADR-fonts-${group}-${version}.tar.gz"
                checksum="$archive.sha256"
                test -s "$archive"
                test -s "$checksum"
                (cd "$src" && sha256sum -c "$(basename "$checksum")")

                unpacked="$TMPDIR/cadr-fonts-${group}"
                mkdir -p "$unpacked"
                tar -xzf "$archive" -C "$unpacked"
                payload="$unpacked/CADR-fonts-${group}-${version}"
                test -d "$payload"
                (cd "$payload" && sha256sum -c SHA256SUMS)

                fontRoot="$out/share/fonts/cadr-fonts/${group}"
                dataRoot="$out/share/cadr-fonts/${group}"
                docRoot="$out/share/doc/cadr-fonts-${group}"
                install -d \
                  "$fontRoot/bdf/source" \
                  "$fontRoot/bdf/runtime" \
                  "$fontRoot/otb/source" \
                  "$fontRoot/otb/runtime" \
                  "$dataRoot" \
                  "$docRoot"

                cp -a "$payload/fonts/unicode/source/." "$fontRoot/bdf/source/"
                cp -a "$payload/fonts/unicode/runtime/." "$fontRoot/bdf/runtime/"
                cp -a "$payload/fonts/otb/source/." "$fontRoot/otb/source/"
                cp -a "$payload/fonts/otb/runtime/." "$fontRoot/otb/runtime/"

                install -m 0644 \
                  "$payload/RELEASE-MANIFEST.json" \
                  "$payload/SHA256SUMS" \
                  "$dataRoot/"
                cp -a "$payload/metadata" "$dataRoot/metadata"
                cp -a "$payload/specimens" "$dataRoot/specimens"
                install -m 0644 \
                  "$payload/README.release.md" \
                  "$payload/LICENSE.project" \
                  "$payload/LICENSE.source" \
                  "$docRoot/"

                configName="75-cadr-fonts-${group}.conf"
                configAvailable="$out/share/fontconfig/conf.avail/$configName"
                configEnabled="$out/etc/fonts/conf.d/$configName"
                install -d "$(dirname "$configAvailable")" "$(dirname "$configEnabled")"
                ${python}/bin/python3 - "$fontRoot" "$group" > "$configAvailable" <<'PY'
import sys

font_root, group = sys.argv[1:]
print('<?xml version="1.0"?>')
print('<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">')
print('<fontconfig>')
print(f'  <description>MIT CADR {group} bitmap fonts</description>')
print(f'  <dir>{font_root}/otb/source</dir>')
print(f'  <dir>{font_root}/otb/runtime</dir>')
print('</fontconfig>')
PY
                ln -s "$configAvailable" "$configEnabled"

                find "$out" -type d -exec chmod 0755 {} +
                find "$out" -type f -exec chmod 0644 {} +
                runHook postInstall
              '';

              doInstallCheck = true;
              installCheckPhase = ''
                runHook preInstallCheck
                fontRoot="$out/share/fonts/cadr-fonts/${group}"
                dataRoot="$out/share/cadr-fonts/${group}"
                docRoot="$out/share/doc/cadr-fonts-${group}"

                countFiles() {
                  local directory=$1
                  local suffix=$2
                  find "$directory" -maxdepth 1 -type f -name "*.$suffix" -printf . | wc -c
                }
                checkCount() {
                  local directory=$1
                  local suffix=$2
                  local expected=$3
                  local actual
                  actual=$(countFiles "$directory" "$suffix")
                  if [[ "$actual" -ne "$expected" ]]; then
                    echo "$directory: expected $expected .$suffix files, found $actual" >&2
                    exit 1
                  fi
                }

                checkCount "$fontRoot/bdf/source" bdf ${toString sourceCount}
                checkCount "$fontRoot/bdf/runtime" bdf ${toString runtimeCount}
                checkCount "$fontRoot/otb/source" otb ${toString sourceCount}
                checkCount "$fontRoot/otb/runtime" otb ${toString runtimeCount}

                for profile in source runtime; do
                  test -s "$fontRoot/bdf/$profile/fonts.dir"
                  test -s "$fontRoot/bdf/$profile/fonts.alias"
                done
                test -s "$dataRoot/RELEASE-MANIFEST.json"
                test -s "$dataRoot/SHA256SUMS"
                test -s "$dataRoot/metadata/SOURCE-MANIFEST.json"
                test -s "$dataRoot/metadata/runtime-source-manifest.json"
                test -s "$dataRoot/metadata/UNICODE-MAPPING.json"
                test -s "$docRoot/README.release.md"
                test -s "$docRoot/LICENSE.project"
                test -s "$docRoot/LICENSE.source"

                if find "$out" -type f -name '*.psf' -print -quit | grep -q .; then
                  echo "Nix package unexpectedly contains a PSF file" >&2
                  exit 1
                fi

                ${python}/bin/python3 - \
                  "$dataRoot/RELEASE-MANIFEST.json" \
                  "${group}" \
                  ${toString sourceCount} \
                  ${toString runtimeCount} <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
group = sys.argv[2]
source_count = int(sys.argv[3])
runtime_count = int(sys.argv[4])
if manifest.get("content_class") != group:
    raise SystemExit("installed release manifest has the wrong content class")
profiles = manifest.get("counts", {}).get("profiles", {})
observed = {
    "source": profiles.get("source", {}).get("artifact_count"),
    "runtime": profiles.get("runtime", {}).get("artifact_count"),
}
expected = {"source": source_count, "runtime": runtime_count}
if observed != expected:
    raise SystemExit(f"installed release counts changed: {observed!r} != {expected!r}")
PY

                queried=0
                while IFS= read -r -d $'\0' font; do
                  family=$(fc-query --format '%{family[0]}\n' "$font" | head -n 1)
                  test -n "$family"
                  queried=$((queried + 1))
                done < <(find "$fontRoot/otb" -type f -name '*.otb' -print0 | sort -z)
                expectedQueried=$((${toString sourceCount} + ${toString runtimeCount}))
                if [[ "$queried" -ne "$expectedQueried" ]]; then
                  echo "fc-query saw $queried OTBs, expected $expectedQueried" >&2
                  exit 1
                fi
                runHook postInstallCheck
              '';

              meta = with pkgs.lib; {
                description = "MIT CADR System 46 ${group} bitmap fonts";
                homepage = "https://github.com/htayj/CADR-fonts";
                # Both the repository-authored build/release work and the
                # recovered upstream font payload use BSD-3-Clause; their
                # distinct notices are installed as LICENSE.project and
                # LICENSE.source, respectively.
                license = licenses.bsd3;
                platforms = platforms.linux;
              };
            };
        in
        rec {
          cadr-fonts-latin = mkCadrFonts {
            group = "latin";
            sourceCount = 118;
            runtimeCount = 42;
          };
          cadr-fonts-symbols = mkCadrFonts {
            group = "symbols";
            sourceCount = 33;
            runtimeCount = 7;
          };
          default = cadr-fonts-latin;
        });

      checks = forAllSystems (system: {
        cadr-fonts-latin = self.packages.${system}.cadr-fonts-latin;
        cadr-fonts-symbols = self.packages.${system}.cadr-fonts-symbols;
      });
    };
}
