from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


otb = load_script("check_otb_identity_tests", "check_otb.py")


class _NameTable:
    def __init__(self, names: dict[int, str]):
        self.names = names

    def getDebugName(self, name_id: int) -> str | None:
        return self.names.get(name_id)


class _Os2Table:
    usWeightClass = 700
    usWidthClass = 5
    fsSelection = 0x21


class OtbIdentityTests(unittest.TestCase):
    def test_composed_add_style_drives_exact_otb_names_and_os2(self) -> None:
        typographic = {
            "family_name": "MIT CADR Times Roman",
            "weight_name": "Bold",
            "slant": "I",
            "setwidth_name": "Normal",
            "add_style_name": "CPT Strike System 46 Runtime",
        }
        style = "CPT-Strike-System-46-Runtime-Unicode Bold Italic"
        self.assertEqual(otb._expected_style(typographic), style)
        font = {
            "name": _NameTable(
                {
                    1: "MIT CADR Times Roman",
                    2: style,
                    4: f"MIT CADR Times Roman {style}",
                }
            ),
            "OS/2": _Os2Table(),
        }
        otb._check_identity(
            font,
            Path("fixture.otb"),
            {"typographic": typographic},
        )

    def test_otb_full_name_mismatch_is_rejected(self) -> None:
        typographic = {
            "family_name": "MIT CADR Helvetica",
            "weight_name": "Bold",
            "slant": "I",
            "setwidth_name": "Normal",
            "add_style_name": "",
        }
        font = {
            "name": _NameTable(
                {
                    1: "MIT CADR Helvetica",
                    2: "Unicode Bold Italic",
                    4: "wrong",
                }
            ),
            "OS/2": _Os2Table(),
        }
        with self.assertRaisesRegex(otb.OtbCheckError, "full name differs"):
            otb._check_identity(
                font,
                Path("fixture.otb"),
                {"typographic": typographic},
            )


if __name__ == "__main__":
    unittest.main()
