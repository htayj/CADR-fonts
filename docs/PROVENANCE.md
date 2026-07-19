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
and is tracked verbatim at `LICENSE.source`; every build also copies it from
the pinned witness to `dist/LICENSE.source`. The tracked copy accompanies the
committed specimen derivatives; the generated copy accompanies build outputs.

`config/source-manifest.json` closes the build over 31 physical authoring
inputs in `src/lmfont`: two ARC containers, 15 standalone AST files, eight KST
files, and six Alto files. It records every filename, byte length, and SHA-256.
The build rejects a missing, dirty, wrong-revision, added, removed, or changed
source witness before decoding anything.

## Runtime witness

Compiled QFASLs remain excluded from the **source profile**: they cannot erase
or rename an authored AST, KST, Alto, or archive observation. They are now the
shape inputs for a separate **System 46 runtime profile**.

`config/runtime-source-manifest.json` closes that profile over exactly the 49
files ending in `.qfasl` under `src/lmfont`. For every input it records the
filename, byte length, SHA-256, decoded PDP-10-word count and digest, decoded
QFASL nibble count, complete-stream checkpoint, exact resident symbol, and one
of three classifications:

| Classification | Count | Meaning |
| --- | ---: | --- |
| `source-backed-current` | 30 | Current compiled object with a reviewed source-profile comparison. |
| `compiled-only` | 17 | Current resident font with no selected authored representation. |
| `legacy-compiled-version` | 2 | Older object whose resident name is also used by a current object. |

The 17 compiled-only current names are `20VR`, `31VR`, `40VR`, `BIGVG`,
`CPT-13FG`, `CPT-HL10`, `CPT-HL10B`, `CPT-TR10I`, `GERM35`, `HL12BI`,
`MEDFNB`, `S30CHS`, `S35GER`, `SAIL12`, `SEARCH`, `SHIP`, and `TR12B1`.
`N43XMS` and `NTOG` are the two legacy artifacts; they bind the already-current
resident names `FONTS:43VXMS` and `FONTS:TOG`. Consequently, the 49 files
represent 47 current runtime logical names plus two labelled older versions.

`medfnt.oqfasl` is not one of those 49 current `.qfasl` inputs. It is a separate
older witness (2,824 bytes, SHA-256
`c0f3df33fab8d6d8de0112aee12bbd63794ddb2c240970778f307e689b06faec`)
whose visible geometry matches the source-profile `MEDFNT`. Current
`medfnt.qfasl` is the runtime authority for the profile.

The exact serialized identity is preserved even where it is irregular. In
particular, `mouse.qfasl` binds the unqualified symbol `MOUSE`; its leader name
is also unqualified. `cm12.qfasl` binds `FONTS:CPT-CM12` but carries an
unqualified `CPT-CM12` leader name, `germ35.qfasl` has an unqualified `GERM35`
leader name, and `ship.qfasl` has no serialized leader name. These observations
are manifest/catalog data, not normalized guesses. The source/runtime spelling
pairs `CM10`/`CPT-CM10`, `CM12`/`CPT-CM12`, and `CPTFON`/`CPTFONT` are likewise
kept explicit.

The runtime decoder is the repository's
`scripts/extract-cadr-qfasl-fonts.py`. It was ported from
[`extract-cadr-qfasl-fonts.py` at commit `d62ad48f`](https://github.com/htayj/lisp-machine-container-museum/blob/d62ad48fbf879fb09c7bc17c49735116cc13e143/scripts/extract-cadr-qfasl-fonts.py),
whose file SHA-256 is
`184d886477086e583c660209de1265a2ce79dec5b813494858cefc6d014ace88`.
The runtime manifest pins that ancestor as lineage evidence. The local decoder
implements only the closed corpus's reviewed serialized-object subset and
rejects all unsupported or executable operations. It never loads a QFASL,
evaluates a form, or executes target code.

`GERM35` also has a closed raster-order evidence record. The pinned
[`fcmp.66`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fcmp.66#L29-L76)
provides the later reference implementation: it distinguishes `FCMP-16` from
the default 32-bit compiler, gives 16-bit wide fonts 16-pixel indexed stripes,
and reverses raster words only in 32-bit mode.
Pinned
[`tvdefs.52`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/tvdefs.52#L4-L30)
states that 16-bit screens order both pixels within a row and rows within a
word oppositely from the normal convention. `GERM35` is the only reviewed
runtime object with `raster_width = 16`, `rasters_per_word = 2`, and an
indexing table, so the exception is structural and artifact-specific rather
than a visual guess. Because the artifact predates that compiler source,
`FCMP-16` is recorded as the reference entry point, not claimed as the literal
function used to create GERM35 in 1978. The manifest additionally pins the preserved directory
date and the later 32-bit TV implementation as chronological cross-checks,
then commits a GERM35-only normalized display-geometry oracle.

## Unicode mapping evidence and policy boundary

The Unicode profile is a derivative view of the raw source and runtime
profiles. The pinned CADR
[`char.18`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmdoc/char.18#L3-L40)
is the primary System 46 evidence for the standard seven-bit printing codes;
the keyboard table in
[`kbd.123`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/kbd.123#L288-L361)
and reader names in
[`rddefs.19`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/rddefs.19#L68-L105)
cross-check names and positions. The contemporary Stanford/ITS repertoire in
[`RFC 734`](https://www.rfc-editor.org/rfc/rfc734.html), page 12, supplies an
independent character-set description. RFC 734 predates Unicode, so the exact
Unicode scalar choices are this project's documented resolution of those
historical names, including raw `000` as U+22C5 DOT OPERATOR and raw `033` as
U+25CA LOZENGE.

The repertoire boundary is supported by the pinned font inventory, recovered
bitmaps, runtime manifest, and direct application references where they
survive. That evidence proves family identity and, for ARROW, MOUSE, TOG,
SWFONT, and SHIP, application-sprite use. It does not prove complete
raw-code-to-Unicode tables for the specialty repertoires.

The ordinary-looking historical fonts also require an explicit boundary. The
pinned [Alto loader](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fntcnv.28#L757-L802)
copies each descriptor into array index `CH` for every code `000` through `177`
without character-set translation, so retained Alto codes cannot be assumed to
follow the later System 46 table. The source reader itself documents raw `137`
as [“underline (old leftarrow)”](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/fread.21#L78-L92).
Reviewed hybrid maps keep proven ASCII positions at standard Unicode values,
remap documented old-arrow positions, and use PUA only for the remaining
divergent or undocumented slots.

The resulting 28 reserved blocks from U+E000 through U+EDFF are a published
**project PUA convention**, not an assignment recovered from CADR and not an
assignment endorsed by Unicode. Bitmap resemblance and a suggestive family
name are deliberately insufficient to infer a standardized character.

[The Unicode profile](UNICODE.md) is the normative, versioned mapping table and
records each family's evidence and uncertainty. Generated
`dist/unicode/UNICODE-MAPPING.json` and the Unicode catalogs are reproducible
expressions of that policy, not independent historical witnesses. The raw
`Misc-FontSpecific` BDF encodings and raw catalogs remain unchanged and retain
authority for archival CADR codes and geometry.

The per-artifact Latin pangram PNGs are likewise generated presentation aids,
not historical witnesses or new character-identification evidence. Their
selection is derived only after Unicode resolution: complete visible
U+0041-U+005A plus a positive-advance U+0020. This excludes application and
symbol repertoires whose raw ASCII-numbered slots are not Latin characters.
Each catalog records the exact rendered text, case decision, bounds, line
layout, renderer hash, image hash, and dimensions.

## Identity and alias contract

Full XLFD names distinguish authored artifacts from current and legacy runtime
objects; alias prefixes alone are insufficient because an X server resolves an
alias to an XLFD, not to a particular file. Current runtime XLFDs therefore use
`System 46 Runtime` as their add-style, while legacy runtime XLFDs carry their
explicit `System 46 Legacy N43XMS` or `System 46 Legacy NTOG` add-style. Source
XLFD add-styles retain source-variant identity such as `KST` and `AL AR1`.

The raw source and runtime `fonts.alias` files are generated under these
deterministic rules and installed together on the X font path:

1. `cadr-source-<artifact>` always targets that exact one of the 151 source
   artifacts.
2. `cadr-runtime-<runtime-name>` targets the current compiled object for each
   of the 47 current runtime logical names.
3. `cadr-runtime-legacy-n43xms` and `cadr-runtime-legacy-ntog` target only the
   labelled older objects; neither may claim a current or unqualified alias.
4. `cadr-<runtime-name>` is the current convenience alias and wins an
   intentional collision with a source artifact of the same name.
5. An otherwise unclaimed `cadr-<source-artifact>` remains a source convenience
   alias. Authored/runtime spelling pairs (`CM10`/`CPT-CM10`,
   `CM12`/`CPT-CM12`, and `CPTFON`/`CPTFONT`) retain both convenience spellings
   for the same current runtime object.

These rules yield 171 unique convenience names and 371 raw aliases: 272 in the
source-path index and 99 in the runtime-path index, across the source,
current-runtime, legacy-runtime, and convenience namespaces. The Unicode
indexes mirror that 272/99 split under disjoint `cadr-unicode-*` names and
target XLFDs whose add-style includes `Unicode` and whose registry/encoding is
`ISO10646-1`. The four indexes therefore expose 742 aliases in total. Alias
collisions with different XLFD targets are build errors.

## Decoder lineage

The initial source decoders and dependency-free JSON/BDF/PNG writers were
ported from sibling repository `genera-emu` at
[commit `2602eab2`](https://github.com/htayj/lisp-machine-container-museum/tree/2602eab2ef1bea4800312f71f9185e9261c6fa6c).
This repository then added the
closed input manifest, source revision checks, historical AST raster-height
handling, runtime-name evidence, complete XLFD profiles, direct font-specific
encodings, X indexes, checksums, and standalone tests.

The later QFASL decoder named above is now the required generator for the
separate runtime profile. It does not participate in AST/KST/Alto source
selection, and the source decoder does not participate in QFASL reconstruction.
Their catalogs and semantic oracles remain independent before the top-level
build combines their X indexes and checksums.

Every generated catalog records SHA-256 hashes for the generator files that
affect decoded output. No build timestamp or absolute source path is stored.

The source manifest commits two semantic-inventory SHA-256 values. The
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

The runtime manifest commits a second pair. Its normalized oracle covers all
49 objects and all 6,170 resident slots, including 481 JSON-only zero-width,
zero-advance, no-ink placeholders; its BDF oracle covers the exact line metrics
and geometry of all 5,689 emitted runtime glyphs. The reviewed SHA-256 values
are `4df48ac7ad77103497fe060404689e40f9e13aa5ae6d2b61b0bac0886c2d3544`
for normalized runtime geometry and
`64d76d91a777a451789b4222468569ef2f7a7936c4f63c0283f5124cf465939d`
for runtime BDF geometry.

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

## Runtime display audit

The 30 source-backed current QFASLs are compared with their reviewed source
references in display coordinates: source character advance, signed x bearing,
baseline, and every set pixel. Transparent compiler storage padding is
reported separately and does not count as an on-screen difference. The
reviewed exceptional mappings are:

- `ARROW` uses `ARROW-KST`, which includes visible `003` and `006`;
- `BIGFNT` uses `BIGFNT-KST`, which fixes canonical code `155` and includes
  visible `000`, `006`, `022`, `023`, `033`, and `036`;
- current `MEDFNT` differs from the older/source-backed form in 57 existing
  visible glyphs and makes `000`, `011`, `012`, `014`, `015`, and `177`
  visible;
- runtime `MOUSE` adds visible `034`, `035`, and `036`.

The remaining source-backed references match every source-represented glyph.
The older `N43XMS` differs from current `43VXMS` in 69 glyphs, while older
`NTOG` and current `TOG` are display-identical but serialization-distinct.

`GERM35` is compiled-only and therefore outside that source-pair comparison.
Its separate historical gate reconstructs the unreversed 16-bit-order words in
display order, verifies that no other artifact takes the exception, and checks
the complete 128-slot result against SHA-256
`681976ee7e14cfc8a5515996d616695191d1e05b4d6d565a2ea97e94134c43c9`.
Release v0.1.0 incorrectly interpreted those serialized words as display
coordinates, producing row-paired and horizontally reversed fragments.
Release v0.1.1 corrects that geometry in the raw, Unicode, OTB, and specimen
outputs without changing GERM35's code points or metrics.

Static comparison is followed by an independent native-X gate. It compiles all
four profiles to PCF and indexes them with `mkfontdir`. Raw eight-bit probes are
drawn through Xvfb/Xlib with `XDrawString`; Unicode BMP probes use real
`XChar2b` arrays with `XDrawString16`. The gate compares each one-bit
framebuffer with an independent BDF renderer and checks advances and text
extents. Every code defined in every emitted BDF is included exactly once, and
each Unicode result must match its raw CADR-code counterpart. The reviewed
result passes for all 400 BDFs, all 40,614 emitted glyph instances, and all 742
aliases across the four font paths. The same independent model tests the
System 46 default of `VSP = 2`, maximum font-map baseline, maximum font-map
character height, and per-font baseline adjustment.

Undefined codes are intentionally excluded. X default-character or fallback
substitution for a code absent from a BDF is server policy, not recovered CADR
behavior, and the user explicitly excluded it from this correction's scope.

## Format evidence

The decoder follows the pinned historical implementations and contemporary
format descriptions:

- AST: [`RD-AST` in `fcmp.66`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fcmp.66#L228-L264).
- KST: [`FNTCNV` KST reader](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fntcnv.28#L331-L382).
- Alto: [`FNTCNV` Alto reader](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fntcnv.28#L747-L819).
- 16-/32-bit runtime raster order: the later reference [`FCMP`/`FCMP-16` implementation in `fcmp.66`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio1/fcmp.66#L29-L76) and [`FONT` screen-order notes in `tvdefs.52`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmio/tvdefs.52#L4-L30).
- Runtime positioning: [`SHEET-TYO` in `shwarm.162`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/shwarm.162#L354-L388).
- Default VSP: [`SHEET :INIT` in `sheet.383`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/sheet.383#L397-L426).
- Mixed-font baseline and line height: [`SHEET-NEW-FONT-MAP` in `sheet.383`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/sheet.383#L507-L539).
- Per-font baseline adjustment: [`SHEET-SET-FONT` in `shwarm.162`](https://github.com/mietek/mit-cadr-system-software/blob/8e978d7d1704096a63edd4386a3b8326a2e584af/src/lmwin/shwarm.162#L80-L83).

The archived host files use Alan Bawden's evacuated PDP-10 representation, so
the first stage reconstructs 36-bit words before parsing any visible text or
raster data.

## Selection and recovery boundary

Source-profile selection precedence is `arc.ast's`, standalone AST, KST,
`ar1.1`, standalone Alto, then optional CLDFNT. CLDFNT is excluded by default
because TVFONT has an AST representation. QFASL/OQFASL/UNFASL inputs are
excluded from that source profile.

Runtime-profile selection is separately closed over exactly the 49 `.qfasl`
files in its manifest. It excludes `medfnt.oqfasl`, all `.unfasl` files, load
bands, heaps, and licensed Symbolics material. The two profiles share the same
pinned public System 46 tree and BSD-3-Clause license but not an input-selection
rule.

Semantically equal representations are recorded as alternates. Divergent
metrics, raster storage, or pixels receive explicit variants such as `-KST` or
`-AL-AR1`. Six Alto outputs omit only objectively impossible character
pointers, and observed out-of-declared-extent pixels are preserved rather than
clipped. Both recovery classes remain explicit in the catalog and validation
manifest.

The source boundary covers 88 authored logical names and 151 representations.
The runtime boundary covers all 49 font QFASLs present in this pinned
`src/lmfont` snapshot, classified as 47 current logical fonts and two older
versions. Neither is a claim to recover every CADR font ever made or fonts from
another system release.

## Release derivation and content partition

Release generation begins only after the raw and Unicode source/runtime
profiles pass their closed corpus checks. It recomputes membership from each
emitted Unicode BDF: **Latin** means at least one visible encoded letter in
U+0041-U+005A or U+0061-U+007A, while **symbols** is the exact complement.
The symbols name covers drawing and sprite families plus Greek, Cyrillic, APL,
mathematics, and music repertoires; names and specimen presence do not select
membership.

The reviewed partition contains 118 source and 42 runtime Latin artifacts and
33 source and seven runtime symbols artifacts. Every one of the 200 identities
appears once, and a source/runtime logical family may not cross the boundary.
Each generic archive carries the selected Unicode BDFs and Unicode-derived OTBs
as usable fonts. Raw CADR-code BDFs remain in a separate `fonts/raw/` tree so
the address transformation remains auditable; distro packages deliberately
install only Unicode BDFs and OTBs.

OTB conversion is checked independently for all 20,307 encoded glyphs derived
from the Unicode BDFs; the unencoded `.notdef` added to each OTB is outside the
claim. The checker requires the exact Unicode repertoire, one-bit bitmap strike, character
advance, and baseline-relative set pixels of the Unicode BDF. It permits only
transparent storage-box trimming, which does not alter display geometry. The
Unicode BDF remains the authoritative derivative record.

Deterministic archives use sorted members, numeric owner/group zero, fixed
modes, and the tagged commit timestamp for both tar and gzip metadata. Each
archive contains a closed manifest and internal checksums and has an adjacent
compressed-file checksum. Repository-authored tooling, documentation, metadata,
and packaging material carries the approved BSD-3-Clause text as
`LICENSE.project`; the recovered font payload and direct derivatives retain the
pinned upstream BSD-3-Clause text as `LICENSE.source`. Both files and their
scopes are recorded independently in the release manifest.
