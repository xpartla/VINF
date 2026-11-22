# VINF 2026 – Dog Breed Advisor

Search engine over dog-breed information for people choosing a dog: own crawler, regex-only entity extraction,
own inverted index with several IDF weightings, and a cosine searcher (part 1); the extraction moved to Apache Spark,
the English Wikipedia dump processed with regexes in Spark and joined to the crawled breeds, and a fielded PyLucene
index with BM25 and Boolean / range / phrase / fuzzy queries (part 2). Course project for *Vyhľadávanie informácií*
(FIIT STU / UI SAV).

Python 3.11+ with `requests`; `pytest` runs the tests, `tiktoken` is only needed for the token statistic, `pyspark`
(Spark 4.x, Java 17+) runs the Spark jobs, PyLucene 10 (not on PyPI) runs in Docker (`Dockerfile`). No database, no
DOM/XPath/wikitext parser: every URL, entity and wiki attribute is extracted with regular expressions.

```
pip install -r requirements.txt
conda install -c conda-forge openjdk=17      # or any Java 17+ on PATH / JAVA_HOME
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
| tests | `python -m pytest tests/ -q` | unit tests, including the regex extractors on 28 real breed pages and 6 real article/list pages (`tests/fixtures/`), the wikitext regexes on real wiki pages, the Spark jobs on a local session (skipped without Java) and the Lucene index (skipped without PyLucene, see below) |

`python src/extractor/run.py --show golden-retriever` pretty-prints one extracted breed entity.

## Spark pipeline (part 2)

Each job runs with plain `python` (local mode, all cores, 8 GB driver; override with `VINF_SPARK_MASTER`,
`VINF_SPARK_DRIVER_MEMORY`) or through `tools/spark_submit.sh <job> [args]`, which ships `src/` as `--py-files` and
takes `SPARK_OPTS="--master yarn ..."` and `hdfs://` paths for a cluster.

| step | command | what it does |
|---|---|---|
| 0 dump | `tools/download_wiki.sh enwiki 20261001` | the 71 bz2 parts of `pages-articles` (25.8 GB) to `data/wiki/enwiki-20261001/`, MD5-checked |
| 1 AKC | `python src/sparkjobs/akc_extract.py [--compare data/extracted]` | part-1 regex extractors on the executors over `data/raw` + `data/meta`, newest fetch per URL, one record per canonical URL → `data/spark/akc/`; `--compare` diffs against the part-1 output |
| 2a wiki scan | `python src/sparkjobs/wiki_extract.py scan [--dump GLOB]` | one pass over the dump split on `</page>`; Java regexes take id/ns/title/redirect of every page and the wikitext of articles with a dog-breed infobox or a dog category → `data/spark/wiki/pages` (parquet) |
| 2b wiki parse | `python src/sparkjobs/wiki_extract.py parse` | Python regexes (`src/wiki/`): infobox, sections, links, categories → `breeds/`, `diseases/` (JSON lines), `redirects` (parquet) |
| 3 join | `python src/sparkjobs/join.py` | AKC breed ↔ wiki breed article (name keys, priority cascade), wiki Health links ↔ dog-disease articles → `data/spark/joined/` + `join_stats.json` |
| 4 index | `python src/indexer/build.py [--part1]` | indexes the Spark output when `data/spark/joined/` exists: breeds with wiki text and facets (`origin_slovakia`, `fci_group_1`, `disease_*`), wiki-only breeds, disease pages |

## Lucene index (part 2)

PyLucene is not pip-installable; the `Dockerfile` adds pytest and requests to the `coady/pylucene` image (PyLucene
10.0.0, Python 3.15, Java 21). Every command runs with the project mounted on `/work`:

```
docker build -t vinf-lucene - < Dockerfile
docker run --rm -i -u "$(id -u):$(id -g)" -v "$PWD":/work vinf-lucene python src/luceneindex/build.py
```

| step | command (after `docker run ... vinf-lucene`) | what it does |
|---|---|---|
| 5 index | `python src/luceneindex/build.py` | fielded Lucene index of the Spark output → `data/lucene/index/`, field statistics → `data/lucene/stats.json` |
| 6 search | `python src/luceneindex/search.py "small dog under 10 kg that lives over 14 years"` | the advisor: query phrases become field constraints (term and range queries), free text is searched with BM25 over the text fields, quoted `"phrases"` are required, `-word` excludes, misspelled names are matched fuzzily; `--strict` turns constraints into filters, `--type`, `--sort popularity\|published`, `--similarity classic`, `--terms`, `--explain N`, `--show-query`, `-i` reads queries from stdin |
| 6b syntax | `python src/luceneindex/search.py --syntax '+type:breed +shedding:[1 TO 2] +origin:france'` | Lucene query syntax: fields, AND/OR/NOT, `+`/`-`, `"phrase"~n`, `word~` (fuzzy), `[a TO b]` on numeric fields, wildcards |
| 7 compare | `python src/luceneindex/compare.py` | old index (own TF-IDF cosine) vs Lucene ClassicSimilarity vs Lucene BM25 on a fixed query set: P@10, rank of the expected document, hits, latency, top 5 |
| tests | `python -m pytest tests/ -q` | the whole suite except the Spark tests (no pyspark in the image) |

## Layout

```
src/crawler/    config.py (headers, timeouts, politeness, site scope), main.py (worker loop), fetcher.py, frontier.py,
                robots.py, store.py, urlextract.py (URL regexes), stats.py
src/extractor/  akc_breed.py (breed entity regexes), akc_page.py (articles, list pages), textutil.py, run.py
src/indexer/    tokenize.py, documents.py (records -> documents + facet tokens), build.py, idf.py (TF/IDF formulas),
                query_expand.py (query phrases -> facet tokens), search.py
src/wiki/       wikitext.py (template reduction, links, sections, categories, plain text), infobox.py, page.py
                (page -> breed / disease record), names.py (join keys)
src/sparkjobs/  session.py, akc_extract.py (job 1), wiki_extract.py (job 2), join.py (job 3)
src/luceneindex/ schema.py (fields, analyzers, boosts), documents.py (records -> fields), plan.py (query phrases ->
                constraints), env.py (JVM, analyzers), build.py, searcher.py (Lucene queries), search.py, compare.py
tests/          pytest suites + gzipped real pages in tests/fixtures/akc/
data/           created by the pipeline, not versioned: raw/ (crawled bodies, never deleted), meta/, frontier/,
                logs/, extracted/, index/, wiki/ (dump), spark/{akc,wiki,joined}/, lucene/
```
