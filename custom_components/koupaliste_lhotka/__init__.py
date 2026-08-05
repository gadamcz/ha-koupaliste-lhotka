"""Integrace Koupaliště Lhotka pro Home Assistant.

Vstupní bod integrace. Home Assistant sem zavolá ve chvíli, kdy uživatel
integraci přidá (nebo při každém startu, pokud už přidaná je).

Životní cyklus:

1. :func:`async_setup_entry` — vytvoří koordinátor, provede první načtení dat
   a nastaví platformy (``sensor``, ``binary_sensor``).
2. Koordinátor pak běží na pozadí a v daném intervalu obnovuje data.
3. :func:`async_unload_entry` — při odebrání integrace vše uklidí.

Integrace **nemá** YAML konfiguraci. Nastavuje se výhradně přes UI
(config flow), což je od HA 2024 doporučený a jediný plně podporovaný způsob.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    ISSUE_PARSE_CHANGED,
    ISSUE_UNREADABLE,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .coordinator import LhotkaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

#: Typový alias: konfigurační záznam, jehož ``runtime_data`` drží koordinátor.
#: Díky němu má editor i mypy jistotu, co v ``entry.runtime_data`` je.
LhotkaConfigEntry = ConfigEntry[LhotkaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LhotkaConfigEntry) -> bool:
    """Nastaví integraci z konfiguračního záznamu."""
    # Interval z UI je validovaný selektorem, ale do .storage se může dostat
    # i jinak (migrace, ruční editace). Nula by znamenala smyčku obnovování
    # bez prodlevy, proto clamp na povolený rozsah.
    try:
        minutes = int(
            entry.options.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES)
        )
    except (TypeError, ValueError):
        minutes = DEFAULT_SCAN_INTERVAL_MINUTES
    minutes = max(MIN_SCAN_INTERVAL_MINUTES, min(MAX_SCAN_INTERVAL_MINUTES, minutes))

    coordinator = LhotkaCoordinator(hass, entry, timedelta(minutes=minutes))

    # První načtení proběhne synchronně: když web není dostupný, Home Assistant
    # nastavení odloží a sám ho později zkusí znovu (ConfigEntryNotReady).
    await coordinator.async_config_entry_first_refresh()

    # runtime_data je moderní náhrada za hass.data[DOMAIN][entry_id] —
    # data mají stejnou životnost jako konfigurační záznam a uklidí se sama.
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Změna nastavení v UI (interval) → znovunačtení integrace.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: LhotkaConfigEntry) -> bool:
    """Odstraní integraci (a s ní entity i běžící úlohy)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: LhotkaConfigEntry) -> None:
    """Znovu načte integraci po změně nastavení."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: LhotkaConfigEntry) -> None:
    """Uklidí po odebrání integrace.

    Hlášky v *Nastavení → Systém → Opravy* nezmizí samy — bez tohoto úklidu
    by uživateli zůstala v systému hláška o integraci, kterou už nemá.
    """
    for issue_id in (ISSUE_UNREADABLE, ISSUE_PARSE_CHANGED):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
