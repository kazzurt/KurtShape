"""Performance-core pinning in the launchers (slice A/B unit U3).

launch-kurtshape.ps1, tools/private-session.ps1 and tools/assistant.ps1 share one switch pair,
-PinPerformanceCores / -NoPinPerformanceCores, backed by tools/performance-cores.ps1. These tests run
only ``launch-kurtshape.ps1 -PrintOnly`` (pointed at an empty runtime root, so even a regression past
-PrintOnly could not find freecad.exe) and PowerShell probes that dot-source the helper or parse the
scripts. Nothing here starts FreeCAD.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "launch-kurtshape.ps1"
HELPER = ROOT / "tools" / "performance-cores.ps1"
PRIVATE_SESSION = ROOT / "tools" / "private-session.ps1"
ASSISTANT = ROOT / "tools" / "assistant.ps1"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden"]
SWITCHES = ("PinPerformanceCores", "NoPinPerformanceCores")
# The shipped default, decided by the slice A/B bench-gui A/B (2026-10-21): 'pin' or 'no-pin'.
SHIPPED_DEFAULT = "no-pin"


def reference_mask():
    """tools/perf/run_ab.py performance_core_mask(), and the group-0 'all processors' mask, as hex or None."""
    spec = importlib.util.spec_from_file_location("kurtshape_run_ab_reference", ROOT / "tools" / "perf" / "run_ab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mask, rows = module.performance_core_mask()
    group0 = sum(1 << row["logical"] for row in rows if row["group"] == 0)
    return (None if mask == group0 else hex(mask)), sum(1 for row in rows if row["group"] == 0)


class LauncherPinningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected_mask, cls.group0_count = reference_mask()

    def powershell(self, *arguments, timeout=60):
        return subprocess.run(POWERSHELL + list(arguments), cwd=str(ROOT), capture_output=True, text=True,
                              creationflags=NO_WINDOW, timeout=timeout)

    def print_only(self, *switches):
        empty = support.scratch(self, "launcher-pinning-")
        result = self.powershell("-File", str(LAUNCHER), "-PrintOnly", "-RuntimeRoot", str(empty),
                                 "-SessionRoot", str(empty), *switches)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        printed = json.loads(result.stdout)
        self.assertFalse((empty / "freecad-1.1.4").exists())
        self.assertTrue(printed["executable"].startswith(str(empty)))
        return printed["performance_cores"]

    def probe(self, script):
        """Run a PowerShell snippet that dot-sources the helper and writes one JSON document."""
        command = "$ErrorActionPreference = 'Stop'; . '" + str(HELPER) + "'; " + script
        result = self.powershell("-Command", command)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def test_print_only_default_reports_the_mask_and_the_shipped_default(self):
        plan = self.print_only()
        self.assertEqual(plan["requested"], "default")
        self.assertEqual(plan["default"], SHIPPED_DEFAULT)
        self.assertEqual(plan["pin"], SHIPPED_DEFAULT == "pin")
        self.assertEqual(plan["performance_core_mask"], self.expected_mask)
        self.assertEqual(plan["logical_processors"], self.group0_count)
        self.assertEqual(plan["mask"], self.expected_mask if plan["pin"] else None)
        self.assertTrue(plan["note"])

    def test_print_only_pin_switch_resolves_the_performance_core_mask(self):
        plan = self.print_only("-PinPerformanceCores")
        self.assertEqual((plan["requested"], plan["pin"]), ("pin", True))
        self.assertEqual(plan["mask"], self.expected_mask)
        if self.expected_mask:
            # A strict, non-empty subset of the group-0 processors.
            mask = int(plan["mask"], 16)
            self.assertGreater(mask, 0)
            self.assertLess(mask, (1 << self.group0_count) - 1 if self.group0_count < 64 else 1 << 63)
        else:
            self.assertIn("homogeneous", plan["note"])

    def test_print_only_no_pin_switch_applies_nothing(self):
        plan = self.print_only("-NoPinPerformanceCores")
        self.assertEqual((plan["requested"], plan["pin"], plan["mask"]), ("no-pin", False, None))
        self.assertEqual(plan["performance_core_mask"], self.expected_mask)

    def test_switches_are_exclusive(self):
        empty = support.scratch(self, "launcher-pinning-")
        result = self.powershell("-File", str(LAUNCHER), "-PrintOnly", "-RuntimeRoot", str(empty),
                                 "-SessionRoot", str(empty), "-PinPerformanceCores", "-NoPinPerformanceCores")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exclusive", result.stderr + result.stdout)

    def test_helper_mask_shape_and_homogeneous_fallback(self):
        rows = lambda spec: "@(" + ",".join(  # noqa: E731
            "[pscustomobject]@{group=%d;logical=%d;efficiency_class=%d}" % row for row in spec) + ")"
        hybrid = [(0, i, 1) for i in range(4)] + [(0, i, 0) for i in range(4, 8)] + [(1, 0, 1), (1, 1, 0)]
        homogeneous = [(0, i, 0) for i in range(8)]
        top_bit = [(0, 63, 1)] + [(0, i, 0) for i in range(4)]
        result = self.probe(
            "$h = " + rows(hybrid) + "; $o = " + rows(homogeneous) + "; $t = " + rows(top_bit) + "; "
            "[ordered]@{ hybrid = (Format-KurtShapeAffinityMask (Resolve-KurtShapePerformanceCoreMask -CpuSets $h)); "
            "homogeneous = (Resolve-KurtShapePerformanceCoreMask -CpuSets $o); "
            "top_bit = (Format-KurtShapeAffinityMask (Resolve-KurtShapePerformanceCoreMask -CpuSets $t)); "
            "pin_hybrid = (Get-KurtShapePinningPlan -PinPerformanceCores -CpuSets $h); "
            "pin_homogeneous = (Get-KurtShapePinningPlan -PinPerformanceCores -CpuSets $o); "
            "live = (Format-KurtShapeAffinityMask (Resolve-KurtShapePerformanceCoreMask -CpuSets @(Get-KurtShapeCpuSets))) "
            "} | ConvertTo-Json -Depth 4 -Compress")
        self.assertEqual(result["hybrid"], "0xf")  # group 1 rows are ignored, as in run_ab.py
        self.assertEqual(result["homogeneous"], 0)
        self.assertEqual(result["top_bit"], "0x8000000000000000")
        self.assertEqual((result["pin_hybrid"]["mask"], result["pin_hybrid"]["logical_processors"]), ("0xf", 8))
        homogeneous_plan = result["pin_homogeneous"]
        self.assertEqual((homogeneous_plan["pin"], homogeneous_plan["mask"], homogeneous_plan["performance_core_mask"]),
                         (True, None, None))
        self.assertIn("homogeneous", homogeneous_plan["note"])
        self.assertEqual(result["live"], self.expected_mask)

    def test_helper_only_defines_functions_and_survives_a_second_dot_source(self):
        """Dot-sourcing defines only the six functions (no variables, no type compiled at load), and the helper
        still works after it is dot-sourced again. It does not prove the type guard: Windows PowerShell 5.1
        accepts a second Add-Type of identical source silently."""
        result = self.powershell("-Command", (
            "$ErrorActionPreference = 'Stop'; $before = @(Get-Variable | ForEach-Object Name); "
            "$typeBefore = [bool]('KurtShapeCpuSetReader' -as [type]); "
            ". '" + str(HELPER) + "'; . '" + str(HELPER) + "'; "
            "$new = @(Get-Variable | ForEach-Object Name | Where-Object { $before -notcontains $_ -and $_ -ne 'before' }); "
            "$typeAfter = [bool]('KurtShapeCpuSetReader' -as [type]); "
            "$null = Get-KurtShapeCpuSets; . '" + str(HELPER) + "'; $null = Get-KurtShapeCpuSets; "
            "[ordered]@{ new_variables = @($new | Where-Object { $_ -notin @('typeBefore') }); type_before = $typeBefore; "
            "type_after_load = $typeAfter; "
            "functions = @(Get-Command -CommandType Function -Name '*KurtShape*' | ForEach-Object Name) "
            "} | ConvertTo-Json -Compress"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["new_variables"], [])
        self.assertFalse(data["type_before"])
        self.assertFalse(data["type_after_load"], "Add-Type must run only inside Get-KurtShapeCpuSets")
        self.assertEqual(sorted(data["functions"]), sorted([
            "Format-KurtShapeAffinityMask", "Get-KurtShapeCpuSets", "Get-KurtShapePinningPlan",
            "Get-KurtShapePinPerformanceCoresDefault", "Resolve-KurtShapePerformanceCoreMask",
            "Set-KurtShapeProcessAffinity"]))

    def test_launchers_expose_the_same_switch_pair(self):
        script = ("$ErrorActionPreference = 'Stop'; $out = [ordered]@{}; foreach ($path in $args) { "
                  "$tokens = $null; $errors = $null; "
                  "$ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors); "
                  "if ($errors.Count) { throw ($path + ': ' + $errors[0].Message) }; "
                  "$out[[IO.Path]::GetFileName($path)] = @($ast.ParamBlock.Parameters | ForEach-Object { "
                  "[ordered]@{ name = $_.Name.VariablePath.UserPath; type = $_.StaticType.FullName; "
                  "has_default = [bool]$_.DefaultValue } }) }; $out | ConvertTo-Json -Depth 4 -Compress")
        result = self.powershell("-Command", "& { " + script + " }", str(LAUNCHER), str(PRIVATE_SESSION), str(ASSISTANT))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        blocks = json.loads(result.stdout)
        self.assertEqual(sorted(blocks), ["assistant.ps1", "launch-kurtshape.ps1", "private-session.ps1"])
        for name, parameters in blocks.items():
            by_name = {parameter["name"]: parameter for parameter in parameters}
            for switch in SWITCHES:
                with self.subTest(script=name, switch=switch):
                    self.assertIn(switch, by_name)
                    self.assertEqual(by_name[switch]["type"], "System.Management.Automation.SwitchParameter")
                    self.assertFalse(by_name[switch]["has_default"], "the default lives in tools/performance-cores.ps1")

    def test_launchers_pin_right_after_start_and_assistant_passes_the_switch_through(self):
        for path, started in ((LAUNCHER, "$launchProcess"), (PRIVATE_SESSION, "$process")):
            with self.subTest(script=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn(". (Join-Path $PSScriptRoot '" + ("tools\\" if path == LAUNCHER else "")
                              + "performance-cores.ps1')", text)
                lines = [line.strip() for line in text.splitlines()]
                start = next(i for i, line in enumerate(lines) if "= Start-Process -FilePath $" in line)
                following = [line for line in lines[start + 1:start + 4] if not line.startswith("-Redirect")]
                pin = next(i for i, line in enumerate(following) if "Set-KurtShapeProcessAffinity" in line)
                self.assertIn("-Process " + started, following[pin])
                # Nothing but the handle grab sits between Start-Process and the affinity call.
                self.assertTrue(all(line == "$null = $process.Handle" for line in following[:pin]), following)
        assistant = ASSISTANT.read_text(encoding="utf-8")
        self.assertIn("-PinPerformanceCores:$PinPerformanceCores -NoPinPerformanceCores:$NoPinPerformanceCores", assistant)
        self.assertNotIn("Start-Process", assistant)


if __name__ == "__main__":
    unittest.main()
