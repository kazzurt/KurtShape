"""Run in bundled FreeCAD Python; one bounded native foundation proof."""
import json
from pathlib import Path
import time
import FreeCAD as App
import Part
import Sketcher

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "validation" / "foundation-probe"
out.mkdir(exist_ok=True)
start = time.perf_counter()
doc = App.newDocument("FoundationProbe")
doc.UndoMode = 1
doc.openTransaction("Create plate")
body = doc.addObject("PartDesign::Body", "Body")
sk = doc.addObject("Sketcher::SketchObject", "PlateProfile")
body.addObject(sk)
points = [(0,0),(60,0),(60,40),(0,40)]
for i, a in enumerate(points):
    b = points[(i+1)%4]
    sk.addGeometry(Part.LineSegment(App.Vector(*a,0), App.Vector(*b,0)), False)
for i in range(4):
    sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i+1)%4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal" if i%2==0 else "Vertical", i))
sk.addConstraint(Sketcher.Constraint("Coincident",0,1,-1,1))
idx = sk.addConstraint(Sketcher.Constraint("Distance", 0, 60.0))
sk.renameConstraint(idx,"Width")
idx = sk.addConstraint(Sketcher.Constraint("Distance",1,40.0))
sk.renameConstraint(idx,"Height")
assert sk.solve() == 0
pad = body.newObject("PartDesign::Pad", "Pad")
pad.Profile = sk
pad.Length = 6
doc.recompute()
hole = doc.addObject("Sketcher::SketchObject", "HoleProfile")
body.addObject(hole)
hole.addGeometry(Part.Circle(App.Vector(30,20,0),App.Vector(0,0,1),4),False)
for kind,value,name in [("DistanceX",30,"CenterX"),("DistanceY",20,"CenterY"),("Diameter",8,"Diameter")]:
    c=Sketcher.Constraint(kind,0,3,value) if kind!="Diameter" else Sketcher.Constraint(kind,0,value)
    idx=hole.addConstraint(c)
    hole.renameConstraint(idx,name)
hole.setExpression("Constraints.CenterX", "PlateProfile.Constraints.Width / 2")
hole.setExpression("Constraints.CenterY", "PlateProfile.Constraints.Height / 2")
pocket = body.newObject("PartDesign::Pocket", "Pocket")
pocket.Profile = hole
pocket.Type = 1
pocket.Reversed = True
doc.recompute()
doc.commitTransaction()
assert body.Shape.isValid() and len(body.Shape.Solids)==1
baseline = body.Shape.Volume
doc.openTransaction("Edit thickness")
pad.Length = 8
doc.recompute()
doc.commitTransaction()
edited = body.Shape.Volume
doc.undo()
doc.recompute()
assert abs(body.Shape.Volume-baseline)<1e-5
doc.redo()
doc.recompute()
assert abs(body.Shape.Volume-edited)<1e-5
doc.saveAs(str(out / "plate.FCStd"))
Part.export([body],str(out / "plate.step"))
body.Shape.exportStl(str(out / "plate.stl"))
App.closeDocument(doc.Name)
doc=App.openDocument(str(out / "plate.FCStd"))
for obj in doc.Objects:
    if obj.TypeId.startswith(("Sketcher::", "PartDesign::")):
        obj.touch()
doc.recompute()
assert doc.Body.Shape.isValid() and abs(doc.Body.Shape.Volume-edited)<1e-5
report={"FreeCAD":App.Version(),"OCCT":Part.OCC_VERSION,"baseline_volume_mm3":baseline,"edited_volume_mm3":edited,"valid":doc.Body.Shape.isValid(),"solids":len(doc.Body.Shape.Solids),"plate_dof":doc.PlateProfile.FullyConstrained,"hole_dof":doc.HoleProfile.FullyConstrained,"seconds":time.perf_counter()-start,"checks":["real constraint solver", "pad", "through pocket", "transaction undo/redo", "native save/reopen", "fresh feature recompute", "STEP/STL export"]}
(out/"result.json").write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
