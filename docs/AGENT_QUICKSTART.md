# Install and model with an agent

Paste this into your agent on the Windows machine:

> Install KurtShape from https://github.com/kazzurt/KurtShape into a short writable
> folder I own. Read the repository's AGENTS.md and docs/WINDOWS_SETUP.md. Check
> Git and 7-Zip, run setup.ps1 with Windows PowerShell, and require its installation
> check to pass. Use the pinned bundled runtime, not a global FreeCAD or Python.
> Launch KurtShape if it is not already running; ask before restarting an existing
> instance. Read capabilities and list_documents through tools/assistant.ps1.
> Tell me the installed commit, check result, and where my CAD files will go.
> Model through the assistant bridge, not by taking over my screen. Wait for my
> modeling request before changing a document.

## Connect

From the checkout root, after launching `KurtShape.cmd`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1 -Operation list_documents
```

These use the bundled Python and only read app state. To submit any supported
operation, write a UTF-8 JSON request file (without BOM), then:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1 -RequestFile .\projects\my-part\request.json
```

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
3. Prefer sketches and native features; `add_polyline` keeps a connected profile.
   Use `preview` for risky geometry. Use geometry selectors rather than guessed
   face/edge indices when possible. Confirm supported arguments via the contract.
4. `save` / `export` need an absolute destination under an allowed folder whose
   directory already exists. New profiles allow `<checkout>/projects` by default.
   A user-chosen Save destination adds that folder. Do not widen grants silently.
5. Preserve originals, use descriptive model folders and retain the build recipe.
   Do not overwrite an FCStd open in another app process.

### Slow operations and retries

The stock client has a bounded HTTP wait. **`outcome_unknown` or a transport
timeout is not proof a feature failed.** Keep the original request ID. Query
`request_status` with the original `request_id` in the same bridge session (see the contract), wait
while pending, and inspect the document after completion. Identical retries
must use the same request ID and identical body. Never issue a new mutation ID
just because a fillet was slow. If the session restarted or the ledger expired,
inspect state and reconcile before deciding what to do next.

### Development

`tools/check-install.ps1` runs a quick isolated native check. `run-checks.ps1`
runs the registered regression suites using the bundled runtime. Three tests
need external private examples and skip when absent; four performance tests
are opt-in. `-Full` requires the external examples and all performance checks.
The GUI recipes use private processes/profiles, but headless or scripted checks
do not replace human viewport acceptance. Never restart the user's app without
asking, and never reuse its profile for a probe.
