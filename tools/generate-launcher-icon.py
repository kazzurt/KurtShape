"""Rebuild the KurtShape shortcut icon: python tools/generate-launcher-icon.py.

Requires Pillow. Projects a regular dodecahedron (12 pentagonal faces) and
writes editable SVG, transparent PNG, and a Windows ICO beside the UI icons.
"""

from itertools import combinations, product
from math import atan2, sqrt
from pathlib import Path

from PIL import Image, ImageDraw


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def mul(a, scale):
    return tuple(x * scale for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def unit(a):
    return mul(a, 1 / sqrt(dot(a, a)))


def main():
    phi = (1 + sqrt(5)) / 2
    vertices = list(product((-1.0, 1.0), repeat=3))
    for a, b in product((-1.0, 1.0), repeat=2):
        vertices.extend(((0, a / phi, b * phi),
                         (a / phi, b * phi, 0),
                         (a * phi, 0, b / phi)))
    faces = {}
    for i, j, k in combinations(range(20), 3):
        normal = cross(sub(vertices[j], vertices[i]), sub(vertices[k], vertices[i]))
        if dot(normal, normal) < 1e-10:
            continue
        normal = unit(normal)
        if dot(normal, vertices[i]) < 0:
            normal = mul(normal, -1)
        distances = [dot(normal, sub(v, vertices[i])) for v in vertices]
        indices = tuple(n for n, d in enumerate(distances) if abs(d) < 1e-7)
        if max(distances) > 1e-7 or len(indices) != 5:
            continue
        center = mul(tuple(sum(vertices[n][axis] for n in indices) for axis in range(3)), 0.2)
        u = unit(sub(vertices[indices[0]], center))
        v = cross(normal, u)
        ordered = sorted(indices, key=lambda n: atan2(dot(sub(vertices[n], center), v),
                                                     dot(sub(vertices[n], center), u)))
        faces[indices] = (ordered, normal)
    assert len(faces) == 12
    edges = {tuple(sorted((face[i], face[(i + 1) % 5])))
             for face, _ in faces.values() for i in range(5)}
    assert len(edges) == 30

    camera = unit((0.22, 1, phi))
    right = unit(cross((0, 1, 0), camera))
    up = cross(camera, right)
    projected = [(dot(v, right), -dot(v, up)) for v in vertices]
    min_x, max_x = min(x for x, y in projected), max(x for x, y in projected)
    min_y, max_y = min(y for x, y in projected), max(y for x, y in projected)
    scale = 440 / max(max_x - min_x, max_y - min_y)
    points = [(256 + (x - (min_x + max_x) / 2) * scale,
               256 + (y - (min_y + max_y) / 2) * scale) for x, y in projected]
    light = unit(add(add(mul(right, -0.65), mul(up, 0.9)), camera))
    visible = [(face, normal) for face, normal in faces.values() if dot(normal, camera) > 1e-7]
    visible.sort(key=lambda item: dot(item[1], camera))
    shapes = []
    for face, normal in visible:
        brightness = 0.58 + 0.55 * max(0, dot(normal, light))
        color = tuple(min(255, round(c * brightness)) for c in (92, 170, 223))
        shapes.append(([points[i] for i in face], color))

    destination = Path(__file__).resolve().parents[1] / 'resources' / 'icons'
    destination.mkdir(parents=True, exist_ok=True)
    stem = destination / 'kurtshape-dodecahedron'
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">',
           '<title>KurtShape regular dodecahedron</title>',
           '<g stroke="#203c55" stroke-width="5" stroke-linejoin="round">']
    image = Image.new('RGBA', (2048, 2048))
    draw = ImageDraw.Draw(image)
    for polygon, color in shapes:
        coords = ' '.join(f'{x:.3f},{y:.3f}' for x, y in polygon)
        svg.append(f'<polygon points="{coords}" fill="#{color[0]:02x}{color[1]:02x}{color[2]:02x}"/>')
        pixels = [(round(x * 4), round(y * 4)) for x, y in polygon]
        draw.polygon(pixels, fill=(*color, 255))
        draw.line(pixels + [pixels[0]], fill=(32, 60, 85, 255), width=20, joint='curve')
    svg.extend(('</g>', '</svg>'))
    stem.with_suffix('.svg').write_text('\n'.join(svg) + '\n', encoding='utf-8')
    image = image.resize((512, 512), Image.Resampling.LANCZOS)
    image.save(stem.with_suffix('.png'))
    image.save(stem.with_suffix('.ico'), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(f'Created {stem} (.svg, .png, .ico); 12 pentagonal faces, 30 edges.')


if __name__ == '__main__':
    main()
