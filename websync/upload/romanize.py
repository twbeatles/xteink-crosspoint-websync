"""Hangul to ASCII romanization for device-safe filenames.

CrossPoint firmware mishandles non-ASCII multipart filenames, so upload names
must stay ASCII. Naive filtering turns every Hangul syllable into "_", which
erases Korean site names from device-side file titles. This module converts
Hangul syllables to Revised-Romanization-style ASCII first, so
"네이버뉴스_2026-07-31" becomes "neibeonyuseu_2026-07-31" instead of
"2026-07-31".
"""
from __future__ import annotations

import unicodedata

# choseong (initial): U+AC00 + cho*588; ㅇ (index 11) is silent.
_CHOSEONG = (
    "g", "kk", "n", "d", "tt", "r", "m", "b", "pp",
    "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h",
)

# jungseong (medial vowel)
_JUNGSEONG = (
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye",
    "o", "wa", "wae", "oe", "yo", "u", "wo", "we",
    "wi", "yu", "eu", "ui", "i",
)

# jongseong (final, index 0 = none)
_JONGSEONG = (
    "", "k", "k", "k", "n", "n", "n", "t",
    "l", "k", "m", "p", "t", "t", "p", "t",
    "m", "p", "p", "t", "t", "ng", "t", "t",
    "k", "t", "p", "t",
)

# Compatibility Jamo (U+3131-U+3163) fallback for lone Jamo in names.
_JAMO_FALLBACK = {
    "ㄱ": "g", "ㄲ": "kk", "ㄴ": "n", "ㄷ": "d", "ㄸ": "tt",
    "ㄹ": "l", "ㅁ": "m", "ㅂ": "b", "ㅃ": "pp", "ㅅ": "s",
    "ㅆ": "ss", "ㅇ": "ng", "ㅈ": "j", "ㅉ": "jj", "ㅊ": "ch",
    "ㅋ": "k", "ㅌ": "t", "ㅍ": "p", "ㅎ": "h",
    "ㅏ": "a", "ㅐ": "ae", "ㅑ": "ya", "ㅒ": "yae", "ㅓ": "eo",
    "ㅔ": "e", "ㅕ": "yeo", "ㅖ": "ye", "ㅗ": "o", "ㅘ": "wa",
    "ㅙ": "wae", "ㅚ": "oe", "ㅛ": "yo", "ㅜ": "u", "ㅝ": "wo",
    "ㅞ": "we", "ㅟ": "wi", "ㅠ": "yu", "ㅡ": "eu", "ㅢ": "ui",
    "ㅣ": "i",
}

_HANGUL_BASE = 0xAC00
_HANGUL_END = 0xD7A3


def _romanize_char(ch: str) -> str | None:
    """Return ASCII romanization, or None when not convertible."""
    code = ord(ch)
    if _HANGUL_BASE <= code <= _HANGUL_END:
        idx = code - _HANGUL_BASE
        cho, jung, jong = idx // 588, (idx % 588) // 28, idx % 28
        return _CHOSEONG[cho] + _JUNGSEONG[jung] + _JONGSEONG[jong]
    if ch in _JAMO_FALLBACK:
        return _JAMO_FALLBACK[ch]
    if ch.isascii():
        return ch
    # Latin diacritics (é→e) via NFKD; CJK and others stay unconvertible.
    decomposed = unicodedata.normalize("NFKD", ch)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    if stripped and all(c.isascii() and (c.isalnum() or c in "-_ ") for c in stripped):
        return stripped
    return None


def romanize_for_filename(text: str) -> str:
    """Convert Hangul in *text* to ASCII; other chars pass through.

    Characters with no ASCII equivalent are returned unchanged so the
    caller's sanitizer can decide their fate (currently "_" + hash suffix
    keeps names unique).
    """
    out: list[str] = []
    for ch in text or "":
        converted = _romanize_char(ch)
        out.append(converted if converted is not None else ch)
    return "".join(out)
