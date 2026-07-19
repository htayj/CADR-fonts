from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))
SCRIPT = REPOSITORY / "scripts" / "check_runtime_dist.py"
spec = importlib.util.spec_from_file_location("check_runtime_dist", SCRIPT)
assert spec is not None and spec.loader is not None
runtime_dist = importlib.util.module_from_spec(spec)
sys.modules["check_runtime_dist"] = runtime_dist
spec.loader.exec_module(runtime_dist)


class RuntimeDistributionHelpersTests(unittest.TestCase):
    def test_display_signature_is_advance_plus_set_pixels(self) -> None:
        glyph = runtime_dist.Glyph(
            code=65,
            advance=5,
            width=4,
            height=2,
            x_offset=-1,
            y_offset=-1,
            rows=(0b0100, 0b0010),
        )
        font = runtime_dist.BdfFont(
            path=Path("fixture.bdf"),
            name="fixture",
            ascent=1,
            descent=1,
            spacing="P",
            glyphs={65: glyph},
        )
        self.assertEqual(
            runtime_dist.display_signatures(font),
            {65: (5, frozenset({(0, 0), (1, -1)}))},
        )

    def test_only_zero_width_zero_advance_no_ink_is_placeholder(self) -> None:
        base = {
            "code": 0,
            "bitmap_width": 0,
            "advance": 0,
            "x_offset": 0,
            "y_offset": 0,
            "rows": [],
        }
        self.assertTrue(runtime_dist.is_nonrendering_placeholder(base))
        self.assertFalse(
            runtime_dist.is_nonrendering_placeholder(base | {"advance": 1})
        )
        self.assertFalse(
            runtime_dist.is_nonrendering_placeholder(
                base | {"bitmap_width": 1, "rows": [1]}
            )
        )

    def test_legacy_runtime_alias_never_becomes_current(self) -> None:
        def record(
            artifact: str, runtime_name: str, classification: str
        ) -> dict[str, object]:
            return {
                "artifact_name": artifact,
                "runtime_name": runtime_name,
                "classification": classification,
                "bdf_profile": {"xlfd_name": f"-xlfd-{artifact}"},
            }

        records = [
            record("CPT-CM10", "CPT-CM10", "source-backed-current"),
            record("CPT-CM12", "CPT-CM12", "source-backed-current"),
            record("CPTFONT", "CPTFONT", "source-backed-current"),
            record("DEMO", "DEMO", "compiled-only"),
            record("OLD-DEMO", "DEMO", "legacy-compiled-version"),
        ]
        aliases = runtime_dist.expected_runtime_aliases(records)
        self.assertEqual(aliases["cadr-demo"], "-xlfd-DEMO")
        self.assertEqual(aliases["cadr-runtime-demo"], "-xlfd-DEMO")
        self.assertEqual(
            aliases["cadr-runtime-legacy-old-demo"], "-xlfd-OLD-DEMO"
        )
        self.assertNotIn("cadr-old-demo", aliases)
        self.assertEqual(aliases["cadr-cm10"], "-xlfd-CPT-CM10")


if __name__ == "__main__":
    unittest.main()
