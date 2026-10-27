"""Validate a native delivery on copies, using an isolated headless session.

Run with bundled pythonw.exe and redirected output. Does not launch or discover
GUI sessions. STEP comparison is explicit; surface sampling adds --surface.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.delivery_validation import validate_delivery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--working", required=True, type=Path)
    parser.add_argument("--export", action="append", default=[], type=Path)
    parser.add_argument("--surface", action="store_true")
    parser.add_argument("--tolerance-mm", type=float, default=0.02)
    parser.add_argument("--max-samples", type=int, default=2000)
    parser.add_argument("--require-current-sources", action="store_true")
    args = parser.parse_args()
    report = validate_delivery(args.source, args.working, exports=args.export, surface=args.surface,
                               tolerance_mm=args.tolerance_mm, max_samples=args.max_samples,
                               require_current_sources=args.require_current_sources)
    print(json.dumps({"passed": report["passed"], "report": str(args.working.resolve() / "delivery-report.json"),
                      "seconds": report["seconds"], "error": report.get("error")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
