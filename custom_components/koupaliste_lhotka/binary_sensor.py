"""Binární senzor „otevřeno / zavřeno“.

Proč samostatná entita, když je stejná informace i v atributu senzoru
otevírací doby? Protože atributy se nedají přímo použít v podmínkách
viditelnosti dashboardových karet ani v uživatelském rozhraní automatizací.
Samostatný ``binary_sensor`` je tedy praktičtější a je to i doporučený
postup Home Assistantu (stav patří do stavu, ne do atributu).
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LhotkaConfigEntry
from .const import KEY_IS_OPEN
from .coordinator import LhotkaCoordinator
from .entity import LhotkaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LhotkaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Vytvoří binární senzor."""
    async_add_entities([LhotkaOpenBinarySensor(entry.runtime_data)])


class LhotkaOpenBinarySensor(LhotkaEntity, BinarySensorEntity):
    """True, když je koupaliště právě otevřené."""

    _attr_name = "Otevřeno"

    def __init__(self, coordinator: LhotkaCoordinator) -> None:
        super().__init__(coordinator, KEY_IS_OPEN)

    @property
    def available(self) -> bool:
        # Stejně jako u otevírací doby: rozvrh máme uložený, takže odpověď
        # umíme dát i při nedostupném webu.
        return self.coordinator.has_schedule

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_open_now

    @property
    def icon(self) -> str:
        return "mdi:pool" if self.is_on else "mdi:pool-thermometer"
