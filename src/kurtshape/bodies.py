"""Resolve native ownership without depending on GUI focus or internal names."""
import FreeCAD as App


def bodies(doc):
    return [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]


def owner(doc, obj):
    if obj is None:
        return None
    matches = [body for body in bodies(doc) if obj == body or obj in body.Group or obj == body.Origin or obj in body.Origin.OriginFeatures]
    return matches[0] if len(matches) == 1 else None


def origin_plane(body, plane):
    return next((obj for obj in body.Origin.OriginFeatures if getattr(obj, "Role", "") == plane + "_Plane"
                 or obj.Name.startswith(plane + "_Plane")), None)


def results(doc):
    # An assembly's current result consists of occurrences, never its hidden
    # embedded source snapshots or an aggregate that repeats the same shapes.
    from . import assembly
    assemblies = [obj for obj in doc.Objects if obj.TypeId == "Assembly::AssemblyObject"]
    if assemblies:
        return assembly.result_objects(doc)
    native_bodies = bodies(doc)
    members = {obj.Name for body in native_bodies for obj in body.Group}
    standalone = [obj for obj in doc.Objects if obj.Name not in members and obj not in native_bodies
                  and obj.TypeId.startswith("Part::") and hasattr(obj, "Shape") and not obj.Shape.isNull()
                  and not any(parent.TypeId.startswith(("Part::", "App::Part")) and hasattr(parent, "Shape") for parent in obj.InList)]
    return native_bodies + standalone
