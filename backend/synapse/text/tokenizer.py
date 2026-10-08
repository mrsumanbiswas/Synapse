"""Tokenisation, stop-word removal and stemming.

``analyze`` turns raw text into the index terms used everywhere else (inverted
index, TF-IDF, LSA). ``surface_words`` keeps readable words for autocomplete.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from .stemmer import stem

WORD_RE = re.compile(r"[a-z0-9]+")
SPAN_RE = re.compile(r"\w+", re.UNICODE)

STOPWORDS = frozenset(
    """
    a about above according across after afterwards again against all almost alone along already
    also although always am among amongst an and another any anyhow anyone anything anyway anywhere
    are around as at be became because become becomes becoming been before beforehand behind being
    below beside besides between beyond both but by can cannot could did do does doing done down
    due during each eg either else elsewhere enough et etc even ever every everyone everything
    everywhere except few for former formerly from further had has have having he hence her here
    hereafter hereby herein hereupon hers herself him himself his how however i ie if in indeed into
    is it its itself just last latter latterly least less made many may me meanwhile might more
    moreover most mostly much must my myself namely neither never nevertheless next no nobody none
    noone nor not nothing now nowhere of off often on once one only onto or other others otherwise
    our ours ourselves out over own per perhaps please put rather re same see seem seemed seeming
    seems several she should since so some somehow someone something sometime sometimes somewhere
    still such than that the their theirs them themselves then thence there thereafter thereby
    therefore therein thereupon these they this those though through throughout thru thus to
    together too toward towards under until up upon us use used using very via was we well were what
    whatever when whence whenever where whereafter whereas whereby wherein whereupon wherever whether
    which while whither who whoever whole whom whose why will with within without would yet you your
    yours yourself yourselves paper propose proposed present presents show shows shown study
    studies approach approaches method methods result results based new novel two three work works
    various ca inc ltd llc gmbh
    """.split()
)


# Stems of academic filler ("state-of-the-art", "recent", "challenges") that are
# searchable but make poor topic labels and fake "bursts".
GENERIC_STEMS = frozenset(
    """
    art state recent challeng futur comprehens achiev perform improv signific outperform demonstr
    extens effect experi evalu public publicli avail code open sourc year decad first larg mani help
    make need includ provid allow develop differ import high low number set best better wai potenti
    kei current exist prior previou problem paper confer proceed intern journal research applic
    techniqu framework task issu aim term gener specif sever common type part provid make lead limit
    com www http http org html
    """.split()
)


def fold(text: str) -> str:
    """Lowercase and strip accents (``Schütze`` -> ``schutze``)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def words(text: str) -> list[str]:
    """All lowercase alphanumeric tokens, stop words included."""
    return WORD_RE.findall(fold(text))


def is_index_word(word: str) -> bool:
    return len(word) >= 2 and word not in STOPWORDS and not word.isdigit()


def analyze(text: str) -> list[str]:
    """Text -> stemmed index terms (stop words dropped, order kept for phrase search)."""
    return [stem(w) for w in words(text) if is_index_word(w)]


def analyze_pairs(text: str) -> list[tuple[str, str]]:
    """Like :func:`analyze` but keeps the surface word next to its stem."""
    return [(stem(w), w) for w in words(text) if is_index_word(w)]


def surface_words(text: str) -> list[str]:
    """Readable words worth suggesting in autocomplete."""
    return [w for w in words(text) if len(w) >= 3 and w.isalpha() and w not in STOPWORDS]


def phrases(text: str, n: int = 2) -> list[str]:
    """Word n-grams made only of content words (``"neural network"``)."""
    tokens = words(text)
    out = []
    for i in range(len(tokens) - n + 1):
        gram = tokens[i : i + n]
        if all(len(t) >= 3 and t.isalpha() and t not in STOPWORDS for t in gram):
            out.append(" ".join(gram))
    return out


def spans(text: str) -> Iterator[tuple[int, int, str]]:
    """(start, end, stem-or-empty) for each word in the original string, for highlighting."""
    for match in SPAN_RE.finditer(text):
        folded = fold(match.group())
        term = stem(folded) if folded.isalnum() and is_index_word(folded) else ""
        yield match.start(), match.end(), term
