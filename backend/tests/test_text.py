from synapse.text import extract
from synapse.text.stemmer import stem
from synapse.text.tokenizer import analyze, phrases, surface_words

PORTER_CASES = {
    "caresses": "caress", "ponies": "poni", "ties": "ti", "caress": "caress", "cats": "cat",
    "feed": "feed", "agreed": "agre", "plastered": "plaster", "bled": "bled", "motoring": "motor",
    "sing": "sing", "conflated": "conflat", "troubled": "troubl", "sized": "size", "hopping": "hop",
    "tanned": "tan", "falling": "fall", "hissing": "hiss", "fizzed": "fizz", "failing": "fail",
    "filing": "file", "happy": "happi", "sky": "sky", "relational": "relat", "conditional": "condit",
    "rational": "ration", "valenci": "valenc", "hesitanci": "hesit", "digitizer": "digit",
    "conformabli": "conform", "radicalli": "radic", "differentli": "differ", "vileli": "vile",
    "analogousli": "analog", "vietnamization": "vietnam", "predication": "predic",
    "operator": "oper", "feudalism": "feudal", "decisiveness": "decis", "hopefulness": "hope",
    "callousness": "callous", "formaliti": "formal", "sensitiviti": "sensit",
    "sensibiliti": "sensibl", "triplicate": "triplic", "formative": "form", "formalize": "formal",
    "electriciti": "electr", "electrical": "electr", "hopeful": "hope", "goodness": "good",
    "revival": "reviv", "allowance": "allow", "inference": "infer", "airliner": "airlin",
    "gyroscopic": "gyroscop", "adjustable": "adjust", "defensible": "defens", "irritant": "irrit",
    "replacement": "replac", "adjustment": "adjust", "dependent": "depend", "adoption": "adopt",
    "homologou": "homolog", "communism": "commun", "activate": "activ", "angulariti": "angular",
    "homologous": "homolog", "effective": "effect", "bowdlerize": "bowdler", "probate": "probat",
    "rate": "rate", "cease": "ceas", "controll": "control", "roll": "roll",
    "generalizations": "gener", "oscillators": "oscil",
}


def test_porter_reference_vocabulary():
    wrong = {w: (stem(w), expected) for w, expected in PORTER_CASES.items() if stem(w) != expected}
    assert wrong == {}


def test_analyze_drops_stopwords_and_stems():
    assert analyze("The networks of Neural Networks are learning!") == ["network", "neural", "network", "learn"]
    assert analyze("Schütze's café") == ["schutz", "cafe"]


def test_surface_words_and_phrases():
    assert surface_words("A deep learning model for cars") == ["deep", "learning", "model", "cars"]
    assert phrases("Deep learning for latent semantic analysis") == [
        "deep learning", "latent semantic", "semantic analysis"]


def test_entities():
    text = ("Contact jane.doe@uni.edu or J.Smith@lab.example.org. Code at https://github.com/x/y. "
            "See doi:10.1145/361219.361220 and arXiv:1706.03762v5. As shown in [1], [2, 4] and [5-7].")
    assert extract.extract_emails(text) == ["jane.doe@uni.edu", "j.smith@lab.example.org"]
    assert extract.extract_urls(text) == ["https://github.com/x/y"]
    assert extract.extract_dois(text) == ["10.1145/361219.361220"]
    assert extract.extract_arxiv_ids(text) == ["1706.03762v5"]
    assert extract.extract_citation_markers(text) == {1: 1, 2: 1, 4: 1, 5: 1, 6: 1, 7: 1}


def test_author_year_citations():
    text = "This follows (Salton et al., 1975) and (Deerwester and Dumais, 1990)."
    assert extract.extract_author_year_citations(text) == ["Salton et al., 1975", "Deerwester and Dumais, 1990"]


def test_clean_text_joins_hyphenation_and_ligatures():
    assert extract.clean_text("infor-\nmation  reﬁnement\r\n\n\n\nnext") == "information refinement\n\nnext"


def test_strip_html():
    html = "<html><style>p{}</style><h1>Title</h1><p>Hello &amp; welcome</p><script>x()</script></html>"
    assert extract.flatten(extract.strip_html(html)) == "Title Hello & welcome"


PAPER = """Inverted Indexes for Fast Retrieval
Ada Lovelace, Alan Turing and Grace Hopper
ada@example.org

Abstract
We study inverted indexes and the vector space model [1] for ranked retrieval,
and latent semantic analysis [2, 3].

Keywords: information retrieval, inverted index; vector space model

1 Introduction
Published: 2021
Search engines [1] rely on inverted files [3-4]. See https://example.org/code.

References
[1] G. Salton, A. Wong, and C. S. Yang. A vector space model for automatic indexing. Communications of the ACM, 18(11):613-620, 1975.
[2] S. Deerwester, S. T. Dumais, G. W. Furnas, T. K. Landauer, and R. Harshman. Indexing by latent semantic analysis. JASIS, 41(6):391-407, 1990. doi:10.1002/(SICI)1097-4571(199009)41:6<391::AID-ASI1>3.0.CO;2-9
[3] Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond. Foundations and Trends in Information Retrieval, 3(4).
[4] A. Vaswani et al. Attention is all you need. In NeurIPS, 2017. arXiv:1706.03762
"""


def test_extract_document():
    doc = extract.extract_document(PAPER)
    assert doc.title == "Inverted Indexes for Fast Retrieval"
    assert doc.authors == ["Ada Lovelace", "Alan Turing", "Grace Hopper"]
    assert doc.abstract.startswith("We study inverted indexes")
    assert doc.keywords == ["information retrieval", "inverted index", "vector space model"]
    assert doc.year == 2021
    assert doc.emails == ["ada@example.org"]
    assert doc.citation_markers == {1: 2, 2: 1, 3: 2, 4: 1}
    refs = doc.references
    assert [r.number for r in refs] == [1, 2, 3, 4]
    assert refs[0].title == "A vector space model for automatic indexing"
    assert refs[0].year == 1975
    assert refs[1].title == "Indexing by latent semantic analysis"
    assert refs[1].doi.startswith("10.1002/(sici)1097-4571")
    assert refs[2].title == "The probabilistic relevance framework: BM25 and beyond"
    assert refs[3].title == "Attention is all you need"
    assert refs[3].arxiv == "1706.03762"
    assert "title:a vector space model for automatic indexing" in refs[0].keys()


def test_normalize_doi():
    assert extract.normalize_doi("https://doi.org/10.1145/361219.361220.") == "10.1145/361219.361220"
    assert extract.normalize_doi("not a doi") is None
