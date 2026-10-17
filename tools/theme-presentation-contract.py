"""Check semantic presentation contrast without importing Qt or FreeCAD.

Run with the bundled Python: python -B tools/theme-presentation-contract.py
This verifies token pairs; native rendered widgets still require GUI evidence.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def read_colors(path):
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "COLORS" for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("Theme has no literal COLORS mapping")


def luminance(color):
    values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in values]
    return sum(weight * value for weight, value in zip((.2126, .7152, .0722), linear))


def contrast(first, second):
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def evaluate(colors):
    pairs = [
        ("Primary text", "ink", "surface", 4.5),
        ("Chrome text", "ink", "chrome", 4.5),
        ("Idle footer", "muted", "chrome", 4.5),
        ("Secondary text", "muted", "surface", 4.5),
        ("Placeholder", "placeholder", "surface", 4.5),
        ("Disabled input", "disabled_ink", "disabled", 4.5),
        ("Disabled chrome text", "disabled_ink", "chrome", 4.5),
        ("Selection text", "selection_ink", "selection", 4.5),
        ("Active picker text", "selection_ink", "active_field_fill", 4.5),
        ("Confirm action text", "surface", "accent", 4.5),
        ("Pressed confirm text", "surface", "accent_pressed", 4.5),
        ("Shaded hover label", "surface", "tooltip", 4.5),
        ("Error feedback", "error", "chrome", 4.5),
        ("Warning feedback", "warning", "chrome", 4.5),
        ("Success feedback", "success", "chrome", 4.5),
        ("Interactive field boundary", "border", "surface", 3.0),
        ("Focus boundary", "accent", "surface", 3.0),
        ("Active picker boundary", "accent", "active_field_fill", 3.0),
    ]
    checks = []
    for label, foreground, background, minimum in pairs:
        ratio = contrast(colors[foreground], colors[background])
        checks.append({"name": label, "foreground_token": foreground, "background_token": background,
                       "foreground": colors[foreground], "background": colors[background],
                       "contrast": round(ratio, 3), "minimum": minimum, "passed": ratio >= minimum})
    return {"passed": all(check["passed"] for check in checks),
            "method": "WCAG sRGB relative luminance of literal theme tokens; native rendering and DPI remain separate checks",
            "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", type=Path, default=Path(__file__).resolve().parents[1] / "src" / "kurtshape" / "theme.py")
    parser.add_argument("--report", type=Path, help="Optional JSON evidence destination")
    args = parser.parse_args()
    result = evaluate(read_colors(args.theme))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for check in result["checks"]:
        state = "PASS" if check["passed"] else "FAIL"
        print(f"{state} {check['name']}: {check['contrast']:.3f}:1 (minimum {check['minimum']:.1f}:1)")
    print(f"{'Passed' if result['passed'] else 'Failed'} {len(result['checks'])} presentation contrast checks")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
