"""Diagnostický výpis pro hlášení problémů.

Uživatel může v Home Assistantu u integrace kliknout na *Stáhnout
diagnostiku* a vzniklý JSON přiložit k issue na GitHubu. Šetří to jedno
kolečko dotazů „a co ti to vlastně píše“.

Bezpečnost: integrace nepracuje s žádnými přihlašovacími údaji ani osobními
daty, takže tu není co skrývat. Přesto sem záměrně nedáváme surové HTML
z webu — bylo by objemné a mohlo by obsahovat nesouvisející obsah stránky.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import LhotkaConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LhotkaConfigEntry
) -> dict[str, Any]:
    """Vrátí stav integrace ve strojově čitelné podobě."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": {
            "options": dict(entry.options),
            "version": entry.version,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "consecutive_failures": coordinator.consecutive_failures,
            "total_failures": coordinator.total_failures,
            "last_error": coordinator.last_error,
        },
        "live": {
            "water_temp": data.live.water_temp if data else None,
            "air_temp": data.live.air_temp if data else None,
            "occupancy": data.live.occupancy if data else None,
            "capacity": data.live.capacity if data else None,
            "badge_open": data.live.badge_open if data else None,
            "updated": data.live_updated.isoformat()
            if data and data.live_updated
            else None,
        },
        "schedule": {
            "rows": len(data.schedule) if data else 0,
            "updated": data.schedule_updated.isoformat()
            if data and data.schedule_updated
            else None,
            "entries": [
                {
                    "month": item.month,
                    "days": item.days_label,
                    "hours": item.hours_label,
                }
                for item in (data.schedule if data else [])
            ],
        },
        "computed": {
            "is_open_now": coordinator.is_open_now,
        },
    }
