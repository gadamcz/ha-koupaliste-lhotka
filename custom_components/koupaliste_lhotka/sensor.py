"""Senzory integrace Koupaliště Lhotka.

Vytvářené entity (názvy jsou krátké, Home Assistant před ně sám doplní
název zařízení — „Koupaliště Lhotka Teplota vody“):

===================  ==========================================================
název entity         obsah
===================  ==========================================================
Teplota vody         teplota vody ve °C
Teplota vzduchu      teplota vzduchu ve °C
Obsazenost           počet osob v areálu (atribut ``kapacita``)
Obsazenost %         obsazenost v % kapacity
Otevírací doba       dnešní otevírací doba + celý rozvrh v atributech
Stav dat             diagnostika čtení (ok / potíže / nedostupné)
===================  ==========================================================

``entity_id`` vzniká při prvním zaregistrování entity a dál se drží podle
``unique_id``. Instalace, které začínaly na verzi 1.x, proto mají
``sensor.lhotka_teplota_vody``, nové instalace
``sensor.koupaliste_lhotka_teplota_vody``.

Číselné senzory používají jednoduchý popisný přístup
(:class:`SensorEntityDescription` + funkce, která z dat vytáhne hodnotu).
Senzor otevírací doby a diagnostický senzor mají vlastní třídy, protože
kromě hodnoty publikují i atributy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import LhotkaConfigEntry
from .const import (
    KEY_AIR_TEMP,
    KEY_OCCUPANCY,
    KEY_OCCUPANCY_PCT,
    KEY_OPENING_HOURS,
    KEY_STATUS,
    KEY_WATER_TEMP,
)
from .coordinator import LhotkaCoordinator, LhotkaData
from .entity import LhotkaEntity
from .scraper import entry_for, last_entry_time

STATE_CLOSED = "Zavřeno"


@dataclass(frozen=True, kw_only=True)
class LhotkaSensorDescription(SensorEntityDescription):
    """Popis senzoru včetně způsobu, jak z dat získat hodnotu."""

    value_fn: Callable[[LhotkaData], float | int | None]


NUMERIC_SENSORS: tuple[LhotkaSensorDescription, ...] = (
    LhotkaSensorDescription(
        key=KEY_WATER_TEMP,
        name="Teplota vody",
        icon="mdi:thermometer-water",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: data.live.water_temp,
    ),
    LhotkaSensorDescription(
        key=KEY_AIR_TEMP,
        name="Teplota vzduchu",
        icon="mdi:thermometer",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda data: data.live.air_temp,
    ),
    LhotkaSensorDescription(
        key=KEY_OCCUPANCY,
        name="Obsazenost",
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="osob",
        value_fn=lambda data: data.live.occupancy,
    ),
    LhotkaSensorDescription(
        key=KEY_OCCUPANCY_PCT,
        name="Obsazenost %",
        icon="mdi:account-group-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=lambda data: data.live.occupancy_pct,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LhotkaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Vytvoří senzory."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        LhotkaNumericSensor(coordinator, description) for description in NUMERIC_SENSORS
    ]
    entities.append(LhotkaOpeningHoursSensor(coordinator))
    entities.append(LhotkaStatusSensor(coordinator))

    async_add_entities(entities)


class LhotkaNumericSensor(LhotkaEntity, SensorEntity):
    """Číselný senzor popsaný přes :class:`LhotkaSensorDescription`."""

    entity_description: LhotkaSensorDescription

    def __init__(
        self,
        coordinator: LhotkaCoordinator,
        description: LhotkaSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, int] | None:
        # Kapacitu publikujeme u počtu osob — dashboardy ji používají
        # k výpočtu volných míst.
        if self.entity_description.key == KEY_OCCUPANCY:
            capacity = self.coordinator.data.live.capacity
            if capacity is not None:
                return {"kapacita": capacity}
        return None


class LhotkaOpeningHoursSensor(LhotkaEntity, SensorEntity):
    """Otevírací doba: stav = dnešní hodiny, atributy = celý rozvrh.

    Tato entita je dostupná i ve chvíli, kdy je web nedostupný — rozvrh se
    mění řádově jednou za sezónu, takže starší kopie je plně použitelná.
    """

    _attr_name = "Otevírací doba"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: LhotkaCoordinator) -> None:
        super().__init__(coordinator, KEY_OPENING_HOURS)

    @property
    def available(self) -> bool:
        return self.coordinator.has_schedule

    @property
    def native_value(self) -> str | None:
        """Dnešní otevírací doba, nebo „Zavřeno“ mimo sezónu."""
        schedule = self.coordinator.data.schedule
        entry = entry_for(schedule, dt_util.now())
        if entry is None:
            return STATE_CLOSED
        return entry.hours_label

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Atributy tvoří veřejný kontrakt — nemazat ani nepřejmenovávat.

        ``rozvrh`` používají uživatelské dashboardy (např. podbarvení grafu
        podle otevírací doby), ``otevreno_ted`` pak šablony a automatizace.
        """
        now = dt_util.now()
        data = self.coordinator.data
        entry = entry_for(data.schedule, now)

        attrs: dict[str, object] = {
            "rozvrh": [
                {
                    "mesic": item.month_name,
                    "dny": item.days_label,
                    "hodiny": item.hours_label,
                }
                for item in data.schedule
            ],
            "otevreno_ted": self.coordinator.is_open_now,
        }

        if entry is not None:
            attrs["dnes_od"] = f"{entry.opens.hour}:{entry.opens.minute:02d}"
            attrs["dnes_do"] = f"{entry.closes.hour}:{entry.closes.minute:02d}"
            last = last_entry_time(entry)
            attrs["posledni_vstup"] = f"{last.hour}:{last.minute:02d}"

        if data.schedule_updated is not None:
            attrs["aktualizovano"] = data.schedule_updated.isoformat()

        # Stav podle webu — užitečné, když areál zavře kvůli počasí.
        if data.live.badge_open is not None:
            attrs["stav_dle_webu"] = "otevřeno" if data.live.badge_open else "zavřeno"

        return attrs


class LhotkaStatusSensor(LhotkaEntity, SensorEntity):
    """Diagnostika čtení dat.

    Smysl: uživatel nemusí hlídat log, aby zjistil, že se data přestala
    načítat. Entita je dostupná vždy — právě proto, aby mohla o problému
    informovat. Hodí se jako podmínka pro automatizaci s notifikací.
    """

    _attr_name = "Stav dat"
    _attr_icon = "mdi:cloud-check-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["ok", "potize", "nedostupne"]
    #: Klíč pro překlad hodnot stavu (viz strings.json → entity.sensor).
    _attr_translation_key = KEY_STATUS

    def __init__(self, coordinator: LhotkaCoordinator) -> None:
        super().__init__(coordinator, KEY_STATUS)

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        """Stav odvozený primárně od toho, jestli poslední načtení vyšlo.

        Nespoléháme jen na počítadlo selhání: coordinator může skončit
        neúspěchem i chybou, která přes naše počítadlo neprojde. Proto je
        rozhodující ``last_update_success``.
        """
        coordinator = self.coordinator
        if coordinator.last_update_success and not coordinator.consecutive_failures:
            return "ok"
        if coordinator.consecutive_failures >= 3:
            return "nedostupne"
        return "potize"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Podrobnosti o čtení dat.

        Záměrně tu **nejsou** časové značky poslední aktualizace: měnily by se
        při každém cyklu, a recorder by kvůli nim ukládal nový řádek každých
        deset minut bez informační hodnoty. Kdy data dorazila, je vidět na
        `last_updated` samotných senzorů a v diagnostice.
        """
        coordinator = self.coordinator
        attrs: dict[str, object] = {
            "posledni_cteni_uspesne": coordinator.last_update_success,
            "neuspesnych_pokusu_v_rade": coordinator.consecutive_failures,
            "neuspesnych_pokusu_celkem": coordinator.total_failures,
            "interval_minut": (
                int(coordinator.update_interval.total_seconds() // 60)
                if coordinator.update_interval
                else None
            ),
        }
        if coordinator.last_error:
            attrs["posledni_chyba"] = coordinator.last_error
        return attrs
