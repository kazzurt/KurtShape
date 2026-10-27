"""Small editable hardware example. Run under bundled pythonw.exe with redirected logs."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kurtshape.session import Session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-root", required=True, type=Path, help="Short isolated scratch folder")
    parser.add_argument("--output", required=True, type=Path, help="Hardware deliverables folder")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with Session.headless(args.session_root, project_roots=[output], batch_helpers=True) as s:
        s.call("list_documents", detail="compact")
        s.call("new", name="M8 flat washer")
        part = s.circle("WasherBlank", (0, 0, 0), 16, 1.6, name="M8 flat washer")
        result = s.batch([
            {"op": "sketch_circle", "id": "HoleProfile", "as": "hole", "x": 0, "y": 0, "diameter": 8.4},
            {"op": "pocket", "id": "Hole", "profile": {"$ref": "hole"}, "operation": "remove",
             "merge_scope": [part], "through_all": True},
        ], label="Washer clearance", preview=True)
        if result.get("accepted") is False:
            raise RuntimeError(result.get("error"))
        manifest = s.finish(part, output, "M8-flat-washer", "M8 flat washer", [0.5, 0.52, 0.56])
        print(manifest, flush=True)


if __name__ == "__main__":
    main()
