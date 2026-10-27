# Native delivery and nominal clearance verification

Use `tools/validate_delivery.py` with the bundled **pythonw.exe**, redirected
stdout/stderr and a fresh descriptive `--working` directory. It uses its own
headless profile and copies the native file before opening it. It neither
discovers a running app nor changes the user's open document. All inputs are
hashed before/after; nonempty evidence directories are refused.

```powershell
$pythonPath = Join-Path $PWD 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\pythonw.exe'
$arguments = @('-B','tools\validate_delivery.py','C:\projects\fixture\fixture.FCStd',
  '--working','C:\projects\fixture-delivery-validation',
  '--export','C:\projects\fixture\fixture.step','--surface')
Start-Process $pythonPath -ArgumentList ($arguments | ForEach-Object { '"' + $_ + '"' }) `
  -WorkingDirectory $PWD -WindowStyle Hidden -Wait `
  -RedirectStandardOutput 'C:\projects\fixture-validation-stdout.log' `
  -RedirectStandardError 'C:\projects\fixture-validation-stderr.log'
```

Read `delivery-report.json` and require `passed:true` (CLI exit 0). The workflow
requires **both** `build_status:valid` and `geometry_check_report.status:valid`,
plus freshly recomputed embedded-source integrity checks. It then saves a
private roundtrip file, closes it, reopens it and repeats those gates. Valid
solids alone do not establish a valid assembly: the original Dodec fixture's
retained reopen report showed valid solid checks alongside a failed source seal.
The verifier rejects that combination and never attempts to repair or reseal it.

Embedded source-file freshness is separate: `current`, `different` or `missing`
is reported per source with its occurrence IDs and SHA-256. Missing source files
are allowed for portable embedded snapshots. Add `--require-current-sources` to
require every external saved source still to exist with the recorded hash.
Embedded integrity itself is mandatory in all modes.

Each source row represents one actual embedded snapshot and lists every
occurrence using it. Occurrence links forward the source's native properties;
they are not counted again as sources. A null or changed embedded source remains
failed through inspection, managed saving and discard recovery, with its original
rejected seal retained in the archive. Recovery availability does not imply that
the recovered geometry passed delivery validation.

The native result used for export comparison includes parent-container world
placements, including legacy Bodies nested in rotated/translated `App::Part`
containers; an object's own placement is not applied twice.

`--export` is repeatable and currently accepts STEP/STP. Each comparison checks
validity, solid count, total volume (relative 1e-7, minimum 1e-5 mm³) and exact
bounds (`--tolerance-mm`, default 0.02). These are coarse consistency checks and
can miss equal-volume changes. **`--surface` is an explicit stronger check**:
both directions sample tessellated triangle centres projected back onto the
exact source faces, and measure against the target's faces. It defaults to a
deterministic cap of 2000 samples per direction (`--max-samples`). Both counts
and maximum measured deviation are reported. This is sampled consistency, not
an exact Hausdorff bound or proof of geometric equivalence. STL comparison is
not implemented. GUI startup/reopening is covered separately by isolated hidden
GUI regressions; a headless pass does not claim GUI acceptance.

## Dodec fixture envelope examples

`check_clearance` is deliberately a small geometric API. The full field contract
is in [OPERATION_CONTRACT.md](OPERATION_CONTRACT.md#clearance-checks-opt-in).
World-space cylinder, oriented box and annular envelopes cover the known fixture
cases without encoding a machine, spindle model or cutting-load rule:

- **Blocked straight Allen key:** a cylinder along the cartridge screw axis,
  tested against the loaded `Hub`, reports the obstructing component and overlap.
  The original socket-head concept's obstruction remains evidence for changing
  access strategy, not permission to alter the hub.
- **External-hex side spanner:** use 66.5 × 26 × 4 boxes with local corner
  `[-6.5,-13,114.5]`, translated to the four Ø56 bolt-circle centres and rotated
  through bolt angle ±15°, 0°. Select the `Hub` and `Cartridge`; the historical
  sampled audit found 2.941 and 1.546 mm minimum respectively. The actual wrench
  must fit the supplied envelope; these three samples are not a continuous swing.
- **Blind dowel ends:** probe from the pin's tip along its axis at the pin radius.
  A blind end exactly matching protrusion returns zero; the fixture was revised
  to through sockets. A finite probe through the remaining 4 mm of flange gives
  no stop in that tested interval. There is no inferred infinite clearance.
- **Rejected radial cutter:** model the recorded radial-normal cutter and holder
  cylinders at the underside of the root. Report their fixture intersections;
  do not omit the flange from `components` to turn the result into a pass.
- **Accepted arm-parallel OD:** for each of three arms, use a complete annulus
  about that arm's axis, starting 22.36 mm from the hub vertex at `[0,0,138]`,
  inner radius 17.425, outer radius 27.425, length 40. This is the exact continuous
  orbit envelope of a Ø10 cylindrical tool centred at radius 22.425. Check all
  fixture components. The known minimum nominal gap is 1.467916 mm at an M8 hex
  head. Holder orbit: inner radius 9.925, outer radius 34.925, length 60, starting
  40 mm farther along the axis. The historical minimum holder/fixture gap is
  34.462863 mm.

Thread/pilot overlaps must be restricted by pair, a short local thread-region
envelope and a maximum nominal overlap volume. This prevents a blanket
"screw overlaps are fine" exemption from hiding a screw-head/flange collision.
Checks describe supplied nominal geometry only. Unmodeled motions, stock,
runout, deflection, casting variation and machine kinematics are outside them.

Native regressions in `tests/test_delivery_clearance.py` cover a 1.468 mm
limiting-component example, continuous annulus interference, zero/4 mm axial
clearance (including a rotated axis), finite probe range, region/volume-bounded
thread overlap, unchanged model state, failed source seals with valid solids,
native save/reopen and equal-volume displaced holes caught by surface sampling.
They also cover nested native container coordinates for targets, component
envelopes, tip probes and delivery exports, and reject malformed legacy solids
and invalid Boolean results independently of the document's build-status flag.
