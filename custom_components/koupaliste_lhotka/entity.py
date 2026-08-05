"""Společný základ pro entity integrace.

:class:`LhotkaEntity` řeší tři věci, které by se jinak opakovaly u každé entity:

* napojení na koordinátor (entita se sama překreslí, když přijdou nová data),
* zařazení pod jedno **zařízení** v Home Assistantu, aby entity držely pohromadě,
* uvedení zdroje dat (*attribution*).

Poznámka k pojmenování: ``_attr_has_entity_name = True`` znamená, že název
entity popisuje jen ji samotnou („Teplota vody“) a Home Assistant před něj
sám doplní název zařízení („Koupaliště Lhotka Teplota vody“).

Ve verzi 2.0.0 tu bylo ``False`` a názvy nesly prefix „Lhotka – “, aby
zůstaly identické s verzí 1.x. To ale v Home Assistantu 2026 nefunguje:
u entit patřících k zařízení se název zařízení předsadí nezávisle na tomto
přepínači, takže vznikaly zdvojené názvy „Koupaliště Lhotka Lhotka – Teplota
vody“. Verze 2.0.1 proto používá krátké názvy.

Na ``entity_id`` už existujících instalací to nemá vliv — ten se odvozuje
jen při prvním zaregistrování entity a dál se drží podle ``unique_id``.
Viz ARCHITECTURE.md, sekce „Nedotknutelné kontrakty“.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, BASE_URL, DOMAIN
from .coordinator import LhotkaCoordinator


class LhotkaEntity(CoordinatorEntity[LhotkaCoordinator]):
    """Základní entita napojená na koordinátor."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: LhotkaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "koupaliste_lhotka")},
            name="Koupaliště Lhotka",
            manufacturer="Koupaliště Lhotka",
            model="Veřejný web",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BASE_URL,
        )
