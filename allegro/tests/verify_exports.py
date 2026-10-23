"""Structural checks only; this does not replace visual CAM inspection.

Usage: python verify_exports.py path/to/Fabricacion/PCB_FAB
No third-party packages required. Does not modify the export.
"""
import json
import re
import sys
from pathlib import Path


def verify(folder):
    folder = Path(folder)
    films = (
        "COPPER_TOP", "COPPER_BOTTOM", "MASK_TOP", "MASK_BOTTOM",
        "OUTLINE", "SILK_TOP", "SILK_BOTTOM",
    )
    for film in films:
        content = (folder / f"{film}.art").read_text(encoding="ascii")
        # Allegro groups multiple extended commands in the same %...% block.
        commands = {token.strip() for block in re.findall(r"%([^%]*)%", content)
                    for token in block.split("*")}
        assert "MOMM" in commands, f"{film}: missing metric units"
        assert "FSLAX55Y55" in commands, f"{film}: unexpected coordinate format"
        assert content.rstrip().endswith("M02*"), f"{film}: incomplete Gerber"
    drills = list(folder.glob("PCB_DRILL*.drl"))
    assert drills, "missing drill files"
    for drill in drills:
        content = drill.read_text(encoding="ascii")
        assert content.startswith("M48"), f"{drill.name}: missing header"
        assert "METRIC," in content, f"{drill.name}: missing metric units"
        assert re.search(r"^T\d+C[.\d]+", content, re.M), "missing tool definitions"
        assert content.rstrip().endswith("M30"), f"{drill.name}: incomplete drill file"
    return {"gerber_files": len(films), "drill_files": len(drills),
            "structural_checks": "PASS", "cam_review_required": True}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), indent=2))
