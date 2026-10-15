# Being-A-DIK-CZ

Neoficiální fanouškovský **český překlad** hry *Being a DIK* od DrPinkCake – web s postupem prací, nástroj na správu překladu a (později) soubory překladu.
*Czech localization of DrPinkCake's AVN* Being a DIK *(unofficial fan project).*

🌐 **Web:** https://badik.filiposakkq.dev · ☕ [Ko-fi](https://ko-fi.com/filiposakkq) · 💬 Discord `@filiposakkq` · [GitHub @Filiposakkq](https://github.com/Filiposakkq)

## Obsah
[O projektu](#o-projektu) · [Překladatelský nástroj](#překladatelský-nástroj) · [Struktura repozitáře](#struktura-repozitáře) ·
[Sezóny a epizody](#sezóny-a-epizody) · [Jak se aktualizují statistiky](#jak-se-aktualizují-statistiky) · [Vývoj a testy](#vývoj-a-testy) ·
[Licence](#licence) · [Podpora a kontakt](#podpora-a-kontakt) · [English summary](#english-summary)

## O projektu
Repozitář obsahuje **web**, **nástroje** a (později) **soubory překladu**. Neobsahuje žádné soubory hry. Hra *Being a DIK* a její obsah patří
DrPinkCake; k použití překladu potřebuješ vlastní legální kopii hry. Projekt není schválený autorem hry.

## Překladatelský nástroj
**BaDIK Translation Manager** (`tools/translation-manager/`) je aplikace, ve které překlad spravuju: počítá postup po souborech, epizodách a
sezónách, hlídá chyby (značky, proměnné), pomáhá s korekturou, má slovník jmen postav a generuje data pro web.

> ⚠️ **Nástroj vzniká hlavně pro mě.** Funguje **jen pro *Being a DIK* – 1. a 2. sezónu**, má **pouze české rozhraní** a není to hotový produkt
> pro všechny. **V plánu:** nejdřív podpora **3. sezóny**, **možná později** přepracování pro **víc Ren'Py her** a **anglické rozhraní** (bez slibů
> a termínů). Kód je veřejný ke čtení, ale [licence](tools/translation-manager/LICENSE) nedovoluje další šíření ani upravené verze bez mého
> písemného souhlasu. Návod a podrobnosti: [tools/translation-manager/README.md](tools/translation-manager/README.md).

## Struktura repozitáře
```
web/                          statický web (bez buildu), CZ/EN; data ze web/progress.json
  progress-model.js           ověření a zpracování dat o postupu (nikdy nedomýšlí čísla)
  assets/                     znak (crest.svg)
  assets/game/                oficiální tiskové obrázky hry (© DrPinkCake) + README s uvedením zdroje
tools/
  translation-manager/        BaDIK Translation Manager (kód, testy, sestavení .exe)
  gen_art.py                  generuje vektorovou grafiku (znak, favicon) do web/
tests/web/                    prohlížečové testy webu a testovací data (viz tests/web/README.md)
.github/workflows/            testy a sestavení .exe při značce manager-v* (nic nepublikuje)
LICENSE · TRANSLATION-LICENSE.md · tools/translation-manager/LICENSE
```
*(Později)* `game/tl/czech/` – soubory překladu.

## Sezóny a epizody
| Sezóna | Epizody | Stav |
|---|---|---|
| 1 | 1–4 | aktivní |
| 2 | 5–8 | aktivní |
| 3 | – | plánováno do budoucna (bez čísel, nezapočítává se do žádných procent) |

Rozdělení je definované na jednom místě (`tools/translation-manager/prehled/seasons.py`) a web ho dostává v `progress.json`.

## Jak se aktualizují statistiky
Web čte jediný soubor, `web/progress.json`, který vytváří BaDIK Translation Manager (schéma 2: celkový postup, sezóny, epizody, odhad dokončení,
historie; bez názvů souborů). **Generování a publikování jsou oddělené:** aplikace data průběžně generuje lokálně a na GitHub je pošle **až po
mém potvrzení** v okně *Publikace* (náhled → potvrzení → commit jen tohoto souboru → push). Nic se neposílá automaticky.
Procenta jsou **orientační** (počítají se z počtu řádků ve skriptu; některé řádky nejdou přeložit, korektury a stavy epizod občas upravuju ručně).
Samostatný `web.json` už není potřeba. Token se nikdy neukládá do repozitáře; přihlášení řeší git.

## Vývoj a testy
```
py -m unittest discover -s tools/translation-manager/tests     # testy nástroje i obsahu webu (jen standardní knihovna)
py tools/gen_art.py                                            # znovu vygeneruje znak a favicon
tools/translation-manager/build_exe.bat                        # sestaví BaDIKTranslationManager.exe
py -m http.server                                              # v kořeni repozitáře: web na /web/, testy webu na /tests/web/model.test.html a site.test.html
```
Web se nasazuje přes Cloudflare Workers (statické soubory z `web/`, viz `web/wrangler.jsonc`) z větve `main`, doména `badik.filiposakkq.dev`.
Změny se dělají na samostatných větvích přes pull request; sloučení do `main` nasadí web.

## Licence
| Co | Licence |
|---|---|
| Přeložený text | **CC BY-NC 4.0** – [`TRANSLATION-LICENSE.md`](TRANSLATION-LICENSE.md) (nekomerčně, s uvedením autora) |
| Kód a grafika webu (`web/`, `tools/gen_art.py`, `tests/web/`) | **MIT** – [`LICENSE`](LICENSE) |
| BaDIK Translation Manager (`tools/translation-manager/`) | **vlastní licence** – [`tools/translation-manager/LICENSE`](tools/translation-manager/LICENSE) (osobní nekomerční použití; šíření, úpravy a komerční použití jen s mým písemným souhlasem) |
| Obrázky ze hry (`web/assets/game/`) | **© DrPinkCake** – oficiální tiskové (press kit) obrázky, použité jen jako ilustrace; **nespadají** pod žádnou z licencí výše, na žádost držitele práv budou odstraněny |

Hra *Being a DIK* a její obsah patří DrPinkCake; repozitář neobsahuje žádné soubory hry, jen těchto několik tiskových obrázků na webu.

## Podpora a kontakt
[Ko-fi](https://ko-fi.com/filiposakkq) · [GitHub @Filiposakkq](https://github.com/Filiposakkq) · Discord `@filiposakkq` · [web](https://badik.filiposakkq.dev) ·
chyby a nápady: [Issues](https://github.com/Filiposakkq/Being-A-DIK-CZ/issues). Jsi držitel práv a chceš něco změnit nebo odstranit? Napiš mi, vyhovím.

## English summary
Unofficial Czech fan translation of *Being a DIK* (DrPinkCake): a website with progress statistics, a translation-management tool and (later) the
translation files. No game files are included. The website shows a few official press-kit images (© DrPinkCake) as illustration.
**The tool (BaDIK Translation Manager) is built mainly for my own use:** it works only for *Being a DIK* seasons 1–2 and has a Czech-only
interface; season 3 support is planned first, and a rework for other Ren'Py games with an English UI may follow later. See
[tools/translation-manager/README.md](tools/translation-manager/README.md). Licenses: translation text CC BY-NC 4.0, website code MIT, the tool
under a custom restrictive license (no redistribution without permission).
