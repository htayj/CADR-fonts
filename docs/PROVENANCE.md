# Provenance and reproducibility

## Source witness

The public input is
[`mietek/mit-cadr-system-software`](https://github.com/mietek/mit-cadr-system-software)
at commit
[`8e978d7d1704096a63edd4386a3b8326a2e584af`](https://github.com/mietek/mit-cadr-system-software/tree/8e978d7d1704096a63edd4386a3b8326a2e584af).
It is present here as `sources/mit-cadr-system-software`, a Git submodule whose
gitlink pins that exact revision.

The upstream `src/README` describes the tree as System 46 recovered from four
ITS backup tapes. Its `src/LICENSE` is a three-clause BSD license, despite the
README's informal “MIT license” wording. The license has SHA-256
`05b8de7c86c946cc747ab71a9aaa7dd56e37365278b5585ab685156eaa90fb92`
and is copied to `dist/LICENSE.source` on every build.

`config/source-manifest.json` closes the build over 31 physical authoring
inputs in `src/lmfont`: two ARC containers, 15 standalone AST files, eight KST
files, and six Alto files. It records every filename, byte length, and SHA-256.
The build rejects a missing, dirty, wrong-revision, added, removed, or changed
source witness before decoding anything.

Compiled QFASL files are not font-shape inputs. Three pinned QFASLs are checked
only as name evidence:

| Authored name | Resident binding | Evidence |
| --- | --- | --- |
| `CM10` | `FONTS:CPT-CM10` | `src/lmfont/cm10.qfasl`, SHA-256 `26bebabd...274ae8f8` |
| `CM12` | `FONTS:CPT-CM12` | `src/lmfont/cm12.qfasl`, SHA-256 `e8cb929d...e4666c5c` |
| `CPTFON` | `FONTS:CPTFONT` | `src/lmfont/cptfon.qfasl`, SHA-256 `4b235f0b...2cd554a` |

Their complete sizes and hashes are in the reviewed manifest. This keeps the
authoring-source corpus separate from compiled-only fonts while preserving the
known runtime names used in XLFD family names and aliases.

The manifest also pins the inert QFASL parser by repository, commit, path, and
SHA-256, plus each witness's decoded PDP-10-word digest and fully consumed
QFASL nibble count. With sibling `../genera-emu` present,
`make audit-runtime-names` verifies those values and extracts the single
serialized `FONT` binding from each file without evaluating compiled code. The
pinned parser is
[`extract-cadr-qfasl-fonts.py` at commit `d62ad48f`](https://github.com/htayj/lisp-machine-container-museum/blob/d62ad48fbf879fb09c7bc17c49735116cc13e143/scripts/extract-cadr-qfasl-fonts.py);
its manifest hash prevents a different local parser from silently supplying
the result.

## Decoder lineage

The initial source decoders and dependency-free JSON/BDF/PNG writers were
ported from sibling repository `genera-emu` at
[commit `2602eab2`](https://github.com/htayj/lisp-machine-container-museum/tree/2602eab2ef1bea4800312f71f9185e9261c6fa6c).
This repository then added the
closed input manifest, source revision checks, historical AST raster-height
handling, runtime-name evidence, complete XLFD profiles, direct font-specific
encodings, X indexes, checksums, and standalone tests.

The later QFASL parser named above is used only by the optional runtime-name
evidence audit. It is not part of the font-shape generator and is never needed
to build the AST/KST/Alto distribution.

Every generated catalog records SHA-256 hashes for the generator files that
affect decoded output. No build timestamp or absolute source path is stored.

The source manifest also commits two semantic-inventory SHA-256 values. The
normalized oracle contains every artifact's source line/raster metrics and
every slot's code, advance, bearing, raster width, and rows—including all
JSON-only no-op slots. The installable oracle independently contains BDF line
metrics and every emitted glyph's encoding, advance, raster box, and rows.
`check_dist.py` derives both from the finished distribution and compares them
with the reviewed values, so a decoder and normalized-JSON change cannot
validate one another circularly or move omitted slots while preserving only
aggregate counts. The current oracles were accepted only after the
150-artifact legacy geometry comparison below and separate review of the added
`BUG-KST` representation.

## Legacy compatibility audit

`scripts/compare_legacy_bdf.py` compares this build with the BDFs published by
the sibling `genera-emu` extraction. The comparison normalizes both old
secondary BDF encodings and new direct encodings into CADR character codes,
removes the zero-width/zero-advance/no-ink slots that the installable profile
cannot carry, then checks every represented glyph's advance, x bearing, raster
width, and baseline-relative set-pixel coordinates. Transparent vertical
padding and descriptive BDF/XLFD metadata are intentionally outside that
geometric comparison.

The reviewed result is 150 of 150 common BDFs geometrically identical, no
removed artifacts, and exactly one added artifact: `bug-kst.bdf`. Run
`make compare-genera` with the sibling checkout present to repeat the audit, or
pass `--legacy` to the script to name another copy of the old BDF directory.

## Format evidence

The decoder follows the pinned historical implementations and contemporary
format descriptions:

- AST: [`RD-AST` in `fcmp.66`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fcmp.66#L228-L264).
- KST: [`FNTCNV` KST reader](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fntcnv.28#L331-L382).
- Alto: [`FNTCNV` Alto reader](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fntcnv.28#L747-L819).
- Runtime positioning: [`SHEET-TYO` in `shwarm.162`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/shwarm.162#L354-L388).

The archived host files use Alan Bawden's evacuated PDP-10 representation, so
the first stage reconstructs 36-bit words before parsing any visible text or
raster data.

## Selection and recovery boundary

Selection precedence is `arc.ast's`, standalone AST, KST, `ar1.1`, standalone
Alto, then optional CLDFNT. CLDFNT is excluded by default because TVFONT has an
AST representation. QFASL/OQFASL/UNFASL inputs are excluded from this
source-backed build.

Semantically equal representations are recorded as alternates. Divergent
metrics, raster storage, or pixels receive explicit variants such as `-KST` or
`-AL-AR1`. Six Alto outputs omit only objectively impossible character
pointers, and observed out-of-declared-extent pixels are preserved rather than
clipped. Both recovery classes remain explicit in the catalog and validation
manifest.

The source-only boundary currently covers 88 authored logical names. It is not
a claim to recover every compiled font in System 46 or every CADR font ever
made.
