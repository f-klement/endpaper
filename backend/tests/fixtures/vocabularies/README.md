# Vocabulary release captures

Trimmed captures of the two upstream releases `vocabulary_dumps.py` converts,
fetched 2026-11-20 and read by `tests/test_vocabulary_dumps.py`.

| File | Source | Licence line, as the publisher states it |
|---|---|---|
| `gnd_sachbegriff_2026_11_20.jsonld` | `https://data.dnb.de/opendata/authorities-gnd-sachbegriff_lds.jsonld.gz`, Last-Modified 2026-11-04 | "Metadata is provided under Creative Commons Zero (CC0 1.0) terms, unless otherwise stated", `https://data.dnb.de/opendata/002_ReadMe.txt` |
| `lcsh_subjects_skos_2026_11_20.jsonl` | `https://id.loc.gov/download/authorities/subjects.skosrdf.jsonld.gz`, Last-Modified 2026-11-18 | "The Library of Congress has prepared this linked data system and is making it available as a public domain data set", `https://id.loc.gov/about/` |

The GND file keeps five subject heading nodes, the record description node of
each and two blank nodes, from the first 3,000,000 decompressed bytes, decoded
and written again as one JSON array of one array; the DNB's decomposed Unicode is
kept as served. The LCSH file keeps six lines verbatim from the first 3,000:
concepts with no, one and several alternate labels, and one `skosxl:Label` node.
