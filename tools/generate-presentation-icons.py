"""Generate KurtShape's original restrained, shaded SVG command icons.

Run with any Python 3: python tools/generate-presentation-icons.py
No dependencies, source screenshot pixels, external assets or app process needed.
The generator is the editable source of truth for resources/icons/*.svg.
"""
from pathlib import Path

INK, LIGHT, MID, DARK = "#51575d", "#dedfe1", "#b8bdc2", "#899198"


def p(d, fill="none", **attrs):
    extra=" ".join(f'{k.replace("_", "-")}="{v}"' for k,v in attrs.items())
    return f'<path d="{d}" fill="{fill}" {extra}/>'


def ellipse(cx,cy,rx,ry,fill="none"):
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}"/>'


def rectangle(x,y,w,h,fill="none",radius=0):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"/>'


def cube(x=12,y=12,r=8):
    return (p(f'M{x-r} {y-r/2} L{x} {y-r} {x+r} {y-r/2} {x} {y} Z',LIGHT)
            +p(f'M{x-r} {y-r/2} L{x} {y} {x} {y+r} {x-r} {y+r/2} Z',MID)
            +p(f'M{x} {y} L{x+r} {y-r/2} {x+r} {y+r/2} {x} {y+r} Z',DARK))


def group(inner,transform):
    return f'<g transform="{transform}">{inner}</g>'


def plus(x=18,y=18):
    return p(f'M{x-3} {y} h6 M{x} {y-3} v6',stroke_width=1.4)


def minus(x=18,y=18):
    return p(f'M{x-3} {y} h6',stroke_width=1.5)


ASSETS = {
    "sketch": p('M3 18 L5 21 19 7 16 4 Z',LIGHT)+p('M3 18 L2 22 5 21 Z',DARK)+p('M2 23 H22'),
    "extrude": cube(y=14,r=7)+p('M9 8 V4 H15 V8',LIGHT)+p('M12 6 V1 M9 4 L12 1 15 4'),
    "remove": cube(y=13,r=8)+p('M8 9 L12 7 16 9 12 12 Z',INK)+minus(19,3),
    "revolve": p('M8 4 H15 Q20 4 20 9 V17 Q20 21 15 21 H8 Z',MID)+ellipse(12,4,6,2,LIGHT)
                +p('M4 2 V21 M4 13 C1 13 1 21 8 22 M3 19 L8 22 7 17'),
    "sweep": p('M3 18 C12 21 5 5 19 5 L20 10 C12 9 18 23 3 23 Z',MID)+ellipse(3,20,2,3,LIGHT),
    "loft": p('M8 4 H16 L22 20 Q12 24 2 20 Z',MID)+ellipse(12,4,4,2,LIGHT)+ellipse(12,20,10,3,LIGHT),
    "fillet": p('M3 21 V9 Q3 3 9 3 H21 V21 Z',MID)+p('M3 9 Q3 3 9 3 H21 L15 9 Z',LIGHT)
               +p('M9 21 V12 Q9 9 12 9 H15 V21'),
    "chamfer": p('M3 21 V9 L9 3 H21 V21 Z',MID)+p('M3 9 L9 3 H21 L15 9 Z',LIGHT)+p('M15 9 V21'),
    "shell": cube(r=9)+p('M7 8 L12 5 17 8 12 11 Z',INK)+p('M7 8 L12 11 V16 L7 13 Z',LIGHT)
              +p('M12 11 L17 8 V13 L12 16 Z',MID),
    "draft": p('M7 4 H17 L22 21 H2 Z',MID)+p('M7 4 L12 1 17 4 12 7 Z',LIGHT)+p('M12 7 V21'),
    "move-face": cube(x=9,y=15,r=6)+p('M14 8 H23 M19 4 L23 8 19 12',stroke_width=1.3),
    "linear-pattern": ''.join(cube(x,y,3.8) for x,y in [(6,6),(17,6),(6,17),(17,17)]),
    "circular-pattern": ''.join(cube(x,y,3) for x,y in [(12,4),(4,12),(20,12),(12,20)])+ellipse(12,12,1.7,1.7,DARK),
    "mirror": p('M2 18 L7 6 10 18 Z',MID)+p('M22 18 L17 6 14 18 Z',LIGHT)+p('M12 2 V22'),
    "boolean": cube(x=9,y=9,r=6)+cube(x=15,y=15,r=6),
    "split": cube(r=9)+p('M1 16 L16 1 23 8 8 23 Z',LIGHT)+p('M8 23 L23 8'),
    "transform": cube(x=8,y=16,r=6)+p('M12 12 L22 2 M15 2 H22 V9',stroke_width=1.3),
    "plane": p('M2 18 L8 4 22 5 16 19 Z',LIGHT)+p('M1 12 H23'),
    "axis": p('M3 21 L21 3 M4 11 L8 15 M15 4 L19 8')+p('M5 16 L8 13 11 16 8 19 Z',MID),
    "point": p('M2 12 H22 M12 2 V22')+ellipse(12,12,3,3,MID),
    "coordinate-system": p('M6 18 V2 M6 18 H22 M6 18 L17 8 M3 5 L6 2 9 5 M19 15 L22 18 19 21 M12 8 H17 V13'),
    "undo": p('M20 18 V11 Q20 7 16 7 H3 M8 2 L3 7 8 12',stroke_width=1.4),
    "redo": p('M4 18 V11 Q4 7 8 7 H21 M16 2 L21 7 16 12',stroke_width=1.4),
    "save": p('M3 2 H18 L22 6 V22 H3 Z',LIGHT)+p('M7 2 V9 H17 V2 M7 22 V14 H18 V22')+rectangle(13,3,2,4,DARK),
    "document-menu": p('M3 6 H21 M3 12 H21 M3 18 H21',stroke_width=1.8),
    "settings": p('M9 2 H15 L16 6 20 5 23 10 20 13 22 17 17 21 13 19 9 22 5 19 6 15 2 12 5 7 9 8 Z',MID)
                 +ellipse(12,12,4,4,LIGHT),
    "search": ellipse(10,10,6.5,6.5,LIGHT)+p('M15 15 L22 22',stroke_width=2),
    "more": ''.join(rectangle(x,10,3,3,DARK,.3) for x in [3,10,17]),
    "fit": p('M2 8 V2 H8 M16 2 H22 V8 M22 16 V22 H16 M8 22 H2 V16')+cube(r=4),
    "normal": p('M3 20 L7 12 H21 L17 20 Z',LIGHT)+p('M12 16 V2 M8 6 L12 2 16 6',stroke_width=1.3),
    "isometric": cube(r=9),
    "rebuild": p('M21 10 A9 9 0 1 0 20 17',stroke_width=1.3)+p('M22 3 V11 H14',MID),
    "check-geometry": cube(x=9,y=11,r=7)+p('M12 19 L16 23 23 13',stroke_width=1.8),
    "measure": p('M2 16 L18 2 22 7 6 21 Z',LIGHT)+p('M6 15 L8 17 M9 12 L11 14 M12 9 L14 11 M15 6 L17 8'),
    "confirm": p('M3 12 L9 18 21 5',stroke_width=2.1),
    "cancel": p('M5 5 L19 19 M19 5 L5 19',stroke_width=1.9),
    "geometry-menu": rectangle(2,3,10,9,LIGHT)+ellipse(17,16,5,5,MID)+p('M2 22 L12 13'),
    "constraints-menu": p('M3 4 H21 M3 20 H21 M6 4 V20 M18 4 V20 M3 12 H21')
                        +p('M9 9 L6 12 9 15 M15 9 L18 12 15 15',stroke_width=1.2),
    "edit-menu": p('M2 7 H14 V21 H2 Z',LIGHT)+p('M8 14 L17 3 21 6 12 17 8 18 Z',MID),
    "line": p('M3 21 L21 3',stroke_width=1.3)+ellipse(3,21,1.6,1.6,MID)+ellipse(21,3,1.6,1.6,MID),
    "polyline": p('M2 20 L8 7 16 16 22 3',stroke_width=1.3)
                +''.join(ellipse(x,y,1.4,1.4,MID) for x,y in [(2,20),(8,7),(16,16),(22,3)]),
    "rectangle": rectangle(3,5,18,14,LIGHT)+ellipse(3,5,1.3,1.3,DARK)+ellipse(21,19,1.3,1.3,DARK),
    "circle": ellipse(12,12,9,9,LIGHT)+ellipse(12,12,1.4,1.4,DARK)+p('M12 12 L19 6'),
    "arc": p('M3 18 A9 9 0 0 1 20 6',stroke_width=1.4)+ellipse(3,18,1.5,1.5,MID)+ellipse(20,6,1.5,1.5,MID),
    "spline": p('M2 20 C17 21 4 2 22 4',stroke_width=1.4)+ellipse(2,20,1.5,1.5,MID)+ellipse(22,4,1.5,1.5,MID),
    "dimension": p('M3 3 V21 M21 3 V21 M3 12 H21 M7 8 L3 12 7 16 M17 8 L21 12 17 16'),
    "trim": p('M4 2 L20 22 M20 2 L4 22',stroke_width=1.2)+ellipse(5,18,3,3,LIGHT)+ellipse(19,18,3,3,LIGHT),
    "construction": p('M2 18 L7 13 M9 11 L14 6 M16 4 L19 1 M5 21 L10 16 M12 14 L17 9 M19 7 L22 4'),
    "pierce": p('M3 19 L20 2 M2 11 H22 M11 2 V22')+ellipse(11,11,3,3,LIGHT),
    "new-document": p('M4 2 H15 L21 8 V22 H4 Z',LIGHT)+p('M15 2 V8 H21')+plus(12,16),
    "open": p('M2 7 H9 L12 10 H22 L19 22 H2 Z',MID)+p('M2 10 V4 H10 L13 7 H20 V10',LIGHT),
    "export": p('M3 9 H14 V22 H3 Z',LIGHT)+p('M10 14 L22 2 M15 2 H22 V9',stroke_width=1.3),
    "recent": ellipse(12,12,9,9,LIGHT)+p('M12 5 V12 L17 16',stroke_width=1.3),
    "example": cube(x=7,y=15,r=5)+cube(x=17,y=7,r=5),
    "adopt-copy": p('M2 2 H14 V17 H2 Z',LIGHT)+p('M8 7 H20 V22 H8 Z',MID)+plus(14,15),
    "recovery": p('M3 22 V8 L12 2 21 8 V22 Z',LIGHT)+p('M8 11 H16 V19 H8 Z')+p('M10 5 H14'),
    "shortcuts": rectangle(2,5,20,14,LIGHT,1)+''.join(rectangle(x,y,2,2,MID) for x in [5,10,15] for y in [8,12])
                 +p('M7 16 H17'),
    "tools": cube(x=8,y=8,r=5)+p('M11 15 L19 7 M17 4 L22 9 20 12 17 9 14 12 12 10 Z',MID),
    "assembly": cube(x=8,y=15,r=6)+cube(x=17,y=6,r=5)+p('M8 9 L13 7'),
    "insert": cube(x=17,y=16,r=5)+p('M2 6 H15 V11 M11 7 L15 11 19 7'),
    "ground": cube(x=12,y=8,r=6)+p('M12 14 V19 M3 19 H21 M5 22 L8 19 M10 22 L13 19 M15 22 L18 19'),
    "fixed-joint": cube(x=6,y=7,r=4)+cube(x=18,y=17,r=4)+p('M6 11 L12 17 18 13 M10 10 L14 14',stroke_width=1.5),
    "revolute-joint": p('M4 5 H10 V20 H4 Z',MID)+p('M14 5 H20 V20 H14 Z',LIGHT)+ellipse(12,12,5,5,LIGHT)
                       +p('M12 9 V15'),
    "slider-joint": p('M2 6 H22 V11 H2 Z',LIGHT)+rectangle(8,4,8,10,MID)+p('M6 19 H18 M9 16 L6 19 9 22 M15 16 L18 19 15 22'),
}

# Related operations still have distinct assets and visible subtractive markings.
ASSETS["groove"] = ASSETS["revolve"] + rectangle(15,16,9,8,"#ffffff") + minus(19,20)
ASSETS["sweep-remove"] = ASSETS["sweep"] + rectangle(15,16,9,8,"#ffffff") + minus(19,20)
ASSETS["loft-remove"] = ASSETS["loft"] + rectangle(15,16,9,8,"#ffffff") + minus(19,20)
ASSETS["build-menu"] = cube() + rectangle(14,14,10,10,"#ffffff") + plus(19,19)
ASSETS["cut-menu"] = cube() + rectangle(14,14,10,10,"#ffffff") + minus(19,19)
ASSETS["modify-menu"] = ASSETS["fillet"] + p('M14 19 L20 13 23 16 17 22 Z',DARK)
ASSETS["patterns-menu"] = ASSETS["linear-pattern"]
ASSETS["reference-menu"] = ASSETS["plane"] + p('M12 1 V23',stroke_dasharray='2 2')
ASSETS["shape-tools-menu"] = ASSETS["boolean"]
ASSETS["new-part"] = cube() + rectangle(14,14,10,10,"#ffffff") + plus(19,19)


def main():
    root=Path(__file__).resolve().parents[1]
    output=root / "resources" / "icons"
    output.mkdir(parents=True,exist_ok=True)
    for name,inner in ASSETS.items():
        svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">\n'
             f'<g stroke="{INK}" stroke-width="0.95" stroke-linecap="round" stroke-linejoin="round">'
             f'{inner}</g>\n</svg>\n')
        (output / f"{name}.svg").write_text(svg,encoding="utf-8")
    print(f"Generated {len(ASSETS)} original SVG icons in {output}")


if __name__ == "__main__":
    main()
