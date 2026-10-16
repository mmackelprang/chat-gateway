"""Build the chat-room avatar set: SVG sources, 256px PNGs, a preview sheet, README.

One source of truth — the ICONS table below. Re-run after editing it:

    python assets/avatars/build.py

Needs PyMuPDF (`fitz`, renders SVG → PNG) and Pillow (preview sheet). These are
build-time tools only; the gateway does not import or depend on them.

Design rules, so additions stay consistent:
- 256×256 viewBox, full-bleed coloured CIRCLE: Google Chat crops avatars to a
  circle, so the corners are transparent rather than cropped away.
- Glyph lives inside a ~70px radius of the centre (safe under the crop), drawn
  as 14px round-capped strokes, plus a few solid fills (`class="f"` in the
  table, expanded to fill attributes by `svg_for`).
- Glyph colour is white, or near-black on light backgrounds, for contrast.
"""

from __future__ import annotations

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVG_DIR = HERE / "svg"
PNG_DIR = HERE / "png"
# CG-92: the same PNGs also ship inside the package, so the admin page renders
# them same-origin. PNG_DIR stays the published home (its raw URLs must not move);
# tests/test_avatars.py fails if the two ever differ.
PKG_PNG_DIR = HERE.parents[1] / "src" / "chat_gateway" / "static" / "admin" / "avatars"
RAW_BASE = "https://raw.githubusercontent.com/mmackelprang/chat-gateway/main/assets/avatars/png"
WHITE, DARK = "#FFFFFF", "#202124"


def _gear() -> str:
    teeth = []
    for i in range(8):
        a = math.radians(i * 45)
        x1, y1 = 128 + 50 * math.cos(a), 128 + 50 * math.sin(a)
        x2, y2 = 128 + 66 * math.cos(a), 128 + 66 * math.sin(a)
        teeth.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     'stroke-width="20" stroke-linecap="butt"/>')
    return ('<circle cx="128" cy="128" r="44"/><circle cx="128" cy="128" r="16"/>'
            + "".join(teeth))


# name: (title, use, background, glyph colour, glyph markup)
# Glyph markup inherits stroke=<glyph colour>, fill=none; class="f" marks a solid fill.
ICONS: dict[str, tuple[str, str, str, str, str]] = {
    "alert": ("Alert", "Loud lane: things that need action now", "#D93025", WHITE,
              '<path d="M128 74c-25 0-42 20-42 46v24l-14 20h112l-14-20v-24c0-26-17-46-42-46z"/>'
              '<line x1="128" y1="62" x2="128" y2="74"/>'
              '<path d="M112 178a16 16 0 0 0 32 0"/>'),
    "warning": ("Warning", "Degraded, watch it", "#F2A600", DARK,
                '<path d="M128 70L190 178H66Z"/>'
                '<line x1="128" y1="108" x2="128" y2="140"/>'
                '<circle class="f" cx="128" cy="160" r="9"/>'),
    "info": ("Info", "Quiet lane: status, digests, no action", "#1A73E8", WHITE,
             '<circle class="f" cx="128" cy="80" r="11"/>'
             '<path d="M110 114h18v64"/><line x1="106" y1="180" x2="150" y2="180"/>'),
    "resolved": ("Resolved", "All-clear threads and closed incidents", "#188038", WHITE,
                 '<polyline points="80,132 114,166 178,96" stroke-width="18"/>'),
    "heartbeat": ("Heartbeat", "Dead-man checks and liveness", "#EC407A", WHITE,
                  '<polyline points="62,132 96,132 112,98 138,170 156,112 168,132 194,132"/>'),
    "report": ("Report", "Scheduled reports and summaries", "#3949AB", WHITE,
               '<rect class="f" x="84" y="134" width="22" height="42" rx="4"/>'
               '<rect class="f" x="117" y="96" width="22" height="80" rx="4"/>'
               '<rect class="f" x="150" y="116" width="22" height="60" rx="4"/>'
               '<line x1="72" y1="188" x2="184" y2="188"/>'),
    "trading": ("Trading", "Markets, positions, fills", "#00897B", WHITE,
                '<line x1="104" y1="68" x2="104" y2="188"/>'
                '<rect class="f" x="90" y="94" width="28" height="62" rx="4"/>'
                # hollow candle: wick drawn as two stubs so it does not cross the body
                '<line x1="152" y1="80" x2="152" y2="108"/><line x1="152" y1="154" x2="152" y2="178"/>'
                '<rect x="138" y="108" width="28" height="46" rx="4" stroke-width="10"/>'),
    "jobs": ("Jobs", "Job search, applications, careers", "#5D4037", WHITE,
             '<rect x="70" y="104" width="116" height="78" rx="12"/>'
             '<path d="M106 104V92a10 10 0 0 1 10-10h24a10 10 0 0 1 10 10v12"/>'
             '<line x1="70" y1="138" x2="186" y2="138"/>'),
    "agent": ("Agent", "AI agents and automated assistants", "#8E24AA", WHITE,
              '<rect x="78" y="98" width="100" height="80" rx="18"/>'
              '<circle class="f" cx="108" cy="134" r="10"/><circle class="f" cx="148" cy="134" r="10"/>'
              '<line x1="112" y1="158" x2="144" y2="158"/>'
              '<line x1="128" y1="98" x2="128" y2="80"/><circle class="f" cx="128" cy="72" r="8"/>'),
    "deploy": ("Deploy", "Releases, rollouts, deploys", "#263238", WHITE,
               '<path d="M128 62c24 20 34 50 28 88h-56c-6-38 4-68 28-88z"/>'
               '<circle cx="128" cy="108" r="11" stroke-width="10"/>'
               '<path d="M100 128l-20 30h22M156 128l20 30h-22"/>'
               '<path d="M116 166l12 26 12-26"/>'),
    "build": ("Build", "CI, builds, jobs and pipelines", "#78909C", WHITE, _gear()),
    "security": ("Security", "Auth, access, secrets, audits", "#1B5E20", WHITE,
                 '<path d="M128 64l54 20v40c0 32-22 56-54 70-32-14-54-38-54-70V84z"/>'
                 '<polyline points="104,128 122,146 154,112"/>'),
    "database": ("Database", "Data, storage, backups", "#0097A7", WHITE,
                 '<ellipse cx="128" cy="86" rx="50" ry="17"/>'
                 '<path d="M78 86v84c0 9 22 17 50 17s50-8 50-17V86"/>'
                 '<path d="M78 128c0 9 22 17 50 17s50-8 50-17"/>'),
    "calendar": ("Calendar", "Schedules, reminders, due dates", "#F4511E", WHITE,
                 '<rect x="72" y="84" width="112" height="98" rx="12"/>'
                 '<line x1="72" y1="116" x2="184" y2="116"/>'
                 '<line x1="104" y1="68" x2="104" y2="96"/><line x1="152" y1="68" x2="152" y2="96"/>'
                 '<circle class="f" cx="104" cy="142" r="7"/><circle class="f" cx="128" cy="142" r="7"/>'
                 '<circle class="f" cx="152" cy="142" r="7"/><circle class="f" cx="104" cy="164" r="7"/>'
                 '<circle class="f" cx="128" cy="164" r="7"/>'),
    "home": ("Home", "Family, household, home automation", "#7CB342", DARK,
             '<path d="M66 128l62-54 62 54"/><path d="M86 114v70h84v-70"/>'
             '<path d="M116 184v-34h24v34"/>'),
    "messages": ("Messages", "Conversations, inbound replies, chat bridges", "#039BE5", WHITE,
                 '<path d="M78 82h100a14 14 0 0 1 14 14v52a14 14 0 0 1-14 14h-58l-30 24v-24H78'
                 'a14 14 0 0 1-14-14V96a14 14 0 0 1 14-14z"/>'
                 '<circle class="f" cx="102" cy="122" r="8"/><circle class="f" cx="128" cy="122" r="8"/>'
                 '<circle class="f" cx="154" cy="122" r="8"/>'),
    "finance": ("Finance", "Money, billing, budgets, P&L", "#C9A227", DARK,
                '<circle cx="128" cy="128" r="62"/>'
                '<path d="M150 102c-8-10-34-12-40 2-7 16 42 16 40 36-2 18-32 18-44 6"/>'
                '<line x1="128" y1="80" x2="128" y2="176"/>'),
    "phone": ("Phone", "Telephony, calls, voicemail", "#AD1457", WHITE,
              # classic handset, solid: a dial read as noise at avatar size
              '<path class="f" transform="translate(128 128) scale(0.72) translate(-125 -140)" '
              'd="M100 70c8 0 12 4 14 10l10 24c2 6 0 12-5 16l-12 10c8 18 22 32 40 40'
              'l10-12c4-5 10-7 16-5l24 10c6 2 10 6 10 14v14c0 10-8 18-18 18C122 209 47 134 47 88'
              'c0-10 8-18 18-18z"/>'),
    "server": ("Server", "Infrastructure, hosts, homelab", "#455A64", WHITE,
               '<rect x="74" y="72" width="108" height="30" rx="8"/>'
               '<rect x="74" y="113" width="108" height="30" rx="8"/>'
               '<rect x="74" y="154" width="108" height="30" rx="8"/>'
               '<circle class="f" cx="96" cy="87" r="6"/><circle class="f" cx="96" cy="128" r="6"/>'
               '<circle class="f" cx="96" cy="169" r="6"/>'
               '<line x1="134" y1="87" x2="164" y2="87"/><line x1="134" y1="128" x2="164" y2="128"/>'
               '<line x1="134" y1="169" x2="164" y2="169"/>'),
    "search": ("Search", "Research, monitoring, discovery", "#5E35B1", WHITE,
               '<circle cx="116" cy="116" r="40"/>'
               '<line x1="146" y1="146" x2="182" y2="182" stroke-width="20"/>'),
}


def svg_for(name: str) -> str:
    title, _use, bg, fg, glyph = ICONS[name]
    # Solid fills as plain attributes, not a <style> rule: renderers (and Chat's
    # own image proxy) vary in CSS support, attributes are universal.
    glyph = glyph.replace('class="f"', f'fill="{fg}" stroke="none"')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
        f"<title>{title}</title>"
        f'<circle cx="128" cy="128" r="128" fill="{bg}"/>'
        f'<g fill="none" stroke="{fg}" stroke-width="14" stroke-linecap="round" '
        f'stroke-linejoin="round">{glyph}</g></svg>\n'
    )


def main() -> None:
    import fitz  # PyMuPDF
    from PIL import Image, ImageDraw, ImageFont

    SVG_DIR.mkdir(exist_ok=True)
    PNG_DIR.mkdir(exist_ok=True)
    PKG_PNG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        svg = svg_for(name)
        (SVG_DIR / f"{name}.svg").write_text(svg, encoding="utf-8", newline="\n")
        doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
        pix = doc[0].get_pixmap(alpha=True)  # 256×256 at the SVG's native size
        pix.save(str(PNG_DIR / f"{name}.png"))
        pix.save(str(PKG_PNG_DIR / f"{name}.png"))
        doc.close()

    cols, cell, pad = 5, 160, 24
    rows = math.ceil(len(ICONS) / cols)
    sheet = Image.new("RGBA", (cols * cell, rows * (cell + pad)), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for i, name in enumerate(ICONS):
        img = Image.open(PNG_DIR / f"{name}.png").convert("RGBA").resize((112, 112), Image.LANCZOS)
        x, y = (i % cols) * cell, (i // cols) * (cell + pad)
        sheet.alpha_composite(img, (x + 24, y + 16))
        w = draw.textlength(name, font=font)
        draw.text((x + (cell - w) / 2, y + 136), name, fill=(32, 33, 36, 255), font=font)
    sheet.convert("RGB").save(HERE / "preview.png", optimize=True)

    lines = [
        "# Chat-room avatars",
        "",
        "Circular avatars for Google Chat incoming webhooks and Chat apps. Every app",
        "registered with the gateway can pick one, so a shared space reads at a glance.",
        "",
        "![preview](preview.png)",
        "",
        "## Using one",
        "",
        "In the Chat space: **Apps & integrations → Webhooks → Add webhook**, then paste",
        "the PNG URL below into **Avatar URL**. The name and avatar are fixed when the",
        "webhook is created; changing them later means a new webhook (see",
        "`docs/registering-an-app.md`).",
        "",
        "URLs serve from `main` of this public repository; they work once this",
        "directory is merged.",
        "",
        "| | Name | Use for | Avatar URL |",
        "|---|---|---|---|",
    ]
    for name, (title, use, _bg, _fg, _g) in ICONS.items():
        lines.append(f'| <img src="png/{name}.png" width="40"> | {title} | {use} | '
                     f"`{RAW_BASE}/{name}.png` |")
    lines += [
        "",
        "## Changing or adding one",
        "",
        "Edit the `ICONS` table in `build.py` and run `python assets/avatars/build.py`.",
        "It rewrites `svg/`, `png/`, `preview.png` and this README. It needs PyMuPDF",
        "and Pillow, which are build-time tools only. Keep glyphs within about 70px of",
        "the centre, because Chat crops avatars to a circle.",
        "",
        "The PNGs are written to a second place too, `src/chat_gateway/static/admin/avatars/`,",
        "so the admin console can show them same-origin. `png/` stays the published home",
        "(the URLs above must not move); `tests/test_avatars.py` fails if the two differ.",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"built {len(ICONS)} avatars -> {SVG_DIR.name}/, {PNG_DIR.name}/, preview.png, README.md")


if __name__ == "__main__":
    main()
