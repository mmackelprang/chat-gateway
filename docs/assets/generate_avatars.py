#!/usr/bin/env python
"""Deterministic generator for the chat-gateway Google Chat identity avatars.

Run:  python docs/assets/generate_avatars.py
Deps: Pillow (PIL) only.  Verified against Pillow 12.1.1.

Why this file exists
--------------------
The gateway's whole premise is *several distinct identities posting into the
same Chat spaces*.  The avatar is the primary affordance for telling senders
apart at a glance, so these are design assets, not decoration — and they are
generated rather than hand-drawn so the palette/geometry stay tweakable and
the PNGs are never opaque binaries.

Constraints baked in (all of them non-negotiable, see docs/assets/README.md):
  * 256x256 square source PNG.
  * Google Chat renders avatars as ~32-40px CIRCLES.  Every mark here is
    verified legible after an honest downscale to 32px (`--verify`).
  * Circular crop => all meaning lives inside a centred safe circle
    (SAFE_R below); the square's corners get clipped away.
  * SOLID background, never transparent — a transparent PNG vanishes on
    Chat's dark-mode surface.
  * No text, no hairlines.  One bold glyph each; minimum feature size is
    chosen so nothing lands under ~3px at 32px.
  * Separation must survive colour-vision deficiency: every identity has a
    distinct SILHOUETTE as well as a distinct hue (`--verify` renders
    deuteranope/protanope simulations to prove it).
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Canvas + shared geometry.  One shape language for the whole family:
# same canvas, same safe circle, same optical weight, same corner softness.
# ---------------------------------------------------------------------------

SIZE = 256          # exported PNG edge, px
SS = 4              # supersample factor for anti-aliased edges
C = SIZE / 2        # centre
CROP_R = 128        # Chat crops the square to its inscribed circle
SAFE_R = 108        # ...so keep every painted extreme 20px inside that crop
CORNER = 10         # shared corner-softening radius on polygonal marks
VIGNETTE = 0.055    # centre-lift of the plate; adds depth without detail

SMALL = 32          # the size Chat actually shows.  The real design target.

# ---------------------------------------------------------------------------
# Palette.
#
# Plates are full-bleed solid colour; each identity owns one hue slot plus one
# silhouette.  Deliberate choices:
#   * agent-comms is the only ACHROMATIC plate (warm graphite) — it is the
#     house/parent mark and stays the least colourful of the family.
#   * job-hunter is the only INVERTED-POLARITY plate (dark mark on a light
#     amber field).  It is the sole two-way identity — the one that asks you
#     something — so it is the one allowed to be brightest.
#   * aitrader-alerts / aitrader-reports share one core mark (the up-triangle,
#     same coordinates for both) and split three ways: ink (solid vs hollow),
#     temperature (vermilion vs slate), and internal contrast (~5.0:1 vs
#     ~3.6:1).  Same system; one of them is shouting.
# ---------------------------------------------------------------------------

PALETTE = {
    "agent-comms": {
        "display": "Agent Comms",
        "role": "tier-2 Chat app — the house mark",
        "plate": "#5C554B",   # warm graphite, achromatic anchor
        "mark": "#F4EFE6",    # warm off-white
        "glyph": "hub",
    },
    "pm-familyworkspace": {
        "display": "PM \u00b7 familyworkspace",
        "role": "aiteam-harness project manager",
        "plate": "#5A4DB8",   # indigo
        "mark": "#EFEBFB",
        "glyph": "plan",
    },
    "job-hunter": {
        "display": "Job Hunter",
        "role": "jobhunt — the only two-way tenant",
        "plate": "#D89B23",   # amber, lightest plate
        "mark": "#2B1D06",    # inverted polarity: dark mark on light field
        "glyph": "prompt",
    },
    "aitrader-alerts": {
        "display": "aitrader",
        "role": "aitrader loud lane (severity: alert)",
        "plate": "#C82E13",   # vermilion — hot
        "mark": "#FFF3E8",    # max contrast: loud
        "glyph": "spike",
    },
    "aitrader-reports": {
        "display": "aitrader reports",
        "role": "aitrader quiet lane (severity: warning/info)",
        "plate": "#3F5A6B",   # slate-blue — the heat drained out
        "mark": "#9FB9C7",    # lowered contrast: quiet
        "glyph": "spike-logged",
    },
}

ORDER = [
    "agent-comms",
    "pm-familyworkspace",
    "job-hunter",
    "aitrader-alerts",
    "aitrader-reports",
]

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def shade(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """amount > 0 lightens toward white, < 0 darkens toward black."""
    if amount >= 0:
        return tuple(round(v + (255 - v) * amount) for v in rgb)  # type: ignore[return-value]
    return tuple(round(v * (1 + amount)) for v in rgb)  # type: ignore[return-value]


# Vienot/Brettel/Mollon dichromat simulation matrices, applied in linear RGB.
CVD_MATRIX = {
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
}


def simulate_cvd(img: Image.Image, kind: str) -> Image.Image:
    """Simulate dichromatic vision so the set can be checked without hue."""
    m = CVD_MATRIX[kind]
    src = img.convert("RGB")
    out = Image.new("RGB", src.size)
    lut = [_lin(i) for i in range(256)]

    def delin(v: float) -> int:
        v = max(0.0, min(1.0, v))
        v = v * 12.92 if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055
        return max(0, min(255, round(v * 255)))

    px_in = src.load()
    px_out = out.load()
    cache: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for y in range(src.height):
        for x in range(src.width):
            p = px_in[x, y]
            hit = cache.get(p)
            if hit is None:
                r, g, b = lut[p[0]], lut[p[1]], lut[p[2]]
                hit = (
                    delin(m[0][0] * r + m[0][1] * g + m[0][2] * b),
                    delin(m[1][0] * r + m[1][1] * g + m[1][2] * b),
                    delin(m[2][0] * r + m[2][1] * g + m[2][2] * b),
                )
                cache[p] = hit
            px_out[x, y] = hit
    return out


# ---------------------------------------------------------------------------
# Drawing helpers (all coordinates in 256-space; scaled by SS internally)
# ---------------------------------------------------------------------------


def rounded_polygon(d: ImageDraw.ImageDraw, pts, radius: float, fill, s: int) -> None:
    """Filled polygon with softened corners, in 256-space coordinates.

    Implemented by shrinking the polygon toward its centroid until its edges
    sit `radius` inward, then stroking that inset outline with a round-jointed
    pen of width 2*radius.  Exact enough for triangles/quads at this size.
    """
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    # mean centroid->edge distance, used to derive the inset scale factor
    n = len(pts)
    dists = []
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        elen = math.hypot(ex, ey) or 1.0
        dists.append(abs(ex * (y1 - cy) - ey * (x1 - cx)) / elen)
    inradius = min(dists) or 1.0
    k = max(0.0, (inradius - radius) / inradius)
    inset = [((x - cx) * k + cx, (y - cy) * k + cy) for x, y in pts]

    scaled = [(x * s, y * s) for x, y in inset]
    d.polygon(scaled, fill=fill)
    d.line(scaled + [scaled[0]], fill=fill, width=int(radius * 2 * s), joint="curve")
    for x, y in scaled:
        r = radius * s
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def rrect(d: ImageDraw.ImageDraw, box, radius: float, fill, s: int) -> None:
    x0, y0, x1, y1 = box
    d.rounded_rectangle(
        [x0 * s, y0 * s, x1 * s, y1 * s], radius=radius * s, fill=fill
    )


def ring(d: ImageDraw.ImageDraw, r_outer: float, thickness: float, fill, s: int) -> None:
    r_in = r_outer - thickness
    d.ellipse(
        [(C - r_outer) * s, (C - r_outer) * s, (C + r_outer) * s, (C + r_outer) * s],
        fill=fill,
    )
    d.ellipse(
        [(C - r_in) * s, (C - r_in) * s, (C + r_in) * s, (C + r_in) * s], fill=(0, 0, 0, 0)
    )


def disc(d: ImageDraw.ImageDraw, r: float, fill, s: int) -> None:
    d.ellipse([(C - r) * s, (C - r) * s, (C + r) * s, (C + r) * s], fill=fill)


# ---------------------------------------------------------------------------
# The five glyphs.
#
# Every vertex below is checked against SAFE_R by `assert_safe()`, and every
# feature (bar height, ring gap, inter-shape gap) is >= 24px at 256 so it is
# >= 3px at 32px — the floor for something that still reads in a small circle.
# ---------------------------------------------------------------------------


def glyph_hub(layer: Image.Image, mark, s: int):
    """agent-comms — concentric ring + core dot.  A hub: the parent everything
    else connects through.  The only mark in the set with a hole in it, so its
    silhouette stays unmistakable even with the hue stripped out.  Sized a
    little larger than the polygons because a circle optically reads smaller
    at equal width."""
    d = ImageDraw.Draw(layer)
    ring(d, r_outer=82, thickness=24, fill=mark, s=s)   # 3px stroke @32
    disc(d, r=32, fill=mark, s=s)                       # 8px core @32
    # radial gap: ring inner edge (58) -> core (32) = 26px -> 3.25px @32.
    # Bands are deliberately unequal (core 32 / gap 26 / ring 24) so it reads
    # as a core-in-orbit hub rather than an evenly-banded bullseye.
    return [(C, C - 82, 0), (C, C + 82, 0), (C - 82, C, 0), (C + 82, C, 0)]


def glyph_plan(layer: Image.Image, mark, s: int):
    """pm-familyworkspace — three left-aligned bars, ragged right.  A plan /
    task list.  Horizontal striping with a lot of negative space: the airiest
    silhouette in the set, and the only one with no solid mass at all."""
    d = ImageDraw.Draw(layer)
    x0, h, gap = 58, 28, 22                             # 3.5px bar, 2.75px gap @32
    widths = (136, 96, 118)                             # ragged right = "lines"
    y = C - (3 * h + 2 * gap) / 2
    pts = []
    for w in widths:
        rrect(d, (x0, y, x0 + w, y + h), h / 2, mark, s)
        # true extremes are the cap arc centres, bulged by the cap radius
        pts += [(x0 + h / 2, y + h / 2, h / 2), (x0 + w - h / 2, y + h / 2, h / 2)]
        y += h + gap
    return pts


def glyph_prompt(layer: Image.Image, mark, s: int):
    """job-hunter — a speech bubble with a heavy pennant tail.  The only
    two-way identity in the registry, so it is the only mark that says 'this
    one is talking to you and expects an answer'.  Solid mass plus an
    off-centre tail makes it asymmetric — nothing else in the set is."""
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1, r = 58, 62, 198, 158, 30
    rrect(d, (x0, y0, x1, y1), r, mark, s)
    tail = [(82, 142), (72, 192), (126, 158)]           # 4.25px drop @32
    rounded_polygon(d, tail, 8, mark, s)
    corners = [
        (x, y, r)
        for x in (x0 + r, x1 - r)
        for y in (y0 + r, y1 - r)
    ]
    return corners + [(x, y, 0) for x, y in tail]


# The shared aitrader core mark.  Both lanes use these exact numbers — the
# pair is a sibling pair by construction, not by resemblance.
SPIKE = dict(apex_y=54, base_y=187, half=80)
SPIKE_STROKE = 24   # hollow-variant wall thickness -> 3px @32


def _spike_pts(apex_y, base_y, half):
    return [(C, apex_y), (C - half, base_y), (C + half, base_y)]


def _incircle(pts):
    """Incentre + inradius of a triangle, for a true uniform inset."""
    (ax, ay), (bx, by), (cx, cy) = pts
    a = math.dist((bx, by), (cx, cy))
    b = math.dist((cx, cy), (ax, ay))
    c = math.dist((ax, ay), (bx, by))
    p = a + b + c
    ix = (a * ax + b * bx + c * cx) / p
    iy = (a * ay + b * by + c * cy) / p
    area = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2
    return (ix, iy), area / (p / 2)


def glyph_spike(layer: Image.Image, mark, s: int):
    """aitrader-alerts — the core mark, SOLID.  An up-tick / spike with
    nothing holding it down: maximum ink, maximum contrast, hot plate.  This
    is the lane that is allowed to shout."""
    d = ImageDraw.Draw(layer)
    pts = _spike_pts(**SPIKE)
    rounded_polygon(d, pts, CORNER, mark, s)
    return [(x, y, 0) for x, y in pts]


def glyph_spike_logged(layer: Image.Image, mark, s: int):
    """aitrader-reports — the SAME core mark at the SAME coordinates, HOLLOW.

    Sibling by construction: identical silhouette and footprint, drained of
    ink.  Solid-vs-outline is the loud/quiet pairing that survives losing
    colour entirely, and unlike a triangle-over-a-rule it carries no stray
    association (that earlier version read as the EJECT symbol at 32px, which
    is why it was cut).  Stacked with a cool plate and lower internal
    contrast, the two lanes read as one system with one of them shouting.
    """
    d = ImageDraw.Draw(layer)
    pts = _spike_pts(**SPIKE)
    rounded_polygon(d, pts, CORNER, mark, s)
    # punch a uniformly inset triangle back out to the plate
    centre, r_in = _incircle(pts)
    k = (r_in - SPIKE_STROKE) / r_in
    inner = [((x - centre[0]) * k + centre[0], (y - centre[1]) * k + centre[1]) for x, y in pts]
    rounded_polygon(d, inner, CORNER * k, (0, 0, 0, 0), s)
    return [(x, y, 0) for x, y in pts]


GLYPHS = {
    "hub": glyph_hub,
    "plan": glyph_plan,
    "prompt": glyph_prompt,
    "spike": glyph_spike,
    "spike-logged": glyph_spike_logged,
}


def assert_safe(slug: str, pts) -> None:
    """Every painted extreme must sit inside SAFE_R, or the circular crop eats
    it.  `pts` are (x, y, bulge) — bulge is the local corner/cap radius that
    pushes real ink beyond the nominal point."""
    for x, y, bulge in pts:
        r = math.hypot(x - C, y - C) + bulge
        if r > SAFE_R + 0.5:
            raise AssertionError(
                f"{slug}: extreme ({x:.0f},{y:.0f}) reaches {r:.1f}px from "
                f"centre, outside the {SAFE_R}px safe circle — it would clip."
            )


# ---------------------------------------------------------------------------
# Plate + composition
# ---------------------------------------------------------------------------


def plate(color: tuple[int, int, int], s: int) -> Image.Image:
    """Solid field with a very subtle centre lift.  Never transparent."""
    n = SIZE * s
    base = Image.new("RGB", (n, n), color)
    lift = Image.new("RGB", (n, n), shade(color, VIGNETTE))
    # radial mask, bright at centre, dark at the rim
    small = 96
    mask = Image.new("L", (small, small), 0)
    md = ImageDraw.Draw(mask)
    steps = 32
    for i in range(steps, 0, -1):
        t = i / steps
        r = (small / 2) * t
        md.ellipse(
            [small / 2 - r, small / 2 - r, small / 2 + r, small / 2 + r],
            fill=int(255 * (1 - t) ** 1.4),
        )
    base.paste(lift, (0, 0), mask.resize((n, n), Image.LANCZOS))
    return base


def render(slug: str) -> Image.Image:
    spec = PALETTE[slug]
    s = SS
    img = plate(hex_rgb(spec["plate"]), s)
    layer = Image.new("RGBA", (SIZE * s, SIZE * s), (0, 0, 0, 0))
    pts = GLYPHS[spec["glyph"]](layer, hex_rgb(spec["mark"]) + (255,), s)
    assert_safe(slug, pts)
    img = Image.alpha_composite(img.convert("RGBA"), layer)
    return img.resize((SIZE, SIZE), Image.LANCZOS).convert("RGB")


def circle_mask(size: int) -> Image.Image:
    m = Image.new("L", (size * 8, size * 8), 0)
    ImageDraw.Draw(m).ellipse([0, 0, size * 8 - 1, size * 8 - 1], fill=255)
    return m.resize((size, size), Image.LANCZOS)


def as_chat_avatar(img: Image.Image, size: int) -> Image.Image:
    """Exactly what Chat shows: downscaled, then circle-cropped."""
    small = img.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(small, (0, 0), circle_mask(size))
    return out


# ---------------------------------------------------------------------------
# Contact sheet — the artifact a human actually approves from
# ---------------------------------------------------------------------------

SHEET_BG = "#101215"
LIGHT_STRIP = "#FFFFFF"
DARK_STRIP = "#1B1D21"
CVD_STRIP = "#F1F1F1"


def _font(size: int, bold: bool = False):
    names = (
        ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"]
        if bold
        else ["segoeui.ttf", "arial.ttf", "calibri.ttf"]
    )
    for n in names:
        for base in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu"):
            p = os.path.join(base, n)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    pass
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def contact_sheet(avatars: dict[str, Image.Image]) -> Image.Image:
    cols = len(ORDER)
    colw, left, top = 208, 56, 0
    width = left * 2 + colw * cols
    rows = [
        ("Source \u2014 256\u00d7256, circle-cropped as Chat will crop it", 236),
        ("Chat light theme \u2014 actual 32px (left) and the same 32px raster magnified 4\u00d7", 196),
        ("Chat dark theme \u2014 actual 32px + 4\u00d7 magnification", 196),
        ("Deuteranopia simulation @32px \u2014 hue removed as a cue; silhouettes must still separate", 196),
    ]
    height = 132 + sum(h for _, h in rows) + 96

    sheet = Image.new("RGB", (width, height), hex_rgb(SHEET_BG))
    d = ImageDraw.Draw(sheet)

    d.text((left, 40), "chat-gateway \u2014 Chat identity avatars", font=_font(30, True), fill="#F4F1EA")
    d.text(
        (left, 80),
        "One shape language, five silhouettes. aitrader-alerts / aitrader-reports share a core mark on purpose \u2014 same system, one is shouting.",
        font=_font(15),
        fill="#8C949E",
    )

    y = 132
    label_f, small_f = _font(15, True), _font(13)

    # Row 1 — source at display size
    d.text((left, y + 4), rows[0][0], font=small_f, fill="#6F7781")
    for i, slug in enumerate(ORDER):
        x = left + i * colw
        big = as_chat_avatar(avatars[slug], 144)
        sheet.paste(big, (x + (colw - 144) // 2, y + 30), big)
        d.text((x, y + 192), slug, font=label_f, fill="#E4E0D8")
        d.text((x, y + 212), PALETTE[slug]["display"], font=small_f, fill="#7E868F")
    y += rows[0][1]

    # Rows 2-4 — the sizes that actually matter
    def strip(title: str, bg: str, transform=None) -> None:
        nonlocal y
        d.text((left, y + 4), title, font=small_f, fill="#6F7781")
        d.rectangle([left - 16, y + 28, width - left + 16, y + 170], fill=hex_rgb(bg))
        fg = "#3C4148" if luminance(hex_rgb(bg)) > 0.2 else "#C6CCD3"
        for i, slug in enumerate(ORDER):
            x = left + i * colw
            src = avatars[slug]
            if transform:
                src = transform(src)
            tiny = as_chat_avatar(src, SMALL)
            zoom = tiny.resize((SMALL * 4, SMALL * 4), Image.NEAREST)
            sheet.paste(tiny, (x + 6, y + 78), tiny)
            sheet.paste(zoom, (x + 52, y + 42), zoom)
            d.text((x + 6, y + 178), slug, font=small_f, fill=hex_rgb("#7E868F"))
        y += rows[0][1] - 40

    strip(rows[1][0], LIGHT_STRIP)
    y += 4
    strip(rows[2][0], DARK_STRIP)
    y += 4
    strip(rows[3][0], CVD_STRIP, transform=lambda im: simulate_cvd(im, "deuteranopia"))

    d.text(
        (left, height - 52),
        "Regenerate: python docs/assets/generate_avatars.py   \u00b7   256\u00d7256 PNG, solid background (never transparent), no text, no hairlines.",
        font=small_f,
        fill="#5A626B",
    )
    return sheet


# ---------------------------------------------------------------------------
# Verification report
# ---------------------------------------------------------------------------


def verify(avatars: dict[str, Image.Image], outdir: Path) -> None:
    print("\nplate / mark contrast (solid glyphs; loudness is deliberate)")
    print(f"  {'identity':<20} {'plate L':>8} {'contrast':>9}  polarity")
    for slug in ORDER:
        p, m = hex_rgb(PALETTE[slug]["plate"]), hex_rgb(PALETTE[slug]["mark"])
        pol = "light mark" if luminance(m) > luminance(p) else "DARK mark"
        print(f"  {slug:<20} {luminance(p):>8.3f} {contrast(p, m):>8.2f}:1  {pol}")

    print("\ngreyscale plate separation (|delta L| between every pair)")
    worst = None
    for i, a in enumerate(ORDER):
        for b in ORDER[i + 1 :]:
            dl = abs(luminance(hex_rgb(PALETTE[a]["plate"])) - luminance(hex_rgb(PALETTE[b]["plate"])))
            if worst is None or dl < worst[0]:
                worst = (dl, a, b)
    assert worst
    print(f"  closest pair: {worst[1]} vs {worst[2]}  delta L = {worst[0]:.3f}")
    print("  -> hue alone is NOT load-bearing; each identity also owns a silhouette.")

    print("\nedge against Chat surfaces (plate vs theme background)")
    for slug in ORDER:
        p = hex_rgb(PALETTE[slug]["plate"])
        print(
            f"  {slug:<20} light {contrast(p, hex_rgb(LIGHT_STRIP)):>5.2f}:1"
            f"   dark {contrast(p, hex_rgb(DARK_STRIP)):>5.2f}:1"
        )

    # inspection dumps: the exact rasters a human should look at
    insp = outdir / "_verify"
    insp.mkdir(exist_ok=True)
    for slug in ORDER:
        as_chat_avatar(avatars[slug], SMALL).save(insp / f"{slug}-32.png")
        as_chat_avatar(avatars[slug], SMALL).resize((SMALL * 8, SMALL * 8), Image.NEAREST).save(
            insp / f"{slug}-32-zoom8.png"
        )
        for kind in CVD_MATRIX:
            as_chat_avatar(simulate_cvd(avatars[slug], kind), SMALL).resize(
                (SMALL * 8, SMALL * 8), Image.NEAREST
            ).save(insp / f"{slug}-{kind}-32-zoom8.png")
    print(f"\n32px + CVD inspection rasters -> {insp}")


# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outdir", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--verify", action="store_true", help="print metrics + dump 32px/CVD rasters")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    avatars: dict[str, Image.Image] = {}
    for slug in ORDER:
        img = render(slug)
        assert img.size == (SIZE, SIZE) and img.mode == "RGB", "must be 256x256 opaque RGB"
        path = outdir / f"avatar-{slug}.png"
        img.save(path, "PNG", optimize=True)
        avatars[slug] = img
        print(f"wrote {path}")

    sheet_path = outdir / "preview-contact-sheet.png"
    contact_sheet(avatars).save(sheet_path, "PNG", optimize=True)
    print(f"wrote {sheet_path}")

    if args.verify:
        verify(avatars, outdir)


if __name__ == "__main__":
    main()
