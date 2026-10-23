"""Run a GUI process on a private Windows desktop and prove that no window of it reached the user's desktop.

Windows keeps one window list per desktop. A process started with STARTUPINFO.lpDesktop naming a
desktop created here (CreateDesktopEx, never SwitchDesktop) creates every one of its top-level
windows there: main window, dialogs, task panels, menus, tooltips, message boxes and native file
dialogs alike. None of them can appear on, or take the foreground of, the desktop the user is
working on, because they do not exist in that desktop's window list. Nothing about the process
itself changes: Qt sees a real ``windows`` platform with real shown windows, so paint, expose,
activation and popup behaviour are the ones the GUI recipes measure.

Usage (from tools/run_gui_recipe.ps1, or by hand with the bundled pythonw.exe)::

    pythonw.exe -B tools\\private_desktop.py --record <launch-record.json> --summary <probe.json>
        --stdout <child-stdout.txt> --stderr <child-stderr.txt> [--cwd <folder>] [--show hidden|normal]
        [--interval-ms 100] -- <executable> [argument ...]

The launcher writes the record (child PID, start time, desktop name) as soon as the child exists,
then samples both desktops until the child exits: the interactive desktop (the one the user sees;
every top-level window owned by the child's process tree that is visible there is a leak) and the
private desktop (the positive control: the windows the GUI really opened). The summary carries
the per-sample counts, every leaked window, and ``passed`` which is true only when no leak was seen
and the foreground window never belonged to the child's tree. The exit code is the child's exit
code when the probe passed, 3 when a window reached the interactive desktop, 2 for a launcher
failure (the child is then never started: there is no fallback to the interactive desktop).

Importable pieces: ``create_desktop``, ``start_on_desktop``, ``process_tree``, ``visible_windows``,
``Probe`` and ``verdict``; tests/test_private_desktop.py exercises them.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
import uuid

user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None

GENERIC_ALL = 0x10000000
DESKTOP_READOBJECTS = 0x0001
DESKTOP_ENUMERATE = 0x0040
STARTF_USESHOWWINDOW = 0x00000001
STARTF_USESTDHANDLES = 0x00000100
SW_HIDE = 0
SW_SHOWNORMAL = 1
CREATE_UNICODE_ENVIRONMENT = 0x00000400
UOI_NAME = 2
WAIT_TIMEOUT = 0x00000102
STILL_ACTIVE = 259
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
HANDLE_FLAG_INHERIT = 0x00000001
# Every new desktop keeps the interactive window station's default heap (20 MB on a stock Windows
# install, registry SharedSection second value); an explicit size spares a tiny CI window station.
DEFAULT_HEAP_KB = 8192
INTERACTIVE_DESKTOP = "Default"
SHOW_WINDOW = {"hidden": SW_HIDE, "normal": SW_SHOWNORMAL}


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

if os.name == "nt":
    user32.CreateDesktopExW.restype = wintypes.HANDLE
    user32.CreateDesktopExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                        wintypes.DWORD, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, WNDENUMPROC, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetForegroundWindow.restype = wintypes.HWND
    kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                                        wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOW),
                                        ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                                         ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class PrivateDesktopError(RuntimeError):
    """The private desktop or the child could not be set up; nothing was started on the user's desktop."""


def _last_error(what):
    code = ctypes.get_last_error()
    return PrivateDesktopError("%s failed (WinError %d: %s)" % (what, code, ctypes.FormatError(code).strip()))


def desktop_name_of_thread():
    """The name of the calling thread's desktop (the one its windows would appear on)."""
    handle = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    return user_object_name(handle)


def user_object_name(handle):
    buffer = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD(0)
    if not user32.GetUserObjectInformationW(handle, UOI_NAME, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)):
        raise _last_error("GetUserObjectInformationW")
    return buffer.value


def new_desktop_name(prefix="KurtShapeRecipe"):
    return prefix + "-" + uuid.uuid4().hex[:12]


def create_desktop(name, heap_kb=DEFAULT_HEAP_KB):
    """Create (never switch to) a desktop in the current window station; returns its handle."""
    handle = user32.CreateDesktopExW(name, None, None, 0, GENERIC_ALL, None, int(heap_kb), None)
    if not handle:
        raise _last_error("CreateDesktopExW(" + name + ")")
    return handle


def open_desktop(name):
    handle = user32.OpenDesktopW(name, 0, False, DESKTOP_READOBJECTS | DESKTOP_ENUMERATE)
    if not handle:
        raise _last_error("OpenDesktopW(" + name + ")")
    return handle


def open_interactive_desktop():
    """The desktop the user is looking at: the input desktop, else the window station's 'Default'."""
    handle = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS | DESKTOP_ENUMERATE)
    if handle:
        return handle
    return open_desktop(INTERACTIVE_DESKTOP)


def close_desktop(handle):
    if handle:
        user32.CloseDesktop(handle)


def process_tree(root_pid):
    """The root PID and every live descendant, from one Toolhelp snapshot."""
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE or not snapshot:
        raise _last_error("CreateToolhelp32Snapshot")
    parents = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    tree = {int(root_pid)}
    grew = True
    while grew:
        grew = False
        for pid, parent in parents.items():
            if parent in tree and pid not in tree and pid != parent:
                tree.add(pid)
                grew = True
    return tree


def _window_record(hwnd):
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_name, 256)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {"hwnd": int(hwnd), "pid": int(pid.value), "title": title.value, "class": class_name.value,
            "rect": [rect.left, rect.top, rect.right, rect.bottom], "iconic": bool(user32.IsIconic(hwnd))}


def visible_windows(desktop_handle, pids):
    """Visible top-level windows on the given desktop whose owner PID is in ``pids``."""
    found = []
    pids = {int(pid) for pid in pids}

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            owner = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if int(owner.value) in pids:
                found.append(_window_record(hwnd))
        return True

    proc = WNDENUMPROC(callback)
    user32.EnumDesktopWindows(desktop_handle, proc, 0)
    return found


def foreground_pid():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _filetime_to_iso(filetime):
    ticks = (int(filetime.dwHighDateTime) << 32) | int(filetime.dwLowDateTime)
    seconds = ticks / 10_000_000 - 11644473600
    whole = int(seconds)
    fraction = ticks % 10_000_000
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(whole)) + ".%07dZ" % fraction


def _inheritable_file(path, mode="ab"):
    stream = open(path, mode)
    import msvcrt
    handle = msvcrt.get_osfhandle(stream.fileno())
    if not kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
        raise _last_error("SetHandleInformation")
    return stream, handle


def _quote(argument):
    """Windows command-line quoting as CommandLineToArgvW reads it."""
    if argument and not any(c in argument for c in ' \t"'):
        return argument
    result = '"'
    backslashes = 0
    for char in argument:
        if char == "\\":
            backslashes += 1
            continue
        if char == '"':
            result += "\\" * (backslashes * 2 + 1) + '"'
        else:
            result += "\\" * backslashes + char
        backslashes = 0
    return result + "\\" * (backslashes * 2) + '"'


def start_on_desktop(desktop_name, command, cwd=None, show="hidden", stdout=None, stderr=None, environment=None):
    """CreateProcessW with lpDesktop = WinSta0\\<desktop_name>; returns (process handle, pid, start time ISO)."""
    if show not in SHOW_WINDOW:
        raise PrivateDesktopError("unknown --show value: " + str(show))
    startup = STARTUPINFOW()
    startup.cb = ctypes.sizeof(STARTUPINFOW)
    startup.lpDesktop = "WinSta0\\" + desktop_name
    startup.dwFlags = STARTF_USESHOWWINDOW
    startup.wShowWindow = SHOW_WINDOW[show]
    streams = []
    inherit = False
    if stdout or stderr:
        out_stream, out_handle = _inheritable_file(stdout) if stdout else _inheritable_file(os.devnull, "wb")
        err_stream, err_handle = _inheritable_file(stderr) if stderr else _inheritable_file(os.devnull, "wb")
        in_stream, in_handle = _inheritable_file(os.devnull, "rb")
        streams = [out_stream, err_stream, in_stream]
        startup.dwFlags |= STARTF_USESTDHANDLES
        startup.hStdOutput, startup.hStdError, startup.hStdInput = out_handle, err_handle, in_handle
        inherit = True
    information = PROCESS_INFORMATION()
    command_line = ctypes.create_unicode_buffer(" ".join(_quote(part) for part in command))
    environment_block = None
    if environment is not None:
        block = "".join(key + "=" + value + "\0" for key, value in sorted(environment.items())) + "\0"
        environment_block = ctypes.create_unicode_buffer(block)
    try:
        ok = kernel32.CreateProcessW(command[0], command_line, None, None, inherit, CREATE_UNICODE_ENVIRONMENT,
                                     environment_block, cwd, ctypes.byref(startup), ctypes.byref(information))
        if not ok:
            raise _last_error("CreateProcessW(" + command[0] + ")")
    finally:
        for stream in streams:
            stream.close()
    kernel32.CloseHandle(information.hThread)
    creation, exit_time, kernel_time, user_time = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    kernel32.GetProcessTimes(information.hProcess, ctypes.byref(creation), ctypes.byref(exit_time),
                             ctypes.byref(kernel_time), ctypes.byref(user_time))
    return information.hProcess, int(information.dwProcessId), _filetime_to_iso(creation)


def exit_code(process_handle):
    code = wintypes.DWORD(0)
    if not kernel32.GetExitCodeProcess(process_handle, ctypes.byref(code)):
        raise _last_error("GetExitCodeProcess")
    return ctypes.c_int32(code.value).value


class Probe:
    """Samples the interactive desktop (leaks) and the private desktop (control) for one process tree."""

    def __init__(self, root_pid, private_desktop, interactive_desktop=None):
        self.root_pid = int(root_pid)
        self.private_desktop = private_desktop
        self.interactive_desktop = interactive_desktop if interactive_desktop else open_interactive_desktop()
        self.interactive_name = user_object_name(self.interactive_desktop)
        self.samples = 0
        self.interactive_max = 0
        self.private_max = 0
        self.leaks = {}
        self.private_windows = {}
        self.foreground_in_tree = 0
        self.tree_max = 1

    def sample(self):
        tree = process_tree(self.root_pid)
        self.tree_max = max(self.tree_max, len(tree))
        leaked = visible_windows(self.interactive_desktop, tree)
        shown = visible_windows(self.private_desktop, tree)
        self.samples += 1
        self.interactive_max = max(self.interactive_max, len(leaked))
        self.private_max = max(self.private_max, len(shown))
        for record in leaked:
            self.leaks.setdefault(record["hwnd"], dict(record, first_sample=self.samples))
        for record in shown:
            self.private_windows.setdefault(record["hwnd"], dict(record, first_sample=self.samples))
        if foreground_pid() in tree:
            self.foreground_in_tree += 1
        return len(leaked), len(shown)

    def summary(self):
        return {"samples": self.samples, "interactive_desktop": self.interactive_name,
                "interactive_visible_max": self.interactive_max, "private_visible_max": self.private_max,
                "foreground_in_tree_samples": self.foreground_in_tree, "process_tree_max": self.tree_max,
                "leaked_windows": list(self.leaks.values()),
                "private_windows": list(self.private_windows.values())}


def verdict(summary):
    """True only when no window of the tree was visible on the interactive desktop and none held the foreground."""
    return (int(summary.get("samples", 0)) > 0 and int(summary.get("interactive_visible_max", 1)) == 0
            and int(summary.get("foreground_in_tree_samples", 1)) == 0 and not summary.get("leaked_windows"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run(arguments):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--record", required=True, help="JSON written when the child exists: pid, start time, desktop")
    parser.add_argument("--summary", required=True, help="JSON written when the child has exited: the probe summary")
    parser.add_argument("--stdout", help="file receiving the child's standard output")
    parser.add_argument("--stderr", help="file receiving the child's standard error")
    parser.add_argument("--cwd", help="the child's working directory")
    parser.add_argument("--show", choices=sorted(SHOW_WINDOW), default="hidden",
                        help="STARTUPINFO show state for the child's first window (default hidden, as Start-Process -WindowStyle Hidden)")
    parser.add_argument("--interval-ms", type=int, default=100, help="sampling interval (default 100 ms)")
    parser.add_argument("--desktop-name", default=None, help="private desktop name (default: a fresh unique name)")
    parser.add_argument("--heap-kb", type=int, default=DEFAULT_HEAP_KB)
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- executable [argument ...]")
    options = parser.parse_args(arguments)
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    if not command:
        parser.error("no command given after --")
    if os.name != "nt":
        parser.error("private desktops exist on Windows only")
    started = time.time()
    desktop_name = options.desktop_name or new_desktop_name()
    interactive_before = desktop_name_of_thread()
    desktop = create_desktop(desktop_name, options.heap_kb)
    probe = None
    process = None
    child_exit = None
    try:
        if user_object_name(desktop) != desktop_name:
            raise PrivateDesktopError("created desktop is not " + desktop_name)
        process, pid, start_time = start_on_desktop(desktop_name, command, cwd=options.cwd, show=options.show,
                                                    stdout=options.stdout, stderr=options.stderr)
        probe = Probe(pid, desktop)
        write_json(options.record, {"pid": pid, "start_time_utc": start_time, "desktop": desktop_name,
                                    "launcher_pid": os.getpid(), "launcher_desktop": interactive_before,
                                    "interactive_desktop": probe.interactive_name, "show": options.show,
                                    "command": command, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))})
        interval = max(10, options.interval_ms)
        while True:
            probe.sample()
            if kernel32.WaitForSingleObject(process, interval) != WAIT_TIMEOUT:
                break
        probe.sample()
        child_exit = exit_code(process)
    finally:
        summary = probe.summary() if probe else {"samples": 0, "leaked_windows": [], "interactive_visible_max": None}
        summary.update({"desktop": desktop_name, "child_exit_code": child_exit, "elapsed_s": round(time.time() - started, 3),
                        "method": "Child started by CreateProcessW with lpDesktop=WinSta0\\" + desktop_name
                                  + " (CreateDesktopEx, never switched to); EnumDesktopWindows+IsWindowVisible over the child's "
                                    "process tree on the interactive desktop every sample; GetForegroundWindow owner checked."})
        summary["passed"] = verdict(summary)
        write_json(options.summary, summary)
        if process:
            kernel32.CloseHandle(process)
        if probe:
            close_desktop(probe.interactive_desktop)
        close_desktop(desktop)
    if not summary["passed"]:
        return 3
    return child_exit if child_exit is not None else 2


def main():
    try:
        code = run(sys.argv[1:])
    except PrivateDesktopError as error:
        sys.stderr.write("private_desktop: " + str(error) + "\n")
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
