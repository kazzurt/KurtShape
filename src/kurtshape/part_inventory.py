"""Read-only solid inventory across legacy, studio and assembly documents."""
from . import assembly, bodies, studio


def rows(doc, include_history=False):
    """Describe native solids without adopting or changing their history.

    Native names remain source IDs; logical part IDs are additional metadata.
    Visibility is deliberately not a final-result test: users may hide finals.
    """
    if not isinstance(include_history, bool):
        raise assembly.AssemblyError("invalid_argument", "include_history must be a boolean")
    final = {obj.Name for obj in bodies.results(doc)
             if hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Solids}
    eligible = {obj.Name for obj in assembly._source_results(doc)}
    result = []
    for obj in doc.Objects:
        if not hasattr(obj, "Shape") or obj.Shape.isNull() or not obj.Shape.Solids:
            continue
        current = obj.Name in final
        if not include_history and not current:
            continue
        role = ("final" if current else "embedded_source" if assembly.is_embedded_source(obj)
                else "helper" if getattr(obj, "KurtShapeInternal", False) else "history")
        result.append({"id": obj.Name, "name": obj.Label, "type": obj.TypeId,
                       "part_id": studio.part_id(obj), "role": role, "final": current,
                       "usable": current and not bool(set(obj.State) & {"Invalid", "Error"}),
                       "usable_basis": "current_result_and_native_state", "geometry_validation": "not_checked",
                       "assembly_source_eligible": obj.Name in eligible,
                       "solid_count": len(obj.Shape.Solids)})
    return result


def source_candidates(doc, final_only=False):
    """Preserve legacy candidate membership unless callers opt into finals."""
    if not isinstance(final_only, bool):
        raise assembly.AssemblyError("invalid_argument", "final_only must be a boolean")
    inventory = {row["id"]: row for row in rows(doc, include_history=True)}
    return [inventory[obj.Name] for obj in assembly._source_results(doc)
            if not final_only or inventory[obj.Name]["final"]]
