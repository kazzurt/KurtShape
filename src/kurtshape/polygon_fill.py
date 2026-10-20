"""Triangulate simple 2D polygons with holes, fast enough for a live Section View.

A Python port of Mapbox's earcut algorithm (ISC licence, see THIRD_PARTY_NOTICES.md):
ear clipping on a doubly linked ring, holes bridged into the outer ring, and a
z-order curve index for rings with more than 80 vertices. Pure Python: the GUI
process keeps numpy out.
"""
from __future__ import annotations


class _Node:
    __slots__ = ("i", "x", "y", "prev", "next", "z", "prevZ", "nextZ", "steiner")

    def __init__(self, i, x, y):
        self.i, self.x, self.y = i, x, y
        self.prev = self.next = self.prevZ = self.nextZ = None
        self.z = 0
        self.steiner = False


def triangulate(rings):
    """Triangles (i, j, k) over the vertices of ``rings`` = [outer, hole, hole, ...] concatenated.

    Each ring is a list of (x, y); rings need not repeat their first vertex. Holes
    must lie inside the outer ring. Orientation does not matter.
    """
    rings = [list(ring) for ring in rings if len(ring) >= 3]
    if not rings:
        return []
    starts, flat = [], []
    for ring in rings:
        starts.append(len(flat))
        flat.extend(ring)
    outer = _linked(flat, 0, starts[1] if len(starts) > 1 else len(flat), True)
    triangles = []
    if outer is None or outer.next is outer.prev:
        return triangles
    if len(starts) > 1:
        outer = _eliminate_holes(flat, starts, outer)
    min_x = min_y = inv_size = 0.0
    if len(flat) > 80:
        end = starts[1] if len(starts) > 1 else len(flat)
        xs = [p[0] for p in flat[:end]]
        ys = [p[1] for p in flat[:end]]
        min_x, min_y = min(xs), min(ys)
        size = max(max(xs) - min_x, max(ys) - min_y)
        inv_size = 32767.0 / size if size else 0.0
    _earcut_linked(outer, triangles, min_x, min_y, inv_size, 0)
    return triangles


def _signed_area(points, start, end):
    total, j = 0.0, end - 1
    for i in range(start, end):
        total += (points[j][0] - points[i][0]) * (points[i][1] + points[j][1])
        j = i
    return total


def _linked(points, start, end, clockwise):
    last = None
    if clockwise == (_signed_area(points, start, end) > 0):
        for i in range(start, end):
            last = _insert(i, points[i][0], points[i][1], last)
    else:
        for i in range(end - 1, start - 1, -1):
            last = _insert(i, points[i][0], points[i][1], last)
    if last is not None and _equals(last, last.next):
        _remove(last)
        last = last.next
    return last


def _filter(start, end=None):
    if start is None:
        return start
    if end is None:
        end = start
    p = start
    while True:
        again = False
        if not p.steiner and (_equals(p, p.next) or _area(p.prev, p, p.next) == 0):
            _remove(p)
            p = end = p.prev
            if p is p.next:
                break
            again = True
        else:
            p = p.next
        if not again and p is end:
            break
    return end


def _earcut_linked(ear, triangles, min_x, min_y, inv_size, stage):
    if ear is None:
        return
    if not stage and inv_size:
        _index_curve(ear, min_x, min_y, inv_size)
    stop = ear
    while ear.prev is not ear.next:
        prev, nxt = ear.prev, ear.next
        if _is_ear_hashed(ear, min_x, min_y, inv_size) if inv_size else _is_ear(ear):
            triangles.append((prev.i, ear.i, nxt.i))
            _remove(ear)
            ear = nxt.next
            stop = nxt.next
            continue
        ear = nxt
        if ear is stop:
            if not stage:
                _earcut_linked(_filter(ear), triangles, min_x, min_y, inv_size, 1)
            elif stage == 1:
                ear = _cure_local_intersections(_filter(ear), triangles)
                _earcut_linked(ear, triangles, min_x, min_y, inv_size, 2)
            elif stage == 2:
                _split_earcut(ear, triangles, min_x, min_y, inv_size)
            break


def _is_ear(ear):
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    ax, bx, cx, ay, by, cy = a.x, b.x, c.x, a.y, b.y, c.y
    x0, x1 = min(ax, bx, cx), max(ax, bx, cx)
    y0, y1 = min(ay, by, cy), max(ay, by, cy)
    p = c.next
    while p is not a:
        if (x0 <= p.x <= x1 and y0 <= p.y <= y1 and _point_in_triangle(ax, ay, bx, by, cx, cy, p.x, p.y)
                and _area(p.prev, p, p.next) >= 0):
            return False
        p = p.next
    return True


def _is_ear_hashed(ear, min_x, min_y, inv_size):
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    ax, bx, cx, ay, by, cy = a.x, b.x, c.x, a.y, b.y, c.y
    x0, x1 = min(ax, bx, cx), max(ax, bx, cx)
    y0, y1 = min(ay, by, cy), max(ay, by, cy)
    min_z = _z_order(x0, y0, min_x, min_y, inv_size)
    max_z = _z_order(x1, y1, min_x, min_y, inv_size)

    def blocks(p):
        return (x0 <= p.x <= x1 and y0 <= p.y <= y1 and p is not a and p is not c
                and _point_in_triangle(ax, ay, bx, by, cx, cy, p.x, p.y) and _area(p.prev, p, p.next) >= 0)

    p, n = ear.prevZ, ear.nextZ
    while p is not None and p.z >= min_z and n is not None and n.z <= max_z:
        if blocks(p):
            return False
        p = p.prevZ
        if blocks(n):
            return False
        n = n.nextZ
    while p is not None and p.z >= min_z:
        if blocks(p):
            return False
        p = p.prevZ
    while n is not None and n.z <= max_z:
        if blocks(n):
            return False
        n = n.nextZ
    return True


def _cure_local_intersections(start, triangles):
    p = start
    while True:
        a, b = p.prev, p.next.next
        if (not _equals(a, b) and _intersects(a, p, p.next, b) and _locally_inside(a, b)
                and _locally_inside(b, a)):
            triangles.append((a.i, p.i, b.i))
            _remove(p)
            _remove(p.next)
            p = start = b
        p = p.next
        if p is start:
            break
    return _filter(p)


def _split_earcut(start, triangles, min_x, min_y, inv_size):
    a = start
    while True:
        b = a.next.next
        while b is not a.prev:
            if a.i != b.i and _is_valid_diagonal(a, b):
                c = _split_polygon(a, b)
                a = _filter(a, a.next)
                c = _filter(c, c.next)
                _earcut_linked(a, triangles, min_x, min_y, inv_size, 0)
                _earcut_linked(c, triangles, min_x, min_y, inv_size, 0)
                return
            b = b.next
        a = a.next
        if a is start:
            return


def _eliminate_holes(points, starts, outer):
    queue = []
    for number in range(1, len(starts)):
        start = starts[number]
        end = starts[number + 1] if number + 1 < len(starts) else len(points)
        ring = _linked(points, start, end, False)
        if ring is None:
            continue
        if ring is ring.next:
            ring.steiner = True
        queue.append(_leftmost(ring))
    queue.sort(key=lambda node: node.x)
    for hole in queue:
        outer = _eliminate_hole(hole, outer)
    return outer


def _eliminate_hole(hole, outer):
    bridge = _find_hole_bridge(hole, outer)
    if bridge is None:
        return outer
    reverse = _split_polygon(bridge, hole)
    _filter(reverse, reverse.next)
    return _filter(bridge, bridge.next)


def _find_hole_bridge(hole, outer):
    p, hx, hy, qx, m = outer, hole.x, hole.y, float("-inf"), None
    while True:
        if p.next.y != p.y and p.next.y <= hy <= p.y:
            x = p.x + (hy - p.y) * (p.next.x - p.x) / (p.next.y - p.y)
            if qx < x <= hx:
                qx = x
                m = p if p.x < p.next.x else p.next
                if x == hx:
                    return m  # the hole touches the outer segment
        p = p.next
        if p is outer:
            break
    if m is None:
        return None
    stop, mx, my, tan_min = m, m.x, m.y, float("inf")
    p = m
    while True:
        if (hx >= p.x >= mx and hx != p.x
                and _point_in_triangle(hx if hy < my else qx, hy, mx, my, qx if hy < my else hx, hy, p.x, p.y)):
            tan = abs(hy - p.y) / (hx - p.x)
            if _locally_inside(p, hole) and (tan < tan_min or (tan == tan_min and (
                    p.x > m.x or (p.x == m.x and _sector_contains_sector(m, p))))):
                m, tan_min = p, tan
        p = p.next
        if p is stop:
            break
    return m


def _sector_contains_sector(m, p):
    return _area(m.prev, m, p.prev) < 0 and _area(p.next, m, m.next) < 0


def _index_curve(start, min_x, min_y, inv_size):
    p = start
    while True:
        if p.z == 0:
            p.z = _z_order(p.x, p.y, min_x, min_y, inv_size)
        p.prevZ, p.nextZ = p.prev, p.next
        p = p.next
        if p is start:
            break
    p.prevZ.nextZ = None
    p.prevZ = None
    _sort_linked(p)


def _sort_linked(head):
    in_size = 1
    while True:
        p, head, tail, merges = head, None, None, 0
        while p is not None:
            merges += 1
            q, p_size = p, 0
            for _ in range(in_size):
                p_size += 1
                q = q.nextZ
                if q is None:
                    break
            q_size = in_size
            while p_size > 0 or (q_size > 0 and q is not None):
                if p_size != 0 and (q_size == 0 or q is None or p.z <= q.z):
                    e, p, p_size = p, p.nextZ, p_size - 1
                else:
                    e, q, q_size = q, q.nextZ, q_size - 1
                if tail is not None:
                    tail.nextZ = e
                else:
                    head = e
                e.prevZ = tail
                tail = e
            p = q
        tail.nextZ = None
        in_size *= 2
        if merges <= 1:
            return head


def _z_order(x, y, min_x, min_y, inv_size):
    x = int((x - min_x) * inv_size)
    y = int((y - min_y) * inv_size)
    x = (x | (x << 8)) & 0x00FF00FF
    x = (x | (x << 4)) & 0x0F0F0F0F
    x = (x | (x << 2)) & 0x33333333
    x = (x | (x << 1)) & 0x55555555
    y = (y | (y << 8)) & 0x00FF00FF
    y = (y | (y << 4)) & 0x0F0F0F0F
    y = (y | (y << 2)) & 0x33333333
    y = (y | (y << 1)) & 0x55555555
    return x | (y << 1)


def _leftmost(start):
    p = leftmost = start
    while True:
        if p.x < leftmost.x or (p.x == leftmost.x and p.y < leftmost.y):
            leftmost = p
        p = p.next
        if p is start:
            return leftmost


def _point_in_triangle(ax, ay, bx, by, cx, cy, px, py):
    return ((cx - px) * (ay - py) >= (ax - px) * (cy - py)
            and (ax - px) * (by - py) >= (bx - px) * (ay - py)
            and (bx - px) * (cy - py) >= (cx - px) * (by - py))


def _is_valid_diagonal(a, b):
    return (a.next.i != b.i and a.prev.i != b.i and not _intersects_polygon(a, b)
            and ((_locally_inside(a, b) and _locally_inside(b, a) and _middle_inside(a, b)
                  and (_area(a.prev, a, b.prev) or _area(a, b.prev, b)))
                 or (_equals(a, b) and _area(a.prev, a, a.next) > 0 and _area(b.prev, b, b.next) > 0)))


def _area(p, q, r):
    return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)


def _equals(p1, p2):
    return p1.x == p2.x and p1.y == p2.y


def _sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def _on_segment(p, q, r):
    return min(p.x, r.x) <= q.x <= max(p.x, r.x) and min(p.y, r.y) <= q.y <= max(p.y, r.y)


def _intersects(p1, q1, p2, q2):
    o1, o2 = _sign(_area(p1, q1, p2)), _sign(_area(p1, q1, q2))
    o3, o4 = _sign(_area(p2, q2, p1)), _sign(_area(p2, q2, q1))
    if o1 != o2 and o3 != o4:
        return True
    return ((o1 == 0 and _on_segment(p1, p2, q1)) or (o2 == 0 and _on_segment(p1, q2, q1))
            or (o3 == 0 and _on_segment(p2, p1, q2)) or (o4 == 0 and _on_segment(p2, q1, q2)))


def _intersects_polygon(a, b):
    p = a
    while True:
        if (p.i != a.i and p.next.i != a.i and p.i != b.i and p.next.i != b.i
                and _intersects(p, p.next, a, b)):
            return True
        p = p.next
        if p is a:
            return False


def _locally_inside(a, b):
    if _area(a.prev, a, a.next) < 0:
        return _area(a, b, a.next) >= 0 and _area(a, a.prev, b) >= 0
    return _area(a, b, a.prev) < 0 or _area(a, a.next, b) < 0


def _middle_inside(a, b):
    p, inside = a, False
    px, py = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
    while True:
        if ((p.y > py) != (p.next.y > py) and p.next.y != p.y
                and px < (p.next.x - p.x) * (py - p.y) / (p.next.y - p.y) + p.x):
            inside = not inside
        p = p.next
        if p is a:
            return inside


def _split_polygon(a, b):
    a2, b2 = _Node(a.i, a.x, a.y), _Node(b.i, b.x, b.y)
    an, bp = a.next, b.prev
    a.next, b.prev = b, a
    a2.next, an.prev = an, a2
    b2.next, a2.prev = a2, b2
    bp.next, b2.prev = b2, bp
    return b2


def _insert(i, x, y, last):
    p = _Node(i, x, y)
    if last is None:
        p.prev = p.next = p
    else:
        p.next, p.prev = last.next, last
        last.next.prev = p
        last.next = p
    return p


def _remove(p):
    p.next.prev = p.prev
    p.prev.next = p.next
    if p.prevZ is not None:
        p.prevZ.nextZ = p.nextZ
    if p.nextZ is not None:
        p.nextZ.prevZ = p.prevZ


# ------------------------------------------------------------------ planar regions from loops
def polygon_area(ring):
    """Signed area of a closed 2D ring (counter-clockwise positive)."""
    total, j = 0.0, len(ring) - 1
    for i in range(len(ring)):
        total += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1])
        j = i
    return total / 2.0


def point_in_ring(point, ring):
    x, y = point
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def regions(rings):
    """Group closed 2D rings into [outer, hole, ...] regions by nesting depth (even = outer)."""
    count = len(rings)
    areas = [abs(polygon_area(ring)) for ring in rings]
    containers = [[j for j in range(count) if j != i and areas[j] > areas[i] and point_in_ring(rings[i][0], rings[j])]
                  for i in range(count)]
    depth = [len(found) for found in containers]
    groups = {i: [i] for i in range(count) if depth[i] % 2 == 0}
    for i in range(count):
        if depth[i] % 2 == 1:
            parents = [j for j in containers[i] if depth[j] == depth[i] - 1]
            if parents:
                groups[min(parents, key=lambda j: areas[j])].append(i)
    return list(groups.values())


def simplify(ring, tolerance):
    """Drop points closer than ``tolerance`` to the chord of their kept neighbours (closed 2D ring)."""
    if len(ring) <= 4 or tolerance <= 0:
        return list(ring)
    kept = [ring[0]]
    limit = tolerance * tolerance
    for index in range(1, len(ring)):
        a, b = kept[-1], ring[index]
        c = ring[(index + 1) % len(ring)]
        dx, dy = c[0] - a[0], c[1] - a[1]
        length2 = dx * dx + dy * dy
        if length2 == 0:
            continue
        cross = (b[0] - a[0]) * dy - (b[1] - a[1]) * dx
        if cross * cross / length2 > limit or (b[0] - a[0]) * dx + (b[1] - a[1]) * dy < 0:
            kept.append(b)
    return kept if len(kept) >= 3 else list(ring)
