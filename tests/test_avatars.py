"""CG-92 Task 3: the packaged avatar icons, their drift guard, and normalize_avatar."""
from pathlib import Path

import pytest

from chat_gateway.registry import (
    AVATAR_DIR,
    AVATAR_NAMES,
    AVATAR_RAW_BASE,
    normalize_avatar,
)

PUBLISHED = Path(__file__).resolve().parents[1] / "assets" / "avatars" / "png"


def test_twenty_bundled_names_including_the_ones_the_board_leans_on():
    assert len(AVATAR_NAMES) == 20
    for name in ("alert", "home", "phone"):
        assert name in AVATAR_NAMES


def test_packaged_icons_are_byte_identical_to_the_published_ones():
    # The public URL Google fetches is pinned to assets/avatars/png/; the page
    # renders the same bytes same-origin from the package. Two homes, one guard.
    published = sorted(p.name for p in PUBLISHED.glob("*.png"))
    packaged = sorted(p.name for p in AVATAR_DIR.glob("*.png"))
    assert published == packaged
    for n in published:
        assert (PUBLISHED / n).read_bytes() == (AVATAR_DIR / n).read_bytes(), n


@pytest.mark.parametrize(
    "raw,want",
    [
        (None, None),
        ("", None),
        ("alert", "alert"),
        (AVATAR_RAW_BASE + "alert.png", "alert"),
        ("https://x.example/a.png", "https://x.example/a.png"),
    ],
)
def test_normalize_avatar_accepts(raw, want):
    assert normalize_avatar(raw) == want


@pytest.mark.parametrize(
    "raw", ["Alert", "http://x.example/a.png", "../alert", "alert.png", 42,
          "https://", "https://a b", "https://x.example/a\n"]
)
def test_normalize_avatar_refuses_without_coercing(raw):
    with pytest.raises(ValueError, match="a bundled icon name or an https URL"):
        normalize_avatar(raw)
