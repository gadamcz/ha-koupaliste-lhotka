"""Konfigurační průvodce (config flow).

Integrace nemá co konfigurovat — cílový web je jediný a URL jsou pevné.
Průvodce proto jen ověří, že se data dají přečíst, a záznam vytvoří.

Záměrně tu **není** políčko na vlastní URL. Kdyby bylo, uživatel (nebo
někdo, kdo se dostane k jeho Home Assistantu) by mohl integraci nasměrovat
na libovolnou adresu v domácí síti a použít ji jako skener — klasická
zranitelnost SSRF. Viz SECURITY.md.

Volitelné nastavení (interval čtení) se mění přes *Možnosti* u již
vytvořené integrace.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    URL_HOME,
)
from .scraper import FetchError, ParseError, async_fetch, parse_home

TITLE = "Koupaliště Lhotka"


class LhotkaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Průvodce přidáním integrace."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Jediný krok: potvrzení uživatelem a ověření dostupnosti dat."""
        # Integrace má smysl jen jednou — web je jediný.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self._async_validate()
            except FetchError:
                errors["base"] = "cannot_connect"
            except ParseError:
                errors["base"] = "invalid_response"
            else:
                return self.async_create_entry(
                    title=TITLE,
                    data={},
                    options={CONF_SCAN_INTERVAL_MINUTES: DEFAULT_SCAN_INTERVAL_MINUTES},
                )

        return self.async_show_form(step_id="user", errors=errors)

    async def _async_validate(self) -> None:
        """Zkusí načíst domovskou stránku a přečíst z ní data.

        Raises:
            FetchError: web není dostupný.
            ParseError: web odpověděl, ale data v něm nejsou.
        """
        session = async_get_clientsession(self.hass)
        result = await async_fetch(session, URL_HOME)
        if result.text is None:
            raise FetchError("Prázdná odpověď")
        await self.hass.async_add_executor_job(parse_home, result.text)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        """Vrátí průvodce nastavením."""
        return LhotkaOptionsFlow()


class LhotkaOptionsFlow(OptionsFlow):
    """Nastavení intervalu čtení."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Zobrazí a uloží nastavení."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL_MINUTES: int(
                        user_input[CONF_SCAN_INTERVAL_MINUTES]
                    )
                }
            )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_MINUTES, default=current
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_MINUTES,
                        max=MAX_SCAN_INTERVAL_MINUTES,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                )
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
