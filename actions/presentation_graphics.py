"""
presentation_graphics.py — High-quality slide visuals rendered with Pillow.

python-pptx native shapes look amateur; these PNG diagrams embed as crisp visuals.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# JARVIS corporate palette (matches presentation_create._THEME)
_BG_DARK = (0x0B, 0x1F, 0x3A)
_BG_PANEL = (0x12, 0x2B, 0x45)
_BG_LIGHT = (0xF4, 0xF7, 0xFA)
_ACCENT = (0x00, 0xB4, 0xD8)
_ACCENT2 = (0x00, 0x7A, 0x99)
_WHITE = (0xFF, 0xFF, 0xFF)
_TEXT_DARK = (0x1A, 0x1A, 0x2E)
_MUTED = (0x5A, 0x6A, 0x7A)

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = _FONT_CANDIDATES if bold else _FONT_CANDIDATES[1:2] + _FONT_CANDIDATES[3:5]
    if bold:
        paths = [_FONT_CANDIDATES[0], _FONT_CANDIDATES[2], _FONT_CANDIDATES[3]]
    else:
        paths = [_FONT_CANDIDATES[1], _FONT_CANDIDATES[4]]
    for path in paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _truncate(text: str, max_chars: int) -> str:
    text = str(text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill,
    outline=None,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _vertical_gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    w, h = size
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color=_ACCENT,
    width: int = 4,
) -> None:
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    head = 14
    for da in (2.6, -2.6):
        ax = x2 - head * math.cos(angle + da)
        ay = y2 - head * math.sin(angle + da)
        draw.line([(x2, y2), (int(ax), int(ay))], fill=color, width=width)


def _wrap_label(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    words = text.split()
    if not words:
        return ""
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines[:2])


def render_architecture_flow(
    nodes: list[str],
    width: int = 1600,
    height: int = 900,
    *,
    title: str = "",
) -> bytes:
    """Horizontal architecture flow — professional boxes + arrows."""
    nodes = [_truncate(n, 28) for n in (nodes or ["Input", "Core", "Output"])[:6]]
    n = len(nodes)
    img = _vertical_gradient((width, height), _BG_PANEL, _BG_DARK)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (24, 24, width - 24, height - 24), 20, None, _ACCENT, 3)

    if title:
        tf = _load_font(36, bold=True)
        draw.text((48, 40), _truncate(title, 48), fill=_WHITE, font=tf)

    margin_x, margin_y = 80, 120 if title else 80
    usable_w = width - margin_x * 2
    usable_h = height - margin_y - 80
    box_h = min(140, usable_h - 40)
    gap = 70
    box_w = max(120, (usable_w - gap * (n - 1)) // n)
    y = margin_y + (usable_h - box_h) // 2
    font = _load_font(26, bold=True)
    small = _load_font(18)

    cx_list: list[tuple[int, int, int, int]] = []
    for i, label in enumerate(nodes):
        x = margin_x + i * (box_w + gap)
        fill = _ACCENT if i % 2 == 0 else _ACCENT2
        _rounded_rect(draw, (x, y, x + box_w, y + box_h), 16, fill, _WHITE, 2)
        wrapped = _wrap_label(draw, label, font, box_w - 24)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=4, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = x + (box_w - tw) // 2
        ty = y + (box_h - th) // 2
        draw.multiline_text((tx, ty), wrapped, fill=_WHITE, font=font, spacing=4, align="center")
        cx_list.append((x, y, x + box_w, y + box_h))

    mid_y = y + box_h // 2
    for i in range(len(cx_list) - 1):
        x1 = cx_list[i][2] + 4
        x2 = cx_list[i + 1][0] - 4
        _draw_arrow(draw, x1, mid_y, x2, mid_y)

    # Subtle step numbers
    for i, (x1, y1, x2, y2) in enumerate(cx_list):
        draw.ellipse((x1 + 10, y1 + 10, x1 + 34, y1 + 34), fill=_BG_DARK, outline=_WHITE, width=2)
        draw.text((x1 + 16, y1 + 12), str(i + 1), fill=_WHITE, font=small)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_vertical_pipeline(
    nodes: list[str],
    width: int = 1200,
    height: int = 1400,
    *,
    title: str = "",
) -> bytes:
    """Vertical pipeline for diagram slides."""
    nodes = [_truncate(n, 32) for n in (nodes or ["Input", "Process", "Output"])[:6]]
    n = len(nodes)
    img = _vertical_gradient((width, height), _BG_PANEL, _BG_DARK)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (24, 24, width - 24, height - 24), 20, None, _ACCENT, 3)

    if title:
        tf = _load_font(40, bold=True)
        draw.text((48, 36), _truncate(title, 40), fill=_WHITE, font=tf)

    margin_x = 100
    top = 120 if title else 60
    bottom = 60
    gap = 36
    box_w = width - margin_x * 2
    usable_h = height - top - bottom
    box_h = max(80, (usable_h - gap * (n - 1)) // n)
    font = _load_font(28, bold=True)

    centers: list[tuple[int, int]] = []
    for i, label in enumerate(nodes):
        y = top + i * (box_h + gap)
        fill = _ACCENT if i % 2 == 0 else _ACCENT2
        _rounded_rect(draw, (margin_x, y, margin_x + box_w, y + box_h), 14, fill, _WHITE, 2)
        wrapped = _wrap_label(draw, label, font, box_w - 40)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=4, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.multiline_text(
            (margin_x + (box_w - tw) // 2, y + (box_h - th) // 2),
            wrapped,
            fill=_WHITE,
            font=font,
            spacing=4,
            align="center",
        )
        centers.append((margin_x + box_w // 2, y + box_h))

    for i in range(len(centers) - 1):
        x, y1 = centers[i]
        _, y2_next = centers[i + 1]
        y2 = y2_next - box_h
        _draw_arrow(draw, x, y1 + 4, x, y2 - 4)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_stack_pyramid(
    layers: list[str],
    width: int = 1200,
    height: int = 1000,
) -> bytes:
    """Technology stack pyramid."""
    layers = [_truncate(l, 36) for l in (layers or ["App", "Services", "Data"])[:6]]
    n = len(layers)
    img = Image.new("RGB", (width, height), _BG_LIGHT)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (20, 20, width - 20, height - 20), 18, _WHITE, _ACCENT, 3)

    font = _load_font(24, bold=True)
    pad = 28
    layer_h = (height - pad * 2 - (n - 1) * 10) // n
    max_w = width - pad * 2

    for i, label in enumerate(layers):
        shrink = i * (max_w * 0.07)
        lw = int(max_w - shrink * 2)
        lx = (width - lw) // 2
        ly = pad + i * (layer_h + 10)
        fill = (_ACCENT, _ACCENT2, _BG_DARK)[i % 3]
        _rounded_rect(draw, (lx, ly, lx + lw, ly + layer_h), 12, fill, _WHITE, 2)
        wrapped = _wrap_label(draw, label, font, lw - 30)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=4, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.multiline_text(
            (lx + (lw - tw) // 2, ly + (layer_h - th) // 2),
            wrapped,
            fill=_WHITE,
            font=font,
            spacing=4,
            align="center",
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_devops_pipeline(
    steps: list[str] | None = None,
    width: int = 1400,
    height: int = 500,
) -> bytes:
    steps = [_truncate(s, 16) for s in (steps or ["Build", "Test", "Deploy", "Monitor"])]
    img = _vertical_gradient((width, height), _BG_PANEL, _BG_DARK)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (16, 16, width - 16, height - 16), 16, None, _ACCENT, 2)

    n = len(steps)
    margin = 50
    gap = 40
    box_w = (width - margin * 2 - gap * (n - 1)) // n
    box_h = height - 120
    y = 60
    font = _load_font(26, bold=True)

    rects: list[tuple[int, int, int, int]] = []
    for i, step in enumerate(steps):
        x = margin + i * (box_w + gap)
        fill = _ACCENT if i % 2 == 0 else _ACCENT2
        _rounded_rect(draw, (x, y, x + box_w, y + box_h), 12, fill, _WHITE, 2)
        bbox = draw.textbbox((0, 0), step, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((x + (box_w - tw) // 2, y + (box_h - th) // 2), step, fill=_WHITE, font=font)
        rects.append((x, y, x + box_w, y + box_h))

    mid_y = y + box_h // 2
    for i in range(len(rects) - 1):
        _draw_arrow(draw, rects[i][2] + 6, mid_y, rects[i + 1][0] - 6, mid_y)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_security_panel(
    labels: list[str] | None = None,
    width: int = 1200,
    height: int = 900,
) -> bytes:
    labels = [_truncate(l, 40) for l in (labels or ["Encryption", "RBAC", "Audit logs"])[:4]]
    img = _vertical_gradient((width, height), _BG_DARK, (0x05, 0x14, 0x28))
    draw = ImageDraw.Draw(img)

    cx, cy = width // 2, height // 2 - 40
    shield = [
        (cx, cy - 180),
        (cx + 140, cy - 80),
        (cx + 120, cy + 100),
        (cx, cy + 180),
        (cx - 120, cy + 100),
        (cx - 140, cy - 80),
    ]
    draw.polygon(shield, fill=_ACCENT, outline=_WHITE)
    draw.polygon(
        [(cx, cy - 120), (cx + 90, cy - 50), (cx + 75, cy + 60), (cx, cy + 120),
         (cx - 75, cy + 60), (cx - 90, cy - 50)],
        fill=_ACCENT2,
    )
    lock_font = _load_font(48, bold=True)
    draw.text((cx - 18, cy - 30), "🔒", fill=_WHITE, font=lock_font)

    font = _load_font(22)
    y = height - 220
    for label in labels:
        _rounded_rect(draw, (80, y, width - 80, y + 52), 10, (0x18, 0x35, 0x55), _ACCENT, 1)
        draw.text((100, y + 14), f"•  {label}", fill=_WHITE, font=font)
        y += 62

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_cloud_infra(
    labels: list[str] | None = None,
    width: int = 1200,
    height: int = 900,
) -> bytes:
    labels = [_truncate(l, 24) for l in (labels or ["Kubernetes", "Multi-cloud", "Auto-scale"])[:4]]
    img = Image.new("RGB", (width, height), _BG_LIGHT)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (20, 20, width - 20, height - 20), 18, _WHITE, _ACCENT, 3)

    font = _load_font(24, bold=True)
    y = 80
    for i, label in enumerate(labels):
        cloud_y = y + i * 200
        _draw_cloud(draw, 120, cloud_y, 320, 120, _ACCENT2, _ACCENT)
        draw.text((480, cloud_y + 42), label, fill=_TEXT_DARK, font=font)
        if i < len(labels) - 1:
            _draw_arrow(draw, 280, cloud_y + 130, 280, cloud_y + 170, _ACCENT2, 3)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_cloud(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    fill,
    outline,
) -> None:
    r = h // 3
    draw.ellipse((x, y + r, x + w, y + h), fill=fill, outline=outline, width=2)
    draw.ellipse((x + w // 4, y, x + w * 3 // 4, y + h * 2 // 3), fill=fill, outline=outline, width=2)
    draw.ellipse((x + w // 2, y + r // 2, x + w, y + h * 3 // 4), fill=fill, outline=outline, width=2)


def render_feature_cards(
    labels: list[str],
    width: int = 1200,
    height: int = 900,
) -> bytes:
    """Card grid for generic content slides — replaces circle icon grid."""
    items = [_truncate(str(x).split(":")[0], 22) for x in (labels or ["AI", "Voice", "Tools", "Ops"])[:4]]
    while len(items) < 4:
        items.append("Feature")

    img = Image.new("RGB", (width, height), _BG_LIGHT)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (20, 20, width - 20, height - 20), 18, _WHITE, _ACCENT, 3)

    cols, rows = 2, 2
    pad = 40
    cw = (width - pad * 3) // cols
    ch = (height - pad * 3) // rows
    font = _load_font(26, bold=True)
    icons = ["🎙", "🧠", "⚙", "☁"]

    for i, label in enumerate(items):
        col, row = i % cols, i // cols
        x = pad + col * (cw + pad)
        y = pad + row * (ch + pad)
        fill = _ACCENT if i % 2 == 0 else _ACCENT2
        _rounded_rect(draw, (x, y, x + cw, y + ch), 16, fill, _WHITE, 2)
        icon_font = _load_font(52, bold=True)
        draw.text((x + 24, y + 24), icons[i % len(icons)], fill=_WHITE, font=icon_font)
        wrapped = _wrap_label(draw, label, font, cw - 48)
        draw.multiline_text((x + 24, y + ch - 90), wrapped, fill=_WHITE, font=font, spacing=4)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def pick_visual_png(item: dict) -> bytes:
    """Choose the best diagram renderer for a slide item."""
    title = str(item.get("title") or "").lower()
    hint = str(item.get("visual_hint") or "").lower()
    layout = str(item.get("layout") or "").lower()
    bullets = item.get("bullets") or []

    if layout == "stack" or any(k in title for k in ("stack", "technology", "components")):
        layers = item.get("stack_layers") or [
            str(b).split(":")[0].strip()[:36] for b in bullets if str(b).strip()
        ]
        return render_stack_pyramid(layers or ["Application", "Services", "Infrastructure"])

    if layout == "diagram" or any(k in title for k in ("architecture", "pipeline", "flow", "overview")):
        nodes = item.get("diagram_nodes") or [
            str(b).split(":")[0].strip()[:32] for b in bullets if str(b).strip()
        ]
        if len(nodes) < 3:
            nodes = ["Voice / UI", "JARVIS Core", "Tools & APIs", "Response"]
        return render_architecture_flow(nodes, title=str(item.get("title") or ""))

    if any(k in hint + title for k in ("security", "shield", "governance", "compliance")):
        return render_security_panel([
            str(b).split(":")[0].strip() for b in bullets[:4]
        ] or None)

    if any(k in hint + title for k in ("devops", "ci/cd", "automation", "deploy")):
        steps = [str(b).split(":")[0].strip()[:16] for b in bullets[:4]]
        return render_devops_pipeline(steps or None)

    if any(k in hint + title for k in ("cloud", "kubernetes", "infra", "multi-cloud")):
        return render_cloud_infra([
            str(b).split(":")[0].strip() for b in bullets[:4]
        ] or None)

    return render_feature_cards(bullets or ["AI", "Voice", "Automation", "Integration"])
