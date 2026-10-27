# Performance-core pinning shared by launch-kurtshape.ps1 and tools\private-session.ps1 (dot-source it).
# Defines functions only: no Add-Type, process start or other side effect happens at load.
#
# On a hybrid CPU (performance + efficiency cores) Windows may schedule a hidden or background FreeCAD on the
# efficiency cores; the same work then runs 1.5-3x slower. Pinning applies an affinity mask of the performance
# cores to the freecad.exe the launcher starts; worker processes it creates later inherit the mask.
# The mask is derived like tools\perf\run_ab.py performance_core_mask(): the logical processors of processor
# group 0 in the highest efficiency class. A homogeneous CPU (one efficiency class) gets no mask.

function Get-KurtShapePinPerformanceCoresDefault {
    # The one place the launchers' default lives. Off: in the slice A/B bench-gui A/B of 2026-10-21 (4 clean runs
    # per side) the kernel-bound metrics were 4.5-7.5 % faster pinned (the rule needs 10 %) and panel_refresh slower.
    return $false
}

function Get-KurtShapeCpuSets {
    # One row per logical processor: processor group, logical index, efficiency class (GetSystemCpuSetInformation).
    if (-not ('KurtShapeCpuSetReader' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class KurtShapeCpuSetReader {
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetSystemCpuSetInformation(IntPtr information, int length, out int returned, IntPtr process, int flags);
    // Flattened rows of three: group, logical processor index, efficiency class.
    public static int[] Read() {
        int needed;
        GetSystemCpuSetInformation(IntPtr.Zero, 0, out needed, IntPtr.Zero, 0);
        if (needed <= 0) { throw new Win32Exception(Marshal.GetLastWin32Error()); }
        IntPtr buffer = Marshal.AllocHGlobal(needed);
        try {
            if (!GetSystemCpuSetInformation(buffer, needed, out needed, IntPtr.Zero, 0)) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            // SYSTEM_CPU_SET_INFORMATION: Size Type Id Group(2) LogicalProcessorIndex CoreIndex
            // LastLevelCacheIndex NumaNodeIndex EfficiencyClass ...
            List<int> rows = new List<int>();
            int offset = 0;
            while (offset < needed) {
                int size = Marshal.ReadInt32(buffer, offset);
                if (size <= 0) { break; }
                rows.Add(Marshal.ReadInt16(buffer, offset + 12) & 0xFFFF);
                rows.Add(Marshal.ReadByte(buffer, offset + 14));
                rows.Add(Marshal.ReadByte(buffer, offset + 18));
                offset += size;
            }
            return rows.ToArray();
        } finally {
            Marshal.FreeHGlobal(buffer);
        }
    }
}
'@
    }
    $flat = [KurtShapeCpuSetReader]::Read()
    for ($index = 0; $index + 2 -lt $flat.Length; $index += 3) {
        [pscustomobject]@{ group = $flat[$index]; logical = $flat[$index + 1]; efficiency_class = $flat[$index + 2] }
    }
}

function Resolve-KurtShapePerformanceCoreMask {
    # Pure: the performance-core mask of processor group 0 for these CPU-set rows, or 0 when there are no
    # efficiency cores to avoid (one efficiency class, or every group-0 processor already in the top class).
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$CpuSets)
    $rows = @($CpuSets | Where-Object { [int]$_.group -eq 0 })
    if (-not $rows.Count) { return [long]0 }
    $top = ($rows | Measure-Object -Property efficiency_class -Maximum).Maximum
    [long]$all = 0
    [long]$mask = 0
    foreach ($row in $rows) {
        $bit = [long]1 -shl [int]$row.logical
        $all = $all -bor $bit
        if ([int]$row.efficiency_class -eq [int]$top) { $mask = $mask -bor $bit }
    }
    if ($mask -eq $all) { return [long]0 }
    return $mask
}

function Format-KurtShapeAffinityMask {
    param([long]$Mask)
    if ($Mask) { return ('0x{0:x}' -f $Mask) }
    return $null
}

function Get-KurtShapePinningPlan {
    # What a launcher does: requested (pin / no-pin / default), the default, and the mask it will apply (or $null).
    param([switch]$PinPerformanceCores, [switch]$NoPinPerformanceCores, [object[]]$CpuSets)
    if ($PinPerformanceCores -and $NoPinPerformanceCores) { throw '-PinPerformanceCores and -NoPinPerformanceCores are exclusive.' }
    $default = [bool](Get-KurtShapePinPerformanceCoresDefault)
    $requested = if ($PinPerformanceCores) { 'pin' } elseif ($NoPinPerformanceCores) { 'no-pin' } else { 'default' }
    $pin = if ($PinPerformanceCores) { $true } elseif ($NoPinPerformanceCores) { $false } else { $default }
    $plan = [ordered]@{
        requested = $requested
        default = $(if ($default) { 'pin' } else { 'no-pin' })
        pin = $pin
        performance_core_mask = $null
        logical_processors = $null
        mask = $null
        note = $null
    }
    try {
        if (-not $PSBoundParameters.ContainsKey('CpuSets')) { $CpuSets = @(Get-KurtShapeCpuSets) }
        $plan.logical_processors = @($CpuSets | Where-Object { [int]$_.group -eq 0 }).Count
        $plan.performance_core_mask = Format-KurtShapeAffinityMask (Resolve-KurtShapePerformanceCoreMask -CpuSets $CpuSets)
    } catch {
        $plan.note = 'CPU sets unavailable (' + $_.Exception.Message + '); no affinity applied'
        return $plan
    }
    if (-not $plan.performance_core_mask) {
        $plan.note = 'no efficiency cores (homogeneous CPU set); no affinity applied'
    } elseif ($pin) {
        $plan.mask = $plan.performance_core_mask
        $plan.note = 'freecad.exe and the workers it starts are pinned to the performance cores'
    } else {
        $plan.note = 'not pinned; Windows may schedule a hidden or background app on the efficiency cores'
    }
    return $plan
}

function Set-KurtShapeProcessAffinity {
    # Applies the plan's mask to a just-started process. Returns the observed mask, or $null when none applies.
    # A failure only warns: the app still runs, unpinned.
    param([Parameter(Mandatory = $true)][Diagnostics.Process]$Process, [Parameter(Mandatory = $true)]$Plan)
    if (-not $Plan.mask) { return $null }
    try {
        $Process.ProcessorAffinity = [IntPtr][Convert]::ToInt64(([string]$Plan.mask).Substring(2), 16)
        $Process.Refresh()
        return (Format-KurtShapeAffinityMask ([long]$Process.ProcessorAffinity))
    } catch {
        Write-Warning ('Could not pin PID ' + $Process.Id + ' to ' + $Plan.mask + ': ' + $_.Exception.Message)
        return $null
    }
}
