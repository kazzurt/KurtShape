"""KurtShape 2D drawings: dimensioned manufacturing drawings from KurtShape models.

Two layers, one process (the bundled FreeCAD 1.1.4 / OCCT 7.8.1 interpreter):

- :mod:`kurtshape.drawing.views` (FreeCAD/OCCT): orthographic views with hidden-line removal,
  half-space section views with hatch boundaries, all as exact 2D lines, arcs and circles
  (B-splines and ellipses as fine polylines) in true size, in a view frame chosen by the caller.
- :mod:`kurtshape.drawing.sheet` (ezdxf, MIT, vendored under ``runtime/vendor/drawing-py311``):
  a sheet on a DXF template (title block fields, revision table, notes), views placed at a scale,
  real DIMENSION / HATCH / MTEXT entities with tolerances, GD&T frames, surface-finish symbols,
  leaders, centre lines and simplified thread lines, in any language (CJK through a TTF/TTC
  style), saved as DXF (R2018, UTF-8) and rendered to a vector PDF and PNG previews.

A drawing is a short Python spec (see ``projects/dodec-bolt-5-16-18-t40/drawing_d021.py``):
dimensions are given in view coordinates of features the model defines, and every dimension's
definition points are checked to lie on the projected geometry, so a drawing cannot silently
dimension something the model does not have.

Install the drafting dependency once: ``tools/setup-drawing-deps.ps1`` (pip --target, no-deps).
"""

VENDOR_DIRNAME = "drawing-py311"
