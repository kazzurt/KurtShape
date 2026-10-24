# KurtShape cookbook

Headless-first recipes distilled from the CADkz part projects (dodec-hub, led-pole-battery,
bref-im-df-interface, dodec-pipe-bolts-single-iteration, bone-mallet, smith-peterson-osteotome,
zimmer-8mm-drill-5978-14). Which app to use is decided in
[AGENTS.md](../AGENTS.md#launching-which-app-an-agent-uses); every argument below is listed in
[OPERATIONS.md](OPERATIONS.md). Lengths are millimetres and angles radians unless a quantity string
says otherwise (`"360 deg"`). Snippets show one request per line without the envelope; `<part>` is a
part id from the last response's `studio.parts`.

## Headless quickstart

Run the script with the bundled interpreter, output redirected:
`runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe -B build.py <scratch> <out> > build.log 2>&1`.
The scratch folder is private (never the live profile) and short (TEMP at most 104 characters);
`<out>` is the only folder it may save to.

```python
import json, os, sys
from pathlib import Path
run, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
for name, sub in (("KURTSHAPE_SESSION_DIR", "session"), ("FREECAD_USER_HOME", "user-data"), ("APPDATA", "appdata"),
                  ("LOCALAPPDATA", "localappdata"), ("TEMP", "temporary"), ("TMP", "temporary")):
    (run / sub).mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(run / sub)
(run / "session" / "settings.json").write_text(json.dumps({"project_roots": [str(out)]}), encoding="utf-8")
sys.path.insert(0, r"C:\path\to\kurtshape\src")
from kurtshape.core import Controller  # imports FreeCAD: only after the environment is set

core, state = Controller(), {}

def call(op, **args):
    global state
    if state:
        args.update(document_id=state["document_id"], expected_revision=state["revision"])
    response = core.dispatch({"op": op, **args})
    if not response["ok"]:
        raise RuntimeError(op + ": " + json.dumps(response["error"], default=str)[:2000])
    if "revision" in response["result"]:  # a document response (full or compact): keep the new revision
        state = response["result"]
    return response["result"]

call("new", name="Plate")
call("sketch_rectangle", id="PlateProfile", width=60, height=40)
call("pad", id="Plate", profile="PlateProfile", length=6, operation="new", name="Plate")
print(call("check_geometry")["geometry_check_report"]["status"])  # "valid"
call("save", path=str(out / "plate.FCStd"))
call("export", path=str(out / "plate.step"))
print([image["path"] for image in call("render_view", views=["iso", "top"], layout="sheet")["images"]])
```

Look at the PNG (copy it out: images are session files) before reporting. Keep each part in
`projects/<part-name>/` with its FCStd, STEP/STL and build script; never save over an FCStd open in
the user's app.

## How to model

### Revolve a profile, then fillet

Draw sharp-cornered half profiles with `add_polyline` and round them with `fillet`, rather than
approximating arcs with short lines: smoother faces, simpler edges. A `closest` edge pick must lie
off the revolve seam, which sits in the sketch plane (y = 0 for an XZ sketch). (bone-mallet)

```json
{"op": "create_sketch", "id": "GripProfile", "plane": "XZ"}
{"op": "add_polyline", "sketch": "GripProfile", "points": [[0, 0], [12.25, 0], [12.25, 131], [5.9, 162.75], [5.9, 258], [0, 258]], "closed": true}
{"op": "revolve", "id": "Grip", "profile": "GripProfile", "axis": {"origin": [0, 0, 0], "direction": [0, 0, 1]}, "angle": "360 deg", "operation": "new"}
{"op": "fillet", "id": "ButtRound", "part": "<part>", "radius": 2, "edges": [{"kind": "closest", "point": [0, 12.25, 0], "query": {"kind": "owned_by", "part": "<part>", "entity_type": "edge"}}]}
```

### Helical cuts (flutes, threads)

Make the path with `create_helix`: it puts one turn on each edge (`segment_length` 1), because an
undivided multi-turn helix gives sweep faces OCCT Booleans miss (`empty_cut`). Sweep with
`frenet:true` and pass `refine:false` on every helical Remove; refining merges the per-turn faces and
breaks the next cut. For a runout, start the sweeps where the flutes should break through, then
refill with one revolve `add` (`refine:false`) of the region under a grinding-wheel floor. Avoid
`boolean_parts` here: it has no `refine` and no result checks. (zimmer-8mm-drill-5978-14)

```json
{"op": "create_helix", "id": "Flute1Helix", "pitch": 40, "height": 75, "radius": 3.2, "axis": {"origin": [0, 49.5, 0], "direction": [0, -1, 0]}}
{"op": "sweep", "id": "Flute1", "profile": "Flute1Section", "path": "Flute1Helix", "frenet": true, "operation": "remove", "merge_scope": ["<part>"], "refine": false}
{"op": "revolve", "id": "FluteRunout", "profile": "FluteRunoutProfile", "axis": {"origin": [0, 0, 0], "direction": [0, 1, 0]}, "operation": "add", "merge_scope": ["<part>"], "refine": false}
```

### Fillet and chamfer references

A plain edge reference must resolve to exactly one edge (`ambiguous_reference` otherwise): a
`closest` point on an `owned_by` query, as above. For design intent use a multi reference
`{"selector": <query>, "all": true}`: every matching edge, re-evaluated at each rebuild. A rim is the
`intersection` of edges `adjacent` to two radius-filtered face sets. Put corners that must blend into
one fillet feature. OCCT carries a fillet along a whole tangent chain and cannot stop inside it:
round a cutter and subtract it instead. (dodec-hub `fillet_queries`, led-pole-battery `steps_shell.py`)

```json
{"op": "fillet", "id": "RimRound", "part": "<part>", "radius": 1, "edges": [{"selector": {"kind": "intersection", "queries": [{"kind": "adjacent", "entity_type": "edge", "adjacency": "edge", "query": {"kind": "geometry", "geometry": "cylinder", "radius": 22, "query": {"kind": "owned_by", "part": "<part>", "entity_type": "face"}}}, {"kind": "adjacent", "entity_type": "edge", "adjacency": "edge", "query": {"kind": "geometry", "geometry": "torus", "minor_radius": 23.875, "query": {"kind": "owned_by", "part": "<part>", "entity_type": "face"}}}]}, "all": true}]}
```

### Patterns of cutters

Model one cutter as a new part, then pattern it as a Remove with `include_source:true`: every
instance cuts, the source included, and no tool part remains. (dodec-hub Sockets, PinHoles)

```json
{"op": "pad", "id": "SocketTool", "profile": "SocketProfile", "length": 55.86, "operation": "new", "name": "Socket tool"}
{"op": "circular_pattern_parts", "id": "Sockets", "parts": ["<tool part>"], "axis": {"origin": [0, 0, 0], "direction": [0, 0, 1]}, "angle": "360 deg", "count": 3, "operation": "remove", "merge_scope": ["<part>"], "include_source": true}
```

### Extrude, Remove and Hole directions

Say the side with `direction`: `"along"` or `"against"` the sketch normal (the sketch's +Z). Omitted, a
`pad` extrudes along it, a `pocket` (studio or legacy) cuts against it and a `hole` drills against it,
into the material under the sketch. A studio Remove's `through_all:true` (its default) cuts both sides
of the sketch plane, so give a blind depth when the side matters. `reversed` still works for one
release but means opposite things per operation (a studio Remove's `false` and a hole's `true` are
both "along"), so do not mix the two: giving both is `invalid_argument`. When a cut or add changes
nothing, the error's `try_direction` names the other side. Check the sign of
`result_report.volume_delta_mm3` (negative: removed). (led-pole-battery, dodec-hub)

```json
{"op": "pocket", "id": "BayPocket", "profile": "BayProfile", "operation": "remove", "merge_scope": ["<part>"], "through_all": false, "length": 8, "direction": "against"}
{"op": "hole", "id": "Drill1", "part": "<part>", "sketch": "DrillCenters1", "diameter": 1.6, "depth": 6.288, "point_angle": "118 deg", "direction": "against"}
```

### Tilted features and the precision frame

`create_plane` puts a sketch on any plane: offset (`base_plane`, `offset`), point-normal (`origin`,
`normal`, `x_direction`), three-point (`points`) or line-angle (`axis`, `reference_normal`,
`angle`). For precision-sensitive geometry (tangent tori, fillets fading into near-tangent creases),
model in an exact local frame at the origin and place the finished part last with `transform_part`
`coordinate_system`: world-coordinate noise of about 1e-13 broke such fillets. (dodec-hub)

```json
{"op": "create_plane", "id": "PinPlane", "origin": [39.86, 0, 18.05], "normal": [0, 0, 1], "x_direction": [1, 0, 0]}
{"op": "create_sketch", "id": "PinProfile", "support": {"feature": "PinPlane"}}
{"op": "transform_part", "id": "PlaceHub", "name": "Dodec Hub", "part": "<part>", "coordinate_system": {"origin": [-348.04, -252.87, 8.17], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}}
```

### Preview, then batch

Try a risky feature with `preview`: it runs on a disposable clone and reports `valid`. For a
dependent sequence, preview one `batch` proposal, check `accepted`, then send `batch` with the same
`steps`, `expected_revision` set to the preview's `base_revision` and a new `request_id`; a failed
batch changes nothing and `error.batch.step` names the step. Name a step with `as` and refer to it
with `{"$ref": alias}` (feature) or `{"$part": alias}` (part). In the app a batch stops at 20 s and a
step on a large part costs about 1 s, so send about 12 steps at a time; headless has no budget.

```json
{"op": "preview", "proposal": {"op": "batch", "steps": [{"op": "sketch_circle", "id": "BossSketch", "as": "boss", "x": 10, "y": 10, "diameter": 6}, {"op": "pad", "id": "Boss", "profile": {"$ref": "boss"}, "length": 10, "operation": "add"}]}}
```

### Assemblies

Build and save each part headless, then in a new document `create_assembly`. List each file's
`assembly_candidates`: studio files also list helper and history bodies, so take the candidate whose
name is the part name. Insert it with `insert_assembly_part` and place it with
`move_assembly_instance`. Occurrences are embedded snapshots: after changing a part, re-export and
insert it again. (led-pole-battery, dodec-pipe-bolts-single-iteration)

Group occurrences into folders as you insert them, by function or sub-assembly, and keep the root
to about 12 instances; the folders are what Kurt sees in both instance lists. They are metadata
only (solver, export and occurrence order are unchanged).

```json
{"op": "assembly_candidates", "path": "<absolute path of Cell 18650.FCStd>"}
{"op": "create_assembly", "id": "LEDPoleBattery", "name": "LED Pole Battery Assembly"}
{"op": "insert_assembly_part", "path": "<absolute path of Cell 18650.FCStd>", "source_id": "<candidate id>", "id": "Cell1", "name": "Cell 18650", "folder": "Electronics/Cells"}
{"op": "move_assembly_instances", "instances": ["Bolt1", "Bolt2"], "folder": "Fasteners/M3"}
{"op": "move_assembly_instance", "instance": "Cell1", "position_mm": [26.7, 22.4, -60], "rotation_xyzw": [0, 0, 0, 1]}
```

### Verify

Every Add, Remove and Intersect is checked and returns `result_report` (`volume_delta_mm3`); a
failed check rejects with `empty_cut`, `empty_add` or `invalid_geometry` naming the feature. Run
`check_geometry` before saving; `inspect` with `measure:"full"` gives `volume_mm3`, `area_mm2` and the
exact `bbox_mm`. Look at a section with `render_view`, and reopen the saved FCStd once. To compare a
rebuild with an original, measure a two-way surface deviation (sample points on each shape, distance
to the other): Booleans against the original fail on coincident faces. (led-pole-battery
`ks.surface_deviation`, bref-im-df-interface fit checks)

```json
{"op": "inspect", "measure": "full"}
{"op": "render_view", "section": {"plane": "XZ", "offset": 0}, "size": [1024, 768]}
```

## Session harness

`src/kurtshape/session.py` is the shared headless and bridge session helper: the quickstart's
environment and `call`, written once for both transports. Its module docstring is the reference.
