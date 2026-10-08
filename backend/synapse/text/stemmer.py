"""Porter stemming algorithm (M. F. Porter, "An algorithm for suffix stripping", 1980).

Implemented from the paper with plain string manipulation. A word is viewed as
``[C](VC){m}[V]`` where C/V are runs of consonants/vowels; ``m`` (the "measure")
decides whether a suffix may be removed.
"""

from __future__ import annotations

from functools import lru_cache

_VOWELS = frozenset("aeiou")


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        # 'y' is a consonant at the start or after a vowel, a vowel after a consonant.
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """Number of VC sequences in ``stem``."""
    m = 0
    previous_vowel = False
    for i in range(len(stem)):
        consonant = _is_consonant(stem, i)
        if consonant and previous_vowel:
            m += 1
        previous_vowel = not consonant
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_consonant(word, len(word) - 1)


def _ends_cvc(word: str) -> bool:
    """*o condition: ends consonant-vowel-consonant, last consonant not w, x or y."""
    if len(word) < 3:
        return False
    n = len(word)
    return (
        _is_consonant(word, n - 3)
        and not _is_consonant(word, n - 2)
        and _is_consonant(word, n - 1)
        and word[-1] not in "wxy"
    )


def _step1a(word: str) -> str:
    if word.endswith("sses") or word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def _step1b(word: str) -> str:
    if word.endswith("eed"):
        return word[:-1] if _measure(word[:-3]) > 0 else word
    for suffix in ("ed", "ing"):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if not _has_vowel(stem):
                return word
            if stem.endswith(("at", "bl", "iz")):
                return stem + "e"
            if _ends_double_consonant(stem) and stem[-1] not in "lsz":
                return stem[:-1]
            if _measure(stem) == 1 and _ends_cvc(stem):
                return stem + "e"
            return stem
    return word


def _step1c(word: str) -> str:
    if word.endswith("y") and _has_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


def _sorted_rules(rules: list[tuple[str, str]]) -> list[tuple[str, str]]:
    # The longest matching suffix wins; once it matches no shorter rule is tried.
    return sorted(rules, key=lambda rule: len(rule[0]), reverse=True)


_STEP2 = _sorted_rules([
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"), ("eli", "e"),
    ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"), ("ator", "ate"),
    ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"),
    ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
])

_STEP3 = _sorted_rules([
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
])

_STEP4 = sorted(
    ["al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent",
     "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize"],
    key=len,
    reverse=True,
)


def _apply_rules(word: str, rules: list[tuple[str, str]]) -> str:
    for suffix, replacement in rules:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            return stem + replacement if _measure(stem) > 0 else word
    return word


def _step4(word: str) -> str:
    for suffix in _STEP4:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if suffix == "ion" and not stem.endswith(("s", "t")):
                continue  # "ion" needs *S or *T; "ou" etc. cannot match either, keep looking
            return stem if _measure(stem) > 1 else word
    return word


def _step5(word: str) -> str:
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _ends_cvc(stem)):
            word = stem
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        word = word[:-1]
    return word


@lru_cache(maxsize=262_144)
def stem(word: str) -> str:
    """Return the Porter stem of a lowercase word (non-alphabetic words are kept)."""
    if len(word) <= 2 or not word.isalpha():
        return word
    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    word = _apply_rules(word, _STEP2)
    word = _apply_rules(word, _STEP3)
    word = _step4(word)
    return _step5(word)
