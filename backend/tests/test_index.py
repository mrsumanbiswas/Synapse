import pytest

from synapse.index.inverted_index import InvertedIndex
from synapse.index.query_parser import (
    ALL, Field, Not, QuerySyntaxError, Resolver, Term, evaluate, parse_query, year_bounds,
)
from synapse.index.trie import Trie
from synapse.text.tokenizer import analyze


# --------------------------------------------------------------------------- trie


def test_trie_complete_orders_by_frequency():
    trie = Trie()
    for word, count in [("machine", 50), ("machinery", 3), ("mach", 1), ("macro", 20), ("learning", 99)]:
        trie.insert(word, count)
    assert [w for w, _, _ in trie.complete("mac", 3)] == ["machine", "macro", "machinery"]
    assert trie.complete("zzz") == []
    assert "macro" in trie and "macr" not in trie
    assert len(trie) == 5


def test_trie_complete_is_exact_top_k():
    import random

    rng = random.Random(7)
    trie = Trie()
    words = {}
    for _ in range(2000):
        word = "".join(rng.choice("abcde") for _ in range(rng.randint(1, 7)))
        count = rng.randint(1, 1000)
        trie.insert(word, count)
        words[word] = words.get(word, 0) + count
    for prefix in ["", "a", "ab", "cde"]:
        expected = sorted((c for w, c in words.items() if w.startswith(prefix)), reverse=True)[:10]
        assert [c for _, c, _ in trie.complete(prefix, 10)] == expected


def test_trie_fuzzy():
    trie = Trie()
    for word, count in [("retrieval", 40), ("retrieve", 10), ("relevance", 30), ("semantic", 25)]:
        trie.insert(word, count)
    assert trie.fuzzy("retreival", 2)[0][:2] == ("retrieval", 2)
    assert trie.fuzzy("semantik", 1) == [("semantic", 1, 25)]
    assert trie.fuzzy("xyz", 1) == []


# --------------------------------------------------------------------------- inverted index


@pytest.fixture
def index():
    idx = InvertedIndex()
    docs = {
        "d1": ("Neural networks", "Deep neural network models for machine learning in python"),
        "d2": ("Java virtual machine", "Garbage collection for java programs and machine code"),
        "d3": ("Machine learning with Python", "Scikit style machine learning library written in python"),
        "d4": ("Graph theory", "PageRank on citation networks"),
    }
    for doc_id, (title, body) in docs.items():
        idx.add(doc_id, analyze(title), analyze(body))
    return idx


def test_postings_and_phrases(index):
    assert index.docs("machin") == {"d1", "d2", "d3"}
    assert index.phrase_docs(analyze("machine learning")) == {"d1", "d3"}
    assert index.phrase_docs(analyze("learning machine")) == set()
    assert index.title_docs("python") == {"d3"}
    index.remove("d3")
    assert index.docs("python") == {"d1"} and "d3" not in index


def test_tfidf_fallback_prefers_title_matches(index):
    scores = index.tfidf_scores(analyze("python"), index.local_idf)
    assert max(scores, key=scores.get) == "d3"


# --------------------------------------------------------------------------- query parser


def _resolver(index: InvertedIndex) -> Resolver:
    def term(text):
        terms = analyze(text)
        return index.docs(terms[0]) if terms else index.all_docs()

    return Resolver(
        term=term,
        phrase=lambda text: index.phrase_docs(analyze(text)),
        field=lambda name, value: {"d1", "d3"} if (name, value) == ("author", "hinton") else set(),
        universe=index.all_docs,
    )


def test_rpn_and_precedence():
    parsed = parse_query("machine learning AND (python OR java) NOT scala")
    assert [str(t) for t in parsed.rpn] == [
        "machine", "learning", "AND", "python", "java", "OR", "AND", "scala", "NOT", "AND"]
    assert str(parsed.ast) == "(machine AND learning AND (python OR java) AND NOT scala)"


def test_unary_not_and_minus():
    assert str(parse_query("NOT a AND b").ast) == "(NOT a AND b)"
    assert str(parse_query("python -java").ast) == "(python AND NOT java)"
    assert str(parse_query('"deep learning" author:"geoffrey hinton" year:2010..2015').ast) == \
        '("deep learning" AND author:"geoffrey hinton" AND year:2010..2015)'


def test_lowercase_operators_are_words():
    assert str(parse_query("salt and pepper").ast) == "(salt AND and AND pepper)"


def test_syntax_errors():
    for bad in ["(a AND b", "a)", "AND a", "a OR"]:
        with pytest.raises(QuerySyntaxError):
            parse_query(bad, strict=True)
    lenient = parse_query("(a AND b", strict=False)
    assert lenient.fallback and str(lenient.ast) == "(a AND b)"


def test_evaluate_boolean(index):
    resolver = _resolver(index)
    assert evaluate(parse_query("Machine Learning AND Python NOT Java").ast, resolver).docs == {"d1", "d3"}
    assert evaluate(parse_query('"machine learning" OR pagerank').ast, resolver).docs == {"d1", "d3", "d4"}
    assert evaluate(parse_query("NOT machine").ast, resolver).docs == {"d4"}
    assert evaluate(parse_query("author:hinton -neural").ast, resolver).docs == {"d3"}
    traced = evaluate(parse_query("python NOT java").ast, resolver, trace=True)
    assert [(s.action, s.size) for s in traced.steps] == [("push", 2), ("push", 1), ("not", 3), ("and", 2)]


def test_constraint_rewrite():
    parsed = parse_query("python NOT java author:hinton")
    assert str(parsed.constraint()) == "(NOT java AND author:hinton)"
    assert parse_query("author:hinton").constraint() == Field("author", "hinton")
    assert parse_query("python OR author:x").constraint() is ALL
    assert parse_query("deep learning").constraint() is ALL
    assert [str(t) for t in parse_query("a NOT (b OR c) d").positive_terms()] == ["a", "d"]
    assert parse_query("NOT NOT x").constraint() is ALL
    assert parse_query("NOT x").constraint() == Not(Term("x"))


def test_year_bounds():
    assert year_bounds("2015") == (2015, 2015)
    assert year_bounds("2010..2020") == (2010, 2020)
    assert year_bounds(">2015") == (2016, None)
    assert year_bounds("<=1999") == (None, 1999)
    with pytest.raises(QuerySyntaxError):
        year_bounds("recent")
