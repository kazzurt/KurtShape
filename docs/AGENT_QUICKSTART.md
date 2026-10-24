# Install and model with an agent

Paste this into your agent on the Windows machine:

> Install KurtShape from https://github.com/kazzurt/KurtShape into a short writable
> folder I own. Read the repository's AGENTS.md and docs/WINDOWS_SETUP.md. Check
> Git and 7-Zip, run setup.ps1 with Windows PowerShell, and require its installation
> check to pass. Use the pinned bundled runtime, not a global FreeCAD or Python.
> Do not launch the KurtShape window yourself: choose the app by the AGENTS.md
> section "Launching: which app an agent uses" (headless by default, a hidden app
> when you need the bridge, my running app only when I ask to watch), and ask
> before restarting an existing instance. Read capabilities and list_documents from
> the one you use. Tell me the installed commit, check result, and where my CAD
> files will go. Model through KurtShape's operations, not by taking over my
> screen. Wait for my modeling request before changing a document.

Which app an agent uses (headless Controller, hidden app, or the user's running app)
is decided once, in [AGENTS.md](../AGENTS.md#launching-which-app-an-agent-uses).
Per-operation arguments and examples are in [OPERATIONS.md](OPERATIONS.md); worked
recipes in [COOKBOOK.md](COOKBOOK.md).

## Connect

From the checkout root, with the user's KurtShape running (they start it):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1 -Operation list_documents
```

These use the bundled Python and only read app state. To submit any supported
operation, write a UTF-8 JSON request file (without BOM), then:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1 -RequestFile .\projects\my-part\request.json
```

### Hidden agent app (no window)

When the [launch rule](../AGENTS.md#launching-which-app-an-agent-uses) calls for the
bridge without the user's app, run a hidden one. It is a private KurtShape with its own
profile, port and folder under `runtime\private\agent`, drawn offscreen with no window:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1 -Hidden -ProjectRoot C:\path\to\my-projects
```

It starts the app (or reuses it if it is running), sends `capabilities` and prints its
session file; pass that file to `-Session` here or to `assistant_client.py --session`.
`-ProjectRoot` (optional, repeatable) lets it save and export to that folder besides
`projects/`. It loads this checkout's code when it starts. When finished, save the
model, `close_document`, and stop it with `.\tools\assistant.ps1 -Hidden -Stop` (its
folder is kept). Give the user the saved path; never save over a file open in their app.
Parallel agents use `-HiddenSession <name>` each.

For a separate app session add `-Session <absolute-path-to-assistant-session.json>`.
By default the client honors `KURTSHAPE_SESSION_DIR`, otherwise it uses this
checkout's `runtime/assistant-session.json`. It connects only to local loopback
with proxies disabled. Do not copy the token into a prompt or log.

## Modeling rules

Read [OPERATION_CONTRACT.md](OPERATION_CONTRACT.md) and the running app's
`capabilities`; typed operations and visible toolbar tools are not identical.
The contract includes request/response examples. Native `.FCStd` is authoritative;
STEP/STL are exports.

1. Start with `list_documents` / `inspect`, or `new` when the user wants a new
   model. Never assume the active document is disposable.
2. Mutations use that document's `document_id` and current `expected_revision`.
   Read the new revision from every successful response. Use one distinct
   `request_id` per intended mutation and retain it with the complete request.
   Add `"detail": "compact"` to a mutation for the status header, the created
   feature and the request's reports (about 1 KB) instead of the full
   inspection; `preview` is a read and needs no `expected_revision`.
3. Prefer sketches and native features; `add_polyline` keeps a connected profile.
   Use `preview` for risky geometry. Use geometry selectors rather than guessed
   face/edge indices when possible. Confirm supported arguments via the contract.
4. `save` / `export` need an absolute destination under an allowed folder whose
   directory already exists. New profiles allow `<checkout>/projects` by default.
   A user-chosen Save destination adds that folder. Do not widen grants silently.
   `save` onto an FCStd that holds another project rejects with
   `save_destination_other_project` unless you pass `"overwrite": true`; pass it only
   when Kurt asked for that file to be replaced.
5. Preserve originals, use descriptive model folders and retain the build recipe.
   Do not overwrite an FCStd open in another app process.
6. Result checks (contract 3.2, OPERATION_CONTRACT §3.2.1): an edit that would leave a
   studio Add/Remove/Intersect empty or invalid is rejected with the creation code; the
   error's `feature` is the failing operation and `trigger` the one you edited, so compare
   them. Read `result_check_report` on accepted mutations and `result_checks` on `inspect`:
   `pending` after native edits (run `check_geometry`), `failed` after rollback/rebuild
   (fix the model before `export`, which validates first). Use `preview` before a risky edit;
   its `valid` tells you whether the commit would be accepted.
7. Parameters (§3.2.3): model the key dimensions as parameters so Kurt can correct them
   in the left panel's Parameters section. `create_parameter` (`type` length, angle or
   number), then bind a dimension with `set_expression` using the `expression_ref` the
   response returns (never a hard-coded `Params.x`), or promote existing dimensions with
   `create_parameter … bind:[{feature, parameter}]`. `edit_parameter` rebuilds what depends
   on it; a failure rolls back and `error.parameter.accepted` says what stands.
8. Batches (§3.2.4): for a dependent sequence, `preview` one `{"op":"batch", steps}`
   proposal, check `accepted`, then send `batch` with the same steps,
   `expected_revision = base_revision` and a new `request_id`. A failed batch changes
   nothing; `error.batch.step` names the step to fix. Reference earlier steps with
   `{"$ref": alias}` / `{"$part": alias}` and give features explicit `id`s when formulas or
   reconciliation need them. Keep batches short; in the app they stop at 20 s, and on a
   large part each step costs about 1 s there, so send about 12 steps at a time.
9. Images (§3.2.2): `render_view` returns PNGs of the current model (views, sections,
   labelled highlights) without touching Kurt's view; check a result visually before
   reporting it.
10. Assemblies: organise occurrences into instance-list folders by function or
   sub-assembly (`Frame`, `Fasteners/M3`, `Electronics`) and leave no more than about
   12 at the root. Pass `folder` to `insert_assembly_part`, or regroup with
   `move_assembly_instances` / `set_assembly_folders`; `inspect` returns each
   instance's `folder` and the tree ([contract](OPERATION_CONTRACT.md#instance-folders-assembly-ux-2026-10-24)).
11. Measure inside KurtShape: `measure {references:[...]}` takes selectors or
   `{object, subelement}` (an occurrence is measured where it sits) and returns
   `{kind, text, values}` (distance with ΔX ΔY ΔZ, parallel distance, angles, Ø;
   [contract](OPERATION_CONTRACT.md#measure-assembly-ux-2026-10-24)). After changing a part,
   `inspect` shows `source.status:"changed"` on its occurrences; update them with
   `refresh_assembly_part {instance, shared:"all"}`. `assembly_instance_source {instance}`
   gives an occurrence's source path and kind.

### Slow operations and retries

**`outcome_unknown` or a transport timeout is not proof a feature failed.**
`tools/assistant_client.py` reconciles for you: it keeps the request ID, polls
`request_status` and returns the stored response, or says `pending` (exit 2:
reconcile later with `--reconcile --request-id <id>`), `unknown` (exit 3: inspect
before acting) or safe to retry (exit 4: inspect, then send a mutation again with a
new request ID). Identical retries of a pending or unknown request must use the
same request ID and identical body; never issue a new mutation ID just because a
fillet was slow. After a restart (`not_recorded`) the old revision is stale, so
inspect and reconcile by explicit ids. `python -B tools/assistant_client.py
--build-check` says whether the running app was started from this checkout's
current code (`current`), predates your edits (`stale`: ask Kurt before restarting) or
runs another tree.

### Development

`tools/check-install.ps1` runs a quick isolated native check. `run-checks.ps1`
runs the registered regression suites using the bundled runtime. Three tests
need external private examples and skip when absent; four performance tests
are opt-in. `-Full` requires the external examples and all performance checks.
The GUI recipes (`tools/run_gui_recipe.ps1`) use private processes and profiles on a
private Windows desktop (since 2026-10-22; the script's header says how), so nothing a
recipe opens reaches the user's screen and a run fails if its window probe saw a
window there. Headless or scripted checks still do not replace human viewport
acceptance. Never restart the user's app without asking, and never reuse its
profile for a probe.
