# Architektura

Tento dokument je **výchozí kontext pro každého, kdo integraci rozvíjí** —
člověka i AI asistenta. Je psaný tak, aby se dal přiložit k zadání („tady je
popis projektu, udělej X“) a asistent z něj pochopil nejen *co* kód dělá, ale
i *proč* je napsaný takhle a čeho se nesmí dotknout.

Pokud jsi AI asistent: přečti si sekce **Nedotknutelné kontrakty** a
**Časté chyby** dřív, než začneš cokoli měnit.

---

## 1. Co integrace dělá

Čte veřejný web `koupaliste-lhotka.cz` (WordPress, HTML generované na serveru)
a převádí ho na entity Home Assistantu. Neexistuje žádné API — jediná cesta
k datům je parsování HTML. Z toho vyplývá celý zbytek návrhu:

* zdroj dat se může **kdykoli změnit** bez ohlášení → parsery musí být
  odolné a jejich selhání musí být viditelné,
* zdroj dat je **cizí server** → čteme ho ohleduplně a s bezpečnostními limity,
* data jsou **veřejná a nekritická** → není tu co šifrovat ani autorizovat.

Zdroje:

| URL | Obsah | Frekvence čtení |
| --- | --- | --- |
| `/` | teplota vody, teplota vzduchu, obsazenost, odznak OTEVŘENO/ZAVŘENO | dle nastavení, výchozí 10 min |
| `/oteviraci-doba/` | tabulka otevírací doby po měsících | 1× za 6 hodin |

---

## 2. Mapa souborů

```
custom_components/koupaliste_lhotka/
├── __init__.py        Vstupní bod: setup/unload config entry, seznam platforem
├── const.py           Všechny konstanty, limity a klíče entit
├── scraper.py         HTTP + parsování HTML. NEZÁVISLÉ na Home Assistantu
├── coordinator.py     Kdy co načíst, cache, backoff, hlášení problémů
├── entity.py          Základní entita (napojení na coordinator, zařízení)
├── sensor.py          Senzory (teploty, obsazenost, otevírací doba, stav dat)
├── binary_sensor.py   binary_sensor „otevřeno“
├── config_flow.py     Průvodce přidáním + nastavení intervalu
├── diagnostics.py     Výpis stavu pro hlášení chyb
├── manifest.json      Metadata integrace
├── strings.json       Texty UI a hlášek (čeština)
├── translations/      cs.json (kopie strings.json), en.json
└── brand/             Ikona a logo integrace (icon.png, logo.png, @2x)
```

`brand/` funguje od Home Assistantu 2026.3: obrázky odtud mají přednost před
centrálním repozitářem `home-assistant/brands`, takže ikona je součástí
integrace a není potřeba nikam posílat pull request. Rozměry musí odpovídat
specifikaci (ikona 256×256 a 512×512, u loga kratší strana 128–256 resp.
256–512) — hlídá to test `tests/test_brand.py`.

Vrstvy a jejich závislosti (šipka = „importuje“):

```
sensor.py ─┐
           ├─► entity.py ─► coordinator.py ─► scraper.py ─► const.py
binary_sensor.py ─┘                    │
                                       └─► (homeassistant.*)
```

**Pravidlo:** `scraper.py` nikdy neimportuje `homeassistant`. Díky tomu se dá
parsování testovat bez běžícího Home Assistantu a testy běží v desetinách
sekundy. Když tohle pravidlo porušíš, přijdeš o celou testovací sadu.

---

## 3. Datový tok

```
     ┌──────────────────────────────────────────────────────┐
     │ DataUpdateCoordinator (coordinator.py)               │
     │  každých N minut:                                    │
     │                                                      │
     │  1. potřebuje rozvrh?  ──► async_fetch(/oteviraci-)  │
     │     (starší než 6 h)        └─► parse_hours()        │
     │                             chyba = jen log,         │
     │                             stará kopie zůstává      │
     │                                                      │
     │  2. vždy:               ──► async_fetch(/)           │
     │                             └─► parse_home()         │
     │                             chyba = UpdateFailed     │
     │                                                      │
     │  3. úspěch → reset backoffu, smazat Repair issue     │
     │     selhání → backoff ×2, po 6 selháních Repair     │
     └───────────────────────┬──────────────────────────────┘
                             │ LhotkaData (dataclass)
                             ▼
              CoordinatorEntity (entity.py) → entity se překreslí
```

`LhotkaData` je jediná věc, kterou entity vidí. Nesahají na síť ani na
parsery — když chceš přidat entitu, potřebná data musí být v `LhotkaData`.

### Proč parsování v executoru

BeautifulSoup je synchronní. Kdyby běžel přímo v asyncio loopu, blokoval by
celý Home Assistant (u velkých stránek desítky ms, což HA loguje jako varování).
Proto `await hass.async_add_executor_job(parse_home, text)`.

### Proč podmíněné dotazy

Coordinator si pamatuje `ETag` a `Last-Modified`. Když se stránka nezměnila,
server odpoví `304 Not Modified` bez těla — ušetří se přenos i parsování.
Uložená naparsovaná data se v tom případě vrátí znovu.

---

## 4. Nedotknutelné kontrakty

Tyhle věci **nemazat a nepřejmenovávat**. Uživatelé je mají v dashboardech,
automatizacích a historii; jejich změna tiše rozbije cizí konfigurace.

### 4.1 `unique_id` entit

Definované v `const.py` jako `KEY_*`. Home Assistant si podle nich pamatuje
entity v registru. Změna `unique_id` = vznik nové entity s příponou `_2`,
ztráta historie a rozbité dashboardy.

| `unique_id` | `entity_id` u instalací z verze 1.x |
| --- | --- |
| `lhotka_water_temp` | `sensor.lhotka_teplota_vody` |
| `lhotka_air_temp` | `sensor.lhotka_teplota_vzduchu` |
| `lhotka_occupancy` | `sensor.lhotka_obsazenost` |
| `lhotka_occupancy_pct` | `sensor.lhotka_obsazenost_2` * |
| `lhotka_opening_hours` | `sensor.lhotka_oteviraci_doba` |
| `lhotka_is_open` | `binary_sensor.lhotka_otevreno` |
| `lhotka_data_status` | `sensor.lhotka_stav_dat` |

\* Ano, `_2` je historická nehoda: název „Lhotka – Obsazenost %“ se
slugifikuje na `lhotka_obsazenost`, což koliduje s počtem osob, takže HA
přidal příponu. Přejmenovat to nelze bez rozbití existujících instalací.

### 4.2 Názvy entit

`entity.py` má `_attr_has_entity_name = True` a entity mají krátké názvy
(„Teplota vody“). Home Assistant před ně sám doplní název zařízení.

Ve verzi 2.0.0 tu bylo `False` s prefixem „Lhotka – “, aby názvy zůstaly
identické s verzí 1.x. Nefunguje to: Home Assistant 2026 předsadí název
zařízení u každé entity, která k zařízení patří, nezávisle na tomto
přepínači — vznikaly proto zdvojené názvy „Koupaliště Lhotka Lhotka –
Teplota vody“. Kdo to chce vrátit, musí entitám odebrat `device_info`, ne
přepnout `has_entity_name`.

Na `entity_id` to nemá vliv: odvozuje se jen při prvním zaregistrování
entity a dál se drží podle `unique_id`. Starší instalace tedy mají
`sensor.lhotka_teplota_vody`, nové `sensor.koupaliste_lhotka_teplota_vody`.

### 4.3 Atributy senzoru otevírací doby

Atribut `rozvrh` má tvar seznamu slovníků s klíči `mesic`, `dny`, `hodiny`
(české názvy!). Existují dashboardy, které z něj kreslí podbarvení grafu podle
otevírací doby, tedy iterují přes tyhle konkrétní klíče.

Stejně tak `otevreno_ted`, `dnes_od`, `dnes_do`, `posledni_vstup`, `kapacita`.

### 4.4 Doména a platforma

`DOMAIN = "koupaliste_lhotka"`. Součást klíče v registru entit — změna
znamená ztrátu všech entit.

---

## 5. Klíčová rozhodnutí a jejich důvody

| Rozhodnutí | Důvod | Co by se stalo jinak |
| --- | --- | --- |
| Config flow místo YAML | HA od 2024 doporučuje UI konfiguraci; HACS ji čeká | YAML platformy HA postupně ruší |
| Jeden coordinator pro obě stránky | Jedno místo, které řídí frekvenci a cache | Každá entita by stahovala sama → 7× více requestů |
| Rozvrh cachovaný a jeho selhání nefatální | Mění se 1× za sezónu; stará kopie je plně použitelná | Krátký výpadek webu by zbytečně zneplatnil otevírací dobu |
| Živá data při selhání → `unavailable` | Stará teplota vydávaná za aktuální je horší než žádná | Uživatel by se rozhodoval podle týden starého čísla |
| `is_open` = rozvrh **a** odznak webu | Rozvrh zná plán, odznak zachytí zavření kvůli počasí; konjunkce chrání před zapomenutým odznakem | Buď by chybělo mimořádné zavření, nebo by hrozilo „otevřeno“ ve 3 ráno |
| URL jako konstanty bez UI políčka | Vylučuje SSRF | Uživatelem zadaná URL = skener interní sítě |
| Dvoustupňové parsování (DOM → regex) | Redesign webu často mění třídy, ale ne texty | Každá změna šablony by integraci vyřadila |
| Diagnostický senzor `stav_dat` | Uživatel nemá hlídat log | Tichá porucha by se objevila až po dnech |
| Repair issue až po 6 selháních | Jedno selhání je běžný šum | Hlášky při každém výpadku Wi-Fi |

---

## 6. Jak integraci rozšířit (recepty)

### Přidat číselný senzor z domovské stránky

1. `scraper.py`: přidej pole do `LiveData` a jeho čtení v `parse_home()`.
2. `tests/fixtures/home.html`: doplň odpovídající HTML.
3. `tests/test_scraper.py`: přidej assert do `test_parse_home_reads_all_values`.
4. `const.py`: nový `KEY_*` (nové, dosud nepoužité `unique_id`).
5. `sensor.py`: nová položka v `NUMERIC_SENSORS` s `value_fn`.
6. `README.md`: doplň do tabulky entit.

Nic víc není potřeba — coordinator ani platformy se nemění.

### Přidat entitu jiného typu (např. `number`, `switch`)

Integrace je *read-only*; ovládat na webu není co. Kdyby přece:
`__init__.py` → `PLATFORMS`, nový soubor platformy podle vzoru
`binary_sensor.py`, dědit z `LhotkaEntity`.

### Změnit parser po redesignu webu

1. Ulož nové HTML do `tests/fixtures/`.
2. Spusť `pytest` → testy ukážou, co přestalo fungovat.
3. Uprav **jen** `scraper.py`. Zachovej dvoustupňovou strategii: nejdřív
   struktura, pak textový fallback.
4. Zvyš verzi v `manifest.json` a doplň `CHANGELOG.md`.

### Přidat text z webu do atributu

Vždy protáhni `_clean_text()` (normalizace mezer + limit délky). Nikdy
nepublikuj surový řetězec z cizího serveru do stavu ani atributu entity.

---

## 7. Časté chyby

Chyby, kterých se v tomhle typu kódu snadno dopustit — včetně AI asistentů:

* **Blokující I/O v event loopu.** `requests.get()` nebo `BeautifulSoup()`
  přímo v `async` funkci. Používej `async_fetch()` a executor.
* **Vlastní `aiohttp.ClientSession`.** Home Assistant má společnou session:
  `async_get_clientsession(hass)`. Vlastní session je únik prostředků.
* **Změna `unique_id` „pro pořádek“.** Viz sekce 4.
* **Přejmenování atributů do angličtiny.** Klíče jsou české záměrně, jsou
  součástí kontraktu.
* **Zapnutí `has_entity_name = True`.** Změní `entity_id` všem uživatelům.
* **Tichý `except Exception: pass`.** Selhání musí být vidět — buď jako
  `UpdateFailed`, nebo v logu, nebo jako Repair issue.
* **Vracení staré hodnoty jako aktuální.** U živých dat je `unavailable`
  správná odpověď.
* **Neomezené regulární výrazy.** `\s*` na nedůvěryhodném vstupu umí
  degenerovat (ReDoS). Používej omezené kvantifikátory `{0,5}`.
* **Konfigurovatelná URL.** Ne. Viz SECURITY.md.
* **Zkracování intervalu pod 5 minut.** Data se tak často nemění a cizí web
  to zbytečně zatěžuje.

---

## 8. Testování

```bash
pytest            # testy parseru — nepotřebují Home Assistant
ruff check .      # lint
```

Testy jsou postavené na fixturách: zkrácených, ale strukturně věrných snímcích
skutečných stránek. Pokrývají mimo jiné:

* čtení všech hodnot z reálné struktury,
* fallback na textové parsování při zmizení CSS tříd,
* dědění měsíce z předchozího řádku tabulky,
* rozsahy dnů včetně přechodu přes konec týdne,
* hranice otevírací doby (přesně v čase otevření a zavření),
* mimo sezónu,
* nesmyslné vstupy (čas 25:00, obří řetězec, prázdná stránka),
* rychlost parseru na patologickém vstupu (ochrana proti ReDoS).

`tests/test_scraper.py` nahrává `scraper.py` přímo ze souboru, aby se
nespouštěl `__init__.py` (ten potřebuje Home Assistant). Když přidáváš testy
pro moduly závislé na HA, budeš potřebovat `pytest-homeassistant-custom-component`.

---

## 9. Prostředí a verze

* Home Assistant 2025.2 nebo novější. Rozhodující je
  `AddConfigEntryEntitiesCallback` v `homeassistant.helpers.entity_platform`
  (na starších verzích spadne import platformy) a `single_config_entry`
  v manifestu; `entry.runtime_data` a `OptionsFlow` bez ručního
  `config_entry` jsou k dispozici od 2024.11.
* Python podle Home Assistantu (3.13+ v HA 2026.x).
* Závislost: `beautifulsoup4>=4.12.0`. `aiohttp` dodává Home Assistant.
* Verze integrace je v `manifest.json` a musí odpovídat gitovému tagu
  (HACS podle tagu nabízí aktualizaci).

---

## 10. Slovníček pojmů Home Assistantu

| Pojem | Význam |
| --- | --- |
| **config entry** | Záznam o jedné nastavené instanci integrace. Vzniká config flow, žije v `.storage`. |
| **config flow** | Průvodce v UI, kterým uživatel integraci přidá. |
| **options flow** | Průvodce dodatečným nastavením už přidané integrace. |
| **coordinator** | `DataUpdateCoordinator` — sdílený stahovač dat pro všechny entity integrace. |
| **platform** | Typ entit v rámci integrace (`sensor`, `binary_sensor`, …). Jeden soubor = jedna platforma. |
| **entity registry** | Databáze entit. Klíč je `(domain, platform, unique_id)`. |
| **unique_id** | Trvalý identifikátor entity od integrace. Podle něj HA entitu poznává mezi restarty. |
| **entity_id** | Adresa entity pro uživatele (`sensor.neco`). Odvozená z názvu při prvním vzniku. |
| **state / attributes** | Hlavní hodnota entity a doplňkové údaje. Stav má limit 255 znaků. |
| **available** | Zda entita zná svou hodnotu. `False` → v UI `Nedostupné`. |
| **UpdateFailed** | Výjimka, kterou coordinator hlásí neúspěšné načtení. |
| **repair issue** | Hláška v *Nastavení → Systém → Opravy*, kterou integrace zakládá programově. |
| **diagnostics** | JSON výpis stavu integrace ke stažení pro hlášení chyb. |
| **HACS** | Neoficiální store pro doplňky. Vyžaduje `hacs.json` a gitové releasy. |
