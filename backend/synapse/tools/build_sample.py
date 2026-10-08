"""Build the bundled sample corpora from open data.

    python -m synapse.tools.build_sample openalex --out datasets/openalex_sample.jsonl.gz
    python -m synapse.tools.build_sample arxiv --out ../infra/ftp/data/arxiv/arxiv_sample.csv

OpenAlex and arXiv metadata are both released under CC0. Without an OpenAlex API
key the free allowance is small, so the OpenAlex builder sticks to cheap
filtered list requests (one credit each) rather than full-text searches.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from ..ingest.parsers import SYNAPSE_FORMAT, normalize_arxiv, normalize_openalex
from ..ingest.sources import ArxivClient, OpenAlexClient

log = logging.getLogger("build_sample")

# OpenAlex topics (https://api.openalex.org/topics) spanning the areas Synapse demos.
TOPICS = {
    "T10286": "Information Retrieval and Search Behavior",
    "T13083": "Advanced Text Analysis Techniques",
    "T10028": "Topic Modeling",
    "T10181": "Natural Language Processing Techniques",
    "T11550": "Text and Document Classification Technologies",
    "T10036": "Advanced Neural Network Applications",
    "T10320": "Neural Networks and Applications",
    "T11273": "Advanced Graph Neural Networks",
    "T10462": "Reinforcement Learning in Robotics",
    "T10203": "Recommender Systems and Techniques",
    "T10742": "Peer-to-Peer Network Technologies",
    "T10715": "Distributed and Parallel Computing Systems",
    "T10317": "Advanced Database Systems and Queries",
    "T11099": "Autonomous Vehicle Technology and Safety",
}
YEAR_BUCKETS = [(1950, 1994), (1995, 2004), (2005, 2011), (2012, 2016), (2017, 2020), (2021, 2025)]

# Foundational papers referenced by the example texts and the README.
CLASSIC_DOIS = [
    "10.1145/361219.361220",  # Salton, Wong & Yang 1975 - vector space model
    "10.1002/(sici)1097-4571(199009)41:6<391::aid-asi1>3.0.co;2-9",  # Deerwester et al. 1990 - LSA
    "10.1016/s0169-7552(98)00110-x",  # Brin & Page 1998 - Google / PageRank
    "10.1145/324133.324140",  # Kleinberg 1999 - HITS
    "10.1023/a:1024940629314",  # Kleinberg 2003 - bursty streams
    "10.1145/775047.775061",  # Kleinberg 2002 - bursty streams (KDD)
    "10.1561/1500000019",  # Robertson & Zaragoza 2009 - BM25
    "10.1108/eb046814",  # Porter 1980 - suffix stripping
    "10.1145/367390.367400",  # Fredkin 1960 - trie memory
    "10.1016/0306-4573(88)90021-0",  # Salton & Buckley 1988 - term weighting
    "10.1037/0033-295x.104.2.211",  # Landauer & Dumais 1997 - Plato's problem
    "10.1145/312624.312649",  # Hofmann 1999 - PLSI
    "10.1162/jmlr.2003.3.4-5.993",  # Blei, Ng & Jordan 2003 - LDA
    "10.3115/v1/d14-1162",  # GloVe
    "10.18653/v1/n19-1423",  # BERT
    "10.48550/arxiv.1706.03762",  # Attention is all you need
    "10.48550/arxiv.1301.3781",  # word2vec
    "10.1145/1327452.1327492",  # MapReduce
    "10.1145/383059.383071",  # Chord
    "10.1145/258533.258660",  # Consistent hashing
    "10.1109/90.663936",  # Rendezvous hashing
    "10.1145/945445.945450",  # Google File System
    "10.1145/1294261.1294281",  # Dynamo
    "10.1145/359545.359563",  # Lamport clocks
    "10.1145/362384.362685",  # Codd 1970 - relational model
    "10.1137/s003614450342480",  # Newman 2003 - complex networks
    "10.1088/1742-5468/2008/10/p10008",  # Louvain communities
    "10.1038/30918",  # Watts & Strogatz
    "10.1126/science.286.5439.509",  # Barabasi & Albert
    "10.1073/pnas.122653799",  # Girvan & Newman
    "10.1109/5.726791",  # LeCun et al. 1998
    "10.1145/3065386",  # AlexNet
    "10.1109/cvpr.2016.90",  # ResNet
    "10.1162/neco.1997.9.8.1735",  # LSTM
    "10.1038/323533a0",  # Backpropagation
    "10.1038/nature14539",  # Deep learning (Nature 2015)
    "10.1038/nature14236",  # DQN
    "10.1038/nature16961",  # AlphaGo
    "10.1145/2623330.2623732",  # DeepWalk
    "10.1145/2939672.2939754",  # node2vec
    "10.1109/cvpr.2012.6248074",  # KITTI
    "10.1002/rob.20147",  # Stanley, DARPA Grand Challenge
    "10.1109/mc.2009.263",  # Matrix factorization for recommenders
    "10.1145/371920.372071",  # Item-based collaborative filtering
    "10.1109/tkde.2005.99",  # Recommender systems survey
    "10.1145/138859.138867",  # Tapestry collaborative filtering
]

ARXIV_QUERIES = [
    ("cat:cs.IR", 50),
    ('cat:cs.CL AND abs:"semantic search"', 35),
    ('cat:cs.RO AND abs:"autonomous driving"', 35),
    ('cat:cs.DC AND abs:"peer-to-peer"', 30),
]


def build_openalex(out: Path, per_bucket: int, expand: int, api_key: str | None) -> None:
    client = OpenAlexClient(api_key=api_key)
    works: dict[str, dict] = {}

    for topic_id, label in TOPICS.items():
        for lo, hi in YEAR_BUCKETS:
            batch = client.list_works(
                filter=f"primary_topic.id:{topic_id},has_abstract:true,language:en,publication_year:{lo}-{hi}",
                sort="cited_by_count:desc",
                per_page=per_bucket,
            )
            for work in batch:
                works.setdefault(work["id"], work)
            log.info("%-48s %d-%d: %3d works (total %d, credits left %s)",
                     label, lo, hi, len(batch), len(works), client.remaining_credits)

    classics = client.works_by_dois(CLASSIC_DOIS)
    for work in classics:
        works.setdefault(work["id"], work)
    log.info("classic papers: %d found, total %d", len(classics), len(works))

    # Co-reference expansion: add the papers this set cites most often, which
    # turns a bag of popular papers into a connected citation graph.
    cited = Counter(ref for w in works.values() for ref in w.get("referenced_works") or [] if ref not in works)
    missing = [ref for ref, count in cited.most_common(expand) if count >= 3]
    for work in client.works_by_ids(missing):
        works.setdefault(work["id"], work)
    log.info("co-reference expansion: +%d candidates, total %d", len(missing), len(works))

    records = [normalize_openalex(w) for w in works.values()]
    records = [r for r in records if r.title and len(r.title) > 3]
    ids = {r.external_id.split(":", 1)[1] for r in records}
    edges = sum(1 for r in records for ref in r.references if ref["key"][3:] in ids)

    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        for record in sorted(records, key=lambda r: (r.year or 0, r.title)):
            fh.write(json.dumps({"format": SYNAPSE_FORMAT, **record.to_dict()}, ensure_ascii=False) + "\n")

    decades = Counter((r.year or 0) // 10 * 10 for r in records)
    log.info("wrote %d records to %s", len(records), out)
    log.info("in-corpus citation edges: %d; with abstract: %d", edges, sum(1 for r in records if r.abstract))
    log.info("by decade: %s", dict(sorted(decades.items())))


def build_arxiv(out: Path) -> None:
    client = ArxivClient()
    rows: dict[str, dict] = {}
    for query, limit in ARXIV_QUERIES:
        entries = client.search(query, max_results=limit, sort_by="relevance")
        for entry in entries:
            rows.setdefault(entry["arxiv_id"], entry)
        log.info("%-45s %d entries (total %d)", query, len(entries), len(rows))

    out.parent.mkdir(parents=True, exist_ok=True)
    columns = ["id", "title", "abstract", "authors", "categories", "published", "doi", "journal_ref", "url"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for entry in rows.values():
            record = normalize_arxiv(entry)
            writer.writerow({
                "id": entry["arxiv_id"],
                "title": record.title,
                "abstract": record.abstract,
                "authors": "; ".join(record.authors),
                "categories": " ".join(record.categories),
                "published": entry.get("published"),
                "doi": record.doi or "",
                "journal_ref": entry.get("journal_ref") or "",
                "url": record.url,
            })
    log.info("wrote %d rows to %s", len(rows), out)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="source", required=True)
    oa = sub.add_parser("openalex", help="research papers with citations from OpenAlex")
    oa.add_argument("--out", type=Path, required=True)
    oa.add_argument("--per-bucket", type=int, default=20, help="papers per topic and era")
    oa.add_argument("--expand", type=int, default=250, help="most-cited missing papers to add")
    oa.add_argument("--api-key", default=None, help="OpenAlex API key (optional)")
    ax = sub.add_parser("arxiv", help="a CSV of arXiv abstracts (no citation data)")
    ax.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.source == "openalex":
        build_openalex(args.out, args.per_bucket, args.expand, args.api_key)
    else:
        build_arxiv(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
