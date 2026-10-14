# Being-A-DIK-CZ
Czech Localization of DrPinkCake's AVN *Being a DIK* (unofficial fan project)

## Being a DIK – český překlad
Neoficiální fanouškovský překlad hry *Being a DIK* (DrPinkCake). Repozitář obsahuje
pouze web a (později) soubory překladu – žádné soubory hry.

## Struktura
- `web/` – statický web (bez buildu), CZ/EN přepínač; data ze `web/progress.json`
- `tools/gen_art.py` – generuje SVG grafiku (`web/assets/`, `web/favicon.svg`)
- (později) `game/tl/czech/` – soubory překladu

## Aktualizace statistik
`progress.py --publish` s `web.json` (`"path": "web/progress.json"`) commitne a pushne
`progress.json`. Token nikdy neukládej do repozitáře.

## Licence
Kód webu: MIT (`LICENSE`). Překlad: viz `TRANSLATION-LICENSE.md`.

## Nasazení
Cloudflare Workers (statické assety z `web/`, viz `wrangler.jsonc`), doména `badik.filiposakkq.dev`.
