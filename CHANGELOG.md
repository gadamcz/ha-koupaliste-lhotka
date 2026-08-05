# Changelog

Formát vychází z [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/),
verzování dodržuje [semver](https://semver.org/lang/cs/).

## [2.0.1] – 2026-08-05

### Přidáno

- Ikona a logo integrace přímo v `brand/` — od Home Assistantu 2026.3 se
  zobrazí bez pull requestu do repozitáře `home-assistant/brands`

### Opraveno

- Zdvojené názvy entit („Koupaliště Lhotka Lhotka – Teplota vody“). Home
  Assistant 2026 předsazuje název zařízení u každé entity, která k zařízení
  patří, nezávisle na `has_entity_name`. Entity proto mají krátké názvy
  („Teplota vody“) a výsledek je „Koupaliště Lhotka Teplota vody“.
- Z téhož důvodu vznikala entita „Otevřeno“ s nešikovným
  `entity_id` `binary_sensor.koupaliste_lhotka_lhotka_otevreno`.

`entity_id` ani historie se touto změnou nemění — odvozuje se jen při prvním
zaregistrování entity a dál se drží podle `unique_id`.

## [2.0.0] – 2026-08-04

Kompletní přepis. **Entity a jejich atributy zůstávají stejné**, takže
existující dashboardy a automatizace fungují dál.

### Přidáno

- Nastavení přes UI (config flow) — YAML konfigurace už není potřeba
- `binary_sensor.lhotka_otevreno` — je právě otevřeno
- `sensor.lhotka_stav_dat` — diagnostika čtení dat s podrobnostmi v atributech
- Atribut `stav_dle_webu` u otevírací doby (odznak OTEVŘENO/ZAVŘENO z webu)
- Hlášení do *Nastavení → Systém → Opravy* při opakovaném selhání
- Volitelný interval čtení (5–120 minut) v nastavení integrace
- Stahovatelná diagnostika pro hlášení chyb
- Zařízení „Koupaliště Lhotka“, pod které se entity řadí
- Anglický překlad UI
- Testy parseru (50 testů) a CI: ruff, pytest, hassfest, HACS validace

### Změněno

- Asynchronní stahování přes společnou session Home Assistantu místo
  blokujícího `requests` — integrace už nezdržuje start ani chod HA
- Jeden `DataUpdateCoordinator` místo čtení v každé entitě zvlášť
- Otevírací doba se načítá jednou za 6 hodin, živá data podle nastavení
- Podmíněné HTTP dotazy (`ETag` / `Last-Modified`) — při nezměněné stránce
  se nepřenáší nic
- Parsování běží v samostatném vlákně, aby neblokovalo event loop
- Dvoustupňové parsování: nejdřív podle struktury HTML, pak textový fallback
- `otevreno_ted` bere v potaz i stavový odznak webu, takže zachytí
  mimořádné zavření kvůli počasí

### Odolnost a bezpečnost

- Exponenciální backoff při nedostupnosti webu (až 60 minut)
- Živá data při selhání hlásí `unavailable` místo staré hodnoty
- Otevírací doba a „otevřeno“ zůstávají funkční z uložené kopie rozvrhu
- Timeout 20 s na požadavek, limit velikosti odpovědi 3 MiB
- Přesměrování se nenásledují a kontroluje se schéma i host odpovědi
  (obrana proti SSRF a proti tichému přechodu na nešifrované HTTP)
- Strop na počet řádků rozvrhu (obrana proti nafouknutí atributu entity)
- Omezené kvantifikátory v regulárních výrazech (obrana proti ReDoS)
- Limit délky a odstranění řídicích znaků u všech textů z webu
- Zahození nevěrohodných hodnot, aby se nedostaly do dlouhodobých statistik
- Každá chyba při čtení živých dat se zaznamená, i ta nečekaná
- Entity se přepínají v okamžik otevření a zavření, ne až s dalším čtením

## [1.0.0] – 2026

- První verze: teplota vody a vzduchu, obsazenost, obsazenost v procentech
- Senzor otevírací doby s celým rozvrhem v atributech
- Konfigurace pomocí YAML platformy
