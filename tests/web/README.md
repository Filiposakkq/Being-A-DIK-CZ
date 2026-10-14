# Testy webu (v prohlížeči)

Dvě stránky testují web ve skutečném prohlížeči; každá po doběhnutí vypíše `N passed, 0 failed`:

| Stránka | Co testuje |
|---|---|
| `model.test.html` | `web/progress-model.js`: zpracování dat o postupu (sezóny 1–4 / 5–8, sezóna 3 plánovaná, odhad jen s platným datem, starý formát, rozbitá data) |
| `site.test.html` | skutečné `web/index.html` v iframe na šířce 1100 / 768 / 360 px: sezóny a epizody se dvěma procenty, stavy, Ko-fi a odkaz na repozitář, licence, přepínač CZ/EN, žádné vodorovné posouvání |

## Spuštění
```
py -m http.server                 # v kořeni repozitáře
```
a otevři `http://localhost:8000/tests/web/model.test.html` a `…/site.test.html`.

Bez ručního otevírání je může spustit i `tools/translation-manager/tests/test_web.py` (v bezhlavém Edge/Chrome), ale jen s proměnnou
`PREHLED_BROWSER_TESTS=1`; jinak se tyto dva testy přeskočí. Ostatní kontroly obsahu webu (odkazy, licence, obrázky, logo) jsou
běžné Python testy a běží vždy.

## Testovací data (`fixtures/`)
| Soubor | Obsah |
|---|---|
| `v2-real-copy.json` | `progress.json` schématu 2 z kopie skutečných dat (jen souhrnná čísla, žádné názvy souborů) |
| `v2-synthetic-estimate.json` | **vymyšlená** čísla jen pro kontrolu vzhledu (odhad dokončení, epizoda „v korekci“) |
| `v1-legacy.json` | starý formát (schéma 1) |
| `broken.json`, `empty.json` | rozbitá / prázdná data – stránka nesmí spadnout |
