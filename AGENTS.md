# Pokyny pro AI asistenty

Tenhle soubor čti první. Je to shrnutí pro AI (Claude Code, Cursor, Copilot…),
která má v repozitáři něco změnit. Podrobnosti jsou v
[ARCHITECTURE.md](ARCHITECTURE.md).

## O co jde

Custom integrace pro Home Assistant. Parsuje veřejný web
`koupaliste-lhotka.cz` (WordPress, HTML ze serveru — žádné API neexistuje)
a dělá z něj entity: teploty, obsazenost, otevírací dobu, „otevřeno“.

## Než začneš měnit kód

1. Přečti [ARCHITECTURE.md](ARCHITECTURE.md), zejména sekce **Nedotknutelné
   kontrakty** (§4) a **Časté chyby** (§7).
2. Spusť `pytest` — ať víš, že výchozí stav je zelený.
3. Zjisti, jestli tvoje změna nespadá do kategorie „rozbije existující
   instalace“ (viz níže).

## Tvrdá pravidla

Tyhle věci **neměň**, dokud si to uživatel výslovně nevyžádá i s vědomím
následků:

- `unique_id` entit (konstanty `KEY_*` v `const.py`) — změna zničí historii
  a rozbije dashboardy uživatelů
- `DOMAIN = "koupaliste_lhotka"`
- české klíče atributů: `rozvrh` (a v něm `mesic`, `dny`, `hodiny`),
  `otevreno_ted`, `dnes_od`, `dnes_do`, `posledni_vstup`, `kapacita`
  (zobrazované *názvy* entit naopak měnit lze — `entity_id` na nich nezávisí)
- bezpečnostní opatření: timeouty, limit velikosti odpovědi, kontrola hostu
  po přesměrování, omezené kvantifikátory v regexech, limit délky textů
- zákaz konfigurovatelné URL (ochrana proti SSRF)

## Konvence, které dodržuj

- `scraper.py` **neimportuje `homeassistant`**. Je to čistý parser, díky
  tomu jdou testy pustit bez HA.
- Žádné blokující I/O v `async` funkcích. HTTP jen přes `async_fetch()`,
  parsování přes `hass.async_add_executor_job(...)`.
- Session z `async_get_clientsession(hass)`, nikdy vlastní.
- Selhání se nepolykají. Buď `UpdateFailed`, nebo log, nebo repair issue.
- U živých dat je při chybě správná odpověď `unavailable`, ne stará hodnota.
- Komentáře vysvětlují **proč**, ne co. Repozitář slouží i jako učební
  materiál, takže vysvětlující komentáře jsou žádoucí, ne šum.
- Uživatelské texty česky (`strings.json`) + anglicky
  (`translations/en.json`); oba soubory musí mít stejné klíče.

## Definice hotového

```bash
ruff check . && ruff format --check . && pytest -q
```

Navíc:

- nová/změněná funkce parseru má test a případně fixture
  v `tests/fixtures/`
- změna chování je popsaná v `CHANGELOG.md`
- nová entita je v tabulce v `README.md`
- při vydání se zvedla `version` v `manifest.json`

## Typická zadání a kde se odehrají

| Zadání | Soubory |
| --- | --- |
| Web se přestavěl, parser nefunguje | `scraper.py`, `tests/fixtures/`, `tests/test_scraper.py` |
| Přidat senzor z existujících dat | `const.py`, `sensor.py`, `README.md` |
| Přidat senzor z nových dat na webu | `scraper.py` (+ `LiveData`), pak jako výše |
| Změnit frekvenci čtení | `const.py` (limity), `coordinator.py` |
| Nová hláška pro uživatele | `strings.json` + `translations/en.json` |
| Změna chování při chybách | `coordinator.py` (`_register_failure`) |
