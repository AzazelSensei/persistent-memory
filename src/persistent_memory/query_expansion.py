"""Query-side Turkish/English folding and synonym expansion.

Folding rationale: ``str.casefold`` maps the Turkish dotted capital "İ"
to "i" + U+0307 (combining dot above), which never equals the plain
ASCII "i" produced from English text, so lexical matching would silently
split Turkish and English spellings of the same term. ``_fold_token``
NFKD-decomposes, strips combining marks, and maps the dotless "ı" to
"i", so "GİRİŞ", "giriş", and "giris" all fold to the same token.

Expansion is applied to the query only — never to the corpus — so stored
records and BM25 document statistics stay untouched.
"""

from __future__ import annotations

import string
import unicodedata

TURKISH_DOTLESS_I = "ı"

# Seed examples distilled from measured failed queries (Turkish/English
# pairs the recall eval showed BM25 missing). Extend this map from your
# own measured failed queries rather than guessing synonyms upfront.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "login": ("giris",),
    "giris": ("login",),
    "reels": ("video", "reel"),
    "reel": ("reels", "video"),
    "video": ("reels", "reel"),
    "indir": ("download", "cek"),
    "download": ("indir",),
    "cek": ("indir",),
}


def _fold_token(token: str) -> str:
    decomposed = unicodedata.normalize("NFKD", token.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.replace(TURKISH_DOTLESS_I, "i")


def _lookup_key(token: str) -> str:
    return _fold_token(token.strip(string.punctuation))


def expand_query(query: str) -> str:
    tokens = query.split()
    extra: list[str] = []
    seen = {_lookup_key(t) for t in tokens}
    for token in tokens:
        for syn in SYNONYMS.get(_lookup_key(token), ()):
            if syn not in seen:
                extra.append(syn)
                seen.add(syn)
    return " ".join(tokens + extra)
