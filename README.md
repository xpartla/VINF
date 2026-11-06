# VINF 2026 – Dog Breed Advisor (part 1)

Search engine over dog-breed information for people choosing a dog: own crawler, regex-only entity extraction,
own inverted index with several IDF weightings, and a cosine searcher. Course project for *Vyhľadávanie informácií*
(FIIT STU / UI SAV), part 1 of 2.

Everything is plain Python 3.11+ with `requests`; `pytest` runs the tests and `tiktoken` is only needed for the
token statistic. No database, no DOM/XPath parsing: every URL and every entity is extracted with regular expressions.

```
pip install -r requirements.txt
```

## Pipeline (run from the project root)

| step | command | what it does |
|---|---|---|
| 1 crawl | `python src/crawler/main.py --site akc` | seeds from the akc.org sitemaps, 2 s politeness delay, raw HTML to `data/raw/`, one JSON metadata line per fetch to `data/meta/akc.jsonl`; `--resume` continues from `data/frontier/`, `--max-pages N` for a sample |
| 2 extract | `python src/extractor/run.py` | regex extraction of breed entities, articles and list pages into `data/extracted/*.jsonl` + field coverage |
| 3 index | `python src/indexer/build.py` | builds the inverted index (term -> [doc, tf]) and the document norms into `data/index/` |
| 4 search | `python src/indexer/search.py "low shedding dog good with children"` | ranked results; `--idf classic\|smooth\|max\|none`, `--tf log\|raw\|binary`, `--type breed\|article\|list`, `-k 10` |
| 4b compare | `python src/indexer/search.py "calm apartment dog" --compare [--md]` | the same query under every IDF method, with the per-term IDF values |
| stats | `python src/crawler/stats.py [--tokens] [--md]` | crawl statistics: fetches, unique pages, MB on disk, relevance by page type, tiktoken tokens |
| tests | `python -m pytest tests/ -q` | unit tests, including the regex extractors on 28 real breed pages and 6 real article/list pages (`tests/fixtures/`) |

`python src/extractor/run.py --show golden-retriever` pretty-prints one extracted breed entity.

## Layout

```
src/crawler/    config.py (headers, timeouts, politeness, site scope), main.py (worker loop), fetcher.py, frontier.py,
                robots.py, store.py, urlextract.py (URL regexes), stats.py
src/extractor/  akc_breed.py (breed entity regexes), akc_page.py (articles, list pages), textutil.py, run.py
src/indexer/    tokenize.py, documents.py (records -> documents + facet tokens), build.py, idf.py (TF/IDF formulas),
                query_expand.py (query phrases -> facet tokens), search.py
tests/          pytest suites + gzipped real pages in tests/fixtures/akc/
data/           created by the pipeline, not versioned: raw/ (crawled bodies, never deleted), meta/, frontier/,
                logs/, extracted/, index/
```
