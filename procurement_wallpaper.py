"""Generate a desktop wallpaper showing what the procurement system can do
and the keyboard shortcuts it ships with.

Run::

    python procurement_wallpaper.py                 # writes wallpaper_2560x1440.png
    python procurement_wallpaper.py 3840 2160       # writes wallpaper_3840x2160.png
    python procurement_wallpaper.py 1920 1080 out.png

The layout adapts to the requested resolution. No external assets - everything
is drawn with Pillow primitives so the file stays in the repo without binary
dependencies on fonts beyond what the system already ships.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

FEATURES = [
    ("Live data sources",          "Zoll-API · TED · Mock · Google Drive"),
    ("17 curated opportunities",   "VEBEG · Zoll · Troostwijk · Domaine · AMW"),
    ("Briefe-Triage",              "PDF/Drive · Rechnungen · Mahnungen · Widerspruch-Entwurf"),
    ("Scoring engine",             "0-100 attractiveness · Bid-Limit (Handbuch §9)"),
    ("Bargain learner",            "Per-Kategorie Fit (±12) · Marktwert 0.5-1.5x"),
    ("5 specialist agents",        "Generalist · Bargain · Scrap · Edelmetall · Triton"),
    ("SQLite persistence",         "decisions · observations · runs · letters · dispatches"),
    ("Alerts",                     "SMTP-Mail + Webhook (env-konfiguriert)"),
    ("Multi-tab dashboard",        "7 Tabs · Ja/Nein-Cards · Postausgang"),
    ("Chat agent",                 "DeepSeek-V3 · 7 Tools · OpenAI-kompatibel"),
]

HOTKEYS = [
    ("1",          "Tab: Hot Deals"),
    ("2",          "Tab: Pipeline"),
    ("3",          "Tab: Agent-Monitor"),
    ("4",          "Tab: Lerner"),
    ("5",          "Tab: Alerts"),
    ("6",          "Tab: Chat"),
    ("7",          "Tab: Briefe-Triage"),
    ("J",          "Ja / Okay  - Karte akzeptieren"),
    ("N",          "Nein / Widerspruch - verwerfen"),
    ("L",          "Spaeter - Watchlist / Wiedervorlage"),
    ("W",          "Top-Entwurf im Postausgang senden"),
    ("/",          "Filter: Stichwort fokussieren"),
    ("R",          "Reload"),
    ("S",          "Spezialisten neu scannen"),
    ("?",          "Hotkey-Hilfe ein/aus"),
]


# ---------------------------------------------------------------------------
# Colour palette (dark, high-contrast)
# ---------------------------------------------------------------------------

BG_TOP    = (10, 14, 26)
BG_BOTTOM = (24, 30, 52)
FG_TITLE  = (240, 244, 252)
FG_SUB    = (160, 174, 200)
FG_BODY   = (220, 226, 240)
ACCENT    = (90, 168, 255)
ACCENT_2  = (255, 178, 102)
DIVIDER   = (60, 70, 96)
KEY_BG    = (40, 50, 80)
KEY_BORDER= (110, 130, 180)


# ---------------------------------------------------------------------------
# Font loader (best-effort with bundled fallbacks)
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
]
_MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/Library/Fonts/Menlo.ttc",
    "C:/Windows/Fonts/consola.ttf",
]


def _find_font(candidates: list[str]) -> str | None:
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _font(size: int, *, mono: bool = False, bold: bool = False) -> ImageFont.ImageFont:
    path = _find_font(_MONO_CANDIDATES if mono else _FONT_CANDIDATES)
    if not path:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _gradient(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def _key_cap(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int,
             label: str, font: ImageFont.ImageFont):
    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=8, fill=KEY_BG, outline=KEY_BORDER, width=2,
    )
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((x + (width - tw) / 2 - bbox[0],
               y + (height - th) / 2 - bbox[1]),
              label, font=font, fill=FG_TITLE)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render(width: int = 2560, height: int = 1440) -> Image.Image:
    img = _gradient(width, height)
    draw = ImageDraw.Draw(img)

    # Scale text sizes against a 1440p baseline
    s = height / 1440
    f_title  = _font(int(96 * s))
    f_sub    = _font(int(34 * s))
    f_h2     = _font(int(54 * s))
    f_body   = _font(int(30 * s))
    f_body_b = _font(int(30 * s), bold=True)
    f_key    = _font(int(28 * s), mono=True, bold=True)
    f_foot   = _font(int(24 * s))

    margin_x = int(120 * s)
    top      = int(110 * s)

    # ---- Title ----
    draw.text((margin_x, top), "EU Procurement Intelligence",
              font=f_title, fill=FG_TITLE)
    sub_y = top + int(120 * s)
    draw.text((margin_x, sub_y),
              "Multi-Agent-Monitor für Behörden-, Militär-, Feuerwehr- "
              "und Edelmetall-Auktionen",
              font=f_sub, fill=FG_SUB)

    # ---- Divider under title ----
    div_y = sub_y + int(70 * s)
    draw.line([(margin_x, div_y), (width - margin_x, div_y)],
              fill=DIVIDER, width=2)

    # ---- Two columns ----
    col_top = div_y + int(60 * s)
    col_right_x = int(width * 0.58)
    col_left_w = col_right_x - margin_x - int(60 * s)

    # Left column: features
    draw.text((margin_x, col_top), "Was funktioniert",
              font=f_h2, fill=ACCENT)
    fy = col_top + int(90 * s)
    row_h = int(64 * s)
    for label, detail in FEATURES:
        bullet_x = margin_x
        draw.ellipse(
            (bullet_x, fy + int(20 * s),
             bullet_x + int(14 * s), fy + int(34 * s)),
            fill=ACCENT,
        )
        draw.text((bullet_x + int(34 * s), fy), label,
                  font=f_body_b, fill=FG_BODY)
        # detail on the same row, indented
        label_bbox = draw.textbbox((0, 0), label, font=f_body_b)
        detail_x = bullet_x + int(34 * s) + (label_bbox[2] - label_bbox[0]) + int(20 * s)
        draw.text((detail_x, fy), detail, font=f_body, fill=FG_SUB)
        fy += row_h

    # Right column: hotkeys
    draw.text((col_right_x, col_top), "Hotkeys (Browser-fokus)",
              font=f_h2, fill=ACCENT_2)
    hy = col_top + int(90 * s)
    key_w_default = int(76 * s)
    key_h = int(56 * s)
    for label, desc in HOTKEYS:
        # widen the key cap for multi-char labels
        kw = key_w_default + max(0, (len(label) - 1) * int(22 * s))
        _key_cap(draw, col_right_x, hy, kw, key_h, label, f_key)
        text_y = hy + int(8 * s)
        draw.text((col_right_x + kw + int(24 * s), text_y),
                  desc, font=f_body, fill=FG_BODY)
        hy += int(72 * s)

    # ---- Footer ----
    foot_y = height - int(80 * s)
    draw.line([(margin_x, foot_y - int(20 * s)),
               (width - margin_x, foot_y - int(20 * s))],
              fill=DIVIDER, width=2)
    draw.text(
        (margin_x, foot_y),
        "streamlit run procurement_dashboard.py   ·   pytest tests/ -v   "
        "·   PROCUREMENT_OFFLINE=1 für Demo",
        font=f_foot, fill=FG_SUB,
    )

    return img


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    width = 2560
    height = 1440
    out: Path | None = None
    if len(argv) >= 3:
        width = int(argv[1])
        height = int(argv[2])
    if len(argv) >= 4:
        out = Path(argv[3])
    if out is None:
        out = Path(f"wallpaper_{width}x{height}.png")

    img = render(width, height)
    img.save(out, format="PNG", optimize=True)
    print(f"Wrote {out} ({width}x{height})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
