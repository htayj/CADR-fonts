from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


gallery = load_script("cadr_specimen_gallery_tests", "update_specimen_gallery.py")


def logical_identity(
    *,
    status: str = "mapped",
    selector: str | None = "FIXED-GOTHIC/ROMAN/13",
    family: str = "MIT CADR Fixed Gothic",
    character_set: str = "STANDARD",
) -> dict[str, object]:
    primary = (
        {
            "family": "FIXED-GOTHIC",
            "face": "ROMAN",
            "size": 13,
            "named_size": None,
            "character_set": character_set,
        }
        if selector is not None
        else None
    )
    return {
        "mapping_status": status,
        "logical_id": "fixture",
        "logical_name": selector,
        "primary": primary,
        "nominal_design_size": 13 if selector is not None else None,
        "measured_pixel_size": 13,
        "desktop_style_disambiguator": None,
        "typographic": {
            "family_name": family,
            "family_kind": "text" if status == "mapped" else status,
            "confidence": "direct",
            "weight_name": "Medium",
            "slant": "R",
            "setwidth_name": "Normal",
            "base_add_style_name": "",
            "add_style_name": "",
        },
    }


class GalleryLabelTests(unittest.TestCase):
    def test_logical_labels_cover_mapped_role_and_unmapped_statuses(self) -> None:
        mapped = logical_identity()
        self.assertEqual(
            gallery.logical_identity_label(mapped), "FIXED-GOTHIC/ROMAN/13"
        )

        role = logical_identity(
            status="role-mapped",
            selector="FIX/ROMAN/12",
            family="MIT CADR Mouse",
            character_set="MOUSE",
        )
        self.assertEqual(
            gallery.logical_identity_label(role),
            "FIX/ROMAN/12 [MOUSE] · MIT CADR Mouse (role-mapped)",
        )

        role_only = logical_identity(
            status="role-mapped",
            selector=None,
            family="MIT CADR Box",
        )
        self.assertEqual(
            gallery.logical_identity_label(role_only),
            "MIT CADR Box (role-mapped)",
        )

        unmapped = logical_identity(
            status="unmapped",
            selector=None,
            family="MIT CADR Mystery",
        )
        self.assertEqual(
            gallery.logical_identity_label(unmapped),
            "MIT CADR Mystery (unmapped)",
        )

    def test_representation_labels_are_separate_from_logical_selectors(self) -> None:
        self.assertEqual(
            gallery.representation_label(
                {
                    "profile": "source",
                    "artifact_name": "13FG",
                    "style_name": "",
                    "logical_name": "13FG",
                }
            ),
            "Authored source",
        )
        self.assertEqual(
            gallery.representation_label(
                {
                    "profile": "source",
                    "artifact_name": "BIGFNT-KST",
                    "style_name": "KST",
                    "logical_name": "BIGFNT",
                }
            ),
            "Authored source · KST",
        )
        self.assertEqual(
            gallery.representation_label(
                {
                    "profile": "runtime",
                    "artifact_name": "13FGB",
                    "style_name": "System 46 Runtime",
                    "runtime_name": "13FGB",
                    "classification": "source-backed-current",
                }
            ),
            "System 46 Runtime · source-backed current object",
        )
        self.assertEqual(
            gallery.representation_label(
                {
                    "profile": "runtime",
                    "artifact_name": "SEARCH",
                    "style_name": "System 46 Runtime",
                    "runtime_name": "SEARCH",
                    "classification": "compiled-only",
                }
            ),
            "System 46 Runtime · compiled-only current object",
        )
        self.assertEqual(
            gallery.representation_label(
                {
                    "profile": "runtime",
                    "artifact_name": "N43XMS",
                    "style_name": "System 46 Legacy N43XMS",
                    "runtime_name": "43VXMS",
                    "classification": "legacy-compiled-version",
                }
            ),
            "System 46 Legacy N43XMS · legacy compiled version",
        )


class GalleryContractTests(unittest.TestCase):
    def test_mapping_provenance_must_match_both_unicode_profiles(self) -> None:
        digest = "a" * 64
        catalogs = {
            profile: {
                "font_identity_mapping_id": "fixture-identities-v1",
                "font_identity_mapping_sha256": digest,
            }
            for profile in ("source", "runtime")
        }
        self.assertEqual(
            gallery._mapping_provenance(catalogs),
            {"id": "fixture-identities-v1", "sha256": digest},
        )

        catalogs["runtime"]["font_identity_mapping_sha256"] = "b" * 64
        with self.assertRaisesRegex(
            gallery.GalleryError, "mapping provenance differs"
        ):
            gallery._mapping_provenance(catalogs)

    def test_identity_and_representation_are_validated_as_siblings(self) -> None:
        identity = logical_identity()
        representation = {
            "profile": "source",
            "artifact_name": "13FG",
            "style_name": "",
            "logical_name": "13FG",
        }
        self.assertIs(
            gallery._validated_logical_identity(
                identity, profile="source", artifact_name="13FG"
            ),
            identity,
        )
        self.assertIs(
            gallery._validated_representation(
                representation, profile="source", artifact_name="13FG"
            ),
            representation,
        )
        with self.assertRaisesRegex(
            gallery.GalleryError, "physical identity differs"
        ):
            gallery._validated_representation(
                representation, profile="source", artifact_name="OTHER"
            )

    def test_manifest_record_preserves_source_variant_and_physical_key(self) -> None:
        identity = logical_identity()
        representation = {
            "profile": "source",
            "artifact_name": "BIGFNT-KST",
            "style_name": "KST",
            "logical_name": "BIGFNT",
        }
        artifact = {
            "content_class": "latin",
            "profile": "source",
            "name": "BIGFNT-KST",
            "record": {
                "logical_name": "BIGFNT",
                "logical_identity": identity,
                "representation": representation,
            },
            "raw_record": {"variant_of": "BIGFNT"},
            "specimen_kind": "raw-glyph-sheet",
        }
        record = gallery.specimen_manifest_record(
            artifact,
            relative="latin/source/bigfnt-kst.png",
            specimen_sha256="c" * 64,
        )
        self.assertEqual(
            (record["profile"], record["artifact_name"]),
            ("source", "BIGFNT-KST"),
        )
        self.assertEqual(record["logical_name"], "BIGFNT")
        self.assertEqual(record["variant_of"], "BIGFNT")
        self.assertIs(record["logical_identity"], identity)
        self.assertIs(record["representation"], representation)

    def test_manifest_record_preserves_runtime_classification_and_text(self) -> None:
        identity = logical_identity()
        representation = {
            "profile": "runtime",
            "artifact_name": "N43XMS",
            "style_name": "System 46 Legacy N43XMS",
            "runtime_name": "43VXMS",
            "classification": "legacy-compiled-version",
        }
        artifact = {
            "content_class": "latin",
            "profile": "runtime",
            "name": "N43XMS",
            "record": {
                "runtime_name": "43VXMS",
                "classification": "legacy-compiled-version",
                "logical_identity": identity,
                "representation": representation,
                "pangram_specimen": {"text": "The five boxing Lisp wizards."},
            },
            "raw_record": {},
            "specimen_kind": "unicode-pangram",
        }
        record = gallery.specimen_manifest_record(
            artifact,
            relative="latin/runtime/n43xms.png",
            specimen_sha256="d" * 64,
        )
        self.assertEqual(
            (record["profile"], record["artifact_name"]),
            ("runtime", "N43XMS"),
        )
        self.assertEqual(record["runtime_name"], "43VXMS")
        self.assertEqual(record["classification"], "legacy-compiled-version")
        self.assertEqual(record["text"], "The five boxing Lisp wizards.")
        self.assertIs(record["logical_identity"], identity)
        self.assertIs(record["representation"], representation)


if __name__ == "__main__":
    unittest.main()
