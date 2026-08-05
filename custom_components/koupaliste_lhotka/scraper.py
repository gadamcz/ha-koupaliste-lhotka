"""Stahování a parsování dat z koupaliste-lhotka.cz.

Tento modul je záměrně **nezávislý na Home Assistantu**. Nezná entity,
coordinatory ani konfigurační záznamy — umí jen dvě věci:

1. bezpečně stáhnout HTML (:func:`async_fetch`),
2. převést HTML na datové struktury (:func:`parse_home`, :func:`parse_hours`).

Proč to tak je:

* **Testovatelnost** — parsery jsou čisté funkce (stejný vstup → stejný výstup),
  takže se dají testovat bez běžícího Home Assistantu (viz ``tests/``).
* **Čitelnost** — když se web změní, opravuje se jen tento soubor.
* **Bezpečnost** — veškerá práce s nedůvěryhodným vstupem (HTML z internetu)
  je soustředěná na jedno místo, kde se dá auditovat.

Struktura webu, ze které parsery vycházejí (stav 2026, WordPress, HTML
generované na serveru — žádný JavaScript není potřeba)::

    <div class="header-obsazenost text-right">
        <div class="opening-hours"><p>OTEVŘENO</p></div>
        <div class="header-obsazenost__inner">
            Teplota vody: <strong>26,5°C</strong></div>
        <div class="header-obsazenost__inner">
            Teplota vzduchu: <strong>37°C</strong></div>
        <div class="header-obsazenost__inner">
            Aktuální obsazenost: <strong>842 / 1000</strong></div>
    </div>

Parsery používají dvoustupňovou strategii: nejdřív se pokusí data najít
podle struktury HTML (CSS třídy), a když to selže, spadnou zpět na hledání
v prostém textu stránky regulárním výrazem. Web tak může projít redesignem
a integrace bude s velkou pravděpodobností dál fungovat.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Final

import aiohttp
from bs4 import BeautifulSoup

from .const import (
    ALLOWED_HOSTS,
    MAX_CACHE_HEADER_LENGTH,
    MAX_RESPONSE_BYTES,
    MAX_SCHEDULE_ROWS,
    MAX_TEXT_LENGTH,
    PLAUSIBLE_OCCUPANCY_MAX,
    PLAUSIBLE_TEMP_RANGE,
    REQUEST_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# --- Chybové typy -----------------------------------------------------------


class ScraperError(Exception):
    """Základ pro všechny chyby tohoto modulu."""


class FetchError(ScraperError):
    """Data se nepodařilo stáhnout (síť, timeout, HTTP chyba, limit velikosti)."""


class ParseError(ScraperError):
    """Data se stáhla, ale nedala se přečíst — nejspíš se změnila struktura webu."""


# --- Datové struktury -------------------------------------------------------


@dataclass(slots=True)
class LiveData:
    """Okamžitý stav areálu z domovské stránky."""

    water_temp: float | None = None
    air_temp: float | None = None
    occupancy: int | None = None
    capacity: int | None = None
    #: Stavový odznak webu: True = OTEVŘENO, False = ZAVŘENO, None = neuvedeno.
    badge_open: bool | None = None

    @property
    def occupancy_pct(self) -> float | None:
        """Obsazenost v procentech kapacity.

        Výsledek je omezený na 0–100 %. Web při plném areálu hlásí „1000 /
        1000“, ale kdyby se čísla rozešla, nesmyslných několik tisíc procent
        by skončilo v dlouhodobých statistikách Home Assistantu.
        """
        if self.occupancy is None or not self.capacity:
            return None
        pct = self.occupancy / self.capacity * 100
        return round(min(100.0, max(0.0, pct)), 1)

    @property
    def is_empty(self) -> bool:
        """True, pokud se nepodařilo přečíst ani jednu hodnotu."""
        return (
            self.water_temp is None
            and self.air_temp is None
            and self.occupancy is None
            and self.badge_open is None
        )


@dataclass(slots=True)
class ScheduleEntry:
    """Jeden řádek tabulky otevírací doby, např. „červen / po – čt / 10:00 – 19:00“."""

    month_name: str
    month: int
    days_label: str
    #: Dny v týdnu podle :meth:`datetime.date.weekday` (pondělí = 0).
    weekdays: tuple[int, ...]
    opens: time
    closes: time

    @property
    def hours_label(self) -> str:
        """Textová podoba hodin, jak ji zobrazujeme uživateli."""
        return f"{_fmt_time(self.opens)} – {_fmt_time(self.closes)}"


@dataclass(slots=True)
class FetchResult:
    """Výsledek HTTP požadavku včetně cache hlaviček."""

    text: str | None
    etag: str | None = None
    last_modified: str | None = None
    #: True, pokud server odpověděl 304 Not Modified a tělo se nepřenášelo.
    not_modified: bool = False


@dataclass(slots=True)
class CacheHeaders:
    """Hlavičky pro podmíněné HTTP dotazy (ušetří přenos i zátěž webu)."""

    etag: str | None = None
    last_modified: str | None = None


# --- Pomůcky ----------------------------------------------------------------

#: Mapování českých názvů měsíců na čísla. Bez diakritiky i s ní, protože
#: web může časem změnit zápis.
# fmt: off
MONTHS: Final[dict[str, int]] = {
    "leden": 1, "ledna": 1,
    "únor": 2, "unor": 2, "února": 2, "unora": 2,
    "březen": 3, "brezen": 3, "března": 3, "brezna": 3,
    "duben": 4, "dubna": 4,
    "květen": 5, "kveten": 5, "května": 5, "kvetna": 5,
    "červen": 6, "cerven": 6, "června": 6, "cervna": 6,
    "červenec": 7, "cervenec": 7, "července": 7, "cervence": 7,
    "srpen": 8, "srpna": 8,
    "září": 9, "zari": 9,
    "říjen": 10, "rijen": 10, "října": 10, "rijna": 10,
    "listopad": 11, "listopadu": 11,
    "prosinec": 12, "prosince": 12,
}
# fmt: on

#: Zkratky dnů → weekday(). Pondělí = 0, aby to odpovídalo Pythonu.
# fmt: off
DAYS: Final[dict[str, int]] = {
    "po": 0, "pondělí": 0, "pondeli": 0,
    "út": 1, "ut": 1, "úterý": 1, "utery": 1,
    "st": 2, "středa": 2, "streda": 2,
    "čt": 3, "ct": 3, "čtvrtek": 3, "ctvrtek": 3,
    "pá": 4, "pa": 4, "pátek": 4, "patek": 4,
    "so": 5, "sobota": 5,
    "ne": 6, "neděle": 6, "nedele": 6,
}
# fmt: on

#: Typy pomlček, které se na webu vyskytují (spojovník, en dash, em dash).
_DASH_CLASS: Final = r"[-–—]"

# Regulární výrazy jsou psané s *omezenými* kvantifikátory ({0,10} místo *),
# aby nemohlo dojít ke catastrophic backtracking (ReDoS) na nepřátelském vstupu.
_RE_TEMP_WATER: Final = re.compile(
    r"teplota\s{0,5}vody\s{0,5}:?\s{0,5}(-?\d{1,3}(?:[.,]\d{1,2})?)\s{0,5}°?\s{0,3}C",
    re.IGNORECASE,
)
_RE_TEMP_AIR: Final = re.compile(
    r"teplota\s{0,5}vzduchu\s{0,5}:?\s{0,5}(-?\d{1,3}(?:[.,]\d{1,2})?)\s{0,5}°?\s{0,3}C",
    re.IGNORECASE,
)
_RE_OCCUPANCY: Final = re.compile(
    r"obsazenost\s{0,5}:?\s{0,5}(\d{1,6})\s{0,5}/\s{0,5}(\d{1,6})",
    re.IGNORECASE,
)
_RE_NUMBER: Final = re.compile(r"-?\d{1,3}(?:[.,]\d{1,2})?")
_RE_TWO_NUMBERS: Final = re.compile(r"(\d{1,6})\s{0,5}/\s{0,5}(\d{1,6})")
_RE_HOURS_RANGE: Final = re.compile(
    r"(\d{1,2})[:.](\d{2})\s{0,5}" + _DASH_CLASS + r"\s{0,5}(\d{1,2})[:.](\d{2})"
)


def _fmt_time(value: time) -> str:
    """Zformátuje čas bez vedoucí nuly — „9:00“, ne „09:00“ (jako web)."""
    return f"{value.hour}:{value.minute:02d}"


def _to_float(raw: str) -> float | None:
    """Převede číslo z webu (desetinná čárka i tečka) na float."""
    try:
        return float(raw.replace(",", "."))
    except (TypeError, ValueError):
        return None


#: Znaky, které nepatří do stavu entity ani do logu:
#: - ASCII řídicí znaky (NUL láme PostgreSQL recorder, ESC umožňuje
#:   injektáž ANSI sekvencí do logu),
#: - Unicode bidi a nulové šířky (U+200B–U+200F, U+202A–U+202E, U+2066–U+2069,
#:   U+FEFF) — dají se zneužít k tomu, aby text v UI vypadal jinak, než je.
_RE_CONTROL_CHARS: Final = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f"
    r"\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)


def clean_text(raw: str | None) -> str:
    """Normalizuje text z webu: zahodí řídicí znaky, sjednotí mezery, zkrátí.

    Používá se na **každý** text pocházející z cizího serveru, než se dostane
    do stavu entity, atributu nebo logu. Omezení délky brání zaplavení
    databáze Home Assistantu, odstranění řídicích znaků chrání recorder
    (NUL) a čitelnost logu (ESC sekvence).
    """
    if not raw:
        return ""
    collapsed = " ".join(_RE_CONTROL_CHARS.sub("", raw).split())
    return collapsed[:MAX_TEXT_LENGTH]


def _plausible_temp(value: float | None) -> float | None:
    """Propustí jen věrohodnou teplotu.

    Nesmyslná hodnota (např. -999 °C po chybě na webu) by se zapsala do
    dlouhodobých statistik Home Assistantu, odkud se odstraňuje ručně.
    """
    if value is None:
        return None
    low, high = PLAUSIBLE_TEMP_RANGE
    return value if low <= value <= high else None


def parse_day_range(label: str) -> tuple[int, ...]:
    """Převede popis dnů („po – čt“, „pá“, „so – ne“) na čísla dnů v týdnu.

    Zvládá i rozsah přes hranici týdne (např. „so – po“ → sobota, nedělě, pondělí).
    Neznámý zápis vrací prázdnou n-tici — volající takový řádek přeskočí.
    """
    parts = [p.strip().lower() for p in re.split(_DASH_CLASS, label) if p.strip()]

    if len(parts) == 1:
        day = DAYS.get(parts[0])
        return (day,) if day is not None else ()

    if len(parts) == 2:
        start, end = DAYS.get(parts[0]), DAYS.get(parts[1])
        if start is None or end is None:
            return ()
        if start <= end:
            return tuple(range(start, end + 1))
        # Rozsah přes konec týdne.
        return tuple(range(start, 7)) + tuple(range(end + 1))

    return ()


# --- Parsování domovské stránky ---------------------------------------------


def parse_home(html: str) -> LiveData:
    """Vytáhne z domovské stránky teploty, obsazenost a stavový odznak.

    Raises:
        ParseError: pokud se nepodařilo přečíst ani jednu hodnotu — to je
            signál, že se web přestavěl a parser potřebuje aktualizaci.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = LiveData()

    # 1) Strukturní čtení: hodnoty jsou v <div class="header-obsazenost__inner">
    #    ve tvaru „Popisek: <strong>hodnota</strong>“.
    for block in soup.select(".header-obsazenost__inner"):
        label = block.get_text(" ", strip=True).lower()
        strong = block.find("strong")
        value = strong.get_text(" ", strip=True) if strong else ""
        if not value:
            continue

        if "vody" in label and (match := _RE_NUMBER.search(value)):
            data.water_temp = _to_float(match.group(0))
        elif "vzduchu" in label and (match := _RE_NUMBER.search(value)):
            data.air_temp = _to_float(match.group(0))
        elif "obsazenost" in label and (match := _RE_TWO_NUMBERS.search(value)):
            data.occupancy = int(match.group(1))
            data.capacity = int(match.group(2))

    # 2) Stavový odznak OTEVŘENO / ZAVŘENO.
    #    Hledáme jen v samotném odznaku (vnitřní <p>), ne v celém bloku —
    #    ten nese i nadpis „Otevírací doba“, takže hledání podpisu „otev“
    #    v celém textu by u zavřeného areálu vrátilo „otevřeno“.
    if badge := soup.select_one(".opening-hours"):
        inner = badge.find("p")
        data.badge_open = _read_badge((inner or badge).get_text(" ", strip=True))

    # 3) Záložní čtení z prostého textu, pokud strukturní selhalo.
    if (
        data.water_temp is None
        or data.air_temp is None
        or data.occupancy is None
        or data.badge_open is None
    ):
        text = soup.get_text(" ", strip=True)
        if data.water_temp is None and (m := _RE_TEMP_WATER.search(text)):
            data.water_temp = _to_float(m.group(1))
        if data.air_temp is None and (m := _RE_TEMP_AIR.search(text)):
            data.air_temp = _to_float(m.group(1))
        if data.occupancy is None and (m := _RE_OCCUPANCY.search(text)):
            data.occupancy = int(m.group(1))
            data.capacity = int(m.group(2))
        if data.badge_open is None:
            # Odznak je na webu velkými písmeny v hlavičce stránky. Hledáme
            # proto jen samostatné slovo ve verzálkách a jen v začátku textu —
            # jinak by odznak omylem přebilo běžné „bufet zavřen“ v textu.
            data.badge_open = _read_badge_strict(text[:400])

    if data.is_empty:
        raise ParseError(
            "Na domovské stránce se nenašla žádná ze očekávaných hodnot "
            "(teplota vody/vzduchu, obsazenost, stav otevření)."
        )

    # Věrohodnost hodnot. Nesmysl z webu radši zahodíme, než abychom ho
    # zapsali do dlouhodobých statistik Home Assistantu.
    data.water_temp = _plausible_temp(data.water_temp)
    data.air_temp = _plausible_temp(data.air_temp)

    limit = PLAUSIBLE_OCCUPANCY_MAX
    if data.capacity is not None and not 0 < data.capacity <= limit:
        data.capacity = None
    if data.occupancy is not None and not 0 <= data.occupancy <= limit:
        data.occupancy = None
    if (
        data.occupancy is not None
        and data.capacity is not None
        and data.occupancy > data.capacity
    ):
        # Web občas hlásí plný areál jako „1000 / 1000“; vyšší číslo než
        # kapacita je ale chyba a rozbilo by procenta.
        _LOGGER.debug(
            "Obsazenost (%s) je vyšší než kapacita (%s), zahazuji kapacitu",
            data.occupancy,
            data.capacity,
        )
        data.capacity = None

    return data


def _read_badge(text: str) -> bool | None:
    """Přečte stavový odznak. Vrací None, když v textu není.

    „Zavřeno“ se testuje první: text může obsahovat obojí (např. „Otevírací
    doba: dnes zavřeno“) a v takovém případě je rozhodující zápor.

    Pozor na slovo „Otevírací“ — proto se hledá kmen ``otevřen``, ne ``otev``.
    """
    lowered = text.lower()
    if re.search(r"zav[řr]en", lowered):
        return False
    if re.search(r"otev[řr]en", lowered):
        return True
    return None


def _read_badge_strict(text: str) -> bool | None:
    """Přísnější varianta pro čtení z celého textu stránky.

    Vyžaduje samostatné slovo ve verzálkách, jak ho web v odznaku používá.
    Tím se odliší skutečný odznak od zmínek v běžném textu („dnes je bufet
    zavřený“), které by jinak přebily stav celého areálu.
    """
    if re.search(r"\bZAV[ŘR]ENO\b", text):
        return False
    if re.search(r"\bOTEV[ŘR]ENO\b", text):
        return True
    return None


# --- Parsování otevírací doby -----------------------------------------------


def parse_hours(html: str) -> list[ScheduleEntry]:
    """Naparsuje tabulku otevírací doby.

    Tabulka má tři sloupce ``[měsíc, dny, hodiny]``, přičemž buňka s měsícem
    je vyplněná jen u prvního řádku daného měsíce (další řádky ji dědí).

    Raises:
        ParseError: pokud se nepodařilo přečíst žádný použitelný řádek.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[ScheduleEntry] = []

    for table in soup.find_all("table"):
        current_name: str | None = None
        current_month: int | None = None

        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 3:
                continue

            month_cell, days_cell, hours_cell = cells[0], cells[1], cells[2]

            if month_cell:
                month = MONTHS.get(month_cell.strip().lower())
                if month is None:
                    # Nejde o řádek rozvrhu (hlavička, poznámka, …).
                    continue
                current_name = clean_text(month_cell)
                current_month = month

            if current_month is None:
                continue

            hours = _RE_HOURS_RANGE.search(hours_cell)
            weekdays = parse_day_range(days_cell)
            if not hours or not weekdays:
                continue

            try:
                opens = time(int(hours.group(1)), int(hours.group(2)))
                closes = time(int(hours.group(3)), int(hours.group(4)))
            except ValueError:
                # Nesmyslný čas (např. 25:00) — řádek zahodíme.
                continue

            if opens == closes:
                # Nulový blok („10:00 – 10:00“) je typo na webu. Kdybychom ho
                # přijali, vypadal by jako blok přes půlnoc a znamenal by
                # „otevřeno nonstop“.
                _LOGGER.debug("Zahazuji nulový blok %s", hours_cell)
                continue

            entries.append(
                ScheduleEntry(
                    month_name=current_name or "",
                    month=current_month,
                    days_label=clean_text(days_cell),
                    weekdays=weekdays,
                    opens=opens,
                    closes=closes,
                )
            )

            if len(entries) >= MAX_SCHEDULE_ROWS:
                # Reálný rozvrh má jednotky řádků. Strop chrání Home Assistant
                # před tím, aby rozbitý (nebo nepřátelský) web nafoukl atribut
                # entity do desítek megabajtů — viz SECURITY.md.
                _LOGGER.warning(
                    "Tabulka otevírací doby má víc než %d řádků, "
                    "zpracovávám jen prvních %d",
                    MAX_SCHEDULE_ROWS,
                    MAX_SCHEDULE_ROWS,
                )
                break

        if entries:
            # První tabulka s použitelnými řádky vyhrává.
            break

    if not entries:
        raise ParseError(
            "Na stránce otevírací doby se nenašla čitelná tabulka. "
            "Mimo sezónu to může být v pořádku, jinak se změnila struktura webu."
        )

    return entries


def entries_for(schedule: list[ScheduleEntry], moment: datetime) -> list[ScheduleEntry]:
    """Všechny řádky rozvrhu platné pro daný den.

    Web dnes uvádí jeden blok na den, ale nic mu nebrání rozdělit den na dva
    (např. přerušení na údržbu). Proto vracíme seznam, ne jeden řádek.
    """
    return [
        entry
        for entry in schedule
        if entry.month == moment.month and moment.weekday() in entry.weekdays
    ]


def entry_for(schedule: list[ScheduleEntry], moment: datetime) -> ScheduleEntry | None:
    """Řádek rozvrhu pro daný okamžik.

    Přednost má blok, který právě probíhá (včetně bloku, který začal včera
    před půlnocí); jinak nejbližší následující blok téhož dne; jinak první
    blok dne. Díky tomu odpovídá „dnešní otevírací doba“ tomu, co uživatele
    zajímá teď.
    """
    now = moment.time()

    # Blok z předchozího dne, který ještě běží (např. 22:00 – 1:00).
    for entry in entries_for(schedule, moment - timedelta(days=1)):
        if entry.closes <= entry.opens and now < entry.closes:
            return entry

    candidates = entries_for(schedule, moment)
    if not candidates:
        return None

    for entry in candidates:
        if _within(entry, now):
            return entry
    upcoming = [entry for entry in candidates if entry.opens > now]
    if upcoming:
        return min(upcoming, key=lambda entry: entry.opens)
    return candidates[0]


def _within(entry: ScheduleEntry, moment: time) -> bool:
    """Spadá čas do bloku? Zvládá i blok přes půlnoc (např. 22:00 – 1:00)."""
    if entry.closes <= entry.opens:
        return moment >= entry.opens or moment < entry.closes
    return entry.opens <= moment < entry.closes


def is_open_by_schedule(schedule: list[ScheduleEntry], moment: datetime) -> bool:
    """Je areál podle rozvrhu v daný okamžik otevřený?"""
    now = moment.time()
    if any(_within(entry, now) for entry in entries_for(schedule, moment)):
        return True

    # Blok začínající před půlnocí pokračuje do dalšího dne, který už má
    # v rozvrhu jiný (nebo žádný) řádek — proto se koukneme i na včerejšek.
    yesterday = moment - timedelta(days=1)
    return any(
        entry.closes <= entry.opens and now < entry.closes
        for entry in entries_for(schedule, yesterday)
    )


def last_entry_time(entry: ScheduleEntry, minutes_before: int = 45) -> time:
    """Čas posledního vstupu — web uvádí 45 minut před zavírací dobou."""
    # Datum je tu jen nosič pro odečtení minut; časová zóna nehraje roli,
    # protože výsledek je opět jen čas (bez data).
    closes = datetime.combine(datetime.min.date(), entry.closes)  # noqa: DTZ901
    return (closes - timedelta(minutes=minutes_before)).time()


# --- HTTP -------------------------------------------------------------------


def _cache_header(value: str | None) -> str | None:
    """Omezí hodnotu cache hlavičky, kterou budeme posílat zpět serveru."""
    if not value:
        return None
    cleaned = _RE_CONTROL_CHARS.sub("", value).strip()
    return cleaned[:MAX_CACHE_HEADER_LENGTH] or None


async def async_fetch(
    session: aiohttp.ClientSession,
    url: str,
    cache: CacheHeaders | None = None,
) -> FetchResult:
    """Stáhne stránku s podmíněným dotazem a bezpečnostními limity.

    Opatření, která tu jsou záměrně:

    * **Timeout** na celý požadavek — bez něj by zaseknutý server dokázal
      zablokovat aktualizaci integrace na neomezenou dobu.
    * **Přesměrování se nenásledují** (``allow_redirects=False``). Kdyby se
      následovala, kompromitovaný web by mohl hlavičkou ``Location`` donutit
      Home Assistant zavolat adresu v domácí síti — a stalo by se to *dřív*,
      než bychom cíl mohli zkontrolovat. Adresy jsou pevné, takže legitimní
      důvod k přesměrování neexistuje.
    * **Kontrola schématu a hostu** výsledné adresy — musí být ``https``
      a jeden z :data:`ALLOWED_HOSTS`. Bez kontroly schématu by přesměrování
      na ``http://`` tiše zrušilo šifrování.
    * **Strop velikosti odpovědi** — brání vyčerpání paměti.
    * **Podmíněný dotaz** (``If-None-Match`` / ``If-Modified-Since``) —
      pokud se stránka nezměnila, server vrátí 304 a nepřenáší se nic.
    * TLS se ověřuje (výchozí chování aiohttp); ověřování se nikde nevypíná.

    Raises:
        FetchError: při jakémkoli problému se stažením.
    """
    headers: dict[str, str] = {
        # Slušný User-Agent: identifikuje se a odkazuje na projekt, aby
        # správce webu věděl, kdo ho navštěvuje, a mohl se ozvat.
        "User-Agent": (
            "HomeAssistant-KoupalisteLhotka/2.0 "
            "(+https://github.com/gadamcz/ha-koupaliste-lhotka)"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "cs,en;q=0.5",
    }
    if cache and cache.etag:
        headers["If-None-Match"] = cache.etag
    if cache and cache.last_modified:
        headers["If-Modified-Since"] = cache.last_modified

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)

    try:
        async with session.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        ) as response:
            # Pojistka: adresa, se kterou jsme skutečně mluvili, musí být
            # ta naše a přes HTTPS. Host se do chybové zprávy nedává —
            # pochází z odpovědi serveru, takže by to byl text, který
            # ovlivňuje cizí strana.
            if response.url.scheme != "https" or response.url.host not in ALLOWED_HOSTS:
                raise FetchError("Odpověď přišla z neočekávané adresy")

            if response.status in (301, 302, 303, 307, 308):
                raise FetchError(
                    f"Server přesměrovává (HTTP {response.status}), "
                    "což u pevné adresy nečekáme"
                )

            if response.status == 304:
                return FetchResult(
                    text=None,
                    etag=cache.etag if cache else None,
                    last_modified=cache.last_modified if cache else None,
                    not_modified=True,
                )

            if response.status != 200:
                raise FetchError(f"HTTP {response.status} pro {url}")

            # Pokud server délku hlásí předem, odmítneme přehnaně velké tělo
            # ještě před stažením.
            declared = response.content_length
            if declared is not None and declared > MAX_RESPONSE_BYTES:
                raise FetchError(
                    f"Odpověď je příliš velká ({declared} B, limit "
                    f"{MAX_RESPONSE_BYTES} B)"
                )

            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise FetchError(f"Odpověď překročila limit {MAX_RESPONSE_BYTES} B")
                chunks.append(chunk)

            raw = b"".join(chunks)
            # Web hlásí UTF-8; charset z hlavičky respektujeme, ale s bezpečným
            # fallbackem a bez pádu na neplatných bajtech.
            encoding = response.charset or "utf-8"
            try:
                text = raw.decode(encoding, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")

            return FetchResult(
                text=text,
                # Hlavičky si pamatujeme a příště posíláme zpět, takže je
                # zkrátíme — jinak by šlo o neomezená data cizí strany
                # držená v paměti i v každém dalším požadavku.
                etag=_cache_header(response.headers.get("ETag")),
                last_modified=_cache_header(response.headers.get("Last-Modified")),
            )

    except FetchError:
        raise
    except aiohttp.ClientError as err:
        # Text výjimky často obsahuje data ze serveru (URL, hlavičky, TLS SAN),
        # a končí v atributu entity i v logu — proto přes clean_text.
        raise FetchError(f"Chyba připojení: {clean_text(str(err))}") from err
    except TimeoutError as err:
        raise FetchError(f"Server neodpověděl do {REQUEST_TIMEOUT_SECONDS} s") from err
