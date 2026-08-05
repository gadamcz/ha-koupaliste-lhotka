# Jak přispět

Díky za zájem. Tenhle projekt je malý, takže i pravidla jsou krátká.

## Než začneš

Přečti si [ARCHITECTURE.md](ARCHITECTURE.md), hlavně sekce **Nedotknutelné
kontrakty** a **Časté chyby**. Ušetří ti to kolo revize.

## Vývojové prostředí

```bash
git clone https://github.com/gadamcz/ha-koupaliste-lhotka
cd ha-koupaliste-lhotka
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

Kontroly, které musí projít (stejné běží i v CI):

```bash
ruff check .        # lint
ruff format --check .
pytest              # testy parseru
```

## Zkoušení v běžícím Home Assistantu

Nejjednodušší je symlink do konfigurační složky:

```bash
ln -s "$PWD/custom_components/koupaliste_lhotka" /cesta/ke/config/custom_components/
```

Po každé změně kódu restartuj Home Assistant. Užitečné je zapnout podrobné
logování:

```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.koupaliste_lhotka: debug
```

## Když se změní web

To je nejčastější důvod k opravě. Postup:

1. Ulož nové HTML do `tests/fixtures/` (zkrácené, ale se zachovanou strukturou).
2. Spusť `pytest` — testy ukážou, co konkrétně přestalo fungovat.
3. Uprav `scraper.py`, ostatní soubory se obvykle měnit nemusí.
4. Zachovej dvoustupňovou strategii parsování (struktura → textový fallback).

## Pravidla pro pull requesty

* **Jedna změna = jeden PR.** Snazší revize i případný revert.
* **Testy k novému chování.** Když opravuješ parser, přilož fixture.
* **Nemění se `unique_id` ani názvy atributů** — rozbilo by to existující
  instalace. Když to je nevyhnutelné, popiš v PR migrační cestu.
* **Komentáře vysvětlují proč, ne co.** Kód říká, co se děje; komentář má
  říct, proč to tak je. Projekt slouží i jako učební materiál, takže
  vysvětlující komentáře jsou vítané.
* **Nové závislosti zdůvodni.** Viz [SECURITY.md](SECURITY.md).
* **Bezpečnostní opatření neodstraňuj** (timeouty, limity velikosti, kontrola
  hostu, omezené regulární výrazy). Když opravdu překáží, otevři nejdřív issue.

## Jazyk

* Kód, názvy proměnných, commit messages: **anglicky** nebo **česky**,
  hlavně konzistentně v rámci souboru.
* Uživatelské texty (`strings.json`, README): **česky**, s anglickým překladem
  v `translations/en.json`.
* Klíče atributů entit jsou **české** — je to součást kontraktu, neměnit.

## Verze a vydání

Používá se [semver](https://semver.org/lang/cs/):

* **patch** — oprava parseru, oprava chyby,
* **minor** — nová entita, nové nastavení,
* **major** — změna, která rozbije existující instalace.

Vydání: zvyš `version` v `manifest.json`, doplň `CHANGELOG.md`, vytvoř gitový
tag `vX.Y.Z` a GitHub release. HACS aktualizace nabízí podle tagu, takže tag
a verze v manifestu si musí odpovídat.

## Hlášení chyb

Použij šablonu issue a přilož **diagnostiku**: *Nastavení → Zařízení a služby
→ Koupaliště Lhotka → ⋮ → Stáhnout diagnostiku*. Je v ní stav integrace,
poslední chyba i naparsovaný rozvrh — obvykle to stačí k určení příčiny.
