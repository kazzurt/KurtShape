"""Generate public three-solid STEP fixtures for the hosted GUI recipes.

The historical filenames exercise Save's suggested filename; these simple
shapes are not the private Dodec designs. Run only in a fresh scratch folder
using the pinned native Python and an isolated FreeCAD profile.
"""
import argparse
import hashlib
import json
from pathlib import Path

import FreeCAD as App
import Part


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    shapes = {
        "Dodec pipe mount.step": [Part.makeBox(20, 12, 8),
                                  Part.makeCylinder(7, 15, App.Vector(35, 0, 0)),
                                  Part.makeBox(9, 14, 6, App.Vector(55, 0, 0))],
        "Dodec Hub Conformal.step": [Part.makeCylinder(30, 12),
                                     Part.makeBox(20, 25, 15, App.Vector(60, 0, 0)),
                                     Part.makeBox(15, 30, 10, App.Vector(-60, 0, 0))],
    }
    receipt = {"fixture_kind": "generated-public-primitives", "sources": {}}
    for name, solids in shapes.items():
        path = args.output / name
        Part.makeCompound(solids).exportStep(str(path))
        reopened = Part.read(str(path))
        if len(reopened.Solids) != 3 or not reopened.isValid():
            raise RuntimeError("Generated STEP did not round-trip three valid solids: " + name)
        receipt["sources"][name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                     "solid_volumes_mm3": [solid.Volume for solid in reopened.Solids]}
    (args.output / "fixture-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
