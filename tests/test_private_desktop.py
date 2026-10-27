"""tools/private_desktop.py: GUI recipe processes run on a private Windows desktop (2026-10-22).

On 2026-10-22 the recipe runner's `Start-Process -WindowStyle Hidden` hid only FreeCAD's first window;
every dialog, task panel, menu and message box a recipe opened appeared on the user's desktop and took
the foreground. The launcher under test creates a desktop with CreateDesktopEx (never switched to), starts
the child there with STARTUPINFO.lpDesktop, and samples the interactive desktop for the child's windows
until the child exits. These tests never open a window on the interactive desktop: the only windows they
create belong to a small ctypes child started through the launcher, so they exist on the private desktop
alone. The leak detector's positive control probes that private desktop as if it were the interactive one.
"""
import ctypes
from ctypes import wintypes
import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import support

sys.path.insert(0, str(support.ROOT / "tools"))
import private_desktop

RUNNER = support.ROOT / "tools" / "run_gui_recipe.ps1"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CHILD_CLASS = "KurtShapePrivateDesktopTest"
# A visible top-level Win32 window pumped for N seconds; writes its thread's desktop name and its own
# IsWindowVisible to the report file. No Qt, so it needs nothing from the environment.
CHILD = '''
import ctypes, sys, time
from ctypes import wintypes
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.GetThreadDesktop.restype = wintypes.HANDLE
procedure = WNDPROC(lambda hwnd, message, wparam, lparam: user32.DefWindowProcW(hwnd, message, wparam, lparam))
window_class = WNDCLASSW()
window_class.lpfnWndProc = procedure
window_class.lpszClassName = "%s"
window_class.hInstance = kernel32.GetModuleHandleW(None)
user32.RegisterClassW(ctypes.byref(window_class))
WS_OVERLAPPEDWINDOW_VISIBLE = 0x10CF0000
hwnd = user32.CreateWindowExW(0, window_class.lpszClassName, "private desktop test window", WS_OVERLAPPEDWINDOW_VISIBLE,
                              100, 100, 320, 200, None, None, window_class.hInstance, None)
user32.ShowWindow(hwnd, 1)
user32.UpdateWindow(hwnd)
desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
name = ctypes.create_unicode_buffer(256)
needed = wintypes.DWORD(0)
user32.GetUserObjectInformationW(desktop, 2, name, 512, ctypes.byref(needed))
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    stream.write(name.value + "\\n" + str(int(user32.IsWindowVisible(hwnd))) + "\\n")
deadline = time.time() + float(sys.argv[2])
message = wintypes.MSG()
while time.time() < deadline:
    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    time.sleep(0.02)
sys.exit(0)
''' % CHILD_CLASS


def child_environment():
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    return environment


@unittest.skipUnless(os.name == "nt", "Windows desktops")
class PrivateDesktopTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, "private-desktop-")
        self.child = self.folder / "child.py"
        self.child.write_text(CHILD, encoding="utf-8")

    def child_command(self, seconds):
        return [sys.executable, "-B", str(self.child), str(self.folder / "child-report.txt"), str(seconds)]

    def child_report(self):
        lines = (self.folder / "child-report.txt").read_text(encoding="utf-8").splitlines()
        return lines[0], lines[1] == "1"

    def test_launcher_keeps_every_child_window_off_the_interactive_desktop(self):
        record = self.folder / "record.json"
        summary = self.folder / "summary.json"
        command = [sys.executable, "-B", str(support.ROOT / "tools" / "private_desktop.py"), "--record", str(record),
                   "--summary", str(summary), "--stdout", str(self.folder / "out.txt"), "--stderr", str(self.folder / "err.txt"),
                   "--cwd", str(self.folder), "--show", "normal", "--interval-ms", "50", "--"] + self.child_command(2.0)
        completed = subprocess.run(command, cwd=str(support.ROOT), capture_output=True, text=True, creationflags=NO_WINDOW,
                                   env=child_environment(), timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        launch = json.loads(record.read_text(encoding="utf-8"))
        probe = json.loads(summary.read_text(encoding="utf-8"))
        desktop, visible = self.child_report()
        self.assertTrue(launch["desktop"].startswith("KurtShapeRecipe-"))
        self.assertEqual(desktop, launch["desktop"], "the child ran on the private desktop")
        self.assertNotEqual(desktop, launch["interactive_desktop"])
        self.assertTrue(visible, "the child's window was a shown window there")
        self.assertTrue(probe["private_windows"], probe)
        self.assertEqual({window["pid"] for window in probe["private_windows"]}, {launch["pid"]})
        self.assertTrue(probe["passed"], probe)
        self.assertEqual(probe["interactive_visible_max"], 0)
        self.assertEqual(probe["leaked_windows"], [])
        self.assertEqual(probe["foreground_in_tree_samples"], 0)
        self.assertGreaterEqual(probe["private_visible_max"], 1)
        self.assertIn(CHILD_CLASS, [window["class"] for window in probe["private_windows"]])
        self.assertGreaterEqual(probe["samples"], 10)
        self.assertEqual(probe["child_exit_code"], 0)
        self.assertEqual(probe["desktop"], launch["desktop"])

    def test_probe_api_sees_the_private_window_and_flags_it_when_told_that_desktop_is_the_interactive_one(self):
        name = private_desktop.new_desktop_name("KurtShapeTest")
        desktop = private_desktop.create_desktop(name)
        self.addCleanup(private_desktop.close_desktop, desktop)
        handle, pid, start_time = private_desktop.start_on_desktop(name, self.child_command(3.0), cwd=str(self.folder),
                                                                   show="normal", environment=child_environment())
        self.addCleanup(private_desktop.kernel32.CloseHandle, handle)
        self.assertRegex(start_time, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{7}Z$")
        honest = private_desktop.Probe(pid, desktop)
        self.addCleanup(private_desktop.close_desktop, honest.interactive_desktop)
        deadline = time.time() + 10
        while time.time() < deadline and not any(window["class"] == CHILD_CLASS for window in honest.private_windows.values()):
            honest.sample()
            time.sleep(0.05)
        self.assertIn(CHILD_CLASS, [window["class"] for window in honest.private_windows.values()], honest.summary())
        self.assertEqual(honest.interactive_max, 0)
        self.assertIn(pid, private_desktop.process_tree(pid))
        self.assertEqual(private_desktop.visible_windows(honest.interactive_desktop, {pid}), [])
        # Positive control for the leak detector: name the child's own desktop as the interactive one.
        control = private_desktop.Probe(pid, honest.interactive_desktop, interactive_desktop=private_desktop.open_desktop(name))
        self.addCleanup(private_desktop.close_desktop, control.interactive_desktop)
        control.sample()
        flagged = control.summary()
        self.assertGreaterEqual(flagged["interactive_visible_max"], 1)
        self.assertIn(CHILD_CLASS, [window["class"] for window in flagged["leaked_windows"]])
        self.assertFalse(private_desktop.verdict(flagged))
        self.assertTrue(private_desktop.verdict(honest.summary()))
        self.assertEqual(private_desktop.kernel32.WaitForSingleObject(handle, 15000), 0)
        self.assertEqual(private_desktop.exit_code(handle), 0)
        self.assertEqual(self.child_report()[0], name)

    def test_verdict_needs_samples_and_tolerates_neither_a_leak_nor_a_stolen_foreground(self):
        clean = {"samples": 5, "interactive_visible_max": 0, "foreground_in_tree_samples": 0, "leaked_windows": []}
        self.assertTrue(private_desktop.verdict(clean))
        self.assertFalse(private_desktop.verdict(dict(clean, samples=0)))
        self.assertFalse(private_desktop.verdict(dict(clean, interactive_visible_max=1)))
        self.assertFalse(private_desktop.verdict(dict(clean, foreground_in_tree_samples=1)))
        self.assertFalse(private_desktop.verdict(dict(clean, leaked_windows=[{"hwnd": 1}])))
        self.assertFalse(private_desktop.verdict({}))

    def test_launcher_starts_nothing_when_the_private_desktop_cannot_be_created(self):
        record = self.folder / "record.json"
        arguments = ["--record", str(record), "--summary", str(self.folder / "summary.json"), "--", sys.executable, "-c", "pass"]
        with patch.object(private_desktop, "create_desktop", side_effect=private_desktop.PrivateDesktopError("no desktop")), \
                patch.object(private_desktop, "start_on_desktop") as start:
            with self.assertRaises(private_desktop.PrivateDesktopError):
                private_desktop.run(arguments)
        start.assert_not_called()
        self.assertFalse(record.exists())
        with patch.object(private_desktop, "create_desktop", side_effect=private_desktop.PrivateDesktopError("no desktop")), \
                patch.object(private_desktop, "start_on_desktop") as start, patch.object(sys, "argv", ["private_desktop.py"] + arguments):
            with self.assertRaises(SystemExit) as stopped:
                private_desktop.main()
        self.assertEqual(stopped.exception.code, 2)
        start.assert_not_called()

    def test_command_line_quoting_round_trips_through_windows_parsing(self):
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        arguments = ["C:\\Program Files\\x\\freecad.exe", "-u", "C:\\a b\\user.cfg", "plain", "", "quote\"inside",
                     "trailing\\", "tab\there", "C:\\path\\"]
        count = ctypes.c_int(0)
        parsed = shell32.CommandLineToArgvW(" ".join(private_desktop._quote(part) for part in arguments), ctypes.byref(count))
        self.assertEqual([parsed[index] for index in range(count.value)], arguments)

    def test_recipe_code_launches_console_children_without_a_console_window(self):
        """A console child of a GUI process gets a console host whose window lives on the interactive desktop
        whatever desktop the parent runs on (bench-gui's git call did exactly that on 2026-10-22, caught by the
        probe), so every subprocess launch in the code the recipes run must pass creationflags (CREATE_NO_WINDOW)."""
        import ast
        launches = {"run", "Popen", "check_output", "check_call", "call"}
        missing = []
        for folder in (support.ROOT / "src" / "kurtshape", support.ROOT / "tools" / "perf"):
            for path in sorted(folder.glob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in launches
                            and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                            and not any(keyword.arg == "creationflags" for keyword in node.keywords)):
                        missing.append("%s:%d subprocess.%s" % (path.relative_to(support.ROOT).as_posix(), node.lineno, node.func.attr))
        self.assertEqual(missing, [], "subprocess launches without creationflags")

    def test_recipe_runner_starts_freecad_only_through_the_launcher(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("private_desktop.py", text)
        self.assertNotIn("Start-Process -FilePath $executable", text, "freecad.exe must never be started on the interactive desktop")
        self.assertIn("desktop_probe", text)
        for required in ("--record", "--summary", "--stdout", "--stderr", "--show', 'hidden'"):
            self.assertIn(required, text, required)
        self.assertRegex(text, r"(?m)^#.*private (Windows )?desktop", "header comment names the method")


if __name__ == "__main__":
    unittest.main()
