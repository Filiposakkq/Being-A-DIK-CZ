"""Optional machine translation: a SUGGESTION for one line, never written anywhere by itself.

Off by default. It sends the English text of the line you ask about to the service you chose, so it needs your explicit
consent in the settings (`mt.consent`) and your own API key, which is stored in plain text in the app's config file.
Nothing is sent until you click the button for a line.

Tags `{i}`, variables `[name]` and escapes (`\\n`) never go to the service as text: they are replaced by `<x id="N"/>`
placeholders and put back afterwards. If a placeholder comes back lost or duplicated, the suggestion carries a warning.

Providers (all REST, no extra packages): "deepl", "openai" (any OpenAI compatible chat endpoint, also local ones),
"libretranslate". Experimental: written from the services' documentation and covered by tests with a fake HTTP layer;
it has not been run against the real services.
"""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .textedit import TOKEN_RE

PROVIDERS = ("deepl", "openai", "libretranslate")
TIMEOUT = 30
PLACEHOLDER_RE = re.compile(r"<\s*x\s+id\s*=\s*[\"']?(\d+)[\"']?\s*/?\s*>", re.IGNORECASE)
SYSTEM_PROMPT = ("You translate dialogue of a visual novel (Ren'Py game) from {src} to {dst}. Keep every <x id=\"N\"/> element "
                 "exactly as it is, once, in a natural place of the sentence. Keep the tone of spoken dialogue. "
                 "Return only the translated text, no explanations and no quotes.")


class MTError(Exception):
    pass


def protect(text, escape=False):
    """Text with tags / variables / escapes replaced by <x id="N"/>; returns (protected, [original tokens])."""
    tokens, out, last = [], [], 0
    esc = html.escape if escape else (lambda t: t)
    for m in TOKEN_RE.finditer(text):
        out.append(esc(text[last:m.start()]))
        tokens.append(m.group(0))
        out.append(f'<x id="{len(tokens)}"/>')
        last = m.end()
    out.append(esc(text[last:]))
    return "".join(out), tokens


def restore(text, tokens, unescape=False):
    """Put the original tokens back. Returns (text, warnings)."""
    seen = []

    def put(m):
        i = int(m.group(1))
        seen.append(i)
        return tokens[i - 1] if 1 <= i <= len(tokens) else ""
    out = PLACEHOLDER_RE.sub(put, text)
    if unescape:
        out = html.unescape(out)
    warnings = []
    lost = [i for i in range(1, len(tokens) + 1) if i not in seen]
    dup = sorted({i for i in seen if seen.count(i) > 1})
    if lost:
        warnings.append("Službě se nepodařilo zachovat: " + ", ".join(tokens[i - 1] for i in lost) + " – doplň to ručně.")
    if dup:
        warnings.append("Tyto značky se v návrhu opakují: " + ", ".join(tokens[i - 1] for i in dup) + ".")
    return out.strip(), warnings


def _post(url, headers, data, timeout=TIMEOUT):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as e:
        raise MTError(f"Spojení se službou se nezdařilo: {getattr(e, 'reason', e)}") from e


HTTP_HINTS = {400: "služba požadavek odmítla (zkontroluj jazyky a nastavení)", 401: "klíč byl odmítnut", 403: "klíč byl odmítnut nebo nemá oprávnění",
              404: "adresa služby neexistuje (zkontroluj adresu / model)", 429: "překročený limit požadavků, zkus to za chvíli",
              456: "vyčerpaná kvóta služby", 500: "chyba na straně služby", 503: "služba je dočasně nedostupná"}


def _check_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise MTError("Adresa služby musí začínat http:// nebo https://.")
    return url.rstrip("/")


def _call(url, headers, data, http):
    status, body = (http or _post)(url, headers, data)
    if status >= 400:
        raise MTError(f"Služba odpověděla chybou {status}: {HTTP_HINTS.get(status, 'neznámá chyba')}.")
    try:
        return json.loads(body)
    except ValueError as e:
        raise MTError("Služba vrátila odpověď, které nerozumím.") from e


def translate(cfg, text, glossary=None, context=None, http=None):
    """Suggest a Czech (target language) translation of `text`. Returns {text, warnings, provider}.

    cfg = {provider, api_key, base_url, model, source_lang, target_lang, consent}.
    glossary = {english term: czech}; context = previous lines [str] (only used by the openai provider).
    http(url, headers, data_bytes) -> (status, body) can be replaced in tests."""
    provider = cfg.get("provider", "")
    if provider not in PROVIDERS:
        raise MTError("Strojový překlad není nastavený.")
    if not cfg.get("consent"):
        raise MTError("Chybí souhlas s odesíláním textu externí službě (Nastavení → Strojový překlad).")
    key = str(cfg.get("api_key", "")).strip()
    base = str(cfg.get("base_url", "")).strip()
    if not key and not (provider in ("openai", "libretranslate") and base):
        raise MTError("Chybí klíč k API.")
    if not text.strip():
        raise MTError("Řádek nemá žádný text k překladu.")
    src, dst = cfg.get("source_lang", "EN") or "EN", cfg.get("target_lang", "CS") or "CS"
    markup = provider in ("deepl", "libretranslate")          # these two parse the text as XML / HTML
    protected, tokens = protect(text, escape=markup)
    if provider == "deepl":
        host = _check_url(base) if base else ("https://api-free.deepl.com" if key.endswith(":fx") else "https://api.deepl.com")
        data = urllib.parse.urlencode({"text": protected, "source_lang": src.upper(), "target_lang": dst.upper(), "tag_handling": "xml",
                                       "non_splitting_tags": "x", "ignore_tags": "x"}).encode("utf-8")
        res = _call(host + "/v2/translate", {"Authorization": f"DeepL-Auth-Key {key}", "Content-Type": "application/x-www-form-urlencoded"}, data, http)
        try:
            out = res["translations"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise MTError("Odpověď DeepL nemá očekávaný tvar.") from e
        result, warnings = restore(out, tokens, unescape=True)
    elif provider == "libretranslate":
        host = _check_url(base or "https://libretranslate.com")
        body = {"q": protected, "source": src.lower(), "target": dst.lower(), "format": "html"}
        if key:
            body["api_key"] = key
        res = _call(host + "/translate", {"Content-Type": "application/json"}, json.dumps(body).encode("utf-8"), http)
        try:
            out = res["translatedText"]
        except (KeyError, TypeError) as e:
            raise MTError("Odpověď LibreTranslate nemá očekávaný tvar.") from e
        result, warnings = restore(out, tokens, unescape=True)
    else:
        host = _check_url(base or "https://api.openai.com/v1")
        system = SYSTEM_PROMPT.format(src=src, dst=dst)
        if glossary:
            system += " Preferred translations of terms: " + "; ".join(f"{k} = {v}" for k, v in glossary.items()) + "."
        user = ("Context (previous lines, do not translate):\n" + "\n".join(context) + "\n\n" if context else "") + "Translate:\n" + protected
        body = {"model": cfg.get("model") or "gpt-4o-mini", "temperature": 0.2,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        res = _call(host + "/chat/completions", headers, json.dumps(body).encode("utf-8"), http)
        try:
            out = res["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise MTError("Odpověď služby nemá očekávaný tvar.") from e
        result, warnings = restore(out.strip().strip('"'), tokens)
    return {"text": result, "warnings": warnings, "provider": provider}
