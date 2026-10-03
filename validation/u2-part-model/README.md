# U2 actual GUI acceptance

Run `powershell -NoProfile -ExecutionPolicy Bypass -File tools/validate-u2-part-model-gui.ps1` from the repository. The launcher prints the PID of its separate hidden FreeCAD process. Read `gui-result.json` after that process exits; a successful launch is not a successful validation.

The recipe uses the production Panel, quantity widgets, native objects, actual modal dialogs, Qt mouse/key events and disposable native previews. It disables Python networking and uses a project-local profile in `runtime/u2-part-model-gui-validation`; it preserves the user's existing process. Small synthetic fixtures supplement the native controller tests and do not establish large-model latency or full Onshape parity.

The accepted scene contains five logical parts: scoped Add preserves an unselected second part; Split produces two sides; Transform creates a copy; a whole-part linear pattern preserves its source and creates another part. Every displayed Body and native Tip must remain visible. Isometric screenshots frame all current geometry and exclude the internal cutting plane. Rollback Up/Down changes current parts while retaining held features in ordered history. New empty sketch owners remain selectable without exposing internal helper Bodies.

The remaining geometry dialogs exercise valid previews and Cancel with unchanged live intent, revision, object inventory and undo/redo. These include Revolve, feature/selector path Sweep, Loft section selection, Boolean, circular pattern, Mirror, Fillet, Chamfer and Shell. Up to face uses an actual selected-face query. Modal controls are captured separately from the main app because QWidget.grab() excludes child top-level windows.

Reference health first verifies a healthy attached-sketch selector, then deliberately injects a missing creator into native QueryInputs to verify the red history marker, diagnostic tooltip, failed build state and unavailable current measurements. This screen fixture is explicitly injected; natural topology regressions are covered by the independent selector tests.

GUI validation caught and repaired native reentrancy during hidden-clone loading, deleted tree items during synchronous checkbox refresh, internal cutting-plane visibility, and hidden generated native Tip providers. Preview evaluation suspends lifetime checks and queued Panel refresh while the clone is active, restores the source camera/selection, and rechecks the revision before rendering. Native openTransaction is application-wide in this FreeCAD version; the preview closes only its owned global transaction ID before restoring the source so later source sync cannot gain an empty undo step.

PNG files and the editable `u2-studio-gui.FCStd` are reproducible local artifacts. The small JSON report is the committed acceptance evidence. The report records the exact FreeCAD and OCCT versions and startup SHA256 values for the participating source modules; it rejects source changes during the isolated run.
