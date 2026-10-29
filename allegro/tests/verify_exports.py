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
    routes = list(folder.glob("PCB_SLOTS*.rou"))
    slots = {"plated": 0, "nonplated": 0}
    for route in routes:
        content = route.read_text(encoding="ascii")
        assert content.startswith("M48"), f"{route.name}: missing header"
        assert "METRIC," in content and re.search(r"^G90$", content, re.M), "unexpected routing units/mode"
        assert content.rstrip().endswith("M30"), "incomplete routing"
        starts = re.findall(r"^M15$", content, re.M)
        segments = re.findall(r"^G01X-?\d+Y-?\d+$", content, re.M)
        assert len(starts) == len(segments) and starts, "unsupported slot routes"
        assert not re.search(r"^G0[23]|^G4[12]", content, re.M), "unsupported routing arcs/compensation"
        slots["plated" if route.name.endswith("_plated.rou") else "nonplated"] += len(starts)
    manifest_file = folder / "manifest.json"
    if manifest_file.exists():
        slot_info = json.loads(manifest_file.read_text(encoding="utf-8")).get("slots", {})
        if slot_info:
            assert slots["plated"] == slot_info["expected_plated"], "missing plated slots"
            assert slots["nonplated"] == slot_info["expected_nonplated"], "missing nonplated slots"
    return {"gerber_files": len(films), "drill_files": len(drills),
            "routing_files": len(routes), "slots": slots,
            "structural_checks": "PASS", "cam_review_required": True}


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), indent=2))
