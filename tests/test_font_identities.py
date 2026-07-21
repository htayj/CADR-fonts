from __future__ import annotations

from collections import Counter
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"
MAPPING = REPOSITORY / "config" / "font-identities.json"


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


identities = load_script("cadr_font_identity_tests", "font_identities.py")


class FontIdentityMappingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = identities.load_font_identities(
            MAPPING,
            verify_evidence=False,
        )

    def resolve_source(self, logical_name: str) -> dict[str, object]:
        assignment = self.mapping["logical_identities"][logical_name]
        primary = assignment["primary"]
        measured_size = (
            primary["size"]
            if primary is not None and primary["size"] is not None
            else 1
        )
        return identities.resolve_font_identity(
            self.mapping,
            profile="source",
            physical_assignment=logical_name,
            artifact_name=logical_name,
            measured_pixel_size=measured_size,
            logical_name=logical_name,
        )

    def test_schema_counts_and_assignment_closure(self) -> None:
        self.assertEqual(
            set(self.mapping),
            {
                "schema_version",
                "mapping_id",
                "profile",
                "source",
                "policy",
                "families",
                "faces",
                "logical_identities",
                "assignments",
                "desktop_style_disambiguators",
                "expected",
            },
        )
        expected = {
            "desktop_style_disambiguator_count": 31,
            "logical_identity_count": 108,
            "mapped_logical_identity_count": 72,
            "primary_selector_count": 98,
            "role_mapped_logical_identity_count": 32,
            "runtime_artifact_count": 49,
            "source_logical_name_count": 88,
            "typographic_family_count": 41,
            "unmapped_logical_identity_count": 4,
        }
        self.assertEqual(self.mapping["expected"], expected)

        logical = self.mapping["logical_identities"]
        assignments = self.mapping["assignments"]
        statuses = Counter(record["mapping_status"] for record in logical.values())
        used_logical = set(assignments["source_logical_names"].values()) | set(
            assignments["runtime_artifacts"].values()
        )
        used_families = {
            record["typographic_family"] for record in logical.values()
        }
        disambiguators = self.mapping["desktop_style_disambiguators"]
        observed = {
            "desktop_style_disambiguator_count": sum(
                len(records) for records in disambiguators.values()
            ),
            "logical_identity_count": len(logical),
            "mapped_logical_identity_count": statuses["mapped"],
            "primary_selector_count": sum(
                record["primary"] is not None for record in logical.values()
            ),
            "role_mapped_logical_identity_count": statuses["role-mapped"],
            "runtime_artifact_count": len(assignments["runtime_artifacts"]),
            "source_logical_name_count": len(assignments["source_logical_names"]),
            "typographic_family_count": len(used_families),
            "unmapped_logical_identity_count": statuses["unmapped"],
        }
        self.assertEqual(observed, expected)
        self.assertEqual(used_logical, set(logical))
        identities.validate_assignment_closure(
            self.mapping,
            source_logical_names=assignments["source_logical_names"],
            runtime_artifacts=assignments["runtime_artifacts"].items(),
        )

    def test_hl8_and_hl14_share_family_but_keep_nominal_sizes(self) -> None:
        hl8 = self.resolve_source("HL8")
        hl14 = self.resolve_source("HL14")

        self.assertEqual(hl8["typographic"]["family_name"], "MIT CADR Helvetica")
        self.assertEqual(
            hl8["typographic"]["family_name"],
            hl14["typographic"]["family_name"],
        )
        self.assertEqual(
            (hl8["nominal_design_size"], hl14["nominal_design_size"]),
            (8, 14),
        )
        self.assertNotEqual(hl8["logical_name"], hl14["logical_name"])

    def test_b_i_and_bi_faces_map_independently(self) -> None:
        expected = {
            "HL7": ("ROMAN", "Medium", "R"),
            "HL7B": ("BOLD", "Bold", "R"),
            "HL7I": ("ITALIC", "Medium", "I"),
            "HL7BI": ("BOLD-ITALIC", "Bold", "I"),
        }
        for logical_name, (face, weight, slant) in expected.items():
            with self.subTest(logical_name=logical_name):
                resolved = self.resolve_source(logical_name)
                self.assertEqual(resolved["primary"]["face"], face)
                self.assertEqual(resolved["typographic"]["weight_name"], weight)
                self.assertEqual(resolved["typographic"]["slant"], slant)
                self.assertEqual(resolved["nominal_design_size"], 7)

    def test_runtime_current_and_legacy_representations_share_logical_font(self) -> None:
        current = identities.resolve_font_identity(
            self.mapping,
            profile="runtime",
            physical_assignment="43VXMS",
            artifact_name="43VXMS",
            measured_pixel_size=43,
            representation_style="System 46 Runtime",
            runtime_name="43VXMS",
            classification="source-backed-current",
        )
        legacy = identities.resolve_font_identity(
            self.mapping,
            profile="runtime",
            physical_assignment="N43XMS",
            artifact_name="N43XMS",
            measured_pixel_size=43,
            representation_style="System 46 Legacy N43XMS",
            runtime_name="43VXMS",
            classification="legacy-compiled-version",
        )

        self.assertEqual(current["logical_id"], "43VXMS")
        self.assertEqual(legacy["logical_id"], current["logical_id"])
        self.assertEqual(
            legacy["typographic"]["family_name"],
            current["typographic"]["family_name"],
        )
        self.assertEqual(
            current["representation"],
            {
                "profile": "runtime",
                "artifact_name": "43VXMS",
                "style_name": "System 46 Runtime",
                "runtime_name": "43VXMS",
                "classification": "source-backed-current",
            },
        )
        self.assertEqual(
            legacy["representation"],
            {
                "profile": "runtime",
                "artifact_name": "N43XMS",
                "style_name": "System 46 Legacy N43XMS",
                "runtime_name": "43VXMS",
                "classification": "legacy-compiled-version",
            },
        )

    def test_desktop_style_normalizes_xlfd_delimiters_only(self) -> None:
        resolved = identities.resolve_font_identity(
            self.mapping,
            profile="source",
            physical_assignment="APL14",
            artifact_name="APL14-AL-AR1",
            measured_pixel_size=15,
            representation_style="AL-AR1",
            logical_name="APL14",
        )

        self.assertEqual(
            resolved["typographic"]["add_style_name"],
            "AL AR1",
        )
        self.assertEqual(
            resolved["representation"]["style_name"],
            "AL-AR1",
        )

    def test_every_physical_assignment_resolves_once(self) -> None:
        assignments = self.mapping["assignments"]
        resolved_physical: set[tuple[str, str]] = set()

        for profile, assignment_key in (
            ("source", "source_logical_names"),
            ("runtime", "runtime_artifacts"),
        ):
            for physical_name, logical_id in assignments[assignment_key].items():
                with self.subTest(profile=profile, physical_name=physical_name):
                    kwargs = {
                        "profile": profile,
                        "physical_assignment": physical_name,
                        "artifact_name": physical_name,
                        "measured_pixel_size": 1,
                    }
                    if profile == "source":
                        kwargs["logical_name"] = physical_name
                    else:
                        kwargs["runtime_name"] = logical_id
                        kwargs["classification"] = (
                            "legacy-compiled-version"
                            if physical_name in {"N43XMS", "NTOG"}
                            else "source-backed-current"
                        )
                    resolved = identities.resolve_font_identity(self.mapping, **kwargs)
                    self.assertEqual(resolved["logical_id"], logical_id)
                    physical_identity = (
                        resolved["representation"]["profile"],
                        resolved["representation"]["artifact_name"],
                    )
                    self.assertNotIn(physical_identity, resolved_physical)
                    resolved_physical.add(physical_identity)

        expected_physical = {
            ("source", name) for name in assignments["source_logical_names"]
        } | {("runtime", name) for name in assignments["runtime_artifacts"]}
        self.assertEqual(resolved_physical, expected_physical)
        self.assertEqual(len(resolved_physical), 88 + 49)

    def test_pinned_evidence_hashes_are_verified(self) -> None:
        verified = identities.load_font_identities(MAPPING, verify_evidence=True)
        for evidence_id, record in verified["source"]["evidence"].items():
            with self.subTest(evidence=evidence_id):
                evidence_path = identities.SOURCE_REPOSITORY / record["path"]
                self.assertEqual(identities.sha256(evidence_path), record["sha256"])

        changed = copy.deepcopy(verified)
        first_evidence = next(iter(changed["source"]["evidence"].values()))
        first_evidence["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            changed_path = Path(temporary) / "font-identities.json"
            changed_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(
                identities.FontIdentityError,
                "font evidence changed",
            ):
                identities.load_font_identities(
                    changed_path,
                    verify_evidence=True,
                )

    def test_pinned_evidence_uses_the_explicit_source_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / "source"
            for record in self.mapping["source"]["evidence"].values():
                relative = Path(record["path"])
                destination = snapshot / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(
                    (identities.SOURCE_REPOSITORY / relative).read_bytes()
                )

            verified = identities.load_font_identities(
                MAPPING,
                source_repository=snapshot,
            )
            self.assertEqual(verified["mapping_id"], self.mapping["mapping_id"])

            first = next(iter(self.mapping["source"]["evidence"].values()))
            (snapshot / first["path"]).write_bytes(b"changed\n")
            with self.assertRaisesRegex(
                identities.FontIdentityError,
                "font evidence changed",
            ):
                identities.load_font_identities(
                    MAPPING,
                    source_repository=snapshot,
                )


if __name__ == "__main__":
    unittest.main()
