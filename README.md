# Being-A-DIK-CZ
Czech Localization of DrPinkCake's AVN *Being a DIK* (unofficial fan project)

## Being a DIK – český překlad
Neoficiální fanouškovský překlad hry *Being a DIK* (DrPinkCake). Repozitář obsahuje
pouze web, nástroje a (později) soubory překladu – žádné soubory hry.

## Struktura
- `web/` – statický web (bez buildu), CZ/EN přepínač; data ze `web/progress.json`
  (`progress-model.js` data ověřuje a chybějící údaje nikdy nedomýšlí)
- `tools/translation-manager/` – **BaDIK Translation Manager**, aplikace pro správu překladu a generování `progress.json`
  (návod, sestavení `.exe`, testy: [tools/translation-manager/README.md](tools/translation-manager/README.md))
- `tools/gen_art.py` – generuje SVG grafiku (`web/assets/`, `web/favicon.svg`)
- `tests/web/` – testy webu (otevři `model.test.html` / `site.test.html` přes `py -m http.server`)
- (později) `game/tl/czech/` – soubory překladu

## Sezóny a epizody
| Sezóna | Epizody | Stav |
|---|---|---|
| 1 | 1–4 | aktivní |
| 2 | 5–8 | aktivní |
| 3 | – | plánováno do budoucna (bez čísel, nezapočítává se do žádných procent) |

Rozdělení je definované na jednom místě (`tools/translation-manager/prehled/seasons.py`) a web ho dostává
v `progress.json`.

## Aktualizace statistik
Web čte jediný soubor, `web/progress.json`, který vytváří aplikace BaDIK Translation Manager (schéma 2: celkový postup,
sezóny, epizody, odhad dokončení, historie; bez názvů souborů). Generování a publikování jsou oddělené:
aplikace data průběžně generuje lokálně a na GitHub je pošle **až po tvém potvrzení** v okně *Publikace*
(náhled → potvrzení → commit jen tohoto souboru → push). Nic se neposílá automaticky.
Samostatný `web.json` už není potřeba – nastavení webu je v aplikaci (*Nastavení → Web*).
Token nikdy neukládej do repozitáře; přihlášení řeší tvůj git.

## Licence
| Co | Licence |
|---|---|
| Přeložený text | **CC BY-NC 4.0** – `TRANSLATION-LICENSE.md` (nekomerčně, s uvedením autora) |
| Kód a grafika webu (`web/`, `tools/gen_art.py`, `tests/web/`) | **MIT** – `LICENSE` |
| BaDIK Translation Manager (`tools/translation-manager/`) | **vlastní licence** – `tools/translation-manager/LICENSE` (osobní nekomerční použití; šíření, úpravy a komerční použití jen s mým písemným souhlasem) |

Hra *Being a DIK* a její obsah patří DrPinkCake; repozitář žádné soubory hry neobsahuje.

## Podpora a kontakt
[Ko-fi](https://ko-fi.com/filiposakkq) · [GitHub @Filiposakkq](https://github.com/Filiposakkq) · Discord `@filiposakkq` · [web](https://badik.filiposakkq.dev)

## Nasazení
Cloudflare Workers (statické assety z `web/`, viz `wrangler.jsonc`), doména `badik.filiposakkq.dev`.
Změny na větvi `main` nasazují web; proto aplikace před publikováním varuje a vyžaduje potvrzení.
