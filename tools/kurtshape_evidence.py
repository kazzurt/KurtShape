"""Shared destinations for disposable validation output and external fixtures."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def register_runtime_folder(path: Path) -> None:
    """Record only new top-level runtime scratch this invocation creates."""
    runtime = (ROOT / "runtime").resolve()
    path = Path(path).resolve()
    if not path.is_relative_to(runtime) or path == runtime:
        return
    top = runtime / path.relative_to(runtime).parts[0]
    if top.exists():
        return
    ledger = runtime / "longrun" / "created.txt"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    label = str(top.relative_to(ROOT))
    recorded = ledger.read_text(encoding="utf-8-sig").splitlines() if ledger.exists() else []
    with ledger.open("a", encoding="utf-8") as stream:
        if str(Path("runtime") / "longrun") not in recorded:
            stream.write(str(Path("runtime") / "longrun") + "\n")
        if label not in recorded and top != ledger.parent:
            stream.write(label + "\n")


def evidence_dir(name: str = "") -> Path:
    """Create an evidence folder; tracked reports require explicit opt-in."""
    if os.environ.get("KURTSHAPE_WRITE_EVIDENCE") == "1":
        base = ROOT / "validation"
    elif os.environ.get("KURTSHAPE_EVIDENCE_DIR"):
        base = Path(os.environ["KURTSHAPE_EVIDENCE_DIR"])
    elif os.environ.get("KURTSHAPE_SESSION_DIR"):
        base = Path(os.environ["KURTSHAPE_SESSION_DIR"]) / "evidence"
    else:
        base = ROOT / "runtime" / "evidence"
    folder = (base / name).resolve()
    register_runtime_folder(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def external_examples() -> Path:
    return Path(os.environ.get("KURTSHAPE_ONSHAPE_EXAMPLES",
                               ROOT.parents[1] / "Onshape examples")).resolve()


def require_external(*filenames: str) -> Path:
    """Return the source folder, or fail before writing misleading evidence."""
    folder = external_examples()
    if not folder.is_dir() or not any(folder.iterdir()):
        print(f"External examples folder is missing or empty: {folder}", file=sys.stderr)
        raise SystemExit(2)
    missing = [filename for filename in filenames if not (folder / filename).is_file()]
    if missing:
        print(f"External examples missing in {folder}: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)
    return folder
