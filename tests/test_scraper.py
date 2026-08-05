"""Testy parserů.

Testy záměrně **nepotřebují Home Assistant** — modul ``scraper`` na něm
nezávisí, takže se dá testovat obyčejným pytestem (``pytest -q``).
To je hlavní důvod, proč je parsování oddělené od integrace.

Fixtures v ``tests/fixtures/`` jsou zkrácené, ale strukturně věrné snímky
skutečných stránek. Když web přestaví HTML, aktualizuje se fixture a testy
okamžitě ukážou, co přestalo fungovat.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Modul nahráváme přímo ze souboru, ne jako součást balíčku. Tím se vyhneme
# importu ``__init__.py``, který potřebuje běžící Home Assistant — testy
# parseru tak jdou pustit v jakémkoli virtualenvu s bs4, aiohttp a pytestem.
_SCRAPER_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "koupaliste_lhotka"
    / "scraper.py"
)


def _load_scraper():
    """Nahraje ``scraper.py`` izolovaně, včetně jeho relativního importu const."""
    import sys
    import types

    package = "koupaliste_lhotka_standalone"
    # Prázdný náhradní balíček — skutečné ``__init__.py`` nespouštíme.
    stub = types.ModuleType(package)
    stub.__path__ = [str(_SCRAPER_PATH.parent)]
    sys.modules[package] = stub

    for name in ("const", "scraper"):
        spec = importlib.util.spec_from_file_location(
            f"{package}.{name}", _SCRAPER_PATH.parent / f"{name}.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{package}.{name}"] = module
        spec.loader.exec_module(module)

    return sys.modules[f"{package}.scraper"]


scraper = _load_scraper()

ParseError = scraper.ParseError
ScheduleEntry = scraper.ScheduleEntry
clean_text = scraper.clean_text
entries_for = scraper.entries_for
entry_for = scraper.entry_for
is_open_by_schedule = scraper.is_open_by_schedule
last_entry_time = scraper.last_entry_time
parse_day_range = scraper.parse_day_range
parse_home = scraper.parse_home
parse_hours = scraper.parse_hours

FIXTURES = Path(__file__).parent / "fixtures"
PRAGUE = ZoneInfo("Europe/Prague")


@pytest.fixture(name="home_html")
def home_html_fixture() -> str:
    return (FIXTURES / "home.html").read_text(encoding="utf-8")


@pytest.fixture(name="hours_html")
def hours_html_fixture() -> str:
    return (FIXTURES / "hours.html").read_text(encoding="utf-8")


@pytest.fixture(name="schedule")
def schedule_fixture(hours_html: str):
    return parse_hours(hours_html)


# --- Domovská stránka -------------------------------------------------------


def test_parse_home_reads_all_values(home_html: str) -> None:
    data = parse_home(home_html)

    assert data.water_temp == 26.5
    assert data.air_temp == 37.0
    assert data.occupancy == 842
    assert data.capacity == 1000
    assert data.badge_open is True
    assert data.occupancy_pct == 84.2


def test_parse_home_detects_closed_badge(home_html: str) -> None:
    data = parse_home(home_html.replace("OTEVŘENO", "ZAVŘENO"))
    assert data.badge_open is False


def test_parse_home_falls_back_to_plain_text() -> None:
    """Když zmizí CSS třídy, parser musí data najít v textu stránky."""
    html = """
    <html><body>
      <p>Teplota vody: 21,3°C Teplota vzduchu: 24°C
         Aktuální obsazenost: 150 / 1000</p>
    </body></html>
    """
    data = parse_home(html)

    assert data.water_temp == 21.3
    assert data.air_temp == 24.0
    assert data.occupancy == 150
    assert data.capacity == 1000
    assert data.badge_open is None


def test_parse_home_raises_when_nothing_found() -> None:
    with pytest.raises(ParseError):
        parse_home("<html><body><p>Stránka nenalezena</p></body></html>")


def test_occupancy_pct_without_capacity() -> None:
    data = parse_home("<html><body>Teplota vody: 20°C</body></html>")
    assert data.occupancy_pct is None


# --- Otevírací doba ---------------------------------------------------------


def test_parse_hours_reads_all_rows(schedule) -> None:
    assert len(schedule) == 8

    june_workdays = schedule[0]
    assert june_workdays.month == 6
    assert june_workdays.month_name == "červen"
    assert june_workdays.weekdays == (0, 1, 2, 3)
    assert june_workdays.opens == time(10, 0)
    assert june_workdays.closes == time(19, 0)
    assert june_workdays.hours_label == "10:00 – 19:00"


def test_parse_hours_inherits_month_from_previous_row(schedule) -> None:
    """Prázdná buňka měsíce dědí měsíc z předchozího řádku."""
    assert [entry.month for entry in schedule] == [6, 6, 6, 6, 7, 8, 9, 9]


def test_parse_hours_raises_without_table() -> None:
    with pytest.raises(ParseError):
        parse_hours("<html><body><p>Mimo sezónu</p></body></html>")


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("po", (0,)),
        ("po – čt", (0, 1, 2, 3)),
        ("so – ne", (5, 6)),
        ("po - ne", (0, 1, 2, 3, 4, 5, 6)),  # obyčejný spojovník
        ("po — ne", (0, 1, 2, 3, 4, 5, 6)),  # em dash
        ("so – po", (5, 6, 0)),  # rozsah přes konec týdne
        ("pondělí – středa", (0, 1, 2)),
        ("bla", ()),
    ],
)
def test_parse_day_range(label: str, expected: tuple[int, ...]) -> None:
    assert parse_day_range(label) == expected


# --- Vyhodnocení rozvrhu ----------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "expected_hours"),
    [
        (datetime(2026, 6, 15, 12, 0, tzinfo=PRAGUE), "10:00 – 19:00"),  # pondělí
        (datetime(2026, 6, 19, 12, 0, tzinfo=PRAGUE), "10:00 – 20:00"),  # pátek
        (datetime(2026, 6, 20, 12, 0, tzinfo=PRAGUE), "9:00 – 20:00"),  # sobota
        (datetime(2026, 7, 3, 12, 0, tzinfo=PRAGUE), "9:00 – 20:00"),
        (datetime(2026, 9, 23, 12, 0, tzinfo=PRAGUE), "10:00 – 18:00"),  # středa
        (datetime(2026, 9, 27, 12, 0, tzinfo=PRAGUE), "9:00 – 18:00"),  # nedělě
    ],
)
def test_entry_for_finds_right_row(
    schedule, moment: datetime, expected_hours: str
) -> None:
    entry = entry_for(schedule, moment)
    assert entry is not None
    assert entry.hours_label == expected_hours


def test_entry_for_outside_season(schedule) -> None:
    assert entry_for(schedule, datetime(2026, 10, 5, 12, 0, tzinfo=PRAGUE)) is None
    assert entry_for(schedule, datetime(2026, 1, 5, 12, 0, tzinfo=PRAGUE)) is None


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 7, 3, 8, 59, tzinfo=PRAGUE), False),  # před otevřením
        (datetime(2026, 7, 3, 9, 0, tzinfo=PRAGUE), True),  # přesně v otevření
        (datetime(2026, 7, 3, 15, 0, tzinfo=PRAGUE), True),
        (datetime(2026, 7, 3, 19, 59, tzinfo=PRAGUE), True),
        (datetime(2026, 7, 3, 20, 0, tzinfo=PRAGUE), False),  # přesně v zavření
        (datetime(2026, 7, 3, 23, 0, tzinfo=PRAGUE), False),
        (datetime(2026, 11, 3, 12, 0, tzinfo=PRAGUE), False),  # mimo sezónu
    ],
)
def test_is_open_by_schedule(schedule, moment: datetime, expected: bool) -> None:
    assert is_open_by_schedule(schedule, moment) is expected


def test_last_entry_time(schedule) -> None:
    july = entry_for(schedule, datetime(2026, 7, 3, 12, 0, tzinfo=PRAGUE))
    assert july is not None
    assert last_entry_time(july) == time(19, 15)


# --- Robustnost / bezpečnost ------------------------------------------------


def test_long_text_is_truncated() -> None:
    """Dlouhý text z webu se do atributů nesmí dostat v plné délce."""
    long_label = "č" * 500
    html = f"""
    <html><body><table>
      <tr><td>červen</td><td>{long_label}</td><td>9:00 – 20:00</td></tr>
    </table></body></html>
    """
    # Dny se nenaparsují (neznámý zápis), takže řádek propadne — parser
    # nesmí spadnout ani vrátit obří řetězec.
    with pytest.raises(ParseError):
        parse_hours(html)


def test_invalid_time_is_skipped() -> None:
    html = """
    <html><body><table>
      <tr><td>červen</td><td>po</td><td>25:00 – 99:00</td></tr>
      <tr><td>červenec</td><td>po</td><td>9:00 – 20:00</td></tr>
    </table></body></html>
    """
    schedule = parse_hours(html)
    assert len(schedule) == 1
    assert schedule[0].month == 7


def test_parser_handles_huge_input_quickly() -> None:
    """Ochrana proti ReDoS: parser musí zvládnout patologický vstup."""
    import time as _time

    hostile = "Teplota vody: " + ("9" * 50_000)
    started = _time.monotonic()
    with pytest.raises(ParseError):
        parse_home(f"<html><body>{hostile}</body></html>")
    assert _time.monotonic() - started < 2.0


def test_redos_pattern_is_fast() -> None:
    """Vstup mířený na backtracking mezerových skupin musí projít rychle."""
    import time as _time

    hostile = "teplota vody" + (" " * 20_000) + "x"
    started = _time.monotonic()
    with pytest.raises(ParseError):
        parse_home(f"<html><body>{hostile}</body></html>")
    assert _time.monotonic() - started < 2.0


def test_schedule_rows_are_capped() -> None:
    """Nepřátelský web nesmí nafouknout atribut entity bez limitu."""
    rows = "<tr><td>červen</td><td>po</td><td>9:00 – 20:00</td></tr>" * 5_000
    schedule = parse_hours(f"<html><body><table>{rows}</table></body></html>")
    assert len(schedule) == scraper.MAX_SCHEDULE_ROWS


def test_clean_text_strips_control_characters() -> None:
    """NUL láme recorder, ESC umožňuje injektáž do logu — obojí musí zmizet."""
    assert clean_text("a\x00b\x1b[31mc") == "ab[31mc"
    assert clean_text("  více   mezer\n\t ") == "více mezer"
    assert len(clean_text("x" * 1_000)) == scraper.MAX_TEXT_LENGTH


def test_implausible_values_are_discarded() -> None:
    """Nesmyslné hodnoty se nesmí dostat do dlouhodobých statistik."""
    data = parse_home(
        "<html><body>Teplota vody: -999°C Teplota vzduchu: 999°C"
        " Aktuální obsazenost: 5 / 1000</body></html>"
    )
    assert data.water_temp is None
    assert data.air_temp is None
    assert data.occupancy == 5


def test_occupancy_above_capacity_drops_percentage() -> None:
    """Obsazenost vyšší než kapacita je chyba webu, ne 300 %."""
    data = parse_home("<html><body>Aktuální obsazenost: 3000 / 1000</body></html>")
    assert data.occupancy == 3000
    assert data.capacity is None
    assert data.occupancy_pct is None


# --- Stavový odznak ---------------------------------------------------------


@pytest.mark.parametrize(
    ("badge_html", "expected"),
    [
        ("<div class='opening-hours'><p>OTEVŘENO</p></div>", True),
        ("<div class='opening-hours'><p>ZAVŘENO</p></div>", False),
        # Nadpis „Otevírací doba“ nesmí být čten jako „otevřeno“.
        (
            "<div class='opening-hours'><p>Otevírací doba: dnes zavřeno</p></div>",
            False,
        ),
        ("<div class='opening-hours'><p>Otevírací doba</p></div>", None),
    ],
)
def test_badge_detection(badge_html: str, expected: bool | None) -> None:
    html = (
        "<html><body>"
        f"{badge_html}"
        "<div class='header-obsazenost__inner'>"
        "Teplota vody: <strong>20°C</strong></div>"
        "</body></html>"
    )
    assert parse_home(html).badge_open is expected


# --- Více bloků za den a přechod přes půlnoc --------------------------------


def _entry(month: int, weekday: int, opens: time, closes: time) -> ScheduleEntry:
    return ScheduleEntry(
        month_name="červenec",
        month=month,
        days_label="po",
        weekdays=(weekday,),
        opens=opens,
        closes=closes,
    )


def test_two_blocks_per_day() -> None:
    """Když má den dva bloky (např. přerušení na údržbu), platí oba."""
    schedule = [
        _entry(7, 0, time(9, 0), time(12, 0)),
        _entry(7, 0, time(14, 0), time(20, 0)),
    ]
    monday = datetime(2026, 7, 6, tzinfo=PRAGUE)  # pondělí

    assert len(entries_for(schedule, monday)) == 2
    assert is_open_by_schedule(schedule, monday.replace(hour=10)) is True
    assert is_open_by_schedule(schedule, monday.replace(hour=13)) is False
    assert is_open_by_schedule(schedule, monday.replace(hour=15)) is True

    # „Dnešní otevírací doba“ ukazuje blok, který právě běží.
    current = entry_for(schedule, monday.replace(hour=15))
    assert current is not None
    assert current.hours_label == "14:00 – 20:00"

    # Mezi bloky ukazuje ten nejbližší následující.
    between = entry_for(schedule, monday.replace(hour=13))
    assert between is not None
    assert between.hours_label == "14:00 – 20:00"


def test_zero_length_block_is_rejected() -> None:
    """„10:00 – 10:00“ je typo, ne nonstop provoz."""
    html = """
    <html><body><table>
      <tr><td>červenec</td><td>po</td><td>10:00 – 10:00</td></tr>
    </table></body></html>
    """
    with pytest.raises(ParseError):
        parse_hours(html)


def test_percentage_is_capped_at_hundred() -> None:
    """Rozejití obsazenosti a kapacity nesmí dát tisíce procent."""
    data = scraper.LiveData(occupancy=99_999, capacity=1_000)
    assert data.occupancy_pct == 100.0


def test_strict_badge_ignores_ordinary_text() -> None:
    """Fallback nesmí považovat běžnou zmínku v textu za stavový odznak."""
    html = (
        "<html><body><p>Bufet je dnes zavřený, areál funguje běžně.</p>"
        "<p>Teplota vody: 22°C</p></body></html>"
    )
    assert parse_home(html).badge_open is None

    html_badge = "<html><body><p>ZAVŘENO</p><p>Teplota vody: 22°C</p></body></html>"
    assert parse_home(html_badge).badge_open is False


def test_overnight_block() -> None:
    """Noční koupání 22:00 – 1:00 musí platit i po půlnoci."""
    schedule = [_entry(7, 0, time(22, 0), time(1, 0))]  # pondělí

    monday_night = datetime(2026, 7, 6, 23, 0, tzinfo=PRAGUE)
    tuesday_early = datetime(2026, 7, 7, 0, 30, tzinfo=PRAGUE)
    tuesday_later = datetime(2026, 7, 7, 2, 0, tzinfo=PRAGUE)

    assert is_open_by_schedule(schedule, monday_night) is True
    assert is_open_by_schedule(schedule, tuesday_early) is True
    assert is_open_by_schedule(schedule, tuesday_later) is False


def test_overnight_block_reported_after_midnight() -> None:
    """Po půlnoci musí „dnešní doba“ ukazovat běžící noční blok, ne ten další."""
    schedule = [
        _entry(7, 0, time(22, 0), time(1, 0)),  # pondělí 22:00 – 1:00
        _entry(7, 1, time(9, 0), time(19, 0)),  # úterý 9:00 – 19:00
    ]
    after_midnight = datetime(2026, 7, 7, 0, 30, tzinfo=PRAGUE)

    entry = entry_for(schedule, after_midnight)
    assert entry is not None
    assert entry.hours_label == "22:00 – 1:00"
    assert is_open_by_schedule(schedule, after_midnight) is True


def test_clean_text_strips_bidi_and_zero_width() -> None:
    """Neviditelné znaky umí v UI předstírat jiný text."""
    assert clean_text("a​b‮c") == "abc"
