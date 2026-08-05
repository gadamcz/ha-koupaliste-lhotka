# Publikování na GitHub a do HACS

Krok za krokem, včetně věcí, na kterých HACS validace obvykle spadne.

## 1. Vytvoření repozitáře

Na GitHubu vytvoř **veřejný** repozitář `ha-koupaliste-lhotka` pod účtem
[`gadamcz`](https://github.com/gadamcz/) — bez README, .gitignore a licence
(máme je tady).

```bash
cd ha-koupaliste-lhotka
git init -b main
git add .
git commit -m "Koupaliště Lhotka 2.0.0 — config flow, coordinator, dokumentace"
git remote add origin git@github.com:gadamcz/ha-koupaliste-lhotka.git
git push -u origin main
```

## 2. Popis a témata repozitáře (HACS to vyžaduje)

HACS odmítne repozitář bez popisu a bez témat. Obojí se nastavuje na hlavní
stránce repozitáře v panelu **About** (ikona ⚙ vpravo).

### Description

Doporučený text (149 znaků, limit GitHubu je 350):

```
Home Assistant integrace pro koupaliště Lhotka v Praze — teplota vody a vzduchu, obsazenost a otevírací doba jako entity. Instalace přes HACS.
```

Anglická varianta, pokud chceš lepší dohledatelnost mimo ČR:

```
Home Assistant integration for Koupaliště Lhotka (Prague public swimming lake) — water and air temperature, occupancy and opening hours. HACS compatible.
```

Do políčka **Website** dej `https://www.koupaliste-lhotka.cz`.

### Topics

Dvanáct témat, vlož je jedno po druhém (GitHub povoluje max. 20; jen malá
písmena, číslice a spojovníky):

```
home-assistant
homeassistant
hacs
hacs-integration
custom-component
custom-integration
home-assistant-integration
python
web-scraping
swimming-pool
prague
czech
```

První čtyři jsou ta podstatná — podle nich repozitář najdou lidé, kteří
hledají doplňky pro Home Assistant, a používá je i HACS.

### Issues

V *Settings → General → Features* zkontroluj zaškrtávátko **Issues**
(u nového repozitáře je zapnuté). `manifest.json` na ně odkazuje, HACS
existenci issue trackeru kontroluje a jsou na ně navázané šablony hlášení
v `.github/ISSUE_TEMPLATE/`.

## 3. První vydání (release)

HACS nabízí uživatelům verze podle gitových tagů. Verze v tagu musí
odpovídat `version` v `manifest.json`.

```bash
git tag v2.0.0
git push origin v2.0.0
```

Pak na GitHubu *Releases → Draft a new release*, vyber tag `v2.0.0`, jako
popis použij sekci z `CHANGELOG.md` a publikuj.

> Bez releasu HACS instaluje z hlavní větve, ale neumí nabídnout aktualizaci.

## 4. Kontrola, že vše projde

Po pushnutí se v *Actions* spustí dva workflow:

| Workflow | Co kontroluje |
| --- | --- |
| **Validate** | `hassfest` (manifest podle pravidel Home Assistantu) a `HACS action` (struktura repozitáře) |
| **Tests** | ruff (lint i formát), pytest, platnost JSON a shodu klíčů v překladech |

Oba musí být zelené. Nejčastější příčiny červené HACS validace: chybí popis
repozitáře, chybí témata, verze v tagu ≠ verze v manifestu.

## 5. Instalace do svého Home Assistantu

HACS → ⋮ → *Custom repositories* → `https://github.com/gadamcz/ha-koupaliste-lhotka`,
kategorie **Integration**. Pak *Download*, restart a přidání integrace v UI.

## 6. Ikona

Nic dělat nemusíš — ikona je součástí integrace ve složce
`custom_components/koupaliste_lhotka/brand/`. Od Home Assistantu 2026.3 se
obrázky odtud použijí přednostně před centrálním repozitářem brands.

Volitelně jde ikonu poslat i do [home-assistant/brands](https://github.com/home-assistant/brands)
— má to smysl pro uživatele na starší verzi HA a je to podmínka zařazení do
veřejného seznamu HACS. Připravené soubory a postup jsou v
[`brands/README.md`](brands/README.md).

Zdrojová SVG jsou v `docs/icon.svg` a `docs/logo.svg`.

## 7. Zařazení do veřejného seznamu HACS (volitelné)

Aby integraci našel každý bez přidávání custom repository, jde požádat
o zařazení do [hacs/default](https://github.com/hacs/default). Podmínky jsou
tvrdší (mimo jiné popis, témata, release, brands ikona, aktivní údržba) a
schvalování trvá týdny. Pro osobní projekt to není potřeba — custom
repository funguje stejně dobře.

## Běžná práce s gitem

### Stáhnout repozitář k sobě (jednou)

```bash
git clone https://github.com/gadamcz/ha-koupaliste-lhotka.git
cd ha-koupaliste-lhotka
```

### Sladit se s tím, co je na GitHubu

```bash
git pull
```

Přesnější varianta, která nevytváří zbytečné „merge“ commity, když jsi mezitím
pracoval i lokálně:

```bash
git pull --rebase
```

### Nahrát změny

```bash
git status                    # co se změnilo
git diff                      # jak konkrétně (q pro ukončení)
git add -A                    # připravit všechny změny
git commit -m "Oprava parseru po redesignu webu"
git push
```

### Nahrát novou verzi (release pro HACS)

Až po zvýšení `version` v `manifest.json` a doplnění `CHANGELOG.md`:

```bash
git add -A
git commit -m "Verze 2.0.1"
git push
git tag v2.0.1
git push origin v2.0.1
```

Pak na GitHubu *Releases → Draft a new release* → vyber tag → publikuj.
Teprve tím HACS nabídne uživatelům aktualizaci.

### Když se něco pokazí

```bash
git restore <soubor>          # zahodit neuložené změny v souboru
git restore .                 # zahodit všechny neuložené změny
git reset --soft HEAD~1       # vrátit poslední commit, změny nechat
git log --oneline -10         # posledních 10 commitů
git push --force-with-lease   # přepsat historii na GitHubu (jen když víš proč)
```

### Konflikt při pull

Git označí sporná místa v souborech značkami `<<<<<<<`, `=======`, `>>>>>>>`.
Uprav soubor tak, jak má vypadat, značky smaž a pak:

```bash
git add <soubor>
git rebase --continue         # při pull --rebase
```

Nebo `git rebase --abort` a zkus to znovu.

## Údržba

Web se může kdykoli přestavět. Když se to stane:

1. Integrace to sama pozná a založí hlášku v *Nastavení → Systém → Opravy*
2. Postup opravy je v [CONTRIBUTING.md](CONTRIBUTING.md), sekce „Když se změní web“
3. Po opravě zvyš `version` v `manifest.json`, doplň `CHANGELOG.md`,
   vytvoř nový tag a release
