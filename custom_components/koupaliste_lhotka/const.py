"""Konstanty integrace Koupaliště Lhotka.

Všechny "magické" hodnoty integrace žijí tady, aby se daly změnit na jednom
místě a aby zbytek kódu šel čtený jako popis chování, ne jako konfigurace.

Bezpečnostní poznámka: URL adresy jsou *konstanty*. Integrace záměrně
neumožňuje uživateli zadat vlastní URL — tím je vyloučená celá třída zranitelností
typu SSRF (Server-Side Request Forgery), kdy by útočník donutil Home Assistant
stahovat data z interní sítě. Viz SECURITY.md.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "koupaliste_lhotka"

# --- Zdroje dat -------------------------------------------------------------

BASE_URL: Final = "https://www.koupaliste-lhotka.cz"
#: Domovská stránka — nese aktuální teploty, obsazenost a stavový odznak.
URL_HOME: Final = f"{BASE_URL}/"
#: Stránka s tabulkou otevírací doby (mění se řádově jednou za sezónu).
URL_HOURS: Final = f"{BASE_URL}/oteviraci-doba/"

#: Hostnames, na které se integrace smí připojit. Používá se jako pojistka
#: proti přesměrování na cizí (např. interní) server — viz scraper.async_fetch.
#: Apex doména je uvedená proto, že WordPress mezi ní a „www“ běžně
#: přesměrovává podle konfigurace.
ALLOWED_HOSTS: Final = frozenset({"www.koupaliste-lhotka.cz", "koupaliste-lhotka.cz"})

# --- Časování ---------------------------------------------------------------

#: Výchozí interval čtení "živých" dat (teploty, obsazenost).
DEFAULT_SCAN_INTERVAL_MINUTES: Final = 10
MIN_SCAN_INTERVAL_MINUTES: Final = 5
MAX_SCAN_INTERVAL_MINUTES: Final = 120

#: Otevírací doba se mění zřídka, proto ji čteme výrazně méně často.
HOURS_REFRESH_INTERVAL: Final = timedelta(hours=6)

#: Dokud rozvrh nemáme vůbec, zkoušíme ho častěji — jinak by po restartu
#: Home Assistantu během krátkého výpadku webu byla otevírací doba
#: nedostupná celých šest hodin.
HOURS_RETRY_INTERVAL: Final = timedelta(minutes=15)

#: HTTP timeout pro jeden požadavek (připojení + čtení).
REQUEST_TIMEOUT_SECONDS: Final = 20

#: Strop exponenciálního backoffu při opakovaném selhání webu.
BACKOFF_MAX_INTERVAL: Final = timedelta(minutes=60)

#: Po kolika neúspěšných pokusech v řadě založit "Repair" hlášku v HA.
FAILURES_BEFORE_ISSUE: Final = 6

# --- Limity (ochrana proti zneužití / chybě na straně webu) -----------------

#: Maximální velikost stažené odpovědi. Chrání proti vyčerpání paměti,
#: pokud by server (nebo útočník na cestě) poslal nesmyslně velké tělo.
MAX_RESPONSE_BYTES: Final = 3 * 1024 * 1024  # 3 MiB

#: Maximální délka textu přebíraného z webu do stavu entity. Zabraňuje tomu,
#: aby se do Home Assistantu (a jeho databáze) dostal neomezeně dlouhý řetězec.
MAX_TEXT_LENGTH: Final = 64

#: Maximální počet řádků rozvrhu. Bez tohoto stropu by nepřátelský (nebo
#: rozbitý) web mohl poslat desítky tisíc validních řádků; všechny by skončily
#: v atributu entity, a tím ve state machine, v každé WebSocket zprávě
#: a v databázi — tedy DoS na celý Home Assistant. Reálný rozvrh má ~8 řádků.
MAX_SCHEDULE_ROWS: Final = 64

#: Věrohodné rozsahy hodnot. Cokoli mimo ně je chyba na webu, ne měření —
#: a zapsané do dlouhodobých statistik by se špatně odstraňovalo.
PLAUSIBLE_TEMP_RANGE: Final = (-30.0, 60.0)
PLAUSIBLE_OCCUPANCY_MAX: Final = 100_000

#: Maximální délka hodnoty cache hlavičky, kterou si od serveru zapamatujeme
#: a příště pošleme zpět. Bez limitu by šlo o neomezená data cizí strany
#: držená v paměti a posílaná v každém požadavku.
MAX_CACHE_HEADER_LENGTH: Final = 200

#: Kapacita areálu, pokud ji web zrovna neuvádí (pro výpočet procent).
FALLBACK_CAPACITY: Final = 1000

#: Jak dlouho se ještě věří stavovému odznaku z webu. Po výpadku delším než
#: tohle se odznak ignoruje a rozhoduje jen rozvrh — jinak by zapomenuté
#: „zavřeno“ držel areál zavřený i dny po znovuotevření.
BADGE_MAX_AGE: Final = timedelta(hours=3)

# --- Konfigurační klíče -----------------------------------------------------

CONF_SCAN_INTERVAL_MINUTES: Final = "scan_interval_minutes"

# --- Klíče entit (unique_id) ------------------------------------------------
#
# POZOR: tyto hodnoty jsou součástí veřejného kontraktu integrace.
# Home Assistant si podle nich pamatuje entity v registru; jejich změna
# uživatelům rozbije entity_id, dashboardy i historii. Viz ARCHITECTURE.md.

KEY_WATER_TEMP: Final = "lhotka_water_temp"
KEY_AIR_TEMP: Final = "lhotka_air_temp"
KEY_OCCUPANCY: Final = "lhotka_occupancy"
KEY_OCCUPANCY_PCT: Final = "lhotka_occupancy_pct"
KEY_OPENING_HOURS: Final = "lhotka_opening_hours"
KEY_STATUS: Final = "lhotka_data_status"
KEY_IS_OPEN: Final = "lhotka_is_open"

ATTRIBUTION: Final = "Data: koupaliste-lhotka.cz"

# --- Repair issues ----------------------------------------------------------

ISSUE_UNREADABLE: Final = "data_unreadable"
ISSUE_PARSE_CHANGED: Final = "parse_changed"
