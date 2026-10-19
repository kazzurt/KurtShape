"""Run one side of a pinned A/B performance comparison (promoted from the 3.2 verification runner).

Each step runs in a fresh bundled-pythonw child (CREATE_NO_WINDOW) with an isolated
session at <checkout>/runtime/bench/<name>-<timestamp> (TEMP at most 104 characters,
because previews save clones under TEMP). The source under test is --source-root:
the live checkout (B) or the frozen copy runtime/bench/f31 (A). Children, and the
worker processes they start, can be pinned to a CPU mask; every step records the
system-wide busy percentage across it (GetSystemTimes) and is marked over the load
gate when busy exceeds --max-busy (32 % on the calibration machine). An over-gate
step is re-run up to --retries times (default 1, as §4.4(a) requires); every
attempt is kept as <stem>-attemptN and the accepted one (else the last) is copied
to <stem>.json.
compare_ab.py discards any step still over the gate. The concurrent-process list
(Win32_Process with command lines) is recorded at the start and the end.

Steps: bench_core configurations plus the interaction probe (``supplement``):
  plate-false    bench_core --fixture plate --holes 60 --repeat 5 --measure false (edits,inspect,checkpoint,preview,rebuild,open)
  plate-true     bench_core plate, --measure true, inspect only
  plate-preview  bench_core plate, --sections preview (ExtrusionEvaluator first/update)
  studio-false / studio-true  bench_core --fixture studio (rebuild,edits,inspect,checkpoint,preview,open)
  supplement     tools/perf/interaction_probe.py [--supplement-args]

Usage (bundled interpreter, output redirected; results are copied to <dest>):
  pythonw.exe -B tools/perf/run_ab.py <dest> --name v32-B1 [--source-root runtime/bench/f31]
      [--affinity 0xffff | --performance-cores] [--only supplement,plate-false]
      [--supplement-args "--fixtures studio,drill --repeat 5"] [--expect-tree <sha256>]
      [--max-busy 32] [--retries 1]
Compare sides with tools/perf/compare_ab.py.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

CHECKOUT = Path(__file__).resolve().parents[2]
PYTHONW = CHECKOUT / "runtime" / "freecad-1.1.4" / "FreeCAD_1.1.4-Windows-x86_64-py311" / "bin" / "pythonw.exe"
MAX_TEMP = 104

STEPS = {
    "plate-false": ["--fixture", "plate", "--holes", "60", "--repeat", "5", "--measure", "false",
                    "--sections", "edits,inspect,checkpoint,preview,rebuild,open"],
    "plate-true": ["--fixture", "plate", "--holes", "60", "--repeat", "5", "--measure", "true",
                   "--sections", "inspect"],
    "plate-preview": ["--fixture", "plate", "--holes", "60", "--repeat", "5", "--measure", "false",
                      "--sections", "preview"],
    "studio-true": ["--fixture", "studio", "--repeat", "5", "--measure", "true",
                    "--sections", "rebuild,edits,inspect,checkpoint,preview,open"],
    "studio-false": ["--fixture", "studio", "--repeat", "5", "--measure", "false",
                     "--sections", "rebuild,edits,inspect,checkpoint,preview,open"],
}
DEFAULT_STEPS = ("plate-false", "plate-true", "studio-true", "studio-false", "supplement")
WATCHED_PROCESSES = ("python.exe", "pythonw.exe", "freecad.exe", "freecadcmd.exe")


def tree_sha256(root):
    """The src/kurtshape tree identity every probe report carries."""
    files = sorted((Path(root) / "src" / "kurtshape").rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(files)


def performance_core_mask():
    """Mask of the highest efficiency class in processor group 0 (hybrid CPUs: performance cores)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    length = wintypes.ULONG(0)
    kernel32.GetSystemCpuSetInformation(None, 0, ctypes.byref(length), None, 0)
    buffer = ctypes.create_string_buffer(length.value)
    if not kernel32.GetSystemCpuSetInformation(buffer, length, ctypes.byref(length), None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    raw, offset, rows = buffer.raw, 0, []
    while offset < length.value:
        size = int.from_bytes(raw[offset:offset + 4], "little")
        # SYSTEM_CPU_SET_INFORMATION: Size Type Id Group(2) LogicalProcessorIndex CoreIndex
        # LastLevelCacheIndex NumaNodeIndex EfficiencyClass ...
        rows.append({"group": int.from_bytes(raw[offset + 12:offset + 14], "little"),
                     "logical": raw[offset + 14], "efficiency_class": raw[offset + 18]})
        offset += size
    top = max(row["efficiency_class"] for row in rows)
    mask = sum(1 << row["logical"] for row in rows if row["efficiency_class"] == top and row["group"] == 0)
    return mask, rows


def system_times():
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    value = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime  # noqa: E731
    return value(idle), value(kernel) + value(user)


def process_query(names=WATCHED_PROCESSES):
    """The read-only Get-CimInstance Win32_Process query of verification §4.4(e), as one PowerShell command."""
    where = " OR ".join(f"Name='{name}'" for name in names)
    return ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            f"$rows = @(Get-CimInstance Win32_Process -Filter \"{where}\" | "
            "Select-Object Name, ProcessId, ParentProcessId, "
            "@{n='CreationDate';e={if ($_.CreationDate) {$_.CreationDate.ToString('o')}}}, CommandLine); "
            "ConvertTo-Json -InputObject $rows -Compress -Depth 2")


def parse_cim_processes(text):
    """Rows of process_query() output (a JSON array; PowerShell may print an object for one row)."""
    data = json.loads(text.strip() or "[]")
    if isinstance(data, dict):
        data = [data]
    return [{"name": row.get("Name"), "pid": row.get("ProcessId"), "parent_pid": row.get("ParentProcessId"),
             "created": row.get("CreationDate"), "command_line": row.get("CommandLine")} for row in data]


def process_list():
    """Read-only record of concurrent Python/FreeCAD processes with their command lines (§4.4(e)).

    Uses Get-CimInstance Win32_Process; falls back to tasklist (no command lines) and says so.
    """
    captured = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        output = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-Command", process_query()], capture_output=True, timeout=120, check=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return {"captured": captured, "method": "Get-CimInstance Win32_Process",
                "processes": parse_cim_processes(output.decode("utf-8", errors="replace"))}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        failure = f"{type(exc).__name__}: {exc}"
    try:
        output = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="replace",
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"captured": captured, "error": f"{failure}; tasklist: {exc}"}
    rows = []
    for row in csv.reader(io.StringIO(output)):
        if row and row[0].lower() in WATCHED_PROCESSES:
            rows.append({"name": row[0], "pid": int(row[1]), "memory": row[4] if len(row) > 4 else None})
    return {"captured": captured, "method": "tasklist (no command lines)", "cim_error": failure, "processes": rows}


def environment(session, source):
    env = os.environ.copy()
    for name in ("KURTSHAPE_WRITE_EVIDENCE", "KURTSHAPE_PERF", "KURTSHAPE_TEST_RUN_DIR", "QT_QPA_PLATFORM"):
        env.pop(name, None)
    folders = {"FREECAD_USER_HOME": "user-data", "TEMP": "temporary", "TMP": "temporary",
               "APPDATA": "appdata", "LOCALAPPDATA": "localappdata", "KURTSHAPE_TEST_TMP": "test-tmp"}
    for name, child in folders.items():
        (session / child).mkdir(parents=True, exist_ok=True)
        env[name] = str(session / child)
    env.update(KURTSHAPE_ROOT=str(source), KURTSHAPE_SESSION_DIR=str(session),
               KURTSHAPE_EVIDENCE_DIR=str(session / "evidence"),
               PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    return env


def run_child(command, env, log, affinity):
    began = time.perf_counter()
    idle0, total0 = system_times()
    with open(log, "w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=CHECKOUT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if affinity:
            # Worker grandchildren inherit the mask.
            ctypes.windll.kernel32.SetProcessAffinityMask(int(process._handle), affinity)
        code = process.wait()
    idle1, total1 = system_times()
    busy = 100.0 * (1 - (idle1 - idle0) / max(1, total1 - total0))
    return {"exit": code, "seconds": time.perf_counter() - began, "pid": process.pid,
            "system_busy_pct_all_cores": round(busy, 1), "affinity": hex(affinity) if affinity else None}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dest")
    parser.add_argument("--name", default="v32-ab")
    parser.add_argument("--only", help="comma-separated steps: " + ", ".join((*STEPS, "supplement")))
    parser.add_argument("--supplement-args", default="")
    parser.add_argument("--probe", default=str(CHECKOUT / "tools" / "perf" / "interaction_probe.py"))
    parser.add_argument("--source-root", help="source under test (default: this checkout)")
    parser.add_argument("--expect-tree", help="refuse to run unless src/kurtshape hashes to this value")
    pin = parser.add_mutually_exclusive_group()
    pin.add_argument("--affinity", help="hex CPU mask for every child, e.g. 0xffff")
    pin.add_argument("--performance-cores", action="store_true", help="pin to the highest efficiency class")
    parser.add_argument("--max-busy", type=float, default=32.0, help="load gate in percent of all cores")
    # Verification §4.4(a): a step over the load gate is discarded and re-run.
    parser.add_argument("--retries", type=int, default=1, help="re-runs of a step that exceeded --max-busy (default 1)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    steps = args.only.split(",") if args.only else list(DEFAULT_STEPS)
    unknown = [name for name in steps if name not in STEPS and name != "supplement"]
    if unknown:
        parser.error("unknown steps: " + ", ".join(unknown))
    if args.retries < 0:
        parser.error("--retries must be >= 0")
    affinity = int(args.affinity, 16) if args.affinity else None
    cpu_sets = None
    if args.performance_cores:
        affinity, cpu_sets = performance_core_mask()
    dest = Path(args.dest).resolve()
    source = Path(args.source_root).resolve() if args.source_root else CHECKOUT
    tree, files = tree_sha256(source)
    if args.expect_tree and tree != args.expect_tree:
        parser.error(f"source tree {tree} does not match --expect-tree {args.expect_tree}")
    session = CHECKOUT / "runtime" / "bench" / (args.name + "-" + time.strftime("%Y%m%d-%H%M%S"))
    if len(str(session / "temporary")) > MAX_TEMP:
        parser.error(f"TEMP would be {len(str(session / 'temporary'))} characters (limit {MAX_TEMP}); use a shorter --name")
    dest.mkdir(parents=True, exist_ok=True)
    session.mkdir(parents=True)
    env = environment(session, source)
    bench = source / "tools" / "perf" / "bench_core.py"
    summary = {"session": str(session), "source_root": str(source), "src_kurtshape_tree_sha256": tree,
               "src_files": files, "affinity": hex(affinity) if affinity else None, "max_busy_pct": args.max_busy,
               "cpu_sets": cpu_sets, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "processes_start": process_list(), "steps": {}}

    def save():
        (dest / "run-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    save()
    for name in [step for step in (*STEPS, "supplement") if step in steps]:
        stem = "supplement" if name == "supplement" else "bench-" + name
        attempts = []
        for attempt in range(args.retries + 1):
            # With retries every attempt keeps its own files; the canonical name gets the chosen one.
            suffix = f"-attempt{attempt + 1}" if args.retries else ""
            if name == "supplement":
                out = dest / f"supplement{suffix}.json"
                command = [str(PYTHONW), "-B", str(Path(args.probe).resolve()), str(out), *args.supplement_args.split()]
            else:
                out = session / "evidence" / "perf" / f"bench-{name}{suffix}.json"
                command = [str(PYTHONW), "-B", str(bench), *STEPS[name], "--out", str(out),
                           "--scratch", str(session / f"w-{name}{suffix}")]
            record = run_child(command, env, dest / f"{stem}{suffix}.log", affinity)
            record.update(command=subprocess.list2cmdline(command), report=str(out),
                          over_load_gate=record["system_busy_pct_all_cores"] > args.max_busy)
            if name != "supplement" and out.is_file():
                shutil.copy2(out, dest / out.name)
            attempts.append(record)
            if not record["over_load_gate"]:
                break
        accepted = next((item for item in attempts if not item["over_load_gate"]), None)
        chosen = accepted or attempts[-1]
        if args.retries and Path(chosen["report"]).is_file():
            shutil.copy2(chosen["report"], dest / f"{stem}.json")
        summary["steps"][name] = {**chosen, "attempts": attempts, "accepted": accepted is not None,
                                  "attempt": attempts.index(chosen) + 1}
        save()
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    summary["processes_end"] = process_list()
    end_tree, _ = tree_sha256(source)
    summary["source_unchanged"] = end_tree == tree
    save()
    print(json.dumps({"dest": str(dest), "session": str(session), "tree": tree,
                      "steps": {name: {key: step[key] for key in ("exit", "seconds", "system_busy_pct_all_cores", "accepted")}
                                for name, step in summary["steps"].items()},
                      "source_unchanged": summary["source_unchanged"]}))
    failed = any(step["exit"] != 0 or not step["accepted"] for step in summary["steps"].values())
    return 1 if failed or not summary["source_unchanged"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
