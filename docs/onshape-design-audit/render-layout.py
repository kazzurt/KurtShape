"""Render the planning-only KurtShape shell schematic; does not touch app code.

Reproduce on Windows:
  C:\\Python314\\python.exe render-layout.py
Optional: --scale 1.5 --output proposed-shell-layout.png
Requires Pillow and Windows Segoe UI fonts. All sizes below are logical pixels.
The icon-only row follows the user's attached Onshape screenshot density.
Glyphs below are original schematic drawings, not edited screenshot pixels.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(output: Path, scale: float = 1.3) -> None:
    W, H = 1560, 1100
    image = Image.new("RGB", (round(W * scale), round(H * scale)), "#ffffff")
    draw = ImageDraw.Draw(image)
    fonts = Path("C:/Windows/Fonts")
    font_cache = {}
    colors = {
        "ink": "#263441", "muted": "#626e7a", "border": "#d3d9df",
        "chrome": "#edf0f3", "surface": "#ffffff", "canvas": "#f7f8f9",
        "blue": "#2867a9", "blue_fill": "#e8f2fc", "green": "#297850",
        "red": "#ac4242", "tree_selected": "#dceafb",
    }

    def S(value):
        return round(value * scale)

    def font(size=12, bold=False):
        key = size, bold
        if key not in font_cache:
            filename = "seguisb.ttf" if bold else "segoeui.ttf"
            font_cache[key] = ImageFont.truetype(str(fonts / filename), S(size))
        return font_cache[key]

    def rect(box, fill, outline=None, radius=0, width=1):
        coords = tuple(S(v) for v in box)
        if radius:
            draw.rounded_rectangle(coords, radius=S(radius), fill=fill,
                                   outline=outline, width=max(1, S(width)))
        else:
            draw.rectangle(coords, fill=fill, outline=outline, width=max(1, S(width)))

    def line(points, fill=None, width=1):
        draw.line([(S(x), S(y)) for x, y in points], fill=fill or colors["border"],
                  width=max(1, S(width)))

    def text(x, y, value, size=12, fill=None, bold=False, anchor=None):
        draw.text((S(x), S(y)), value, font=font(size, bold), fill=fill or colors["ink"],
                  anchor=anchor)

    def circle(x, y, r, fill, outline=None, width=1):
        draw.ellipse((S(x-r), S(y-r), S(x+r), S(y+r)), fill=fill,
                     outline=outline, width=max(1, S(width)))

    def chevron(x, y, direction="down", color=None):
        points = [(x-3, y-1), (x, y+2), (x+3, y-1)] if direction == "down" else [(x-1,y-3),(x+2,y),(x-1,y+3)]
        line(points, color or colors["muted"], 1.2)

    def button(x, y, w, label, primary=False, h=28):
        rect((x, y, x+w, y+h), colors["blue"] if primary else colors["surface"],
             colors["blue"] if primary else colors["border"], radius=2)
        text(x+w/2, y+h/2, label, fill="#ffffff" if primary else colors["ink"], anchor="mm")

    def check(x, y, color=None):
        line([(x-4,y),(x-1,y+3),(x+5,y-4)], color or colors["green"], 1.6)

    def cross(x, y, color=None):
        line([(x-3,y-3),(x+3,y+3)], color or colors["muted"], 1.3)
        line([(x+3,y-3),(x-3,y+3)], color or colors["muted"], 1.3)

    def icon(x, y, kind, color=None):
        c = color or "#51565b"
        light, mid, dark = "#d8dadc", "#b5b8bb", "#8c9297"

        def stroke(points, width=1.1, tint=None):
            line([(x+dx,y+dy) for dx,dy in points], tint or c, width)

        def poly(points, fill=light):
            coords=[(S(x+dx),S(y+dy)) for dx,dy in points]
            draw.polygon(coords, fill=fill)
            draw.line(coords+[coords[0]],fill=c,width=max(1,S(1)))

        def ellipse(box, fill=None, width=1):
            draw.ellipse(tuple(S(v) for v in (x+box[0],y+box[1],x+box[2],y+box[3])),
                         fill=fill, outline=c, width=max(1,S(width)))

        def cube(dx=0,dy=0,r=8):
            poly([(dx-r,dy-r/2),(dx,dy-r),(dx+r,dy-r/2),(dx,dy)],light)
            poly([(dx-r,dy-r/2),(dx,dy),(dx,dy+r),(dx-r,dy+r/2)],mid)
            poly([(dx,dy),(dx+r,dy-r/2),(dx+r,dy+r/2),(dx,dy+r)],dark)

        # Original compact CAD glyphs retain solid/face/section distinctions.
        if kind == "sketch":
            poly([(-9,7),(-5,10),(8,-3),(4,-7)],"#eeeeef")
            poly([(-9,7),(-10,11),(-5,10)],dark)
            stroke([(-10,12),(10,12)],1)
        elif kind in {"extrude", "remove"}:
            cube(0,2,8)
            if kind == "extrude":
                poly([(-3,-8),(3,-8),(3,-3),(-3,-3)],light)
                stroke([(0,-4),(0,-11),(-3,-8),(0,-11),(3,-8)],1.1)
            else:
                poly([(-3,-3),(2,-5),(5,-3),(0,0)],"#656b70")
                stroke([(-3,-10),(3,-10)],1.5)
        elif kind in {"revolve", "groove"}:
            poly([(-4,-8),(5,-8),(8,-4),(8,5),(4,8),(-4,8)],mid)
            ellipse((-7,-9,5,-4),light)
            stroke([(-8,-11),(-8,10)],1)
            draw.arc((S(x-9),S(y-3),S(x+4),S(y+11)),45,230,fill=c,width=S(1.2))
            stroke([(-9,6),(-7,10),(-3,8)])
            if kind == "groove":
                rect((x+2,y+5,x+11,y+10),colors["surface"])
                stroke([(3,8),(10,8)],1.6)
        elif kind == "sweep":
            stroke([(-8,8),(-5,8),(-4,3),(-1,-3),(4,-6),(8,-6)],6,mid)
            stroke([(-8,8),(-5,8),(-4,3),(-1,-3),(4,-6),(8,-6)],1)
            ellipse((-10,5,-5,10),light)
        elif kind == "loft":
            poly([(-4,-8),(4,-8),(9,8),(-9,8)],mid)
            ellipse((-4,-10,4,-6),light)
            ellipse((-9,5,9,10),light)
            stroke([(-4,-6),(-9,6)],1)
        elif kind == "fillet":
            poly([(-9,8),(-9,-3),(-4,-8),(7,-8),(9,-6),(9,8)],mid)
            poly([(-9,-3),(-4,-8),(7,-8),(3,-3)],light)
            draw.arc((S(x-9),S(y-8),S(x+1),S(y+2)),180,270,fill=c,width=S(1.2))
            stroke([(-4,-3),(-4,8)],1)
        elif kind == "chamfer":
            poly([(-9,8),(-9,-3),(-3,-9),(8,-9),(8,8)],mid)
            poly([(-9,-3),(-3,-9),(8,-9),(2,-3)],light)
            stroke([(2,-3),(2,8)],1)
        elif kind == "shell":
            cube(0,1,9)
            poly([(-5,-3),(0,-6),(5,-3),(0,0)],"#666d72")
            poly([(-5,-3),(0,0),(0,5),(-5,2)],light)
            poly([(0,0),(5,-3),(5,2),(0,5)],mid)
        elif kind == "draft":
            poly([(-5,-8),(4,-8),(9,8),(-9,8)],mid)
            poly([(-5,-8),(0,-10),(5,-8),(0,-5)],light)
            stroke([(0,-5),(0,8)])
        elif kind == "hole":
            cube(0,1,9)
            ellipse((-5,-6,5,1),"#62686d")
            draw.arc((S(x-5),S(y-3),S(x+5),S(y+4)),0,180,fill=c,width=S(1))
        elif kind == "move_face":
            cube(-2,2,7)
            stroke([(5,0),(11,0),(8,-3),(11,0),(8,3)],1.4)
        elif kind == "pattern":
            for dx,dy in [(-5,-5),(5,-5),(-5,5),(5,5)]:
                cube(dx,dy,4)
        elif kind == "circular_pattern":
            for dx,dy in [(-7,0),(0,-7),(7,0),(0,7)]:
                cube(dx,dy,3)
            ellipse((-2,-2,2,2),dark)
        elif kind == "mirror":
            poly([(-10,6),(-5,-3),(-2,6)],mid)
            poly([(10,6),(5,-3),(2,6)],light)
            stroke([(0,-10),(0,10)])
        elif kind == "transform":
            cube(-3,4,6)
            stroke([(1,-1),(9,-9),(4,-9),(9,-9),(9,-4)],1.4)
        elif kind == "boolean":
            cube(-3,-3,6)
            cube(3,3,6)
        elif kind == "split":
            cube(0,0,9)
            poly([(-12,4),(4,-11),(12,-4),(-4,11)],"#e2e4e5")
            stroke([(-4,11),(12,-4)],1.3)
        elif kind == "plane":
            poly([(-10,6),(-3,-7),(10,-6),(3,7)],light)
            stroke([(-11,0),(11,0)],1)
        elif kind == "datum_axis":
            stroke([(-9,8),(9,-8)],1.2)
            poly([(-7,3),(-4,6),(-1,3),(-4,0)],light)
            stroke([(-2,-7),(2,-3)],1)
        elif kind == "datum_point":
            stroke([(-9,0),(9,0)],1)
            stroke([(0,-9),(0,9)],1)
            ellipse((-3,-3,3,3),mid)
        elif kind == "fit":
            for dx, dy, sx, sy in [(-8,-8,1,1),(8,-8,-1,1),(-8,8,1,-1),(8,8,-1,-1)]:
                stroke([(dx,dy+sy*4),(dx,dy),(dx+sx*4,dy)],1.3)
            poly([(-3,3),(-3,-3),(3,-3),(3,3)],light)
        elif kind == "normal":
            poly([(-9,5),(-4,-2),(7,-2),(3,5)],light)
            stroke([(0,0),(0,-10),(-3,-7),(0,-10),(3,-7)],1.3)
        elif kind == "isometric":
            cube(0,0,9)
        elif kind == "measure":
            poly([(-10,5),(-7,9),(10,-5),(7,-9)],light)
            for t in [-6,-2,2,6]:
                stroke([(t,-t*.7),(t+2,-t*.7+3)],1)
        elif kind == "rebuild":
            draw.arc((S(x-9),S(y-9),S(x+9),S(y+9)),30,325,fill=c,width=S(1.4))
            poly([(8,-6),(8,1),(3,-3)],mid)
        elif kind == "check":
            cube(-2,0,7)
            stroke([(1,7),(4,10),(10,2)],1.8)
        elif kind in {"undo", "redo"}:
            sign = -1 if kind == "undo" else 1
            stroke([(-sign*6,5),(-sign*6,-3),(sign*6,-3),(sign*2,-7),(sign*6,-3),(sign*2,1)],1.4)
        elif kind == "save":
            poly([(-9,-9),(6,-9),(9,-6),(9,9),(-9,9)],None)
            stroke([(-5,-9),(-5,-3),(4,-3),(4,-9)],1.3)
            stroke([(-5,9),(-5,2),(5,2),(5,9)],1.3)
        elif kind == "settings":
            import math
            for angle in range(0,360,45):
                a=math.radians(angle)
                stroke([(6*math.cos(a),6*math.sin(a)),(10*math.cos(a),10*math.sin(a))],2.6)
            ellipse((-7,-7,7,7),mid)
            ellipse((-3,-3,3,3),colors["chrome"])
        else:
            raise ValueError(f"Unknown schematic glyph: {kind}")

    def badge(x, y, n):
        circle(x,y,11,colors["blue"])
        text(x,y,str(n),11,"#ffffff",True,"mm")

    # Caption explicitly distinguishes a proposal from a current application capture.
    text(60, 31, "KurtShape · Onshape-style shell direction", 25, bold=True)
    text(60, 69, "Proposed layout — schematic, not a running build", 17, colors["blue"], True)
    text(1500, 76, "Plate example · all content and states illustrative", 12, colors["muted"], anchor="ra")

    X,Y,R,B = 60,118,1500,898
    WORK_TOP, WORK_BOTTOM = 198,840
    LEFT = X+250
    rect((X,Y,R,B), colors["surface"], colors["border"])
    rect((X,Y,R,Y+44), colors["chrome"])
    rect((X,Y+44,R,WORK_TOP), "#f4f6f8")
    line([(X,Y+44),(R,Y+44)])
    line([(X,WORK_TOP),(R,WORK_TOP)])

    # Light document header: local truth, identity and essential actions.
    text(76,131,"KurtShape",14,bold=True)
    for yy in [135,141,147]:
        line([(190,yy),(205,yy)],"#51565b",1.7)
    line([(224,128),(224,152)])
    text(239,130,"Plate example",14,bold=True)
    text(351,134,"Part Studio",11,colors["muted"])
    text(448,134,"Unsaved changes · local FCStd",11,colors["muted"])
    badge(701,141,1)
    rect((1398,127,1426,155),colors["blue"],radius=2)
    icon(1412,141,"save","#ffffff")
    icon(1450,141,"settings")
    chevron(1474,141)

    # User-requested icon-only toolsets: 29 CAD/history glyphs in 32px targets.
    # Each capability is present in the installed feature catalog or shell.
    # No visible command names, category labels or text More button.
    groups = [
        ["undo","redo"],
        ["sketch","extrude","remove","revolve","sweep","loft"],
        ["fillet","chamfer","shell","draft","groove","move_face"],
        ["pattern","circular_pattern","mirror","transform","boolean","split"],
        ["plane","datum_axis","datum_point"],
        ["fit","normal","isometric","measure","rebuild","check"],
    ]
    target_left=74
    for gi,toolset in enumerate(groups):
        for kind in toolset:
            tx=target_left+16
            if kind == "fillet":
                rect((target_left,166,target_left+31,198),colors["blue_fill"],radius=2)
            icon(tx,182,kind,colors["blue"] if kind == "fillet" else None)
            target_left+=32
        if gi > 0:
            chevron(target_left+3,183)
            target_left+=10
        if gi < len(groups)-1:
            line([(target_left+6,170),(target_left+6,195)])
            target_left+=12
    rect((1158,168,1481,196),"#e9edf1",colors["border"],radius=2)
    text(1170,175,"Search tools…",11,colors["muted"])
    text(1449,176,"Alt+C",10,colors["muted"],anchor="ra")

    # Fixed-width history with independently resizable parts region.
    rect((X,WORK_TOP,LEFT,WORK_BOTTOM),"#ffffff")
    line([(LEFT,WORK_TOP),(LEFT,WORK_BOTTOM)])
    text(76,217,"Features (3)",12,bold=True)
    rect((76,246,294,274),"#ffffff",colors["border"],radius=2)
    text(87,252,"Filter features",11,colors["muted"])
    text(84,292,"Origin",12)
    chevron(75,301,"right")
    tree = [("Plane 1","plane"),("Sketch 1","sketch"),("Extrude 1","extrude")]
    for i,(label,kind) in enumerate(tree):
        yy=334+i*27
        if label == "Extrude 1":
            rect((X+1,yy-5,LEFT-1,yy+20),colors["tree_selected"])
        icon(86,yy+7,kind)
        text(104,yy,label,12)
    line([(76,423),(293,423)],colors["blue"],2)
    circle(83,423,3,colors["blue"])
    text(92,432,"End of history",10,colors["muted"])
    rect((X+1,638,LEFT-1,646),"#eef1f4")
    for dy in [0,3]:
        line([(167,640+dy),(200,640+dy)],"#a6b0b9")
    badge(285,641,4)
    text(76,662,"Parts (1)",12,bold=True)
    rect((76,691,294,727),"#f3f7fb",colors["border"],radius=2)
    icon(89,709,"shell")
    text(106,700,"Plate",12)
    text(241,702,"Active",10,colors["blue"],True)
    text(76,742,"Active target for new features",11,colors["muted"])

    # Real geometry remains native: no fabricated model illustration.
    rect((LEFT+1,WORK_TOP+1,R-1,WORK_BOTTOM-1),colors["canvas"])
    badge(1128,216,2)
    text(1012,498,"Native FreeCAD viewport",22,"#818d98",False,"mm")
    text(1012,533,"Quiet canvas · native model, camera and picking retained",12,colors["muted"],anchor="mm")
    text(1440,227,"View",11,colors["muted"])
    rect((1399,250,1468,319),None,"#b8c1c9",radius=3)
    text(1434,284,"TOP",11,colors["muted"],anchor="mm")
    text(1404,337,"Native view cube",10,colors["muted"])
    line([(1465,804),(1478,804)],"#9aa7b0")
    line([(1465,804),(1465,789)],"#9aa7b0")

    # Compact bounded-height modeless editor defaults beside history, as in Onshape.
    PX,PY,PW,PH = 326,218,300,350
    rect((PX+2,PY+3,PX+PW+2,PY+PH+3),"#e2e6eb",radius=3)
    rect((PX,PY,PX+PW,PY+PH),colors["surface"],"#bbc6d2",radius=3)
    rect((PX+1,PY+1,PX+PW-1,PY+39),"#f5f7f9",radius=2)
    line([(PX,PY+40),(PX+PW,PY+40)])
    text(PX+13,PY+12,"Fillet",13,bold=True)
    rect((PX+121,PY+7,PX+211,PY+33),"#ffffff",colors["border"],radius=2)
    check(PX+134,PY+20)
    text(PX+146,PY+12,"Confirm",11)
    rect((PX+217,PY+7,PX+287,PY+33),"#ffffff",colors["border"],radius=2)
    cross(PX+229,PY+20,colors["red"])
    text(PX+239,PY+12,"Cancel",11)
    text(PX+13,PY+55,"Edges",12,bold=True)
    text(PX+270,PY+58,"1 selected",10,colors["muted"],anchor="ra")
    rect((PX+13,PY+82,PX+287,PY+121),colors["blue_fill"],"#72a0cd",radius=2)
    line([(PX+13,PY+121),(PX+287,PY+121)],colors["blue"],2)
    text(PX+24,PY+93,"Pick edges in viewport",12,colors["blue"])
    rect((PX+13,PY+129,PX+287,PY+160),"#f5f8fb",colors["border"],radius=2)
    text(PX+24,PY+137,"Extrude 1 · Edge4",11)
    cross(PX+272,PY+144)
    text(PX+13,PY+184,"Radius",12)
    rect((PX+98,PY+175,PX+287,PY+206),"#ffffff",colors["border"],radius=2)
    text(PX+110,PY+183,"1.00 mm",12)
    text(PX+13,PY+224,"Advanced options",11,colors["muted"])
    chevron(PX+275,PY+232,"right")
    line([(PX+13,PY+256),(PX+287,PY+256)])
    check(PX+22,PY+280)
    text(PX+37,PY+272,"Preview current",11,colors["green"],True)
    text(PX+13,PY+298,"Ready to confirm · model remains unchanged",10,colors["muted"])
    badge(PX+PW-12,PY+PH+17,3)

    # These are local document tabs, not fictional cloud workspaces.
    rect((LEFT,840,R-1,870),"#edf0f3")
    rect((LEFT,840,LEFT+185,870),"#ffffff")
    line([(LEFT,840),(LEFT+185,840)],colors["blue"],2)
    text(LEFT+16,848,"Plate example *",12,colors["blue"])
    cross(LEFT+168,855)
    text(LEFT+207,848,"+ New local document",11,colors["muted"])
    text(1294,849,"Local FCStd documents",10,colors["muted"])
    rect((X+1,870,R-1,B-1),"#f0f3f6")
    line([(X,870),(R,870)])
    text(76,877,"mm",11,colors["muted"])
    text(129,877,"Build current",11,colors["muted"])
    text(LEFT+16,877,"Fillet preview · ready",11,colors["green"])
    text(1374,877,"Diagnostics (0)",11,colors["muted"])
    badge(1260,884,5)

    # Outside-frame legend documents decisions rather than pretending to be UI.
    text(60,923,"What changes in this proposal",16,bold=True)
    entries = [
        (1,"Document hierarchy","File actions consolidate; document identity and local save truth stay visible."),
        (2,"Dense icon-only toolsets","29 CAD/history glyphs in 32px targets; names and shortcuts via tooltip/help in the app."),
        (3,"Explicit edit state","300px movable editor beside history; active blue picker, removable reference, inline readiness."),
        (4,"Scalable left panel","250px history/parts region with independent split; active target is separate from selection."),
        (5,"Local navigation and status","Tabs represent local documents; units, build state and diagnostics have stable homes."),
    ]
    for i,(n,title,detail) in enumerate(entries):
        yy=960+i*23
        badge(72,yy+7,n)
        text(92,yy,title+" — ",11,bold=True)
        title_width=draw.textlength(title+" — ",font=font(11,True))/scale
        text(92+title_width,yy,detail,11,colors["muted"])
    text(1500,1078,"Planning schematic · proposed logical dimensions and tokens · no application code changed",10,colors["muted"],anchor="ra")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("proposed-shell-layout.png"))
    parser.add_argument("--scale", type=float, default=1.3)
    args = parser.parse_args()
    if not 0.5 <= args.scale <= 4:
        parser.error("--scale must be between 0.5 and 4")
    render(args.output, args.scale)
    print(args.output.resolve())
