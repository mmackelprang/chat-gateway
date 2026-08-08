# Switchboard — brand guide

**Proposed display name:** Switchboard
**Tagline:** *One gateway, every agent.*

## Why this name

The gateway owns identities, delivery, threading, and routing — and deliberately nothing else.
That is a telephone **switchboard**: it connects callers without ever joining the conversation
(hard rule #1: transport, never schemas). The vintage-telephony name also sits comfortably next
to the household's RotaryPhone project — a nice accidental family resemblance.

**Alternates considered:** *Relay* (accurate, heavily used in the industry), *Trunkline*
(telephony-correct, obscure), *Operator* (charming, collides with k8s terminology).

## The mark

A hub-and-spoke: four tenant nodes wired through one central chat bubble. The bubble is the only
white element — the gateway is the one thing all traffic passes through, and the only thing that
speaks Chat.

## Palette

| Color | Hex | Role |
|---|---|---|
| Indigo | `#3949AB` | Background / primary brand color |
| Wire Teal | `#4FD1C5` | Tenant nodes, accents, links |
| Line Lavender | `#C9D2FF` | Spokes, secondary strokes |
| White | `#FFFFFF` | The bubble, text on dark |

## Voice

Infrastructure voice: quiet, exact, boring on purpose. The gateway brand never claims features —
it claims guarantees (delivery, identity, opt-in/opt-out).

## Files in this directory

| File | Use |
|---|---|
| `logo.svg` | Full lockup (mark + wordmark + tagline) for README headers and docs |
| `favicon.svg` | Square app mark, scales from 16px to full size |
| `favicon.ico` | Legacy multi-size favicon (16/32/48) for browsers that want `.ico` |
| `favicon-32.png` | 32px PNG favicon |
| `apple-touch-icon.png` | 180px iOS home-screen icon |
| `icon-512.png` | Large raster for app manifests, social cards, stores |

### Wiring the favicon into a web page

```html
<link rel="icon" href="/branding/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/branding/favicon.ico" sizes="16x16 32x32 48x48">
<link rel="apple-touch-icon" href="/branding/apple-touch-icon.png">
```

### README header

```markdown
<p align="center"><img src="branding/logo.svg" alt="Switchboard" width="520"></p>
```

## Typography

Wordmark: **Montserrat Bold** (falls back to Segoe UI / system sans). Body text: the platform
default sans. For code-adjacent surfaces, any monospace at hand — the brand doesn't pin one.

The logo's wordmark is live SVG text, so it renders with whatever sans is installed; if you want
it pixel-identical everywhere, convert the text to outlines in any SVG editor and re-save.

## Dark and light backgrounds

The tile carries its own background, so both `logo.svg` and `favicon.svg` work unchanged on
light or dark pages. The wordmark in `logo.svg` is dark ink — on a dark page, either rely on the
tile alone (use `favicon.svg`) or restyle the two `<text>` fills to `#F0F2F5`.

---
*Generated as a proposal — names, colors, and marks are suggestions to accept, tweak, or reject.*
