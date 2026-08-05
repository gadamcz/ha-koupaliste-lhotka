<img src="docs/logo.png" alt="Koupaliště Lhotka" width="360">

# Koupaliště Lhotka pro Home Assistant

[![hacs][hacs-badge]][hacs] [![release][release-badge]][releases] [![license][license-badge]](LICENSE)
[![validate][validate-badge]][validate] [![tests][tests-badge]][tests]

Integrace čte veřejně dostupná data z webu [koupaliste-lhotka.cz][web] — teplotu
vody a vzduchu, aktuální obsazenost a otevírací dobu — a vytvoří z nich entity
v Home Assistantu.

Žádné přihlášení, žádný API klíč. Integrace se jen chová jako slušný návštěvník
webu: čte ho v rozumném intervalu, používá podmíněné dotazy a při nedostupnosti
sama zpomalí.

## Entity

| Entita | Typ | Popis |
| --- | --- | --- |
| Teplota vody | °C | Teplota vody v jezeře |
| Teplota vzduchu | °C | Teplota vzduchu |
| Obsazenost | osob | Počet osob v areálu |
| Obsazenost % | % | Obsazenost v procentech kapacity |
| Otevírací doba | text | Dnešní otevírací doba, např. `9:00 – 20:00` |
| Otevřeno | on/off | Je právě otevřeno (`binary_sensor`) |
| Stav dat | enum | Diagnostika čtení (`ok` / `potize` / `nedostupne`) |

`entity_id` skládá Home Assistant z názvu zařízení a entity, takže u nové
instalace vznikne `sensor.koupaliste_lhotka_teplota_vody`. Instalace, které
začínaly na verzi 1.x, si drží původní `sensor.lhotka_teplota_vody` —
`entity_id` se odvozuje jen při prvním zaregistrování entity. Skutečné
hodnoty si vždy zkopíruj z *Nastavení → Zařízení a služby*, nepiš je z příkladů.

### Atributy

**Obsazenost**

| Atribut | Popis |
| --- | --- |
| `kapacita` | Maximální kapacita areálu (osob) |

**Otevírací doba**

| Atribut | Popis |
| --- | --- |
| `rozvrh` | Celý rozvrh — seznam `{mesic, dny, hodiny}` |
| `dnes_od`, `dnes_do` | Dnešní hodiny odděleně |
| `otevreno_ted` | `true`/`false` — otevřeno v tuto chvíli |
| `posledni_vstup` | Čas posledního vstupu (45 min před zavírací dobou) |
| `stav_dle_webu` | Stavový odznak z webu (`otevřeno` / `zavřeno`) |
| `aktualizovano` | Kdy se naposledy načetl rozvrh |

**Stav dat**

| Atribut | Popis |
| --- | --- |
| `posledni_cteni_uspesne` | `true`/`false` — vyšel poslední pokus |
| `neuspesnych_pokusu_v_rade` | Kolik pokusů za sebou selhalo |
| `neuspesnych_pokusu_celkem` | Součet od startu Home Assistantu |
| `posledni_chyba` | Text poslední chyby (jen při potížích) |
| `interval_minut` | Aktuální interval čtení (roste při potížích) |

Časové značky tu záměrně nejsou — měnily by se při každém čtení a databáze
by kvůli nim rostla bez užitku. Kdy data dorazila, je vidět na samotných
senzorech a ve stahovatelné diagnostice.

## Instalace

### HACS (doporučeno)

[![Přidat repozitář do HACS][hacs-repo-badge]][hacs-repo]

Nebo ručně:

1. HACS → ⋮ → **Custom repositories**
2. Repozitář `https://github.com/gadamcz/ha-koupaliste-lhotka`, kategorie **Integration**
3. Najdi *Koupaliště Lhotka*, klikni **Download**
4. Restartuj Home Assistant
5. **Nastavení → Zařízení a služby → Přidat integraci → Koupaliště Lhotka**

[![Přidat integraci][config-flow-badge]][config-flow]

### Ručně

Zkopíruj `custom_components/koupaliste_lhotka/` do své konfigurační složky
(`/config/custom_components/koupaliste_lhotka/`), restartuj Home Assistant
a přidej integraci v UI.

## Nastavení

Jediná volba je **interval čtení** (výchozí 10 minut, minimum 5).
Změníš ji v *Nastavení → Zařízení a služby → Koupaliště Lhotka → Konfigurovat*.

Otevírací doba se načítá jednou za 6 hodin nezávisle na tomto intervalu —
mění se řádově jednou za sezónu, takže častější čtení by bylo plýtvání.

## Jak se integrace chová při problémech

Web třetí strany občas nefunguje. Integrace na to reaguje takto:

| Situace | Chování |
| --- | --- |
| Web neodpovídá | Entity živých hodnot zešednou (`unavailable`) — radši žádná hodnota než tichá lež o staré teplotě |
| Web neodpovídá opakovaně | Interval čtení se zdvojnásobuje až na 60 minut, aby se web nebombardoval |
| Selhalo 6 pokusů v řadě | V *Nastavení → Systém → Opravy* se objeví hláška s vysvětlením |
| Web se přestavěl | Jiná hláška v Opravách — tohle znamená, že integrace potřebuje aktualizaci; nahlas prosím issue |
| Web funguje, ale mimo sezónu | `sensor.lhotka_oteviraci_doba` je `Zavřeno`, `binary_sensor.lhotka_otevreno` je `off` |
| Krátký výpadek | Otevírací doba i „otevřeno“ zůstávají dostupné z uložené kopie rozvrhu (pokud se rozvrh už aspoň jednou načetl) |
| Restart HA během výpadku webu | Rozvrh se ještě nestihl načíst, proto se zkouší každých 15 minut, dokud ho integrace nemá |

Zdraví integrace vidíš kdykoli na `sensor.lhotka_stav_dat` — ten je dostupný
i ve chvíli, kdy všechno ostatní zešedne.

## Příklady použití

Notifikace, když se voda ohřeje a není plno:

```yaml
automation:
  - alias: "Koupaliště — dobré podmínky"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.lhotka_teplota_vody
        above: 24
    conditions:
      - condition: state
        entity_id: binary_sensor.lhotka_otevreno
        state: "on"
      - condition: numeric_state
        entity_id: sensor.lhotka_obsazenost_2
        below: 60
    actions:
      - action: notify.persistent_notification
        data:
          message: >
            Voda má {{ states('sensor.lhotka_teplota_vody') }} °C
            a je obsazeno {{ states('sensor.lhotka_obsazenost_2') }} %.
```

Upozornění, že se data přestala načítat:

```yaml
automation:
  - alias: "Koupaliště — problém s daty"
    triggers:
      - trigger: state
        entity_id: sensor.lhotka_stav_dat
        to: "nedostupne"
        for: "01:00:00"
    actions:
      - action: notify.persistent_notification
        data:
          message: >
            Data z koupaliště se nedaří číst:
            {{ state_attr('sensor.lhotka_stav_dat', 'posledni_chyba') }}
```

Volná místa jako šablonový senzor:

```yaml
template:
  - sensor:
      - name: "Lhotka – volná místa"
        unit_of_measurement: "osob"
        state: >
          {{ (state_attr('sensor.lhotka_obsazenost', 'kapacita') | int(0))
             - (states('sensor.lhotka_obsazenost') | int(0)) }}
        availability: "{{ has_value('sensor.lhotka_obsazenost') }}"
```

## Přechod z verze 1.x (YAML)

Verze 1.x se nastavovala v `configuration.yaml` jako platforma senzoru.
Verze 2.0 používá UI.

1. Smaž z `configuration.yaml` blok `sensor: - platform: koupaliste_lhotka`
2. Aktualizuj integraci a restartuj Home Assistant
3. Přidej integraci v UI

**Entity zůstanou stejné.** Integrace používá identická `unique_id`, takže
Home Assistant existující entity převezme — `entity_id`, historie, dashboardy
i automatizace fungují dál. Stejně tak zůstávají zachované všechny atributy
včetně `rozvrh` a `otevreno_ted`.

Nově vzniká entita **Otevřeno** (`binary_sensor`) a **Stav dat**. Pokud sis
dříve vytvořil vlastní šablonový helper se stejným názvem, smaž ho — jinak
dostane nová entita příponu `_2`.

Zobrazované názvy se změní: Home Assistant je skládá jako „Koupaliště Lhotka
Teplota vody“ místo dřívějšího „Lhotka – Teplota vody“. `entity_id` ani
historie se tím nemění; pokud ti starý název chybí, přepiš ho v nastavení
entity.

## Vývoj

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest            # testy parseru, bez potřeby Home Assistantu
ruff check .      # lint
```

Architektura, datový tok a kontrakt entit jsou popsané v
[ARCHITECTURE.md](ARCHITECTURE.md) — ten dokument je zároveň napsaný tak, aby
posloužil jako vstupní kontext pro AI asistenta, který bude integraci rozvíjet
(zkrácené pokyny jsou v [AGENTS.md](AGENTS.md)).

Bezpečnostní opatření a hranice hrozeb popisuje [SECURITY.md](SECURITY.md),
postup vydání nové verze [PUBLISHING.md](PUBLISHING.md).

Ikona je součástí integrace ve složce
[`custom_components/koupaliste_lhotka/brand/`](custom_components/koupaliste_lhotka/brand/)
— od Home Assistantu 2026.3 mají lokální obrázky přednost před centrálním
repozitářem brands. Zdrojová SVG jsou v `docs/`.

## Poděkování a právní poznámka

Data poskytuje [koupaliste-lhotka.cz][web]; integrace je neoficiální a s
provozovatelem areálu nemá žádný vztah. Čte pouze veřejně dostupné stránky,
nijak neobchází přístupová omezení a snaží se web zatěžovat minimálně.
Pokud si provozovatel nepřeje, aby integrace existovala, otevřete prosím issue —
repozitář bude stažen.

[web]: https://www.koupaliste-lhotka.cz
[hacs]: https://github.com/hacs/integration
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[validate-badge]: https://github.com/gadamcz/ha-koupaliste-lhotka/actions/workflows/validate.yml/badge.svg
[validate]: https://github.com/gadamcz/ha-koupaliste-lhotka/actions/workflows/validate.yml
[tests-badge]: https://github.com/gadamcz/ha-koupaliste-lhotka/actions/workflows/tests.yml/badge.svg
[tests]: https://github.com/gadamcz/ha-koupaliste-lhotka/actions/workflows/tests.yml
[hacs-repo-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-repo]: https://my.home-assistant.io/redirect/hacs_repository/?owner=gadamcz&repository=ha-koupaliste-lhotka&category=integration
[config-flow-badge]: https://my.home-assistant.io/badges/config_flow_start.svg
[config-flow]: https://my.home-assistant.io/redirect/config_flow_start/?domain=koupaliste_lhotka
[release-badge]: https://img.shields.io/github/v/release/gadamcz/ha-koupaliste-lhotka
[releases]: https://github.com/gadamcz/ha-koupaliste-lhotka/releases
[license-badge]: https://img.shields.io/github/license/gadamcz/ha-koupaliste-lhotka
