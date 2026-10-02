"""Read-only inventory of generated Onshape Part Studio text and STEP pairs.

This is a lexical inventory, never a FeatureScript evaluator or converter.
Run with Python stdlib: python -B tools/inventory_sources.py
"""
from __future__ import annotations
import collections
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT.parents[1] / "Onshape examples"


def balanced_end(text, start, opening="{", closing="}"):
    depth, quote, escaped = 0, None, False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("Unbalanced source at offset %d" % start)


def counts(pattern, text):
    return dict(sorted(collections.Counter(re.findall(pattern, text)).items()))


def inventory(path):
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    records = []
    for match in re.finditer(r"features\.(\w+)\s*=\s*function\(id\)\s*\{", text):
        begin = match.end() - 1
        end = balanced_end(text, begin)
        block = text[begin:end]
        names = re.findall(r'"Feature Name"\s*:\s*"([^"\n]*)"', block)
        families = re.findall(r"\b(\w+)\(context,\s*id\s*\+", block)
        guard = re.search(r"if\s*\((.*?)\)\s*\{", block, re.S)
        records.append({
            "id": match[1], "name": names[0] if names else "<unnamed>",
            "line": text.count("\n", 0, begin) + 1,
            "families": list(dict.fromkeys(families)),
            "guard": " ".join(guard[1].split()) if guard else None,
            "entities": counts(r"\b(skCircle|skLineSegment|skArc|skEllipse|skSpline|skPoint)\(", block),
            "constraints": counts(r"ConstraintType\.(\w+)", block),
            "compressed_queries": block.count("qCompressed("),
            "expressions": list(dict.fromkeys(re.findall(r"'expression'\s*:\s*\"([^\"]*)\"", block))),
        })
    step = path.with_suffix(".step")
    st = step.read_text() if step.exists() else ""
    configuration = re.search(r"export function main\(\)\s*\{\s*return build\((.*?)\);", text, re.S)
    families = dict(sorted(collections.Counter(f for r in records for f in r["families"]).items()))
    for record in records:
        record["conversion_status"] = "unsupported_source_representation"
        record["native_feature_id"] = None
    return {
        "source_relative_path": str(path.relative_to(ROOT.parents[1])),
        "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw),
        "representation": "generated Part Studio FeatureScript, not API feature JSON",
        "feature_script_version": re.search(r"FeatureScript\s+(\d+)", text)[1],
        "imports": re.findall(r"^import\(.*", text, re.M),
        "default_units": re.search(r'"Default Units"\s*:\s*(\[.*?\])', text)[1],
        "main_configuration": configuration[1] if configuration else None,
        "configuration_names": re.findall(r"'Name'\s*:\s*\"([^\"]*)\"", text[:text.find("const buildPrivate")]),
        "feature_count": len(records), "families": families,
        "sketch_entities": counts(r"\b(skCircle|skLineSegment|skArc|skEllipse|skSpline|skPoint)\(", text),
        "constraint_types": counts(r"ConstraintType\.(\w+)", text),
        "compressed_query_count": text.count("qCompressed("),
        "features": records,
        "step": {
            "relative_path": str(step.relative_to(ROOT.parents[1])),
            "sha256": hashlib.sha256(step.read_bytes()).hexdigest() if step.exists() else None,
            "header": st[:st.find("DATA;")],
            "lexical_manifold_brep_count": len(re.findall(r"=MANIFOLD_SOLID_BREP\(", st)),
            "si_units": re.findall(r"SI_UNIT\([^;]+", st),
        },
        "provenance_gaps": ["confirmed Onshape link-to-file binding", "frozen source revision", "STEP configuration binding", "two edited STEP references (Kurt deferred them)", "critical dimension acceptance from Kurt"],
        "correspondence": "Filename pairing only; geometry and same-revision/configuration correspondence unverified",
        "count_caveat": "Static definitions across conditional branches; not necessarily the active configuration feature count",
        "native_conversion": {
            "status": "rejected", "editable_conversion_count": 0,
            "reasons": ["Generated FeatureScript execution/translation is not implemented",
                        "Sketch planes, projected topology and compressed queries cannot be mapped by guessing",
                        "Full feature order/constraints/expressions/configuration must survive conversion; no supported-looking subset is silently extracted"],
            "feature_families_beyond_first_slice": sorted(set(families) - {"newSketch", "extrude"}),
            "subset_caveat": "Presence of newSketch/extrude is not evidence that their geometry, constraints, booleans or references meet the declared subset",
        },
    }


def main():
    results = [inventory(p) for p in sorted(SOURCES.glob("*.txt"))]
    out = ROOT / "validation" / "source-inventory.json"
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for r in results:
        print(json.dumps({k: r[k] for k in ["source_relative_path", "feature_count", "families", "main_configuration", "compressed_query_count"]}, indent=2))


if __name__ == "__main__":
    main()
