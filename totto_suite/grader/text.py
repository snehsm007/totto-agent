"""Text utilities for the deterministic checks (no network, no models).

Times, dates, sentence segments, a stop-word language guesser and the
emoji/markdown/symbol patterns that text-to-speech reads out badly.
"""

from __future__ import annotations

import datetime as _dt
import html
import re
from typing import Iterator

# --- segments ------------------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[^\s])")


def segments(text: str) -> list[str]:
    """Sentence-level segments. Lines are split on sentence punctuation; a line
    ending with ':' (a heading such as 'Qualifying:' or 'Times in UTC:') is
    joined with the next non-empty line so list items keep their heading."""
    lines = [ln.strip() for ln in (text or "").split("\n")]
    lines = [ln for ln in lines if ln]
    merged: list[str] = []
    carry = ""
    for ln in lines:
        if carry:
            ln = carry + " " + ln
            carry = ""
        if ln.endswith(":"):
            carry = ln
            continue
        merged.append(ln)
    if carry:
        merged.append(carry)
    out: list[str] = []
    for ln in merged:
        out.extend(s for s in _SENT_SPLIT.split(ln) if s.strip())
    return out


def excerpt(text: str, limit: int = 240) -> str:
    one = " ".join((text or "").split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def around(text: str, start: int, end: int, width: int = 90) -> str:
    """Excerpt of ``text`` around [start, end)."""
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    s = text[lo:hi]
    return ("…" if lo > 0 else "") + " ".join(s.split()) + ("…" if hi < len(text) else "")


# --- times ---------------------------------------------------------------------

_T_COLON = re.compile(r"\b(\d{1,2}):(\d{2})\b(?:\s*([AaPp])\.?\s?[Mm]\b\.?)?")
_T_H = re.compile(r"\b(\d{1,2})\s?h\s?(\d{2})\b")
_T_AMPM = re.compile(r"\b(\d{1,2})\s?([AaPp])\.?\s?[Mm]\b\.?")
_T_UHR = re.compile(r"\b(\d{1,2})(?:[.:](\d{2}))?\s?Uhr\b")


def _norm(h: int, m: int, ampm: str | None) -> set[str]:
    if m > 59 or h > 24:
        return set()
    if ampm:
        if h < 1 or h > 12:
            return set()
        a = ampm.lower()
        hh = (h % 12) + (12 if a == "p" else 0)
        return {f"{hh:02d}:{m:02d}"}
    if h <= 12:
        return {f"{h % 24:02d}:{m:02d}", f"{(h + 12) % 24:02d}:{m:02d}"}
    return {f"{h % 24:02d}:{m:02d}"}


def _exact(h: int, m: int) -> set[str]:
    return {f"{h:02d}:{m:02d}"} if h <= 24 and m <= 59 else set()


def find_times(text: str) -> list[tuple[str, int, int, set[str]]]:
    """[(matched text, start, end, {'HH:MM' candidates})] for clock times:
    '14:00', '7:30 AM', '2 PM', '15h30', '14 Uhr', '14.00 Uhr'."""
    text = text or ""
    found: list[tuple[str, int, int, set[str]]] = []
    taken: list[tuple[int, int]] = []

    def add(m: re.Match, cands: set[str]) -> None:
        if not cands:
            return
        s, e = m.span()
        if any(s < te and ts < e for ts, te in taken):
            return
        taken.append((s, e))
        found.append((m.group(0), s, e, cands))

    # '14 Uhr' / '15h30' are 24-hour conventions: one exact candidate.
    for m in _T_UHR.finditer(text):
        add(m, _exact(int(m.group(1)), int(m.group(2) or 0)))
    for m in _T_COLON.finditer(text):
        add(m, _norm(int(m.group(1)), int(m.group(2)), m.group(3)))
    for m in _T_H.finditer(text):
        add(m, _exact(int(m.group(1)), int(m.group(2))))
    for m in _T_AMPM.finditer(text):
        add(m, _norm(int(m.group(1)), 0, m.group(2)))
    found.sort(key=lambda x: x[1])
    return found


def time_values(text: str) -> set[str]:
    out: set[str] = set()
    for _, _, _, cands in find_times(text):
        out |= cands
    return out


# --- dates ---------------------------------------------------------------------

MONTHS = {
    # en
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # de
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "mai": 5, "juni": 6,
    "juli": 7, "oktober": 10, "dezember": 12,
    # fr
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
    # es
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    # it
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "settembre": 9, "ottobre": 10, "dicembre": 12,
    # pt
    "janeiro": 1, "fevereiro": 2, "março": 3, "maio": 5, "junho": 6,
    "julho": 7, "setembro": 9, "outubro": 10, "dezembro": 12,
}
_MONTH_ALT = "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True))
_D_MD = re.compile(
    rf"\b(?P<mon>{_MONTH_ALT})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<year>\d{{4}}))?",
    re.I,
)
_D_DM = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th|er|º|°)?\.?\s+(?:of\s+|de\s+|di\s+)?(?P<mon>{_MONTH_ALT})\b\.?(?:,?\s+(?:de\s+)?(?P<year>\d{{4}}))?",
    re.I,
)
_D_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<mon>\d{2})-(?P<day>\d{2})")
_D_NUM = re.compile(r"\b(?P<day>\d{1,2})[./](?P<mon>\d{1,2})[./](?P<year>\d{4})\b")
_YEAR = re.compile(r"\b(20\d{2})\b")


def find_dates(text: str, default_year: int | None = None) -> list[tuple[str, int, int, _dt.date | None, bool]]:
    """[(matched, start, end, date|None, has_explicit_year)].

    A date without a year takes the next explicit year that follows it in the
    same text ('July 3 - July 5, 2026'), else ``default_year``."""
    text = text or ""
    raw: list[tuple[int, int, str, int, int, int | None]] = []
    taken: list[tuple[int, int]] = []
    for rx, numeric in ((_D_ISO, True), (_D_NUM, True), (_D_MD, False), (_D_DM, False)):
        for m in rx.finditer(text):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            mon = m.group("mon")
            month = int(mon) if numeric else MONTHS.get(mon.lower().rstrip("."))
            if not month:
                continue
            year = m.group("year")
            taken.append((s, e))
            raw.append((s, e, m.group(0), month, int(m.group("day")), int(year) if year else None))
    raw.sort()
    out = []
    for s, e, matched, month, day, year in raw:
        explicit = year is not None
        if year is None:
            later = _YEAR.search(text, e)
            if later and later.start() - e < 40:
                year = int(later.group(1))
            else:
                year = default_year
        try:
            date = _dt.date(year, month, day) if year else None
        except ValueError:
            date = None
        out.append((matched, s, e, date, explicit))
    return out


# --- language ------------------------------------------------------------------

STOPWORDS = {
    "en": set(
        "the and is are you your to of for in on with that this it what when where which "
        "will can be at from my me we our have has about just let here there would like "
        "please thank thanks how do does not but or an if so i'm it's i'll you're".split()
    ),
    "de": set(
        "der die das und ist sind ich du sie wir ihr nicht mit für auf ein eine einen dem "
        "den des zu von wie wann wo was wer auch noch nächste nächsten rennen bitte danke "
        "gerne dein deine dich dir uns unser unsere hier gibt schon aber oder wenn dass im "
        "zum zur statt findet eigentlich aktuellen ob kann können für über ihre ihnen wird "
        "um uhr freitag samstag sonntag oktober training freies".split()
    ),
    "fr": set(
        "le la les et est sont je tu vous nous il elle pas avec pour sur un une des du au "
        "aux qui que quoi quand où comment merci bonjour votre vos mon ma mes ce cette "
        "prochain prochaine course billets oui très plus mais ou si c'est j'ai dans".split()
    ),
    "es": set(
        "el la los las y es son yo tú usted nosotros no con para por un una unos del al que "
        "qué cuándo dónde cómo gracias hola su sus mi mis este esta próxima próximo carrera "
        "sí muy pero más está puedo".split()
    ),
    "it": set(
        "il lo la gli le e è sono io tu lei noi non con per su un una del della che quando "
        "dove come grazie ciao suo mio questo questa prossima prossimo gara sì molto ma più "
        "sei posso".split()
    ),
    "pt": set(
        "o a os as e é são eu você nós não com para por um uma do da dos das que quando onde "
        "como obrigado obrigada olá seu sua meu minha este esta próxima próximo corrida sim "
        "muito mas mais".split()
    ),
}
_WORD = re.compile(r"[a-zà-öø-ÿß']+", re.I)
_URL = re.compile(r"https?://\S+|www\.\S+|\S+\.(?:com|org|net)\S*", re.I)
_CODE = re.compile(r"`[^`]*`|\w+\([^)]*\)")


def words(text: str) -> list[str]:
    clean = _CODE.sub(" ", _URL.sub(" ", html.unescape(text or "")))
    return [w.lower().strip("'") for w in _WORD.findall(clean) if w.strip("'")]


def detect_language(text: str, min_hits: int = 3) -> tuple[str | None, dict[str, int]]:
    """Stop-word language guess. Returns (code | None if not confident, hits)."""
    ws = words(text)
    hits = {lang: sum(1 for w in ws if w in sw) for lang, sw in STOPWORDS.items()}
    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    best, best_n = ranked[0]
    second_n = ranked[1][1]
    if best_n < min_hits or best_n < 1.5 * second_n or best_n - second_n < 2:
        return None, hits
    return best, hits


# --- TTS-unfriendly patterns ---------------------------------------------------

EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2B50\u2B55\u231A-\u231B\u23E9-\u23FA\uFE0F\u200D]"
)
MARKDOWN = {
    "bold": re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__"),
    "header": re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"),
    "bullet": re.compile(r"(?m)^\s*[*\-•]\s+\S"),
    "table": re.compile(r"(?m)^\s*\|.*\|\s*$"),
    "link": re.compile(r"\[[^\]\n]+\]\([^)\s]+\)"),
    "inline_code": re.compile(r"`[^`\n]+`"),
}
SPOKEN_SYMBOLS = {
    "hash_number": re.compile(r"#\d+"),
    "position_token": re.compile(r"\bP\d{1,2}\b"),
    "raw_url": re.compile(r"https?://\S+"),
    "arrow": re.compile(r"->|=>|→"),
    "stray_markup": re.compile(r"(?<!\*)\*(?!\*)|\|"),
}


def iter_strings(obj) -> Iterator[str]:
    """All string leaves of a nested dict/list (keys excluded)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from iter_strings(v)
