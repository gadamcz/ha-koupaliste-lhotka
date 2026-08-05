"""Kontrola obrázků ikony a loga.

Home Assistant od verze 2026.3 bere obrázky ze složky ``brand/`` uvnitř
integrace a má na ně přesné požadavky. Když je nesplní, ikona se prostě
nezobrazí — bez chybové hlášky, takže se to snadno přehlédne.

Test tedy hlídá to, co by jinak nikdo nezkontroloval, a zároveň slouží jako
strojově čitelná dokumentace specifikace. Kdyby se obrázky měnily,
poznáme rozbití hned.

Specifikace (developers.home-assistant.io):

* ikona musí být čtvercová, 256×256 px, hDPI verze 512×512 px,
* u loga musí být kratší strana 128–256 px, u hDPI verze 256–512 px,
* PNG, průhlednost je preferovaná.
"""

from __future__ import annotations

from pathlib import Path

import pytest

png = pytest.importorskip(
    "PIL.Image",
    reason="Kontrola rozměrů vyžaduje Pillow (pip install -r requirements-dev.txt)",
)

BRAND_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "koupaliste_lhotka"
    / "brand"
)


@pytest.mark.parametrize(
    "filename", ["icon.png", "icon@2x.png", "logo.png", "logo@2x.png"]
)
def test_brand_file_exists(filename: str) -> None:
    assert (BRAND_DIR / filename).is_file(), f"chybí brand/{filename}"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("icon.png", 256), ("icon@2x.png", 512)],
)
def test_icon_is_square_with_exact_size(filename: str, expected: int) -> None:
    with png.open(BRAND_DIR / filename) as image:
        assert image.size == (expected, expected)


@pytest.mark.parametrize(
    ("filename", "low", "high"),
    [("logo.png", 128, 256), ("logo@2x.png", 256, 512)],
)
def test_logo_shorter_side_in_range(filename: str, low: int, high: int) -> None:
    with png.open(BRAND_DIR / filename) as image:
        shorter = min(image.size)
        assert low <= shorter <= high, (
            f"brand/{filename}: kratší strana {shorter} px mimo rozsah {low}–{high}"
        )


@pytest.mark.parametrize(
    "filename", ["icon.png", "icon@2x.png", "logo.png", "logo@2x.png"]
)
def test_images_are_png_with_alpha(filename: str) -> None:
    with png.open(BRAND_DIR / filename) as image:
        assert image.format == "PNG"
        assert image.mode in ("RGBA", "LA", "P"), (
            f"brand/{filename}: režim {image.mode} bez průhlednosti"
        )


def test_hdpi_variants_are_exactly_double() -> None:
    """@2x verze musí být přesně dvojnásobek, jinak vzniká rozmazání."""
    for base, hdpi in (("icon.png", "icon@2x.png"), ("logo.png", "logo@2x.png")):
        with png.open(BRAND_DIR / base) as small, png.open(BRAND_DIR / hdpi) as large:
            assert large.size == (small.size[0] * 2, small.size[1] * 2), (
                f"{hdpi} není dvojnásobek {base}"
            )
