# Bezpečnost

## Hlášení zranitelností

Nezakládej prosím veřejné issue. Napiš na adresu uvedenou v profilu správce
repozitáře nebo použij *Security → Report a vulnerability* na GitHubu.

## Model hrozeb

Integrace běží **uvnitř** Home Assistantu, tedy s jeho plnými právy. Nemá
žádné přihlašovací údaje ani osobní data, ale zpracovává **nedůvěryhodný
vstup z internetu** (HTML cizího serveru). Z toho vychází celý bezpečnostní
návrh.

Uvažovaní útočníci:

1. **Kompromitovaný nebo podvržený cílový web** — útočník ovládá HTML, které
   integrace parsuje.
2. **Aktivní útočník na síti** (MITM) — snaží se odpověď podvrhnout.
3. **Uživatel Home Assistantu se slabšími právy** — snaží se integraci zneužít
   k průzkumu sítě.

Mimo rozsah: kompromitovaný hostitel Home Assistantu (tam už je vše ztraceno),
dostupnost cizího webu (řeší se odolností, ne bezpečností).

## Opatření

| Hrozba | Opatření | Kde v kódu |
| --- | --- | --- |
| **SSRF** — integrace donucena volat interní adresy | URL jsou konstanty; config flow nemá políčko pro URL | `const.py`, `config_flow.py` |
| **SSRF přes přesměrování** — server pošle `Location: http://192.168.x.x` | Přesměrování se **nenásledují** (`allow_redirects=False`) a odpověď 3xx je chyba. Kontrola hostu *po* požadavku by nestačila — přesměrovaný požadavek by se už vykonal (blind SSRF) | `scraper.async_fetch` |
| **Downgrade na HTTP** — přesměrování na `http://` téhož hostu | Kontroluje se schéma i host výsledné adresy proti `ALLOWED_HOSTS` | `scraper.async_fetch` |
| **MITM / podvržená odpověď** | Výhradně HTTPS s ověřováním certifikátu; ověřování se nikde nevypíná (žádné `ssl=False`, `verify=False`) | `scraper.async_fetch` |
| **Vyčerpání paměti** — nesmyslně velká odpověď | Kontrola `Content-Length` předem + hard limit 3 MiB při čtení po blocích | `scraper.async_fetch`, `MAX_RESPONSE_BYTES` |
| **Nafouknutí atributu entity** — web pošle desetitisíce řádků rozvrhu | Strop 64 řádků; bez něj by se obsah dostal do state machine, WebSocket zpráv a databáze | `MAX_SCHEDULE_ROWS`, `scraper.parse_hours` |
| **Zablokování integrace** — server drží spojení otevřené | `ClientTimeout(total=20 s)` na každý požadavek | `REQUEST_TIMEOUT_SECONDS` |
| **ReDoS** — vstup navržený k zahlcení regulárního výrazu | Všechny kvantifikátory jsou omezené (`{0,5}`, `{1,6}`), žádné vnořené `*`; doba běhu na patologickém vstupu je pokrytá testem | `scraper.py`, `test_parser_handles_huge_input_quickly` |
| **Zaplavení databáze / UI dlouhým textem** | Každý text z webu (včetně textů výjimek) prochází `clean_text()` — limit 64 znaků a odstranění řídicích znaků | `MAX_TEXT_LENGTH`, `coordinator._register_failure` |
| **Nesmyslné hodnoty v dlouhodobých statistikách** | Teploty mimo −30…60 °C a obsazenost mimo 0…100 000 se zahodí, nulový blok v rozvrhu se odmítne a procenta jsou ohraničená na 0–100 % | `PLAUSIBLE_TEMP_RANGE`, `scraper.parse_home`, `LiveData.occupancy_pct` |
| **Neomezené hlavičky vracené serveru** | `ETag`/`Last-Modified` se před uložením zkrátí na 200 znaků a zbaví řídicích znaků | `MAX_CACHE_HEADER_LENGTH` |
| **Injektáž do logu** (ANSI sekvence, nové řádky) | `clean_text()` odstraňuje řídicí znaky včetně ESC a NUL i Unicode bidi/nulové šířky. Výjimka: `_LOGGER.exception()` vypisuje traceback tak, jak ho vydá Python | `scraper.clean_text` |
| **XSS / injekce do UI** | Do stavů a atributů jdou jen naparsovaná čísla a normalizované krátké texty; surové HTML se nikam nepředává ani neukládá | `scraper.py`, `diagnostics.py` |
| **XXE / entity expansion** | Používá se `html.parser` (čistý Python, bez externích entit), nikoli XML parser | `scraper.parse_home` |
| **Únik dat do logu** | Logují se jen normalizované chybové texty a počty; do diagnostiky se nedává surové HTML | `coordinator.py`, `diagnostics.py` |
| **Zneužití integrace k zátěži cizího webu** | Minimální interval 5 minut, podmíněné dotazy (304), exponenciální backoff při chybách, rozvrh nejvýš 4× denně i při selhání, identifikující User-Agent | `const.py`, `coordinator.py` |
| **Blokování event loopu** (dostupnost HA) | Veškeré parsování běží v executoru | `coordinator.py` |
| **Tichá porucha** — integrace nefunguje a nikdo to neví | Každá výjimka při čtení živých dat (i nečekaná) se zaznamená, `sensor.lhotka_stav_dat` ji vystaví a po 6 selháních vznikne hláška v Opravách. Chyby při čtení rozvrhu jsou nefatální a jdou do logu — mimo sezónu tabulka na webu být nemusí | `coordinator._register_failure`, `sensor.py` |

## Co integrace nedělá

* nespouští žádný kód z odpovědi (žádné `eval`, `exec`, `pickle`),
* nevykonává JavaScript ze stránky,
* nezapisuje na disk (kromě běžného stavu Home Assistantu),
* nepřijímá příchozí spojení a nevystavuje žádný endpoint,
* nekomunikuje s ničím jiným než s `koupaliste-lhotka.cz` (s `www` i bez)
  přes HTTPS — a to bez následování přesměrování, takže cílový server
  nemůže spojení přesměrovat jinam,
* nepracuje s hesly, tokeny ani osobními údaji.

## Závislosti

Jediná externí závislost je `beautifulsoup4` (parsování HTML, čistý Python,
široce používaná i v samotném Home Assistantu). `aiohttp` dodává Home
Assistant a integrace používá jeho společnou session.

Menší počet závislostí = menší plocha pro útok přes dodavatelský řetězec.
Nová závislost je vždy rozhodnutí, které je potřeba zdůvodnit v pull requestu.

## Poznámka k etice scrapingu

Integrace čte pouze veřejně dostupné stránky, neobchází žádné přihlášení,
CAPTCHA ani technická omezení a snaží se web zatěžovat co nejméně (podmíněné
dotazy, dlouhý interval, backoff). Identifikuje se vlastním User-Agentem
s odkazem na repozitář, aby provozovatel webu věděl, kdo ho navštěvuje.
