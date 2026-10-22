"""Native pending-line movement through the actual hidden Qt child hit target.

Call pending_line_probe(panel) while a private sketch is already in edit mode.
Reuse result['target_pixels'] after suppressing an overlay to compare the same
viewport locations. This never moves the physical pointer or captures a screen.
"""
from __future__ import annotations

import math
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from pivy import coin


def _identity(widget):
    if widget is None:
        return None
    return {'class': widget.metaObject().className(), 'name': widget.objectName(),
            'visible': widget.isVisible(), 'enabled': widget.isEnabled(),
            'transparent_for_mouse': widget.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)}


def _ancestry(widget):
    result = []
    while widget is not None and len(result) < 10:
        result.append(_identity(widget))
        widget = widget.parentWidget()
    return result


def _preview(view):
    search = coin.SoSearchAction()
    search.setName('EditCurvesCoordinate')
    search.apply(view.getSceneGraph())
    path = search.getPath()
    return [list(p.getValue()) for p in path.getTail().point.getValues()] if path is not None else []


def _scene_state(view, global_point):
    graphics = view.graphicsView()
    if not hasattr(graphics, 'scene'):
        return {'graphics': _identity(graphics), 'available': False}
    scene = graphics.scene()
    if scene is None:
        return {'available': False}
    result = {'available': True, 'grabber': None, 'items': []}
    grabber = scene.mouseGrabberItem()
    if grabber is not None:
        result['grabber'] = {'type': type(grabber).__name__, 'visible': grabber.isVisible()}
        if isinstance(grabber, QtWidgets.QGraphicsProxyWidget):
            result['grabber']['widget'] = _identity(grabber.widget())
    for item in graphics.items(graphics.mapFromGlobal(global_point))[:8]:
        row = {'type': type(item).__name__, 'visible': item.isVisible(), 'enabled': item.isEnabled()}
        if isinstance(item, QtWidgets.QGraphicsProxyWidget):
            row['widget'] = _identity(item.widget())
        result['items'].append(row)
    return result


def pending_line_probe(panel, target_pixels=None, commit=False):
    main = panel.main
    app = QtWidgets.QApplication.instance()
    sketch = panel.active_sketch()
    if sketch is None:
        raise AssertionError('Open a private sketch edit before the motion probe')
    active = main.findChild(QtWidgets.QMdiArea).activeSubWindow()
    viewport = next(w for w in active.findChildren(QtWidgets.QWidget)
                    if w.metaObject().className() == 'QOpenGLWidget' and w.isVisible() and w.width() > 300)
    view = Gui.getDocument(sketch.Document.Name).activeView()
    ratio = viewport.devicePixelRatioF()
    initial_count = sketch.GeometryCount

    def hit(point):
        return main.childAt(main.mapFromGlobal(viewport.mapToGlobal(point)))

    def preview_pixel(points):
        if len(points) < 2:
            return None
        world = sketch.Placement.multVec(App.Vector(*points[-1]))
        pixel = view.getPointOnViewport(world)
        return [float(pixel[0]) / ratio, viewport.height() - 1 - float(pixel[1]) / ratio]

    def move(point, direct=False):
        receiver = viewport if direct else hit(point)
        global_point = viewport.mapToGlobal(point)
        state = {'target': [point.x(), point.y()], 'direct_gl': direct, 'receiver': _identity(receiver),
                 'receiver_ancestry': _ancestry(receiver),
                 'scene': _scene_state(view, global_point), 'spontaneous': False,
                 'main_active': main.isActiveWindow(),
                 'cursor_owned': getattr(getattr(panel, 'sketch_cursor', None), 'counters', None),
                 'global_pointer_widget': _identity(app.widgetAt(QtGui.QCursor.pos()))}
        if receiver is None:
            state['error'] = 'No Qt child receiver at this viewport position'
            return state
        local = receiver.mapFromGlobal(global_point)
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(local), QtCore.QPointF(global_point),
                                QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
        before = time.perf_counter()
        app.sendEvent(receiver, event)
        state['dispatch_ms'] = (time.perf_counter() - before) * 1000
        QtTest.QTest.qWait(65)
        points = _preview(view)
        projected = preview_pixel(points)
        state.update(preview=points, preview_pixel=projected,
                     error_px=math.hypot(projected[0] - point.x(), projected[1] - point.y()) if projected else None,
                     accepted=event.isAccepted())
        return state

    def is_gl(point):
        return hit(point) is viewport

    def free_point_candidates():
        return [point for y in (.72, .55, .3, .85, .15) for x in (.16, .32, .5, .68, .84)
                if is_gl(point := QtCore.QPoint(round(viewport.width() * x), round(viewport.height() * y)))]

    Gui.Selection.clearSelection()
    Gui.Selection.clearPreselection()
    panel.native_command('Sketcher_StopOperation')
    action = next(action for action in panel.sketch_bar.actions() if action.text() == 'Line')
    button = panel.sketch_bar.widgetForAction(action)
    QtTest.QTest.mouseClick(button, QtCore.Qt.LeftButton)
    # Sketcher's task-mode change reasserts native dock overlays asynchronously.
    # Discover hit targets only after the actual toolbar command and its timer.
    QtTest.QTest.qWait(450)
    try:
        free_points = free_point_candidates()
        if len(free_points) < 2:
            raise AssertionError('The overlay leaves fewer than two unobstructed viewport test points')
        start, free = free_points[0], free_points[-1]
        initial_moves = [dict(stage='start_move', **move(start))]
        QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, start)
        QtTest.QTest.qWait(100)
        initial_moves.append(dict(stage='outside_pending', **move(free)))
        # Native overlay/task updates may be triggered by the first pending
        # point rather than activation alone. Poll only after native preview.
        discovery = []
        requested = target_pixels
        deadline = time.monotonic() + 3.0
        while True:
            candidates, overlays, grid_hits = [], [], []
            for widget in main.findChildren(QtWidgets.QWidget):
                if 'Overlay' not in widget.metaObject().className():
                    continue
                raw_rect = QtCore.QRect(widget.mapTo(viewport, QtCore.QPoint()), widget.size())
                rect = raw_rect.intersected(viewport.rect())
                row = dict(widget=_identity(widget), raw_rect=list(raw_rect.getRect()),
                           overlap=list(rect.getRect()), hits=[])
                overlays.append(row)
                if not widget.isVisible() or rect.width() < 3 or rect.height() < 3:
                    continue
                for x, y in ((.15, .5), (.5, .5), (.85, .5), (.5, .08), (.5, .25), (.5, .75)):
                    point = QtCore.QPoint(rect.left() + round((rect.width() - 1) * x), rect.top() + round((rect.height() - 1) * y))
                    receiver = hit(point)
                    row['hits'].append(dict(point=[point.x(), point.y()], receiver=_identity(receiver)))
                    if receiver is not viewport and any('Overlay' in entry['class'] for entry in _ancestry(receiver)):
                        candidates.append((point.x(), point.y()))
            # Verify actual normal hit ownership independently of native widget
            # rectangles. Dock overlay animation can invalidate layout caches.
            for y in (.1, .25, .4, .55, .7, .85):
                for x in (.1, .25, .4, .55, .7, .85, .95):
                    point = QtCore.QPoint(round((viewport.width() - 1) * x), round((viewport.height() - 1) * y))
                    receiver = hit(point)
                    if receiver is not viewport:
                        ancestors = _ancestry(receiver)
                        grid_hits.append(dict(point=[point.x(), point.y()], ancestry=ancestors))
                        if any('Overlay' in entry['class'] for entry in ancestors):
                            candidates.append((point.x(), point.y()))
            discovery.append(dict(elapsed_ms=round((time.monotonic() - deadline + 3) * 1000),
                                  viewport_size=[viewport.width(), viewport.height()],
                                  overlays=overlays, non_gl_grid_hits=grid_hits))
            discovered = list(dict.fromkeys(candidates))[:8]
            if requested is None and discovered:
                target_pixels = discovered
                break
            # Explicit fixed-source replay observes the entire matching timer
            # window too, so a delayed reappearance cannot yield a false pass.
            if time.monotonic() >= deadline:
                target_pixels = requested if requested is not None else discovered
                break
            QtTest.QTest.qWait(250)
        free_points = free_point_candidates()
        if len(free_points) < 2:
            raise AssertionError('The overlay leaves fewer than two unobstructed viewport test points')
        free = free_points[-1]
        requested_targets = [list(point) for point in target_pixels]
        targets = [QtCore.QPoint(int(x), int(y)) for x, y in target_pixels if viewport.rect().contains(QtCore.QPoint(int(x), int(y)))]
        result = {'method': 'Native toolbar Line; Qt main.childAt receiver routing versus direct GL at identical target pixels. Synthetic events, no OS pointer movement.',
                  'viewport': _identity(viewport), 'viewport_size': [viewport.width(), viewport.height()],
                  'requested_target_pixels': requested_targets,
                  'target_pixels': [[p.x(), p.y()] for p in targets], 'start': [start.x(), start.y()],
                  'free': [free.x(), free.y()], 'count_before': initial_count, 'moves': initial_moves, 'discovery': discovery}
        result['entry_command'] = panel.sketch_references.native_command_for_context()
        if not targets:
            result.update(blocked_candidates=False, count_after=sketch.GeometryCount,
                          geometry_unchanged=sketch.GeometryCount == initial_count,
                          reason='No overlay-owned viewport hit target was discovered after native toolbar activation and pending preview')
            return result
        for point in targets:
            result['moves'].append(dict(stage='routed_overlay', **move(point)))
            result['moves'].append(dict(stage='direct_gl_same_target', **move(point, direct=True)))
            result['moves'].append(dict(stage='routed_free_release', **move(free)))
        result['count_after'] = sketch.GeometryCount
        result['geometry_unchanged'] = sketch.GeometryCount == initial_count
        result['blocked_candidates'] = any((row.get('receiver') or {}).get('class') != 'QOpenGLWidget'
                                           for row in result['moves'] if row['stage'] == 'routed_overlay')
        result['causal_pairs'] = []
        rows = result['moves'][2:]
        for index in range(0, len(rows), 3):
            routed, direct, released = rows[index:index + 3]
            result['causal_pairs'].append({'target': routed['target'], 'routed_error_px': routed.get('error_px'),
                                           'direct_error_px': direct.get('error_px'), 'released_error_px': released.get('error_px'),
                                           'routed_receiver': routed.get('receiver')})
        if commit:
            point = targets[len(targets) // 2]
            result['moves'].append(dict(stage='commit_move', **move(point)))
            receiver = hit(point)
            if receiver is None:
                raise AssertionError('No actual Qt receiver at the selected commit location')
            local = receiver.mapFromGlobal(viewport.mapToGlobal(point))
            QtTest.QTest.mouseClick(receiver, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, local)
            QtTest.QTest.qWait(180)
            committed = {'target': [point.x(), point.y()], 'receiver': _identity(receiver),
                         'receiver_ancestry': _ancestry(receiver), 'geometry_count': sketch.GeometryCount,
                         'count_delta': sketch.GeometryCount - initial_count, 'solve_result': sketch.solve()}
            if sketch.GeometryCount > initial_count:
                geometry = sketch.Geometry[-1]
                committed['geometry_type'] = geometry.TypeId
                if hasattr(geometry, 'StartPoint') and hasattr(geometry, 'EndPoint'):
                    committed['endpoints'] = [list(geometry.StartPoint), list(geometry.EndPoint)]
                    committed['endpoint_pixels'] = [preview_pixel([None, list(endpoint)])
                                                    for endpoint in (geometry.StartPoint, geometry.EndPoint)]
                    committed['error_px'] = min(math.hypot(pixel[0] - point.x(), pixel[1] - point.y())
                                                for pixel in committed['endpoint_pixels'])
            result['commit'] = committed
            result['moves'].append(dict(stage='continuous_pending', **move(free)))
            result['count_after_continuous_move'] = sketch.GeometryCount
        return result
    finally:
        panel.native_command('Sketcher_StopOperation')
        QtTest.QTest.qWait(80)
        if 'result' in locals():
            result['cleanup_command'] = panel.sketch_references.native_command_for_context()
            result['cleanup_cursor'] = getattr(getattr(panel, 'sketch_cursor', None), 'counters', None)
            result['cleanup_midpoint_guard'] = getattr(panel.sketch_snapping, '_midpoint_guard', None) is not None
