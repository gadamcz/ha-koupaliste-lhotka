"""Koordinátor stahování dat — jedno místo, které ví, kdy a co načíst.

Home Assistant nabízí vzor :class:`DataUpdateCoordinator`: **jeden** objekt
stahuje data a všechny entity se na něj jen dívají. Kdyby si každá entita
stahovala data sama, integrace by web volala pětkrát častěji, než je potřeba.

Co tento koordinátor řeší nad rámec základního vzoru:

* **Dvě různé kadence.** Teploty a obsazenost se mění po minutách, otevírací
  doba po měsících. Rozvrh se proto načítá jen jednou za pár hodin.
* **Podmíněné dotazy.** Pamatuje si ``ETag``/``Last-Modified`` a při
  nezměněné stránce se přenese jen hlavička (HTTP 304) místo celého HTML.
* **Parsování mimo hlavní vlákno.** BeautifulSoup je synchronní; kdyby běžel
  v event loopu, blokoval by celý Home Assistant. Proto ``async_add_executor_job``.
* **Exponenciální backoff.** Když web neodpovídá, integrace ho přestane
  bombardovat každých 10 minut a interval postupně prodlouží až na hodinu.
* **Hlášení problémů.** Po několika selháních v řadě založí v Home Assistantu
  položku v *Nastavení → Systém → Opravy*, aby uživatel nemusel číst log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    BACKOFF_MAX_INTERVAL,
    BADGE_MAX_AGE,
    DOMAIN,
    FAILURES_BEFORE_ISSUE,
    FALLBACK_CAPACITY,
    HOURS_REFRESH_INTERVAL,
    HOURS_RETRY_INTERVAL,
    ISSUE_PARSE_CHANGED,
    ISSUE_UNREADABLE,
    URL_HOME,
    URL_HOURS,
)
from .scraper import (
    CacheHeaders,
    FetchError,
    LiveData,
    ParseError,
    ScheduleEntry,
    async_fetch,
    clean_text,
    entries_for,
    is_open_by_schedule,
    parse_home,
    parse_hours,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class LhotkaData:
    """Kompletní obraz dat, se kterým pracují entity.

    Entity nikdy nesahají na internet ani na parsery — čtou jen tuhle strukturu.
    """

    live: LiveData
    schedule: list[ScheduleEntry] = field(default_factory=list)
    #: Kdy se naposledy povedlo přečíst živá data.
    live_updated: datetime | None = None
    #: Kdy se naposledy povedlo přečíst rozvrh.
    schedule_updated: datetime | None = None


class LhotkaCoordinator(DataUpdateCoordinator[LhotkaData]):
    """Stahuje a drží data z koupaliste-lhotka.cz."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        scan_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=entry,
        )
        self._session = async_get_clientsession(hass)
        self._base_interval = scan_interval

        # Cache hlaviček pro podmíněné dotazy.
        self._cache_home = CacheHeaders()
        self._cache_hours = CacheHeaders()

        # Poslední úspěšně naparsovaná data (potřebná pro odpověď 304).
        self._live: LiveData | None = None
        self._schedule: list[ScheduleEntry] = []
        self._live_updated: datetime | None = None
        self._schedule_updated: datetime | None = None
        #: Kdy jsme se o rozvrh naposledy *pokusili* (i neúspěšně). Bez toho
        #: by se nedostupná stránka rozvrhu stahovala každý cyklus.
        self._schedule_attempted: datetime | None = None

        # Diagnostika pro uživatele i pro stavovou entitu.
        self.consecutive_failures = 0
        self.last_error: str | None = None
        self.total_failures = 0

        #: Zrušení naplánovaného překreslení na hranici otevírací doby.
        self._unsub_boundary: CALLBACK_TYPE | None = None

    # --- Vlastnosti pro stavovou entitu a diagnostiku -----------------------

    @property
    def has_schedule(self) -> bool:
        """Máme rozvrh publikovaný v datech (byť starší)?

        Čte se ze snímku ``self.data``, ne z interní cache — entity musí mít
        `available` a hodnotu odvozené ze *stejného* zdroje, jinak by mohly
        publikovat „Zavřeno“ v okamžiku, kdy rozvrh existuje jen v cache.
        """
        return bool(self.data and self.data.schedule)

    @property
    def is_open_now(self) -> bool:
        """Je areál otevřený právě teď?

        Kombinuje dva zdroje:

        * **rozvrh** — plánované hodiny (spolehlivý základ),
        * **odznak na webu** — zachytí i mimořádné zavření kvůli počasí.

        Bereme je konjunktivně: otevřeno musí platit podle rozvrhu *a* web to
        nesmí vyvracet. Tím se vyhneme falešnému „otevřeno“ ve tři ráno, kdyby
        odznak na webu zůstal zapomenutý v poloze OTEVŘENO.

        Odznak se ale bere v potaz jen tehdy, když jsou živá data svěží.
        Po delším výpadku webu by staré „zavřeno“ jinak držel areál zavřený
        i dlouho po znovuotevření.
        """
        if self.data is None:
            return False

        if self.data.live.badge_open is False and self._badge_is_fresh():
            return False

        return is_open_by_schedule(self.data.schedule, dt_util.now())

    def _badge_is_fresh(self) -> bool:
        """Je stavový odznak z webu dost aktuální, aby se mu dalo věřit?"""
        if self.data is None or self.data.live_updated is None:
            return False
        return (dt_util.now() - self.data.live_updated) <= BADGE_MAX_AGE

    # --- Hlavní smyčka ------------------------------------------------------

    async def _async_update_data(self) -> LhotkaData:
        """Načte data. Voláno Home Assistantem podle ``update_interval``."""
        # 1) Rozvrh — pouze pokud je starý nebo ho ještě nemáme.
        #    Selhání tady není fatální: rozvrh se mění výjimečně, takže
        #    starší kopie je pořád lepší než žádná data.
        if self._needs_schedule_refresh():
            await self._async_refresh_schedule()

        # 2) Živá data — tohle je jádro integrace.
        try:
            live = await self._async_fetch_live()
        except (FetchError, ParseError) as err:
            self._register_failure(err)
            # UpdateFailed říká Home Assistantu „tenhle pokus nevyšel“.
            # Entity živých hodnot zešednou (unavailable), což je správné:
            # radši žádná hodnota než tichá lež o staré teplotě.
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            # Sem spadne cokoli nečekaného — RecursionError z BeautifulSoupu
            # nad patologickým HTML, MemoryError, TypeError po redesignu webu.
            # Bez tohohle bloku by coordinator selhal, ale diagnostický senzor
            # by dál hlásil „ok“ a nespustil by se backoff ani hlášení.
            self._register_failure(err)
            _LOGGER.exception("Neočekávaná chyba při načítání dat")
            raise UpdateFailed(f"Neočekávaná chyba: {clean_text(str(err))}") from err

        self._register_success()

        # Entity se samy překreslí jen s novými daty. Otevírací doba se ale
        # mění podle hodin, ne podle dat — proto si na nejbližší okamžik
        # otevření/zavření naplánujeme překreslení.
        self._schedule_boundary_update()

        return LhotkaData(
            live=live,
            schedule=list(self._schedule),
            live_updated=self._live_updated,
            schedule_updated=self._schedule_updated,
        )

    # --- Živá data ----------------------------------------------------------

    async def _async_fetch_live(self) -> LiveData:
        """Stáhne a naparsuje domovskou stránku."""
        result = await async_fetch(self._session, URL_HOME, self._cache_home)

        if result.not_modified and self._live is not None:
            # Stránka se nezměnila — ušetřili jsme přenos i parsování.
            _LOGGER.debug("Domovská stránka nezměněna (HTTP 304)")
            self._live_updated = dt_util.now()
            return self._live

        if result.text is None:
            # 304 bez uložených dat (např. po restartu) — zkusíme znovu bez cache.
            self._cache_home = CacheHeaders()
            result = await async_fetch(self._session, URL_HOME)
            if result.text is None:
                raise FetchError("Server nevrátil obsah domovské stránky")

        # BeautifulSoup je synchronní → do executoru, aby neblokoval event loop.
        live: LiveData = await self.hass.async_add_executor_job(parse_home, result.text)

        # Kapacita chybí jen výjimečně; bez ní nejde spočítat procenta.
        if live.capacity is None and live.occupancy is not None:
            live.capacity = FALLBACK_CAPACITY

        self._cache_home = CacheHeaders(result.etag, result.last_modified)
        self._live = live
        self._live_updated = dt_util.now()
        return live

    # --- Rozvrh -------------------------------------------------------------

    def _needs_schedule_refresh(self) -> bool:
        """Má se rozvrh zkusit načíst?

        Rozhoduje čas *pokusu*, ne úspěchu — kdyby se koukalo na úspěch,
        nedostupná (nebo mimo sezónu neexistující) tabulka by se stahovala
        každý cyklus, tedy 144× denně místo 4×.

        Dokud ale rozvrh nemáme *vůbec*, zkoušíme ho v kratším intervalu:
        po restartu Home Assistantu během chvilkového výpadku webu by jinak
        byla otevírací doba nedostupná celých šest hodin.
        """
        if self._schedule_attempted is None:
            return True
        interval = HOURS_REFRESH_INTERVAL if self._schedule else HOURS_RETRY_INTERVAL
        return (dt_util.now() - self._schedule_attempted) >= interval

    async def _async_refresh_schedule(self) -> None:
        """Načte tabulku otevírací doby. Chyby jen loguje.

        Selhání tady záměrně **není** fatální ani se nepočítá do statistiky
        selhání: rozvrh se mění výjimečně a mimo sezónu tabulka na webu
        nemusí být vůbec. Zachytává se i nečekaná výjimka, aby nemohla
        shodit celý aktualizační cyklus a obejít tak sledování zdraví.
        """
        self._schedule_attempted = dt_util.now()
        try:
            result = await async_fetch(self._session, URL_HOURS, self._cache_hours)

            if result.not_modified and self._schedule:
                self._schedule_updated = dt_util.now()
                self._cache_hours = CacheHeaders(result.etag, result.last_modified)
                return

            if result.text is None:
                return

            schedule: list[ScheduleEntry] = await self.hass.async_add_executor_job(
                parse_hours, result.text
            )
            self._schedule = schedule
            self._schedule_updated = dt_util.now()
            self._cache_hours = CacheHeaders(result.etag, result.last_modified)
            _LOGGER.debug("Otevírací doba načtena: %d řádků", len(schedule))

        except ParseError as err:
            # Mimo sezónu web tabulku nemusí zobrazovat vůbec — to není chyba
            # integrace, jen o rozvrhu nic nevíme.
            _LOGGER.debug("Otevírací dobu nelze přečíst: %s", err)
        except FetchError as err:
            _LOGGER.debug("Otevírací dobu nelze stáhnout: %s", err)
        except Exception:
            # Nečekaná chyba (např. RecursionError z BeautifulSoupu nad
            # patologickým HTML). Nesmí propadnout do hlavního cyklu, protože
            # tam by obešla registraci selhání i backoff.
            _LOGGER.exception("Neočekávaná chyba při načítání otevírací doby")

    # --- Překreslení na hranici otevírací doby ------------------------------

    @callback
    def _schedule_boundary_update(self) -> None:
        """Naplánuje překreslení entit na nejbližší otevření nebo zavření.

        Bez tohoto by se ``binary_sensor.lhotka_otevreno`` přepnul až s další
        aktualizací dat — tedy se zpožděním až celého intervalu (v backoffu
        i hodiny). Časovač nic nestahuje, jen řekne entitám „přepočítej se“.
        """
        self._cancel_boundary()

        moment = self._next_boundary()
        if moment is None:
            return

        self._unsub_boundary = async_track_point_in_time(
            self.hass, self._boundary_reached, moment
        )

    @callback
    def _boundary_reached(self, _now: datetime) -> None:
        self._unsub_boundary = None
        self.async_update_listeners()
        self._schedule_boundary_update()

    @callback
    def _cancel_boundary(self) -> None:
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None

    def _next_boundary(self) -> datetime | None:
        """Nejbližší budoucí okamžik otevření nebo zavření (max. 8 dní dopředu)."""
        if not self._schedule:
            return None

        now = dt_util.now()
        for offset in range(9):
            day = now + timedelta(days=offset)
            # Den skládáme z místní půlnoci, ne přes replace() — jinak by
            # v den přechodu na letní/zimní čas vznikl posunutý okamžik.
            midnight = dt_util.start_of_local_day(day)
            candidates = [
                midnight + timedelta(hours=moment.hour, minutes=moment.minute)
                for entry in entries_for(self._schedule, day)
                for moment in (entry.opens, entry.closes)
            ]
            future = [candidate for candidate in candidates if candidate > now]
            if future:
                return min(future)
        return None

    async def async_shutdown(self) -> None:
        """Uklidí časovač při vypnutí integrace."""
        self._cancel_boundary()
        await super().async_shutdown()

    # --- Sledování zdraví ---------------------------------------------------

    def _register_success(self) -> None:
        """Úspěch: zrušit backoff a případné hlášení problému."""
        if self.consecutive_failures:
            _LOGGER.info(
                "Data z koupaliste-lhotka.cz jsou opět dostupná "
                "(po %d neúspěšných pokusech)",
                self.consecutive_failures,
            )
        self.consecutive_failures = 0
        self.last_error = None

        if self.update_interval != self._base_interval:
            self.update_interval = self._base_interval

        for issue_id in (ISSUE_UNREADABLE, ISSUE_PARSE_CHANGED):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def _register_failure(self, err: Exception) -> None:
        """Selhání: prodloužit interval a po několika pokusech to nahlásit."""
        self.consecutive_failures += 1
        self.total_failures += 1
        # Text chyby může nést data ze serveru a jde do atributu entity
        # i do logu — proto normalizace a zkrácení.
        self.last_error = clean_text(str(err))

        # Exponenciální backoff — ohleduplnost k cizímu webu i k vlastnímu CPU.
        if self.update_interval and self.update_interval < BACKOFF_MAX_INTERVAL:
            self.update_interval = min(self.update_interval * 2, BACKOFF_MAX_INTERVAL)
            _LOGGER.debug(
                "Interval čtení dočasně prodloužen na %s", self.update_interval
            )

        # >= a ne ==: async_create_issue je idempotentní, ale kdyby uživatel
        # hlášku zavřel, při dalším selhání se má objevit znovu.
        if self.consecutive_failures >= FAILURES_BEFORE_ISSUE:
            # ParseError = web se přestavěl (musí zasáhnout vývojář).
            # FetchError = web je nedostupný (většinou přejde samo).
            issue_id = (
                ISSUE_PARSE_CHANGED if isinstance(err, ParseError) else ISSUE_UNREADABLE
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=issue_id,
                translation_placeholders={
                    "attempts": str(self.consecutive_failures),
                    "error": clean_text(str(err)),
                },
            )
