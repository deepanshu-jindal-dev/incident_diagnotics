#!/usr/bin/env python3
"""Build the Incident Diagnostics Engine deck (16 slides) on the corporate
template. Bullet text goes in template placeholders (inherits theme fonts);
the full narration goes in speaker notes; diagram placeholder boxes (A-H)
mark where hand-drawn diagrams will be added."""
import math
from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.dml import MSO_THEME_COLOR

TEMPLATE = "/Users/deepanshu.jindal1/Downloads/Demoes_Rajesh_Visit_June_2026.pptx"
OUT = "/Users/deepanshu.jindal1/Downloads/Incident_Diagnostics_video.pptx"
_IMG_ERROR = "/Users/deepanshu.jindal1/Downloads/demo_error.png"
_IMG_DIAG = "/Users/deepanshu.jindal1/Downloads/demo_diagnosis.png"
_IMG_CODE = "/Users/deepanshu.jindal1/Downloads/slide4_code.png"  # slide 4 source screenshot

prs = Presentation(TEMPLATE)
master = prs.slide_masters[0]
LAYOUTS = {l.name: l for l in master.slide_layouts}

# Drop the template's existing slides (parts + rels), keep masters/layouts.
sldIdLst = prs.slides._sldIdLst
for sldId in list(sldIdLst):
    prs.part.drop_rel(sldId.get(qn("r:id")))
    sldIdLst.remove(sldId)


def add(layout_name):
    return prs.slides.add_slide(LAYOUTS[layout_name])


def ph(slide, idx):
    for p in slide.placeholders:
        if p.placeholder_format.idx == idx:
            return p
    raise KeyError(f"no placeholder idx={idx}")


def set_text(placeholder, value):
    tf = placeholder.text_frame
    if isinstance(value, str):
        tf.text = value
        return
    tf.text = value[0]
    for line in value[1:]:
        tf.add_paragraph().text = line


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def add_verdict(placeholder, text, color):
    """Append a blank line + a bold accent-colored closing line to a card,
    so the column doesn't read as half-empty."""
    tf = placeholder.text_frame
    tf.add_paragraph()
    p = tf.add_paragraph()
    r = p.add_run()
    r.text = text
    r.font.bold = True
    r.font.size = Pt(13)
    r.font.name = "ServiceNow Sans Medium"
    r.font.color.rgb = color


def _no_bullet(p):
    """Strip any inherited bullet from a placeholder paragraph."""
    pPr = p._p.get_or_add_pPr()
    for tag in ("a:buChar", "a:buAutoNum"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)
    if pPr.find(qn("a:buNone")) is None:
        pPr.append(pPr.makeelement(qn("a:buNone"), {}))


def _fill_phased(placeholder, groups, accent, item_color=RGBColor(0xC9, 0xD2, 0xDE)):
    """Fill a column placeholder with phase sub-headers + their items.

    groups = [("Phase 1 · name", ["item", "item"]), ...]"""
    tf = placeholder.text_frame
    tf.word_wrap = True
    para_idx = 0
    for gi, (header, items) in enumerate(groups):
        hp = tf.paragraphs[0] if para_idx == 0 else tf.add_paragraph()
        para_idx += 1
        if gi > 0:
            hp.space_before = Pt(9)
        _no_bullet(hp)
        hr = hp.add_run()
        hr.text = header
        hr.font.bold = True
        hr.font.size = Pt(12.5)
        hr.font.name = _B_FONT
        hr.font.color.rgb = accent
        for it in items:
            ip = tf.add_paragraph()
            para_idx += 1
            _no_bullet(ip)
            ir = ip.add_run()
            ir.text = "•  " + it
            ir.font.size = Pt(10)
            ir.font.name = _B_FONT
            ir.font.color.rgb = item_color


def _stat_card(slide, x, y, w, h, value, label, accent):
    """A big-number metric card for the performance slide."""
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(x), Inches(y), Inches(w), Inches(h))
    card.fill.solid()
    card.fill.fore_color.rgb = _B_CHIP
    card.line.color.rgb = accent
    card.line.width = Pt(1.25)
    card.shadow.inherit = False
    tf = card.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = value
    r.font.bold = True
    r.font.size = Pt(28)
    r.font.name = _B_FONT
    r.font.color.rgb = accent
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.CENTER
    p2.space_before = Pt(4)
    r2 = p2.add_run()
    r2.text = label
    r2.font.size = Pt(11)
    r2.font.name = _B_FONT
    r2.font.color.rgb = _B_MUTED


def build_diagram_index(slide):
    items = [
        ("The problem", "why a stack trace is hard to trace"),
        ("The core insight", "give the LLM a map of code, not raw code"),
        ("System architecture", "build offline, diagnose in seconds"),
        ("Feature A · Graph Builder", "code → knowledge graph"),
        ("Feature B · Reasoning Engine", "the five diagnosis phases"),
        ("Demo, tests & performance", "a real incident, end to end"),
        ("Limitations & roadmap", "what's next"),
    ]
    y0, step, h = 2.1, 0.68, 0.56
    bx, bw = 0.9, 0.56
    for i, (title, sub) in enumerate(items):
        y = y0 + i * step
        _chip(slide, bx, y, bw, h, str(i + 1), _B_GREEN, _B_NAVY, None)
        tb = slide.shapes.add_textbox(Inches(bx + bw + 0.32), Inches(y - 0.05),
                                      Inches(10.5), Inches(h + 0.1))
        tf = tb.text_frame
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = title
        r.font.size = Pt(16)
        r.font.bold = True
        r.font.name = _B_FONT
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r2 = p.add_run()
        r2.text = "      " + sub
        r2.font.size = Pt(12)
        r2.font.name = _B_FONT
        r2.font.color.rgb = _B_MUTED


def build_diagram_perf(slide):
    metrics = [
        ("—", "Build full graph"),
        ("—", "Diagnose one incident"),
        ("—", "Incremental update / file"),
        ("—", "Save graph → pickle"),
        ("—", "Load graph ← pickle"),
        ("—", "TF-IDF index build"),
    ]
    X0, ROW_W, cols, gap = 0.6, 12.13, 3, 0.4
    cw = (ROW_W - gap * (cols - 1)) / cols
    ch, y0, ystep = 1.9, 2.55, 2.15
    for i, (value, label) in enumerate(metrics):
        row, col = i // cols, i % cols
        x = X0 + col * (cw + gap)
        y = y0 + row * ystep
        _stat_card(slide, x, y, cw, ch, value, label, _B_GREEN)
    _caption(slide, "Merged Flask · Werkzeug · Jinja graph  —  2,909 nodes · "
             "12,227 edges  ·  pickle — MB on disk", 0.6, 6.95, 12.13)


def diagram_box(slide, label, desc, left=1.2, top=2.3, width=10.93, height=4.5):
    box = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(left), Inches(top), Inches(width), Inches(height))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xF2, 0xF2, 0xF2)
    box.line.color.rgb = RGBColor(0xB7, 0xB7, 0xB7)
    box.line.width = Pt(1)
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p0 = tf.paragraphs[0]
    p0.alignment = PP_ALIGN.CENTER
    r = p0.add_run()
    r.text = f"◆  DIAGRAM {label}"
    r.font.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    p1 = tf.add_paragraph()
    p1.alignment = PP_ALIGN.CENTER
    r1 = p1.add_run()
    r1.text = desc
    r1.font.size = Pt(12)
    r1.font.italic = True
    r1.font.color.rgb = RGBColor(0x70, 0x70, 0x70)
    return box


# ── Native diagram A: "raw code → knowledge graph" ─────────────────────
_GNODE_COLOR = {
    "function": RGBColor(0x2E, 0x75, 0xB6),   # blue
    "class":    RGBColor(0x37, 0x9D, 0x4F),   # green
    "module":   RGBColor(0xE0, 0x86, 0x1A),   # orange
}
_GEDGE_COLOR = {
    "CALLS":   RGBColor(0xCF, 0x24, 0x2D),    # red
    "RAISES":  RGBColor(0xE0, 0x86, 0x1A),    # orange
    "IMPORTS": RGBColor(0x2E, 0x75, 0xB6),    # blue
}
_NODE_W, _NODE_H = 2.25, 0.62
_RX, _RY = _NODE_W / 2, _NODE_H / 2
_WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _caption(slide, text, left, top, width, color=RGBColor(0xC9, 0xD2, 0xDE)):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(0.3))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run()
    r.text = text
    r.font.size = Pt(12)
    r.font.bold = True
    r.font.color.rgb = color


def _node(slide, cx, cy, label, ntype):
    sh = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(cx - _RX), Inches(cy - _RY),
        Inches(_NODE_W), Inches(_NODE_H))
    sh.fill.solid()
    sh.fill.fore_color.rgb = _GNODE_COLOR.get(ntype, RGBColor(0x80, 0x80, 0x80))
    sh.line.color.rgb = _WHITE
    sh.line.width = Pt(1.0)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = _WHITE
    return sh


def _edge(slide, a, b, rel):
    """Connector from node center a to node center b, trimmed to the rounded-
    rectangle boundary, with an arrowhead and a colored relationship pill."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    eps = 1e-6
    t = min(_RX / abs(ux) if abs(ux) > eps else 1e9,
            _RY / abs(uy) if abs(uy) > eps else 1e9)
    gap = 0.06
    sx, sy = ax + ux * (t + gap), ay + uy * (t + gap)
    ex, ey = bx - ux * (t + gap), by - uy * (t + gap)
    color = _GEDGE_COLOR.get(rel, RGBColor(0xB0, 0xB0, 0xB0))

    conn = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(sx), Inches(sy), Inches(ex), Inches(ey))
    conn.line.color.rgb = color
    conn.line.width = Pt(2.25)
    conn.shadow.inherit = False
    ln = conn.line._get_or_add_ln()
    ln.append(ln.makeelement(qn("a:tailEnd"),
                             {"type": "triangle", "w": "med", "len": "med"}))

    mx, my = (sx + ex) / 2, (sy + ey) / 2
    lbl = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Inches(mx - 0.48), Inches(my - 0.13),
                                 Inches(0.96), Inches(0.26))
    lbl.fill.solid()
    lbl.fill.fore_color.rgb = _WHITE
    lbl.line.color.rgb = color
    lbl.line.width = Pt(0.75)
    lbl.shadow.inherit = False
    tfl = lbl.text_frame
    tfl.margin_top = Inches(0.0)
    tfl.margin_bottom = Inches(0.0)
    p = tfl.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = rel
    r.font.size = Pt(9)
    r.font.bold = True
    r.font.color.rgb = color


def _legend(slide, left, top):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(6.0), Inches(0.3))
    p = tb.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    for color, name, tail in (
        (_GNODE_COLOR["function"], "function", "      "),
        (_GNODE_COLOR["class"], "class", "      "),
        (_GNODE_COLOR["module"], "module", ""),
    ):
        dot = p.add_run()
        dot.text = "● "
        dot.font.size = Pt(11)
        dot.font.color.rgb = color
        lab = p.add_run()
        lab.text = name + tail
        lab.font.size = Pt(10)
        lab.font.color.rgb = RGBColor(0xC9, 0xD2, 0xDE)


_SLIDE4_CODE = '''import os
from jinja2 import Template
from .loaders import loader
from .errors import TemplateNotFound

DEFAULT_ENCODING = "utf-8"

def render_template(name, **context):
    source = get_source(name)
    template = Template(source)
    return template.render(**context)

def get_source(name):
    if name not in loader.cache:
        path = loader.resolve(name)
        if not os.path.exists(path):
            raise TemplateNotFound(name)
        loader.cache[name] = _read(path)
    return loader.cache[name]

def _read(path):
    with open(path, encoding=DEFAULT_ENCODING) as f:
        return f.read()'''


def _render_python_code(tf, code, size=9):
    """Fill a text frame with syntax-highlighted Python as native coloured runs.

    Uses Pygments' Monokai palette to colour one run per token; falls back to
    flat light-grey text if Pygments is unavailable."""
    _DEFAULT = RGBColor(0xF8, 0xF8, 0xF2)
    try:
        from pygments.lexers import PythonLexer
        from pygments.styles import get_style_by_name
        style = get_style_by_name("monokai")
        tokens = list(PythonLexer().get_tokens(code))
    except Exception:
        tokens = None

    def colour(ttype):
        try:
            c = style.style_for_token(ttype).get("color")
            return RGBColor.from_string(c) if c else _DEFAULT
        except Exception:
            return _DEFAULT

    if tokens is None:                      # fallback: monochrome
        for i, line in enumerate(code.split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.line_spacing = 1.0
            r = p.add_run()
            r.text = line or " "
            r.font.name = "Consolas"
            r.font.size = Pt(size)
            r.font.color.rgb = RGBColor(0xEA, 0xEA, 0xEA)
        return

    # Split token stream into lines (token values may contain newlines).
    line_segs = [[]]
    for ttype, val in tokens:
        parts = val.split("\n")
        for k, part in enumerate(parts):
            if k > 0:
                line_segs.append([])
            if part:
                line_segs[-1].append((ttype, part))
    if line_segs and not line_segs[-1]:     # drop trailing newline's empty line
        line_segs.pop()

    for i, segs in enumerate(line_segs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.0
        if not segs:
            r = p.add_run()
            r.text = " "
            r.font.name = "Consolas"
            r.font.size = Pt(size)
            continue
        for ttype, text in segs:
            r = p.add_run()
            r.text = text
            r.font.name = "Consolas"
            r.font.size = Pt(size)
            r.font.color.rgb = colour(ttype)


def build_diagram_a(slide):
    # ── Left: an editor-style panel with the raw source ─────────────────
    _caption(slide, "RAW SOURCE CODE", 0.55, 1.98, 4.8)
    PANEL_L, PANEL_T, PANEL_W = 0.5, 2.32, 4.9
    panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                   Inches(PANEL_L), Inches(PANEL_T),
                                   Inches(PANEL_W), Inches(4.05))
    panel.fill.solid()
    panel.fill.fore_color.rgb = RGBColor(0x1E, 0x1E, 0x1E)
    panel.line.color.rgb = RGBColor(0x4A, 0x4A, 0x4A)
    panel.line.width = Pt(1)
    panel.shadow.inherit = False
    # Source rendered as NATIVE syntax-highlighted text (crisp vector glyphs,
    # one coloured run per token) — same native-text approach as the rest of
    # the deck, instead of a flat screenshot.
    tf = panel.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Inches(0.16)
    tf.margin_top = Inches(0.5)
    _render_python_code(tf, _SLIDE4_CODE)

    # Editor title bar + traffic-light dots + filename, drawn over the panel top.
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                 Inches(PANEL_L), Inches(PANEL_T),
                                 Inches(PANEL_W), Inches(0.34))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor(0x33, 0x33, 0x33)
    bar.line.fill.background()
    bar.shadow.inherit = False
    for i, dot_color in enumerate((0xFF5F56, 0xFFBD2E, 0x27C93F)):
        d = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(PANEL_L + 0.16 + i * 0.20),
            Inches(PANEL_T + 0.11), Inches(0.12), Inches(0.12))
        d.fill.solid()
        d.fill.fore_color.rgb = RGBColor((dot_color >> 16) & 0xFF,
                                         (dot_color >> 8) & 0xFF, dot_color & 0xFF)
        d.line.fill.background()
        d.shadow.inherit = False
    fn = slide.shapes.add_textbox(Inches(PANEL_L + 0.85), Inches(PANEL_T + 0.04),
                                  Inches(2.6), Inches(0.26))
    fr = fn.text_frame.paragraphs[0].add_run()
    fr.text = "templating.py"
    fr.font.name = "Consolas"
    fr.font.size = Pt(10)
    fr.font.color.rgb = RGBColor(0xB5, 0xB5, 0xB5)

    # ── Middle: transform arrow ─────────────────────────────────────────
    arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW,
                                   Inches(5.55), Inches(4.0), Inches(0.95), Inches(0.7))
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = RGBColor(0x9A, 0x9A, 0x9A)
    arrow.line.fill.background()
    arrow.shadow.inherit = False

    # ── Right: the same code as a clean labeled graph ───────────────────
    _caption(slide, "KNOWLEDGE GRAPH  —  what the engine sees", 6.7, 1.98, 6.3)
    nodes = {
        "render_template":  (8.05, 3.0, "function"),
        "Template":         (11.7, 3.0, "class"),
        "get_source":       (9.7, 4.5, "function"),
        "loader":           (8.05, 6.0, "module"),
        "TemplateNotFound": (11.7, 6.0, "class"),
    }
    edges = [
        ("render_template", "get_source", "CALLS"),
        ("render_template", "Template", "CALLS"),
        ("get_source", "loader", "IMPORTS"),
        ("get_source", "TemplateNotFound", "RAISES"),
    ]
    # Draw edges first, then nodes on top (hides line ends behind the nodes).
    for src, dst, rel in edges:
        _edge(slide, nodes[src][:2], nodes[dst][:2], rel)
    for name, (cx, cy, ntype) in nodes.items():
        _node(slide, cx, cy, name, ntype)

    _legend(slide, 6.7, 6.55)


# ── Native diagram B: two rows of chips on the dark canvas ─────────────
_B_NAVY = RGBColor(0x03, 0x2D, 0x42)    # slide background navy (theme dk2)
_B_CHIP = RGBColor(0x0E, 0x3D, 0x54)    # slightly elevated card surface
_B_BLUE = RGBColor(0x52, 0xB8, 0xFF)    # accent3
_B_GREEN = RGBColor(0x63, 0xDF, 0x4E)   # accent1
_B_MUTED = RGBColor(0x9F, 0xB2, 0xC0)   # muted caption grey
_B_FONT = "ServiceNow Sans Medium"


def _arrow_end(conn):
    ln = conn.line._get_or_add_ln()
    ln.append(ln.makeelement(qn("a:tailEnd"),
                             {"type": "triangle", "w": "med", "len": "med"}))


def _connect(slide, x1, y1, x2, y2, color, width=1.5, dash=False, arrow=True):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                   Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    c.shadow.inherit = False
    ln = c.line._get_or_add_ln()
    if dash:
        ln.append(ln.makeelement(qn("a:prstDash"), {"val": "dash"}))
    if arrow:
        _arrow_end(c)
    return c


def _chip(slide, x, y, w, h, label, fill, text_color, border):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if border is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = border
        sh.line.width = Pt(1.25)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.size = Pt(10.5)
    r.font.bold = True
    r.font.name = _B_FONT
    r.font.color.rgb = text_color
    return sh


def _phase_label(slide, x, y, name, accent, sub, width=9.0):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(width), Inches(0.34))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run()
    r.text = name
    r.font.size = Pt(13)
    r.font.bold = True
    r.font.name = _B_FONT
    r.font.color.rgb = accent
    r2 = p.add_run()
    r2.text = "     " + sub
    r2.font.size = Pt(11)
    r2.font.name = _B_FONT
    r2.font.color.rgb = _B_MUTED


def _chip_row(slide, labels, y, h, accent, gap, highlight=None):
    X0, ROW_W = 0.6, 12.13
    n = len(labels)
    box_w = (ROW_W - gap * (n - 1)) / n
    spans = []
    for i, lab in enumerate(labels):
        bx = X0 + i * (box_w + gap)
        if highlight and lab == highlight:
            _chip(slide, bx, y, box_w, h, lab, accent, _B_NAVY, None)
        else:
            _chip(slide, bx, y, box_w, h, lab, _B_CHIP, accent, accent)
        spans.append((bx, bx + box_w))
        if i > 0:
            _connect(slide, spans[i - 1][1], y + h / 2, bx, y + h / 2,
                     accent, width=1.6)
    return spans


def build_diagram_b(slide):
    # Build row (top): elevated navy chips, blue accents; graph highlighted.
    _phase_label(slide, 0.6, 2.0, "BUILD PHASE", _B_BLUE, "offline · runs once")
    build = _chip_row(slide,
                      ["Repos", "AST Parser", "Entity Resolver", "Enrichment",
                       "Knowledge Graph"],
                      2.42, 0.72, _B_BLUE, gap=0.45, highlight="Knowledge Graph")
    # Diagnosis row (bottom): elevated navy chips, green accents.
    _phase_label(slide, 0.6, 4.35, "DIAGNOSIS PHASE", _B_GREEN,
                 "per incident · runs in seconds")
    diag = _chip_row(slide,
                     ["Stack Trace", "Diagnosis Engine", "Root Cause"],
                     4.77, 0.72, _B_GREEN, gap=0.55, highlight="Diagnosis Engine")

    # "pre-built graph" handoff: a clean arrow from the Knowledge Graph chip
    # down to the Diagnosis Engine (the box that diagram D expands).
    gl, gr = build[-1]
    gx = (gl + gr) / 2
    tl, tr = diag[1]
    tx = (tl + tr) / 2
    _connect(slide, gx, 3.14, tx, 4.66, _B_BLUE, width=2.5)
    midx = (gx + tx) / 2
    pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(midx - 0.85), Inches(3.63), Inches(1.7),
                                  Inches(0.3))
    pill.fill.solid()
    pill.fill.fore_color.rgb = _B_NAVY
    pill.line.color.rgb = _B_BLUE
    pill.line.width = Pt(1.0)
    pill.shadow.inherit = False
    pp = pill.text_frame.paragraphs[0]
    pp.alignment = PP_ALIGN.CENTER
    pr = pp.add_run()
    pr.text = "pre-built graph"
    pr.font.size = Pt(10)
    pr.font.bold = True
    pr.font.name = _B_FONT
    pr.font.color.rgb = _B_BLUE


# ── Native diagram C: parser pipeline + 9-relationship catalog ─────────
def build_diagram_c(slide):
    # Top: the from-scratch parser pipeline (blue), ending in the Graph.
    _phase_label(slide, 0.6, 1.95, "THE PIPELINE", _B_BLUE,
                 "tokenize → parse → walk")
    _chip_row(slide,
              ["Source code", "Tokenizer", "Parser", "AST Walker", "Graph"],
              2.4, 0.72, _B_BLUE, gap=0.45, highlight="Graph")

    # Centered "produces" arrow into the relationship catalog.
    _connect(slide, 6.665, 3.22, 6.665, 3.68, _B_BLUE, width=2.0)
    lbl = slide.shapes.add_textbox(Inches(6.85), Inches(3.3), Inches(1.6), Inches(0.3))
    lr = lbl.text_frame.paragraphs[0].add_run()
    lr.text = "produces"
    lr.font.size = Pt(10)
    lr.font.italic = True
    lr.font.name = _B_FONT
    lr.font.color.rgb = _B_MUTED

    # Bottom: the 9 typed relationships as a clean 3x3 grid of pills (green).
    _phase_label(slide, 0.6, 3.8, "9 TYPED RELATIONSHIPS", _B_GREEN,
                 "every call, import, inheritance, raise & catch")
    rels = ["CALLS", "IMPORTS", "EXTENDS",
            "RAISES", "CATCHES", "CONTAINS",
            "DECORATES", "INSTANTIATES", "IMPLEMENTS"]
    cols, pill_w, pill_h, gap_x, gap_y = 3, 3.0, 0.5, 0.4, 0.16
    x0 = (13.33 - (cols * pill_w + (cols - 1) * gap_x)) / 2
    y0 = 4.26
    for i, rel in enumerate(rels):
        rr, cc = divmod(i, cols)
        _chip(slide, x0 + cc * (pill_w + gap_x), y0 + rr * (pill_h + gap_y),
              pill_w, pill_h, rel, _B_CHIP, _B_GREEN, _B_GREEN)


# ── Native diagram GB: graph-builder feature cards (2×3 grid) ──────────
def _feature_card(slide, x, y, w, h, title, desc, accent):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  Inches(x), Inches(y), Inches(w), Inches(h))
    card.fill.solid()
    card.fill.fore_color.rgb = _B_CHIP
    card.line.color.rgb = accent
    card.line.width = Pt(1.25)
    card.shadow.inherit = False
    tf = card.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Inches(0.2)
    tf.margin_right = Inches(0.2)
    tf.margin_top = Inches(0.16)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.size = Pt(13)
    r.font.bold = True
    r.font.name = _B_FONT
    r.font.color.rgb = accent
    p2 = tf.add_paragraph()
    p2.space_before = Pt(5)
    r2 = p2.add_run()
    r2.text = desc
    r2.font.size = Pt(10)
    r2.font.name = _B_FONT
    r2.font.color.rgb = _B_MUTED


def build_diagram_gb(slide):
    _phase_label(slide, 0.6, 2.0, "WHAT THE GRAPH BUILDER GIVES YOU", _B_BLUE,
                 "beyond a single-file parse", width=12.13)
    feats = [
        ("Multi-repo support",
         "Merge many codebases — local paths or remote Git URLs — into one "
         "unified graph, so a call that crosses repo boundaries is still a "
         "first-class edge."),
        ("Graph updates",
         "Incremental: when files change, only those files' nodes are removed "
         "and reprocessed (git-HEAD tracked) — no full rebuild of the graph."),
        ("Enrichment",
         "Every node carries TF-IDF semantic vectors for search and git "
         "history for recency — who last changed it, and when."),
    ]
    X0, ROW_W, cols, gap = 0.6, 12.13, 3, 0.35
    cw = (ROW_W - gap * (cols - 1)) / cols
    ch, y0 = 2.7, 3.2
    for i, (title, desc) in enumerate(feats):
        x = X0 + i * (cw + gap)
        _feature_card(slide, x, y0, cw, ch, title, desc, _B_BLUE)


# ── Native diagram D: the 5 phases inside the Diagnosis Engine ─────────
def build_diagram_d(slide):
    _phase_label(slide, 0.6, 2.05, "INSIDE THE DIAGNOSIS ENGINE", _B_GREEN,
                 "five phases, run in sequence")
    phases = [
        ("1 · Parse", "error type, message,\nframes & keywords"),
        ("2 · Locate", "find the crash-site\nnode in the graph"),
        ("3 · Traverse", "bidirectional BFS\n+ candidate scoring"),
        ("4 · Verify", "3 structural checks\n(anti-hallucination)"),
        ("5 · Explain", "LLM writes up\nthe verified result"),
    ]
    X0, ROW_W, n, gap = 0.6, 12.13, 5, 0.5
    box_w = (ROW_W - gap * (n - 1)) / n
    y, h = 2.85, 0.8
    spans = []
    for i, (name, desc) in enumerate(phases):
        x = X0 + i * (box_w + gap)
        if i == 3:  # Verify — highlighted as the most important phase
            _chip(slide, x, y, box_w, h, name, _B_GREEN, _B_NAVY, None)
        else:
            _chip(slide, x, y, box_w, h, name, _B_CHIP, _B_GREEN, _B_GREEN)
        spans.append((x, x + box_w))
        if i > 0:
            _connect(slide, spans[i - 1][1], y + h / 2, x, y + h / 2,
                     _B_GREEN, 1.6)
        db = slide.shapes.add_textbox(Inches(x), Inches(y + h + 0.14),
                                      Inches(box_w), Inches(0.75))
        dtf = db.text_frame
        dtf.word_wrap = True
        for j, line in enumerate(desc.split("\n")):
            p = dtf.paragraphs[0] if j == 0 else dtf.add_paragraph()
            p.alignment = PP_ALIGN.CENTER
            rr = p.add_run()
            rr.text = line
            rr.font.size = Pt(9.5)
            rr.font.name = _B_FONT
            rr.font.color.rgb = _B_MUTED

    # "most important" tag under the Verify phase.
    vx0, vx1 = spans[3]
    tag = slide.shapes.add_textbox(Inches(vx0), Inches(y + h + 0.92),
                                   Inches(vx1 - vx0), Inches(0.3))
    tp = tag.text_frame.paragraphs[0]
    tp.alignment = PP_ALIGN.CENTER
    tr = tp.add_run()
    tr.text = "★ most important"
    tr.font.size = Pt(10)
    tr.font.bold = True
    tr.font.name = _B_FONT
    tr.font.color.rgb = _B_GREEN
    # bottom "Phases 1–5 …" pointer removed per user edit


# ── Native diagram E: bidirectional-BFS traversal with scoring + pruning ──
_E_AMBER = RGBColor(0xE0, 0x86, 0x1A)
_E_DIM = RGBColor(0x6E, 0x82, 0x90)


def _tnode(slide, cx, cy, w, h, name, sub, fill, name_color, sub_color, border):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(cx - w / 2), Inches(cy - h / 2),
                                Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if border is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = border
        sh.line.width = Pt(1.25)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = name
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.name = _B_FONT
    r.font.color.rgb = name_color
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run()
    r2.text = sub
    r2.font.size = Pt(9)
    r2.font.name = _B_FONT
    r2.font.color.rgb = sub_color
    return (cx - w / 2, cx + w / 2)


def build_diagram_e(slide):
    W, H = 2.5, 0.8
    cols = [2.0, 5.1, 8.2, 11.3]
    path_y, prune_y = 3.3, 4.78
    for cx, htext in zip(cols, ["CRASH SITE", "HOP 1", "HOP 2",
                                "HOP 3 · ROOT CAUSE"]):
        tb = slide.shapes.add_textbox(Inches(cx - 1.55), Inches(2.02),
                                      Inches(3.1), Inches(0.3))
        pp = tb.text_frame.paragraphs[0]
        pp.alignment = PP_ALIGN.CENTER
        rr = pp.add_run()
        rr.text = htext
        rr.font.size = Pt(11)
        rr.font.bold = True
        rr.font.name = _B_FONT
        rr.font.color.rgb = _B_BLUE

    # Winning path: crash site → downstream callees → root cause. The selected
    # node out-scores its pruned sibling at every hop, and the score climbs to
    # its peak at the root cause — the node that *changed* (git recency).
    crash = _tnode(slide, cols[0], path_y, W, H, "charge", "crash site",
                   _E_AMBER, _B_NAVY, _B_NAVY, None)
    h1 = _tnode(slide, cols[1], path_y, W, H, "get_cart", "score 0.31",
                _B_CHIP, _B_GREEN, _B_MUTED, _B_GREEN)
    h2 = _tnode(slide, cols[2], path_y, W, H, "load_timeout", "score 0.37",
                _B_CHIP, _B_GREEN, _B_MUTED, _B_GREEN)
    root = _tnode(slide, cols[3], path_y, W, H, "get_payment_timeout",
                  "0.42 · root cause", _B_GREEN, _B_NAVY, _B_NAVY, None)
    # Pruned candidates (one per hop), greyed out — each below the selected node.
    p1 = _tnode(slide, cols[1], prune_y, W, H, "create_session", "0.18 · pruned",
                _B_CHIP, _E_DIM, _E_DIM, _E_DIM)
    p2 = _tnode(slide, cols[2], prune_y, W, H, "SessionManager", "0.14 · pruned",
                _B_CHIP, _E_DIM, _E_DIM, _E_DIM)
    p3 = _tnode(slide, cols[3], prune_y, W, H, "OrderService", "0.11 · pruned",
                _B_CHIP, _E_DIM, _E_DIM, _E_DIM)

    path = [crash, h1, h2, root]
    for a, b in zip(path, path[1:]):
        _connect(slide, a[1], path_y, b[0], path_y, _B_GREEN, 2.5)
    for prev, pr in ((crash, p1), (h1, p2), (h2, p3)):
        _connect(slide, prev[1], path_y + 0.15, pr[0], prune_y, _E_DIM, 1.25)

    # ── Bottom strip: the 5 signals this phase scores each candidate on ───
    # (moved here from the Feature-B overview — it is Phase-3 detail).
    _phase_label(slide, 0.6, 5.55, "EACH CANDIDATE IS SCORED ON 5 SIGNALS",
                 _B_GREEN, "weighted sum → ranked · beam keeps the top 15",
                 width=12.13)
    signals = [
        ("Git recency · 0.35", "what changed"),
        ("Proximity · 0.20", "1 / (1 + hops)"),
        ("Keyword · 0.20", "matched / total"),
        ("Error type · 0.15", "RAISES edge only"),
        ("Connectivity · 0.10", "entry nodes only"),
    ]
    sX0, sROW_W, sn, sgap = 0.6, 12.13, 5, 0.4
    sbox_w = (sROW_W - sgap * (sn - 1)) / sn
    sy, sh = 6.05, 0.55
    for i, (name, sub) in enumerate(signals):
        sx = sX0 + i * (sbox_w + sgap)
        _chip(slide, sx, sy, sbox_w, sh, name, _B_CHIP, _B_GREEN, _B_GREEN)
        _cap(slide, sx, sy + sh + 0.06, sbox_w, sub, size=8.5, mono=True)


# ── Native diagram P1: Phase 1 parse pipeline + ParsedIncident output ──
def _cap(slide, x, y, w, text, size=9.5, mono=False, color=None):
    cb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.6))
    tf = cb.text_frame
    tf.word_wrap = True
    for j, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.name = "Consolas" if mono else _B_FONT
        r.font.color.rgb = color or _B_MUTED


def build_diagram_p1(slide):
    _phase_label(slide, 0.6, 2.0, "PHASE 1 · PARSE", _B_GREEN,
                 "raw text → structured incident · never crashes on any input",
                 width=12.13)
    stages = [
        ("Raw trace text", "any format in"),
        ("Pre-process", "strip timestamps,\nlog levels, brackets"),
        ("Detect language", "Python / JS / … chain"),
        ("Extract structure", ""),   # caption removed per user edit
    ]
    X0, ROW_W, n, gap = 0.6, 12.13, 4, 0.5
    box_w = (ROW_W - gap * (n - 1)) / n
    y, h = 2.7, 0.8
    spans = []
    for i, (name, desc) in enumerate(stages):
        x = X0 + i * (box_w + gap)
        if i == n - 1:
            _chip(slide, x, y, box_w, h, name, _B_GREEN, _B_NAVY, None)
        else:
            _chip(slide, x, y, box_w, h, name, _B_CHIP, _B_GREEN, _B_GREEN)
        spans.append((x, x + box_w))
        if i > 0:
            _connect(slide, spans[i - 1][1], y + h / 2, x, y + h / 2, _B_GREEN, 1.6)
        if desc:
            _cap(slide, x, y + h + 0.12, box_w, desc)

    _phase_label(slide, 0.6, 4.55, "OUTPUT · ParsedIncident", _B_BLUE,
                 "the structure every later phase reads", width=12.13)
    fields = [
        ("error_type", "AttributeError"),
        ("error_message", "NoneType has no attr"),
        ("frames", "file : line : function"),
        ("keywords", ""),   # caption removed per user edit
    ]
    fy, fh = 5.05, 0.7
    for i, (name, desc) in enumerate(fields):
        x = X0 + i * (box_w + gap)
        _chip(slide, x, fy, box_w, fh, name, _B_CHIP, _B_BLUE, _B_BLUE)
        if desc:
            _cap(slide, x, fy + fh + 0.1, box_w, desc, size=8.5, mono=True)
    # bottom "Handles …" line removed per user edit


# ── Native diagram P2: Phase 2 entry-node discovery (two cards) ────────
def _stepchip(slide, x, y, w, h, main, sub, accent):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = _B_CHIP
    shp.line.color.rgb = accent
    shp.line.width = Pt(1.0)
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.18)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run()
    r.text = main
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.name = _B_FONT
    r.font.color.rgb = accent
    if sub:
        r2 = p.add_run()
        r2.text = "    " + sub
        r2.font.size = Pt(8.5)
        r2.font.name = _B_FONT
        r2.font.color.rgb = _B_MUTED


def build_diagram_p2(slide):
    cards = [
        dict(x=0.6, accent=_B_GREEN, tag="PRIMARY · stack trace",
             sub="exact matching — always more precise than search",
             steps=[("1   name + file match", ""),
                    ("2   line proximity", "innermost def ≤ line"),
                    ("3   position weight", "deepest 1.0 → 0.4")]),
        dict(x=6.93, accent=_B_BLUE, tag="FALLBACK · natural-language query",
             sub="used only when the trace has no frames",
             steps=[("TF-IDF cosine search", "ranked on keywords"),
                    ("filter", "keep functions / classes")]),
    ]
    card_w, card_y, card_h = 5.8, 2.45, 3.05
    bottoms = []
    for c in cards:
        x, acc = c["x"], c["accent"]
        cont = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                      Inches(x), Inches(card_y),
                                      Inches(card_w), Inches(card_h))
        cont.fill.solid()
        cont.fill.fore_color.rgb = _B_NAVY
        cont.line.color.rgb = acc
        cont.line.width = Pt(1.75)
        cont.shadow.inherit = False
        _phase_label(slide, x + 0.32, card_y + 0.22, c["tag"], acc, "",
                     width=card_w - 0.6)
        _cap(slide, x + 0.32, card_y + 0.6, card_w - 0.64, c["sub"],
             size=9.5, color=_B_MUTED)
        sy, sh, sgap = card_y + 1.2, 0.5, 0.16
        for main, sub in c["steps"]:
            _stepchip(slide, x + 0.4, sy, card_w - 0.8, sh, main, sub, acc)
            sy += sh + sgap
        bottoms.append((x + card_w / 2, card_y + card_h))

    ex_w, ex_h = 3.8, 0.8
    ex_x = 0.6 + (12.13 - ex_w) / 2
    ex_y = 6.0
    _chip(slide, ex_x, ex_y, ex_w, ex_h, "≤ 5 entry nodes", _B_GREEN, _B_NAVY, None)
    for cx, cb in bottoms:
        _connect(slide, cx, cb, ex_x + ex_w / 2, ex_y, _B_MUTED, 1.6)


# ── Native diagram P5: Phase 5 explain (planned) — context → LLM → output ─
def build_diagram_p5(slide):
    _chip(slide, 0.6, 2.0, 12.13, 0.5,
          "PLANNED · not yet implemented — this is the intended approach",
          _B_CHIP, _E_AMBER, _E_AMBER)

    # Inputs (left, stacked)
    _phase_label(slide, 0.6, 2.75, "INPUTS", _B_GREEN, "all deterministic", width=4.0)
    inx, inw, inh = 0.6, 3.4, 0.75
    inputs = [
        ("Verified context", "root cause · confidence · checks · git · reasons", _B_GREEN),
        ("Candidate code", "the function source", _B_BLUE),
        ("Graph neighbors", "callers & callees", _B_BLUE),
    ]
    iy0, istep = 3.2, 1.15
    icenters = []
    for i, (name, sub, acc) in enumerate(inputs):
        y = iy0 + i * istep
        # all inputs are subtle chips with an accent border (green = the
        # deterministic, already-verified one — distinguished by colour, not weight)
        _chip(slide, inx, y, inw, inh, name, _B_CHIP, acc, acc)
        _cap(slide, inx, y + inh + 0.02, inw, sub, size=8)
        icenters.append(y + inh / 2)

    # LLM box (centre)
    lx, ly, lw, lh = 5.0, 3.6, 3.0, 1.6
    _chip(slide, lx, ly, lw, lh, "LLM", _B_CHIP, _B_GREEN, _B_GREEN)
    _cap(slide, lx, ly + lh - 0.5, lw, "constrained prompt", size=9, color=_B_GREEN)
    for cy in icenters:
        _connect(slide, inx + inw, cy, lx, ly + lh / 2, _B_GREEN, 1.8)

    # Outputs (right, stacked)
    _phase_label(slide, 9.0, 2.75, "OUTPUT", _B_BLUE, "human-readable", width=4.0)
    ox, ow, oh = 9.0, 3.7, 0.75
    outputs = ["Why it broke — plain English", "Suggested fix", "Owning team / where to route"]
    oy0, ostep = 3.2, 1.15
    for i, name in enumerate(outputs):
        y = oy0 + i * ostep
        _chip(slide, ox, y, ow, oh, name, _B_CHIP, _B_BLUE, _B_BLUE)
        _connect(slide, lx + lw, ly + lh / 2, ox, y + oh / 2, _B_BLUE, 1.8)

    _cap(slide, 0.6, 6.75, 12.13,
             "The LLM only explains a result the graph already proved — it never "
             "selects the root cause, so it cannot hallucinate one.",
             size=10.5, color=_B_GREEN)


# ── Native diagram F: deterministic-verification funnel ────────────────
def build_diagram_f(slide):
    cx = 6.665
    rows = [
        ("Top candidates from traversal", 9.6, _B_CHIP, _B_BLUE, _B_BLUE),
        ("1 · Path exists?   (BFS either direction · CALLS / IMPORTS · ≤200 nodes)", 8.2,
         _B_CHIP, _B_BLUE, _B_BLUE),
        ("2 · Modified in the last 30 days?   (git recency)", 6.8,
         _B_CHIP, _B_BLUE, _B_BLUE),
        ("3 · Keywords align?   (name / docstring / commit message)", 5.4,
         _B_CHIP, _B_BLUE, _B_BLUE),
        ("Verified root cause", 4.1, _B_GREEN, _B_NAVY, None),
    ]
    y0, h, step = 1.9, 0.6, 0.76
    for i, (label, w, fill, tc, bd) in enumerate(rows):
        y = y0 + i * step
        _chip(slide, cx - w / 2, y, w, h, label, fill, tc, bd)
        if i > 0:
            last = len(rows) - 1
            _connect(slide, cx, y0 + (i - 1) * step + h, cx, y,
                     _B_GREEN if i == last else _B_BLUE, 2.0)

    # "mandatory gate" tag beside the path check (row 1), to its left.
    y1 = y0 + step
    mt = slide.shapes.add_textbox(Inches(cx - rows[1][1] / 2 - 2.05),
                                  Inches(y1 + 0.13), Inches(1.9), Inches(0.36))
    mp = mt.text_frame.paragraphs[0]
    mp.alignment = PP_ALIGN.RIGHT
    mr = mp.add_run()
    mr.text = "mandatory gate"
    mr.font.size = Pt(10)
    mr.font.bold = True
    mr.font.name = _B_FONT
    mr.font.color.rgb = _E_AMBER

    # Confidence scale under the verdict.
    yv = y0 + (len(rows) - 1) * step + h
    cs = slide.shapes.add_textbox(Inches(cx - 4.5), Inches(yv + 0.14),
                                  Inches(9.0), Inches(0.32))
    cp = cs.text_frame.paragraphs[0]
    cp.alignment = PP_ALIGN.CENTER
    cr = cp.add_run()
    cr.text = "all 3 pass → HIGH        2 → MEDIUM        1 → LOW"
    cr.font.size = Pt(11)
    cr.font.bold = True
    cr.font.name = _B_FONT
    cr.font.color.rgb = RGBColor(0xC9, 0xD2, 0xDE)


# ── Native diagram (slide 2): incident workflow, today vs. with engine ─
def build_diagram_problem(slide):
    w, h = 2.5, 0.62
    # TODAY — the developer's manual hunt
    _phase_label(slide, 0.6, 1.92, "TODAY — without the engine", _E_AMBER,
                 "the manual hunt", width=8.5)
    today = ["Stack trace fires", "Trace by hand", "Escalate to owner",
             "Root cause: hours"]
    x0, gap, yt = 0.7, 0.55, 2.42
    spans = []
    for i, lab in enumerate(today):
        x = x0 + i * (w + gap)
        _chip(slide, x, yt, w, h, lab, _B_CHIP, _E_AMBER, _E_AMBER)
        spans.append((x, x + w))
        if i > 0:
            _connect(slide, spans[i - 1][1], yt + h / 2, x, yt + h / 2,
                     _E_AMBER, 1.8)
    tg = slide.shapes.add_textbox(Inches(0.7), Inches(yt + h + 0.12),
                                  Inches(11.6), Inches(0.3))
    tr = tg.text_frame.paragraphs[0].add_run()
    tr.text = ("the trace shows the crash site, not the cause  ·  manual cross-repo "
               "tracing  ·  every hop waits on whoever knows that code")
    tr.font.size = Pt(10.5)
    tr.font.italic = True
    tr.font.name = _B_FONT
    tr.font.color.rgb = _B_MUTED

    # WITH THE ENGINE — on-call dev fixes it directly, or hands off a precise lead
    _phase_label(slide, 0.6, 4.1, "WITH THE ENGINE", _B_GREEN,
                 "the dev fixes it directly", width=8.5)
    yb = 4.78
    ux = 0.7
    ex = x0 + (w + gap)
    _chip(slide, ux, yb, w, h, "Stack trace", _B_CHIP, _B_GREEN, _B_GREEN)
    _chip(slide, ex, yb, w, h, "Diagnostics Engine", _B_GREEN, _B_NAVY, None)
    _connect(slide, ux + w, yb + h / 2, ex, yb + h / 2, _B_GREEN, 1.8)

    out_x = x0 + 2 * (w + gap)
    self_y, sup_y = yb - 0.55, yb + 0.55
    _chip(slide, out_x, self_y, w, h, "Fix it directly", _B_CHIP,
          _B_GREEN, _B_GREEN)
    _chip(slide, out_x, sup_y, w, h, "Route precise lead", _B_CHIP, _B_MUTED, _B_MUTED)
    _connect(slide, ex + w, yb + h / 2, out_x, self_y + h / 2, _B_GREEN, 1.8)
    _connect(slide, ex + w, yb + h / 2, out_x, sup_y + h / 2, _B_MUTED, 1.4)

    for ty, txt, col in ((self_y, "cause is in my code", _B_GREEN),
                         (sup_y, "owned by another team", _B_MUTED)):
        tb = slide.shapes.add_textbox(Inches(out_x + w + 0.15), Inches(ty + 0.13),
                                      Inches(2.9), Inches(0.36))
        rr = tb.text_frame.paragraphs[0].add_run()
        rr.text = txt
        rr.font.size = Pt(9.5)
        rr.font.bold = True
        rr.font.name = _B_FONT
        rr.font.color.rgb = col


# ── Native diagram G: demo — scenario (left) vs. engine result (right) ─
def build_diagram_g(slide):
    RED = RGBColor(0xD0, 0x32, 0x2D)
    # LEFT: 5-file call chain, crash + planted bug marked.
    _phase_label(slide, 0.6, 2.0, "THE SCENARIO", _B_BLUE, "5-file demo app")
    files = [
        ("app.py", None, _B_BLUE),
        ("order.py", None, _B_BLUE),
        ("payment.py", "AttributeError here", _E_AMBER),
        ("session.py", None, _B_BLUE),
        ("config.py", "planted bug", RED),
    ]
    nx, nw, nh = 2.2, 2.7, 0.56
    y0, step = 2.55, 0.74
    for i, (name, tag, accent) in enumerate(files):
        y = y0 + i * step
        if name == "config.py":
            _chip(slide, nx - nw / 2, y, nw, nh, name, RED, _WHITE, None)
        else:
            _chip(slide, nx - nw / 2, y, nw, nh, name, _B_CHIP, accent, accent)
        if i > 0:
            _connect(slide, nx, y0 + (i - 1) * step + nh, nx, y, _B_MUTED, 1.4)
        if tag:
            tb = slide.shapes.add_textbox(Inches(nx + nw / 2 + 0.15),
                                          Inches(y + 0.1), Inches(2.5), Inches(0.36))
            tp = tb.text_frame.paragraphs[0]
            tr = tp.add_run()
            tr.text = tag
            tr.font.size = Pt(9.5)
            tr.font.bold = True
            tr.font.name = _B_FONT
            tr.font.color.rgb = accent

    # RIGHT: real screenshots from a live run (error trace + diagnosis output).
    _phase_label(slide, 6.55, 2.0, "FROM A REAL RUN", _B_GREEN,
                 "python3 run_demo.py", width=6.5)
    img_x, img_w = 6.55, 6.55
    # demo_error.png 1460x446 (aspect 3.27); demo_diagnosis.png 1600x426 (3.76)
    err_h = img_w / 3.27
    diag_h = img_w / 3.76
    err_y = 2.5
    diag_y = err_y + err_h + 0.18
    for path, x, y, h in (
        (_IMG_ERROR, img_x, err_y, err_h),
        (_IMG_DIAG, img_x, diag_y, diag_h),
    ):
        pic = slide.shapes.add_picture(path, Inches(x), Inches(y),
                                       width=Inches(img_w), height=Inches(h))
        pic.line.color.rgb = RGBColor(0x4A, 0x4A, 0x4A)
        pic.line.width = Pt(0.75)
        pic.shadow.inherit = False


# ── Native sequence diagram: temporal execution flow of one incident ───
def _seq_label(slide, x, y, text, color, center=True, w=5.0, size=11):
    left = x - w / 2 if center else x
    left = max(0.05, min(left, 13.33 - w))
    tb = slide.shapes.add_textbox(Inches(left), Inches(y), Inches(w), Inches(0.26))
    tf = tb.text_frame
    tf.word_wrap = False
    tf.margin_top = Inches(0.01)
    tf.margin_bottom = Inches(0.01)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER if center else PP_ALIGN.LEFT
    r = p.add_run()
    r.text = text
    r.font.name = "Consolas"
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = color


def build_sequence_diagram(slide):
    # Real participants from src/diagnosis (IncidentEngine orchestrates).
    actors = ["IncidentEngine", "StackTraceParser", "TraversalEngine",
              "TFIDFEnricher", "Verifier"]
    X0, ROWW = 0.6, 12.2
    n = len(actors)
    colw = ROWW / n
    cx = [X0 + (i + 0.5) * colw for i in range(n)]
    # Narrower boxes → wider gaps between actor labels (more breathing room).
    box_w, box_h, box_y = 2.06, 0.56, 1.98
    life_top, life_bot = box_y + box_h, 7.0
    for i, a in enumerate(actors):
        accent = _B_GREEN if a == "IncidentEngine" else _B_BLUE
        _chip(slide, cx[i] - box_w / 2, box_y, box_w, box_h, a, _B_CHIP,
              accent, accent)
        _connect(slide, cx[i], life_top, cx[i], life_bot, _B_MUTED, 1.0,
                 dash=True, arrow=False)

    # Real call sequence from IncidentEngine.diagnose(). Labels shortened so
    # they read large on a projector; full signatures live in the code.
    CALL, RET = _B_GREEN, _B_MUTED
    msgs = [
        (0, 1, "parse(raw_trace)", "call"),
        (1, 0, "ParsedIncident", "ret"),
        (0, 2, "find_entry_nodes(incident, …)", "call"),
        (2, 3, "search(query, …)   — fallback only", "call"),
        (3, 2, "ranked nodes", "ret"),
        (2, 0, "entry_nodes", "ret"),
        (0, 2, "traverse(entry_nodes, max_hops=4)", "call"),
        (2, 2, "_evaluate_node()  —  score + beam-15 prune", "self"),
        (2, 0, "candidate_root_causes", "ret"),
        (0, 4, "verify_candidates(…, top_n=5)", "call"),
        (4, 4, "3 checks:  path · git · keyword → confidence", "self"),
        (4, 0, "verified root cause", "ret"),
    ]
    y0, step = 2.92, 0.37
    for k, (fr, to, label, kind) in enumerate(msgs):
        y = y0 + k * step
        if kind == "self":
            x = cx[fr]
            left_side = x > 9.0
            d = -0.8 if left_side else 0.8       # wider loop
            hh = 0.13                            # taller loop (±hh)
            _connect(slide, x, y - hh, x + d, y - hh, CALL, 1.8, arrow=False)
            _connect(slide, x + d, y - hh, x + d, y + hh, CALL, 1.8, arrow=False)
            _connect(slide, x + d, y + hh, x, y + hh, CALL, 1.8)   # arrow back
            _seq_label(slide, x + (-3.0 if left_side else 3.0), y - 0.24,
                       label, CALL, center=True, w=5.0)
            continue
        if kind == "call":
            _connect(slide, cx[fr], y, cx[to], y, CALL, 2.0, dash=False)
            color = CALL
        else:  # return — dashed, muted grey, thinner so it visually recedes
            _connect(slide, cx[fr], y, cx[to], y, RET, 1.3, dash=True)
            color = RET
        _seq_label(slide, (cx[fr] + cx[to]) / 2, y - 0.24, label, color, w=5.0)

    # Legend — make the call/return visual language explicit.
    ly = life_bot + 0.14
    _connect(slide, 4.45, ly, 5.05, ly, CALL, 2.0)
    _seq_label(slide, 5.12, ly - 0.13, "call", CALL, center=False, w=1.1, size=10)
    _connect(slide, 6.5, ly, 7.1, ly, RET, 1.3, dash=True)
    _seq_label(slide, 7.17, ly - 0.13, "return", RET, center=False, w=1.4, size=10)


def add_table(slide, rows, left=1.2, top=2.4, width=10.93, height=2.4,
              font_size=13):
    gf = slide.shapes.add_table(len(rows), len(rows[0]),
                                Inches(left), Inches(top),
                                Inches(width), Inches(height))
    tbl = gf.table
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = str(val)
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(font_size)
                    if r == 0:
                        run.font.bold = True
    return gf


# ═══════════════════════════════════════════════════════════════════════
# SLIDE 1 — Title
s = add("Cover Green")
set_text(ph(s, 0), "Incident Diagnostics Engine — From Stack Trace to Root Cause")
# Nudge letter-spacing slightly positive so glyphs (e.g. "Tr" in Trace) can't
# collide at the large cover size.
for _p in ph(s, 0).text_frame.paragraphs:
    for _r in _p.runs:
        _r._r.get_or_add_rPr().set("spc", "60")
set_text(ph(s, 10), "Automated multi-hop root cause analysis using code knowledge graphs")
set_text(ph(s, 11), "Deepanshu Jindal  ·  June 2026")
notes(s, "Hi everyone. What I built this summer is a system that takes a raw "
         "production error and automatically traces it back to the exact function "
         "or class that caused it — across multiple repositories, without any "
         "human guessing. Let me walk you through the problem, the approach, and "
         "what actually works today.")

# SLIDE 2 — Agenda
s = add("Title and Content")
set_text(ph(s, 0), "Agenda")
set_text(ph(s, 13), "What this talk covers")
build_diagram_index(s)
notes(s, "Quick roadmap of the talk. I'll start with the problem and why existing "
         "tools fall short, then the core insight behind the approach. From there "
         "the architecture, the two big pieces — the graph builder and the "
         "reasoning engine with its five phases — then a live demo with results and "
         "performance numbers, and finally the honest limitations and what's next.")

# SLIDE 3 — The Problem
s = add("Title and Content")
set_text(ph(s, 0), "The Problem")
set_text(ph(s, 13), "How a developer diagnoses a production incident — today vs. with the engine")
build_diagram_problem(s)
notes(s, "Picture yourself on call. A production error fires and you get a stack "
         "trace. The trace tells you where it crashed — but the actual cause is "
         "almost never there. It's three or four calls away: a function that was "
         "quietly changed last week, a config value that stopped being valid, a "
         "helper that started returning None. So today you trace it by hand — "
         "reading code across repos, running git blame, and when it crosses into "
         "code you don't own, you escalate and wait on whoever does. Hours go by. "
         "With the engine, you hand it that same stack trace and it gives you the "
         "root-cause function directly — file, line, confidence, and what changed. "
         "If it's in your code, you fix it yourself. If it's another team's, you "
         "hand them the exact root cause instead of a vague 'it's broken.' Same "
         "developer, same incident — minutes instead of hours.")

# SLIDE 4 — Why Existing Tools Fail
s = add("Title with Three Columns and Headers")
set_text(ph(s, 0), "Why Existing Tools Fail")
set_text(ph(s, 1), "Pasting a stack trace into an LLM breaks in three systematic ways")
set_text(ph(s, 16), "LLM context blindness")
set_text(ph(s, 20), "Token bloat")
set_text(ph(s, 21), "Single-hop RAG")
set_text(ph(s, 22), "It has never seen your codebase — it guesses at the relationships between files.")
set_text(ph(s, 23), "Feeding raw source is expensive; you hit context limits before the relevant code even appears.")
set_text(ph(s, 24), "Retrieval returns the chunk nearest the query — but bugs are multi-hop, and the cause is far from the error.")
add_verdict(ph(s, 22), "→ Confident, but guessing.", RGBColor(0x63, 0xDF, 0x4E))
add_verdict(ph(s, 23), "→ Out of room before it starts.", RGBColor(0x63, 0xDF, 0x4E))
add_verdict(ph(s, 24), "→ Looks in the wrong place.", RGBColor(0x63, 0xDF, 0x4E))
notes(s, "The obvious first instinct is to paste the stack trace into an LLM. And "
         "sometimes it gets lucky. But it fails in three systematic ways. First, the "
         "LLM has never seen your codebase — it guesses at relationships between "
         "files. Second, feeding raw source code is expensive and you hit context "
         "limits before the relevant section even appears. Third, standard RAG "
         "retrieves the single chunk closest to the query. But bugs are multi-hop "
         "failures — the relevant code is nowhere near the error message. None of "
         "these tools understand architecture. They understand text.")

# SLIDE 5 — The Core Insight
s = add("Title Only")
set_text(ph(s, 0), "The Core Insight")
# match the other slide titles' geometry exactly (avoid a zero-width box)
ph(s, 0).left = Inches(0.60)
ph(s, 0).top = Inches(0.58)
ph(s, 0).width = Inches(12.12)
ph(s, 0).height = Inches(0.65)
# inherit the layout's full title size (like slides 3 & 5) so the subheading
# hugs right under it instead of leaving a gap
for _para in ph(s, 0).text_frame.paragraphs:
    for _run in _para.runs:
        _run.font.size = None
# subheading: the thesis, styled like the other slides' subtitles (20pt, bg1)
_sub = s.shapes.add_textbox(Inches(0.60), Inches(1.20), Inches(12.13), Inches(0.65))
_sub.text_frame.word_wrap = True
_sr = _sub.text_frame.paragraphs[0].add_run()
_sr.text = ("Don't ask the LLM to read code. Give it a map of how code "
            "behaves — and make it reason over that map.")
_sr.font.size = Pt(20)
_sr.font.name = "ServiceNow Sans"
_sr.font.color.theme_color = MSO_THEME_COLOR.BACKGROUND_1
build_diagram_a(s)
notes(s, "The core insight was this: instead of feeding code to an LLM, pre-compute "
         "a structural map of the entire codebase — which function calls which, "
         "what each class extends, what exceptions each function raises. Then when an "
         "incident happens, reason over that map deterministically. The LLM only "
         "comes in at the very end, to explain a result the graph has already proven "
         "is real.")

# SLIDE 6 — System Architecture Overview
s = add("Title and Content")
set_text(ph(s, 0), "System Architecture Overview")
set_text(ph(s, 13), "Two separate phases: an offline build, a real-time diagnosis")
build_diagram_b(s)
notes(s, "The system has two completely separate phases. The build phase runs "
         "offline — it processes your repositories and produces a knowledge graph. "
         "The diagnosis phase runs when an incident happens — it takes a stack "
         "trace and reasons over that pre-built graph in seconds. These two phases "
         "never overlap, which is what makes the diagnosis fast.")

# SLIDE 7 — Feature A: The Graph Builder
s = add("Title and Content")
set_text(ph(s, 0), "Feature A: The Graph Builder")
set_text(ph(s, 13), "Built from scratch — 2,909 nodes · 12,227 edges across "
                    "Flask, Werkzeug & Jinja")
build_diagram_c(s)
notes(s, "For Feature A, I built a complete Python AST pipeline from scratch — "
         "character-level tokenizer, full grammar parser, and a walker that converts "
         "the AST into graph nodes and edges. No external parser libraries. Every "
         "function, class, and module becomes a node. Every call, import, "
         "inheritance, exception raise, and catch becomes a typed edge. On top of the "
         "structural graph, I layered two enrichment steps: TF-IDF vectors built from "
         "scratch for semantic search, and git commit history pulled via the GitHub "
         "API so every node knows when it was last touched and by whom. The result "
         "for the merged Flask, Werkzeug and Jinja graph is 2,909 nodes and 12,227 "
         "edges.")

# SLIDE 8 — Feature A: Graph Builder Capabilities
s = add("Title with Three Columns and Headers")
set_text(ph(s, 0), "Feature A: What the Graph Builder Can Do")
set_text(ph(s, 1), "Capabilities beyond parsing a single file")
set_text(ph(s, 16), "Multi-repo support")
set_text(ph(s, 20), "Graph updates")
set_text(ph(s, 21), "Enrichment")
set_text(ph(s, 22), "Merge many codebases — local paths or remote Git URLs — into "
                    "one unified graph, so a call that crosses repo boundaries is "
                    "still a first-class edge.")
set_text(ph(s, 23), "Incremental: when files change, only those files' nodes are "
                    "removed and reprocessed, tracked by git HEAD — no full rebuild "
                    "of the graph.")
set_text(ph(s, 24), "Every node carries TF-IDF semantic vectors for search and git "
                    "history for recency — who last changed it, and when.")
add_verdict(ph(s, 22), "→ One graph across repos.", RGBColor(0x63, 0xDF, 0x4E))
add_verdict(ph(s, 23), "→ No full rebuilds.", RGBColor(0x63, 0xDF, 0x4E))
add_verdict(ph(s, 24), "→ Search + recency, built in.", RGBColor(0x63, 0xDF, 0x4E))
notes(s, "Beyond turning one file into nodes and edges, the graph builder has a "
         "few capabilities worth calling out. It supports multiple repositories — "
         "you can merge several codebases into one unified graph, so a call that "
         "crosses repo boundaries is still a first-class edge. It ingests from a "
         "local path or directly from a Git URL, shallow-cloning and caching remote "
         "repos. It does incremental updates: when files change it removes just "
         "those files' nodes and reprocesses them, tracking the git HEAD hash, so "
         "there's no full rebuild. Entity resolution links raw symbol references to "
         "real cross-file node IDs through four matching strategies. Every node is "
         "enriched with both TF-IDF semantic vectors and git recency. And there's a "
         "visualizer that exports the whole graph to a standalone interactive HTML "
         "view.")

# SLIDE 9 — Feature B: The Reasoning Engine
s = add("Title and Content")
set_text(ph(s, 0), "Feature B: The Reasoning Engine")
set_text(ph(s, 13), "Five phases: Parse → Locate → Traverse → Verify → Explain")
build_diagram_d(s)
notes(s, "Feature B is the reasoning engine. It runs five phases in sequence. Phase "
         "one parses the raw stack trace into structure — error type, message, "
         "individual frames, and keywords. It handles real-world formats: "
         "log-prefixed lines, chained exceptions, timestamp noise. Phase two finds "
         "where in the graph the crash site is — using exact function name and "
         "file path matching first, with TF-IDF semantic search as a fallback if the "
         "exact node isn't in the graph. Phase three traverses outward from that "
         "crash site — backward to callers and forward into the functions it "
         "called — up to four hops deep, scoring every candidate it encounters. "
         "Phase four then verifies with three structural checks, and phase five "
         "explains the verified result. The next five slides take each phase in "
         "turn.")

# SLIDE 10 — Phase 1: Parse
s = add("Title and Content")
set_text(ph(s, 0), "Phase 1: Parse the Stack Trace")
set_text(ph(s, 13), "Raw incident text → a structured ParsedIncident")
build_diagram_p1(s)
notes(s, "Phase one turns raw incident text into structure. Real production logs "
         "are messy — timestamps, log-level prefixes, thread names, chained "
         "exceptions, sometimes truncated. So the parser first pre-processes: it "
         "strips timestamps, log levels and bracketed prefixes line by line. Then "
         "it detects the language and runs the matching frame parser to pull out "
         "each frame — file, line, function. Three tiers of regex extract the error "
         "type, then the error message, then keywords — which are camel-split "
         "(NoneType becomes none, type) and stripped of stop-words. The output is a "
         "ParsedIncident: error type, message, frames, and keywords. It never "
         "crashes — any failure returns an empty incident rather than throwing.")

# SLIDE 11 — Phase 2: Locate
s = add("Title and Content")
set_text(ph(s, 0), "Phase 2: Locate the Crash Site")
set_text(ph(s, 13), "Map each frame to its node in the graph")
build_diagram_p2(s)
notes(s, "Phase two answers: where in the graph did this crash happen? If we have "
         "stack frames, we use exact matching only — function name plus file path — "
         "because that's always more precise than search. When two definitions in "
         "the same file share a name, line-number proximity breaks the tie: the "
         "correct node is the innermost definition at or before the frame's line. "
         "Each frame gets a position weight — the deepest frame, closest to the "
         "exception, weighted 1.0 down to 0.4 for the outermost caller. We return up "
         "to five entry nodes. Only when there are no frames — a natural-language "
         "query — do we fall back to TF-IDF semantic search over the keywords, "
         "keeping the top function and class nodes.")

# SLIDE 12 — Phase 3: Multi-hop Backward Traversal
s = add("Title and Content")
set_text(ph(s, 0), "Phase 3: Multi-Hop BFS Traversal")
set_text(ph(s, 13), "Bidirectional BFS · beam width 15 · max 4 hops")
build_diagram_e(s)
notes(s, "Here is that traversal in motion. It starts at the crash site and walks "
         "outward in both directions — backward to callers, and forward into the "
         "functions the crash site called. That forward direction is what matters "
         "here: the bug isn't in who called charge, it's downstream, in something "
         "charge called that returned bad data. The key idea is that it does not "
         "keep everything: it scores each candidate with the five signals shown "
         "along the bottom and applies a beam width of 15, so only the top scorers at "
         "each hop survive. The green chain is the surviving path; the greyed-out "
         "nodes are the ones pruned at each hop — each scoring lower than the node "
         "we kept. The score climbs along the true causal path and peaks at the "
         "root cause: get_payment_timeout scores highest, even three hops out, "
         "because git recency — the node that just changed — outweighs proximity.")

# SLIDE 13 — Phase 4: Deterministic Verification
s = add("Title and Content")
set_text(ph(s, 0), "Phase 4: Deterministic Verification")
set_text(ph(s, 13), "The anti-hallucination layer — three structural checks")
build_diagram_f(s)
notes(s, "This is the most important phase. Before any LLM sees a result, every top "
         "candidate goes through three structural checks. Check one: does a path "
         "actually exist in the graph between this candidate and the crash site? "
         "It's a BFS over CALLS and IMPORTS edges in either direction — the cause "
         "can be upstream of the crash or downstream of it — capped at 200 nodes. "
         "If no path exists, the candidate is immediately disqualified — no score "
         "can override this. Check two: was this node modified in the last 30 days? "
         "Check three: do any of the error keywords appear in the node's name, "
         "docstring, or commit message? Candidates that pass all three get confidence "
         "HIGH, two get MEDIUM, one gets LOW. The error-type / RAISES check people "
         "ask about is not here — that's a scoring signal back in traversal. The key "
         "point: the LLM never sees a candidate that failed the path check.")

# SLIDE 14 — Phase 5: Explain
s = add("Title and Content")
set_text(ph(s, 0), "Phase 5: Explain the Result")
set_text(ph(s, 13), "Turn the verified root cause into a human explanation — planned")
build_diagram_p5(s)
notes(s, "Phase five is the only phase not yet implemented — so let me be precise "
         "about what exists and what's planned. Today the engine already produces a "
         "deterministic explanation context for the verified root cause: the node, "
         "its location, the confidence, which checks passed, the git evidence, and "
         "the scoring reasons. That string is built and carried through the report — "
         "ready for a prompt, but no LLM is called yet. The intended approach: feed "
         "that verified context, plus the candidate's source code and its immediate "
         "graph neighbors, to an LLM with a constrained prompt — and have it produce "
         "three things: a plain-English explanation of why it broke, a suggested "
         "fix, and who owns it. The crucial design point is the guarantee: the LLM "
         "only ever explains a result the graph has already proven structurally. It "
         "never selects the root cause itself, so it cannot hallucinate one. The "
         "deterministic engine decides; the LLM just narrates.")

# SLIDE 15 — Execution Sequence
s = add("Title and Content")
set_text(ph(s, 0), "Execution Sequence — One Incident")
set_text(ph(s, 13), "Temporal flow of the diagnosis algorithm, end to end")
build_sequence_diagram(s)
notes(s, "This is the same diagnosis, viewed as the actual call sequence. "
         "IncidentEngine orchestrates everything. It calls StackTraceParser.parse "
         "to get a ParsedIncident, then TraversalEngine.find_entry_nodes to locate "
         "the crash site — which falls back to TFIDFEnricher.search only when there's "
         "no exact match (e.g. a natural-language query). It then calls "
         "TraversalEngine.traverse: scoring and beam-15 pruning happen internally via "
         "_evaluate_node on each hop. Finally it calls Verifier.verify_candidates, "
         "which runs the path-exists, git-recency and keyword checks internally and "
         "returns the verified root cause. Scoring, pruning and the checks are "
         "internal methods — not separate services.")

# SLIDE 16 — Demo
s = add("Title and Content")
set_text(ph(s, 0), "Demo")
set_text(ph(s, 13), "Planted config bug → AttributeError 3 hops downstream → found with HIGH confidence")
build_diagram_g(s)
notes(s, "Let me show you this working. The demo is a five-file order-processing "
         "app. I planted one bug: config.get_payment_timeout() returns 0 instead of "
         "30. That makes the payment session time out, so get_cart returns None, and "
         "three calls later PaymentService.charge crashes with an AttributeError when "
         "it reads cart.total. The crucial part: the traceback ends at charge — "
         "config.py never appears in it. The engine takes that traceback and walks "
         "downstream through the call chain — charge, get_cart, load_timeout, "
         "get_payment_timeout — and lands on get_payment_timeout in config.py, three "
         "hops away, with HIGH confidence: a structural path exists, the node was "
         "just modified in git, and the keywords align. The crash site is where it "
         "hurt; the engine found where it started. The LLM then explains the fix in "
         "plain English.")

# SLIDE 17 — Test Results
s = add("Title and Content")
set_text(ph(s, 0), "Test Results")
set_text(ph(s, 13), "Six cases on the merged Flask / Werkzeug / Jinja graph — "
                    "all root causes found and verified valid (medium confidence)")
add_table(s, [
    ["TC", "Scenario", "Input", "Error type", "Root cause", "File"],
    ["TC1", "404 Not Found", "stack trace", "NotFound", "match", "map.py"],
    ["TC2", "MethodNotAllowed", "stack trace", "MethodNotAllowed", "match", "map.py"],
    ["TC3", "TemplateNotFound", "stack trace", "TemplateNotFound", "get_source", "loaders.py"],
    ["TC4", "UndefinedError", "stack trace", "UndefinedError", "render_template", "templating.py"],
    ["TC5", "AppContext teardown", "stack trace", "RuntimeError", "pop", "ctx.py"],
    ["TC6", "Natural language query", "NL query", "—", "jinja_loader", "scaffold.py"],
], left=0.6, top=2.3, width=12.13, height=3.7, font_size=11)
notes(s, "I ran six test cases against the merged Flask, Werkzeug, and Jinja graph. "
         "Test cases one through five are real stack traces from those frameworks "
         "— cross-repo failures, one to three hops deep. Test case six is a "
         "natural language query with no stack trace at all, which falls back "
         "entirely to TF-IDF. All six cases correctly identified the root cause node "
         "and passed verification. The natural language path is slower but works "
         "— entry node scoring uses TF-IDF results directly with max hops forced "
         "to zero since there is no structural starting point.")

# SLIDE 18 — Performance
s = add("Title and Content")
set_text(ph(s, 0), "Performance")
set_text(ph(s, 13), "How fast it builds, queries, and updates")
build_diagram_perf(s)
notes(s, "A few numbers on speed. Building the full merged graph from scratch "
         "takes [BUILD], on a graph of 2,909 nodes and 12,227 edges. Once it's "
         "built, diagnosing a single incident takes [QUERY] end to end — parse, "
         "locate, traverse and verify. Incremental updates are [UPDATE] per changed "
         "file, since only that file's nodes are reprocessed. Persisting the graph "
         "to a pickle is [SAVE] and loading it back is [LOAD], and building the "
         "TF-IDF index takes [TFIDF]. These are the numbers that make it practical "
         "to keep the graph current and answer incidents in seconds.")

# SLIDE 19 — Key Design Decisions
s = add("Title with Three Columns and Headers")
set_text(ph(s, 0), "Key Design Decisions")
set_text(ph(s, 1), "Three decisions shaped the whole architecture")
set_text(ph(s, 16), "Exact match > TF-IDF")
set_text(ph(s, 20), "The verifier is the source of truth")
set_text(ph(s, 21), "The LLM explains, never decides")
set_text(ph(s, 22), "For entry-node finding with a stack trace, exact name + path matching always wins. TF-IDF is a fallback for natural-language queries only.")
set_text(ph(s, 23), "Traversal scores only rank candidates — they cannot validate them. A great score with no structural path is still wrong.")
set_text(ph(s, 24), "The LLM receives only the verified sub-graph, never raw code. Hallucination is eliminated by architecture, not by prompting.")
add_verdict(ph(s, 22), "→ No noise from fuzzy matches.", RGBColor(0x63, 0xDF, 0x4E))
add_verdict(ph(s, 23), "→ Structure decides, not score.", RGBColor(0x63, 0xDF, 0x4E))
add_verdict(ph(s, 24), "→ Hallucination ruled out by design.", RGBColor(0x63, 0xDF, 0x4E))
notes(s, "Three decisions shaped the whole architecture. First: exact matching "
         "always beats TF-IDF for entry node finding when a stack trace is available. "
         "TF-IDF is a fallback for natural language queries only — using it for "
         "structured stack traces introduced noise. Second: the verifier is the "
         "source of truth, not the scorer. Traversal scores rank candidates but "
         "cannot validate them. A node with a great score and no structural path is "
         "still wrong. Third: the LLM only receives the verified sub-graph, not raw "
         "code. It explains a result the graph produced — it does not produce the "
         "result itself. This is why hallucinations are eliminated by architecture, "
         "not by prompting.")

# SLIDE 20 — Known Limitations
s = add("Title with Three Columns and Headers")
set_text(ph(s, 0), "Known Limitations")
set_text(ph(s, 1), "Where the current system breaks — and why it's not trivial to fix")
set_text(ph(s, 16), "Python only — other languages are stubs")
set_text(ph(s, 20), "Graph stops at service boundaries")
set_text(ph(s, 21), "TF-IDF fallback is weak on ambiguous queries")
set_text(ph(s, 22), "Language detection recognises JS, Java, Go and Ruby, but only "
                    "the Python parser, walker and stack-trace parser are built. "
                    "Any non-Python file falls through to 'unknown' and produces no "
                    "graph nodes — so today the engine is effectively Python-only.")
set_text(ph(s, 23), "If a crash crosses an HTTP call to another service, traversal "
                    "stops there. No inter-service call relationships exist in the "
                    "graph. This is the biggest gap for real microservice debugging.")
set_text(ph(s, 24), "Natural-language entry-node finding works for specific queries "
                    "but degrades on vague inputs. No semantic understanding — "
                    "purely keyword overlap.")
notes(s, "Three honest limitations. First, it's Python-only today — language "
         "detection recognises JS, Java, Go and Ruby, but only the Python parser "
         "and walker are actually implemented, so non-Python files produce no "
         "nodes. Second, and the biggest: the graph stops at service boundaries. "
         "If a crash crosses an "
         "HTTP call into another service, traversal halts — there are no "
         "inter-service edges yet, which is the main gap for real microservice "
         "debugging. Third, the TF-IDF fallback for natural-language queries is "
         "purely keyword overlap with no semantic understanding, so it degrades on "
         "vague inputs.")

# SLIDE 21 — What's Built vs. What's Next
s = add("Title with Two Columns and Header")
set_text(ph(s, 0), "What's Built vs. What's Next")
set_text(ph(s, 1), "Everything on the left is built and tested today")
set_text(ph(s, 16), "Built ✓")
set_text(ph(s, 17), "Roadmap")
_fill_phased(ph(s, 18), [
    ("Phase 1 · Graph Builder", [
        "Custom AST pipeline (tokenizer → parser → walker)",
        "9 typed edge relationships",
        "Entity resolver",
        "TF-IDF + git enrichment",
        "Incremental updates · multi-repo merged graph",
    ]),
    ("Phase 2 · Reasoning Engine", [
        "5-phase diagnosis engine",
        "Bidirectional traversal + 5-signal scoring",
        "Deterministic verification (3 checks)",
        "6-case test suite",
    ]),
], _B_GREEN)
_fill_phased(ph(s, 19), [
    ("Phase 1 · Graph Builder", [
        "Graph database storage (persistence)",
        "Graph refresh on push",
        "Multi-language parsers (beyond Python)",
        "HTTP_CALL edges + route extraction (microservices)",
    ]),
    ("Phase 2 · Reasoning Engine", [
        "LLM explanation layer (Phase 5)",
        "Stronger semantic entry-node search",
    ]),
], _B_BLUE)
notes(s, "Here is where things stand. Everything on the left is built and tested. "
         "The graph builder, the full diagnosis pipeline, incremental updates, "
         "multi-repo support, error type alignment — all working. The roadmap is "
         "clear: graph database storage for persistence, language parsers beyond "
         "Python, and the biggest one — HTTP call edge traversal. Right now if a "
         "crash crosses a service boundary via an HTTP call, the engine stops at that "
         "boundary. Adding synthetic endpoint nodes that bridge HTTP calls into graph "
         "edges would make this a true microservice debugger.")

# SLIDE 22 — Beyond the Main Project
s = add("Title with Two Columns and Header")
set_text(ph(s, 0), "Beyond the Main Project")
set_text(ph(s, 1), "What else I built and learned this summer")
set_text(ph(s, 16), "Main project")
set_text(ph(s, 17), "Beyond it")
set_text(ph(s, 18), [
    "Incident Diagnostics Engine",
    "Automated multi-hop root-cause analysis",
    "Over a self-built code knowledge graph",
    "— the subject of this talk —",
])
for _p in ph(s, 18).text_frame.paragraphs:
    for _r in _p.runs:
        _r.font.size = Pt(13)
_fill_phased(ph(s, 19), [
    ("Also built · standalone MCP agent (JS)", [
        "MCP servers expose 100+ tools → context overflow on local LLMs",
        "Filters to the 3–5 tools relevant to each query",
        "Compacts tool responses before the model → far fewer tokens",
    ]),
    ("Also learned", [
        "Model Context Protocol & MCP servers",
        "LLM-driven tool selection + token budgeting",
        "Response summarization for token efficiency",
        "Agent building in JS with a local model (Ollama / Mistral)",
    ]),
], _B_BLUE)
notes(s, "Quick note on the wider picture. The Incident Diagnostics Engine was my "
         "main project, but I also built a standalone MCP agent in JavaScript. The "
         "problem there: official MCP integrations expose over a hundred tools at "
         "once, which overflows the context of a local LLM and makes it pick wrong "
         "tools. So I built an agent that first filters those hundred-plus tools "
         "down to the three to five relevant to the query, then compacts the tool "
         "responses before the model ever sees them — cutting token use "
         "dramatically. Along the way I learned a lot about the Model Context "
         "Protocol, tool selection, token budgeting, and response summarization.")

# SLIDE 23 — Closing
s = add("Statement Green")
set_text(ph(s, 0), "Any engineer. Any codebase. Structurally verified root cause in seconds.")
notes(s, "What this system gives you is a debugger that reasons like your best "
         "engineer — but has read every file, knows every call relationship, and "
         "never forgets what changed last week. The graph does the diagnosis. The "
         "LLM does the explaining. And the verifier makes sure no one is guessing. "
         "Thank you.")

# Remove every empty placeholder so no "click to add text" / footer prompts
# show behind the diagrams. All intended content is filled, so anything still
# empty is just a template prompt.
_removed = 0
for _slide in prs.slides:
    for _ph in list(_slide.placeholders):
        if not (_ph.text or "").strip():
            _ph._element.getparent().remove(_ph._element)
            _removed += 1

prs.save(OUT)
print("Saved:", OUT, "—", len(prs.slides._sldIdLst), "slides;",
      _removed, "footers removed")
