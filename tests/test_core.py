"""Consequential native behavior checks, run with bundled FreeCAD Python."""
import json
import math
from pathlib import Path
import shutil
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import FreeCAD as App
from kurtshape.core import Controller, metadata


class NativeCoreTests(unittest.TestCase):
    def setUp(self):
        self.core=Controller()
        self.state=self.call(op="new",name="Acceptance plate")

    def tearDown(self):
        for doc in list(self.core.documents.values()):
            if App.getDocument(doc.Name):
                App.closeDocument(doc.Name)

    def call(self,**req):
        if req["op"] not in {"new","open"}:
            req.update(document_id=self.state["document_id"],expected_revision=self.state["revision"])
        response=self.core.dispatch(req)
        self.assertTrue(response["ok"],response)
        self.state=response["result"]
        return self.state

    def plate(self):
        self.call(op="sketch_rectangle",id="PlateProfile",width=60,height=40)
        self.call(op="pad",profile="PlateProfile",length=6)
        self.call(op="sketch_circle",id="HoleProfile",x=30,y=20,diameter=8,center_on="PlateProfile")
        self.call(op="pocket",profile="HoleProfile")

    def test_geometry_edits_history_and_fresh_relocation(self):
        self.plate()
        baseline=(60*40-math.pi*4**2)*6
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"],baseline,places=6)
        self.assertTrue(all(f["fully_constrained"] for f in self.state["features"] if "fully_constrained" in f))
        self.call(op="set_parameter",feature="PlateProfile",parameter="Width",value=80)
        doc=self.core.documents[self.state["document_id"]]
        self.assertAlmostEqual(doc.HoleProfile.Geometry[0].Center.x,40)
        self.call(op="undo")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"],baseline,places=6)
        self.call(op="redo")
        self.call(op="set_parameter",feature="HoleProfile",parameter="Diameter",value=10)
        expected=(80*40-math.pi*5**2)*6
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"],expected,places=6)
        folder=ROOT/"validation"/"core-acceptance"
        relocated=folder/"relocated-plate-project"
        relocated.mkdir(parents=True,exist_ok=True)
        original=folder/"plate.FCStd"
        self.call(op="save",path=str(original))
        self.call(op="save",path=str(original))
        self.assertTrue(original.with_suffix(".recovery.FCStd").exists())
        self.call(op="export",path=str(folder/"plate.step"))
        self.call(op="export",path=str(folder/"plate.stl"))
        saved_id=self.state["document_id"]
        App.closeDocument(doc.Name)
        shutil.copy2(original,relocated/"plate.FCStd")
        self.state=self.call(op="open",path=str(relocated/"plate.FCStd"))
        self.assertEqual(saved_id,self.state["document_id"])
        self.call(op="rebuild")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"],expected,places=6)
        self.assertEqual(self.state["measurements"]["solid_count"],1)

    def test_stale_native_edit_and_failure_rollback(self):
        self.plate()
        stale=dict(self.state)
        doc=self.core.documents[self.state["document_id"]]
        # Simulates a native GUI transaction against the same FCStd engine.
        doc.openTransaction("Native thickness edit")
        doc.Pad.Length=7
        doc.recompute()
        doc.commitTransaction()
        response=self.core.dispatch({"op":"set_parameter","document_id":stale["document_id"],"expected_revision":stale["revision"],"feature":"Pad","parameter":"Length","value":8})
        self.assertEqual(response["error"]["code"],"stale_revision")
        self.call(op="inspect")
        volume=self.state["measurements"]["volume_mm3"]
        self.call(op="sketch_circle",id="Outside",x=1000,y=1000,diameter=8)
        revision=self.state["revision"]
        response=self.core.dispatch({"op":"pocket","document_id":self.state["document_id"],"expected_revision":revision,"profile":"Outside","id":"FailedPocket"})
        self.assertFalse(response["ok"])
        self.assertIsNone(doc.getObject("FailedPocket"))
        self.call(op="inspect")
        self.assertEqual(self.state["revision"],revision)
        self.assertEqual(self.state["build_status"],"valid")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"],volume)
        self.assertTrue(self.state["last_failed_attempt"]["rejected"])
        response=self.core.dispatch({"op":"set_parameter","document_id":self.state["document_id"],"expected_revision":revision,"feature":"HoleProfile","parameter":"CenterX","value":20})
        self.assertEqual(response["error"]["code"],"expression_driven")


if __name__=="__main__":
    begin=time.perf_counter()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(NativeCoreTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    (ROOT/"validation"/"core-test-result.json").write_text(json.dumps({"tests":result.testsRun,"passed":result.wasSuccessful(),"seconds":time.perf_counter()-begin,"errors":[str(x) for x in result.errors],"failures":[str(x) for x in result.failures]},indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
