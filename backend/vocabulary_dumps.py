"""Turning a vocabulary's upstream release into its JSON Lines data file.

**One seam, `convert`, and two first class sources behind it**: the GND subject
headings the DNB publishes (`authorities-gnd-sachbegriff_lds.jsonld.gz`, one
JSON-LD document) and LCSH as id.loc.gov publishes it
(`subjects.skosrdf.jsonld.gz`, one JSON-LD graph per line). Neither source is
named in code. The scheme's `origin-format` picks the reader, and every reader
yields JSON-LD nodes to one mapper that knows the label properties of both
ontologies, so a third vocabulary published in either shape needs a
declaration and no code.

**Written aside, renamed only on a clean exit** (ADR 0009, section 4). The data
file is written under a temporary name beside the declared one and replaces it
only once every node has been read; the returned `Release` carries the entry
count and SHA-256 a load checks against. A conversion that raises leaves the
previous data file, or none, under the declared name.

**The DNB serves no MARC21 dump of the subject headings.** Measured 2026-11-20
against `https://data.dnb.de/opendata/`: the Sachbegriff file exists as JSON-LD,
RDF/XML and Turtle only, which is why the GND converter reads JSON-LD.
"""

import codecs
import gzip
import hashlib
import json
import logging
import os
import tempfile
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Final

import vocabularies
from vocabularies import Entry, Release, Scheme

logger = logging.getLogger("endpaper.vocabulary_dumps")

#: The longest single JSON value a reader decodes, in characters. Measured
#: 2026-11-20 over the first 3,000 LCSH lines, the longest was 12,685; a GND
#: node is a few hundred. A value over this is a broken or hostile release,
#: refused rather than buffered.
MAX_VALUE: Final = 4 * 1024 * 1024

#: The largest data file a conversion writes, in bytes. A release that
#: decompresses past it is refused before it fills the directory the database
#: lives in: a repeated LCSH entry line compresses 294 to 1 under gzip
#: (measured 2026-11-20), so a release's own size bounds nothing. Set far above
#: a whole vocabulary rather than measured against one.
MAX_DATA_FILE: Final = 4 * 1024**3

#: What a reader asks of the stream at a time, in characters.
_CHUNK: Final = 64 * 1024

type _Stream = IO[bytes] | gzip.GzipFile

#: Per ontology, the property holding an entry's label and the one holding its
#: alternate labels, in every spelling the two sources serve: the DNB writes
#: full IRIs, id.loc.gov compacts SKOS under its own context.
_GND: Final = "https://d-nb.info/standards/elementset/gnd#"
_SKOS: Final = "http://www.w3.org/2004/02/skos/core#"
_LABELS: Final = (
    (f"{_GND}preferredNameForTheSubjectHeading", f"{_GND}variantNameForTheSubjectHeading"),
    (f"{_SKOS}prefLabel", f"{_SKOS}altLabel"),
    ("skos:prefLabel", "skos:altLabel"),
)


class ConversionFailed(ValueError):
    """A release this converter could not turn into a data file."""


#: Each container name of `origin-format`, and how its stream is unwrapped.
_CONTAINERS: Final[dict[str, Callable[[_Stream], _Stream]]] = {
    "gzip": lambda stream: gzip.GzipFile(fileobj=stream),
}


def convert(scheme: Scheme, release: IO[bytes], data_file: Path) -> Release:
    """Write `scheme`'s entries from `release` to `data_file`, and record them.

    `release` is the bytes as fetched from `scheme.origin`; each container its
    `origin-format` names is unwrapped in order and the last name picks the
    reader. A release yielding no entry is refused, because that is a mapping
    that read nothing rather than an empty vocabulary.
    """
    containers, serialisation = _formats(scheme)
    stream: _Stream = release
    for container in containers:
        stream = _CONTAINERS[container](stream)
    nodes = _READERS[serialisation](_text_stream(stream))
    try:
        return _written_aside(data_file, _entries(scheme.id, nodes))
    except ConversionFailed:
        raise
    # A cut download is `EOFError`, a gzip stream ending before its trailer; a
    # corrupt one is `zlib.error`, which is not an `OSError`. `ValueError` covers
    # bad UTF-8, bad JSON and an integer past Python's digit limit, and
    # `RecursionError` a value nested past the decoder's depth.
    except (EOFError, OSError, zlib.error, ValueError, RecursionError) as failure:
        raise ConversionFailed(f"{scheme.id}: the release could not be read: {failure}") from failure


def _formats(scheme: Scheme) -> tuple[list[str], str]:
    """The containers `scheme`'s `origin-format` names, in unwrapping order,
    and its serialisation; refused where it names one this module cannot read."""
    if not scheme.origin_format:
        raise ConversionFailed(f"{scheme.id} declares no `origin-format`, so there is nothing to convert")
    *containers, serialisation = scheme.origin_format
    unknown = [name for name in containers if name not in _CONTAINERS] + [
        name for name in [serialisation] if name not in _READERS
    ]
    if unknown:
        raise ConversionFailed(f"{scheme.id}: no converter here reads {unknown}")
    return containers, serialisation


def _text_stream(stream: IO[bytes] | gzip.GzipFile) -> Iterator[str]:
    """The release as text, a chunk at a time; a UTF-8 sequence cut by a chunk
    boundary is completed by the next one rather than refused."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    while chunk := stream.read(_CHUNK):
        yield decoder.decode(chunk)
    yield decoder.decode(b"", final=True)


def _json_lines(chunks: Iterator[str]) -> Iterator[dict[str, object]]:
    """The nodes of a JSON Lines release: each line's `@graph`, or the line."""
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        *lines, buffer = buffer.split("\n")
        if len(buffer) > MAX_VALUE:
            raise ConversionFailed(f"a line runs past {MAX_VALUE} characters")
        for line in lines:
            yield from _nodes_of_line(line)
    yield from _nodes_of_line(buffer)


def _nodes_of_line(line: str) -> Iterator[dict[str, object]]:
    if not line.strip():
        return
    value = json.loads(line)
    graph = value.get("@graph") if isinstance(value, dict) else None
    yield from (node for node in (graph if isinstance(graph, list) else [value]) if isinstance(node, dict))


def _json_document(chunks: Iterator[str]) -> Iterator[dict[str, object]]:
    """Every object inside the arrays of one JSON document, decoded one at a time.

    The DNB's file is one flattened JSON-LD array of arrays of nodes, hundreds
    of megabytes uncompressed, so it is never decoded whole: the brackets and
    commas between objects are stepped over and each object is decoded alone.
    """
    decoder = json.JSONDecoder()
    buffer, at, more = "", 0, True
    while True:
        at = _past_separators(buffer, at)
        if at == len(buffer):
            buffer, more = _refilled("", chunks)
            at = 0
            if not more and not buffer:
                return
            continue
        try:
            value, end = decoder.raw_decode(buffer, at)
        except json.JSONDecodeError as failure:
            buffer, more = _completed(failure, buffer[at:], more, chunks)
            at = 0
            continue
        if isinstance(value, dict):
            yield value
        at = end


def _past_separators(buffer: str, at: int) -> int:
    """The first index from `at` that is not whitespace, a comma or a bracket."""
    while at < len(buffer) and buffer[at] in " \t\r\n,[]":
        at += 1
    return at


def _completed(
    failure: json.JSONDecodeError, rest: str, more: bool, chunks: Iterator[str]
) -> tuple[str, bool]:
    """`rest`, a value the buffer cut short, with the next chunk read onto it;
    refused where no chunk is left or the value runs past `MAX_VALUE`."""
    if not more or len(rest) > MAX_VALUE:
        raise ConversionFailed(f"the release is not a JSON document: {failure}") from failure
    return _refilled(rest, chunks)


def _refilled(buffer: str, chunks: Iterator[str]) -> tuple[str, bool]:
    chunk = next(chunks, None)
    return (buffer, False) if chunk is None else (buffer + chunk, True)


#: Each serialisation name of `origin-format`, and the reader yielding its nodes.
_READERS: Final[dict[str, Callable[[Iterator[str]], Iterator[dict[str, object]]]]] = {
    "json": _json_document,
    "jsonl": _json_lines,
}

# The names a declaration accepts are `vocabularies`' to say, and this module
# imports that one, so the two sets cannot live here. Refused at import when
# they disagree: a name accepted there and missing here would load a
# declaration and then fail its first refresh.
if set(_CONTAINERS) != vocabularies.CONTAINERS or set(_READERS) != vocabularies.SERIALISATIONS:
    raise RuntimeError(
        "`origin-format` names accepted by `vocabularies` and read by "
        f"`vocabulary_dumps` disagree: {sorted(vocabularies.CONTAINERS)} against "
        f"{sorted(_CONTAINERS)}, {sorted(vocabularies.SERIALISATIONS)} against {sorted(_READERS)}"
    )


def _entries(scheme: str, nodes: Iterator[dict[str, object]]) -> Iterator[Entry]:
    """An entry per node carrying a label; blank nodes, record descriptions and
    LCSH's deprecated `skosxl:Label` nodes carry none and are passed over, and
    so is a node whose id is not the scheme's publisher's spelling, which
    would put a second id form in the copy.

    **The foreign ones are counted and logged once**, because a publisher that
    changes its id form fails the rule on nearly every node, and the conversion
    would then succeed on the few left with no trace of what it dropped.
    """
    foreign = 0
    for node in nodes:
        identifier = node.get("@id")
        if not isinstance(identifier, str) or identifier.startswith("_:"):
            continue
        if not vocabularies.is_publisher_identifier(scheme, identifier):
            foreign += 1
            continue
        for label_key, synonyms_key in _LABELS:
            labels = _values(node.get(label_key))
            if labels:
                yield Entry(
                    id=vocabularies.stored_identifier(scheme, identifier),
                    scheme=scheme,
                    subject=vocabularies.heading_text(labels[0]),
                    synonyms=tuple(
                        vocabularies.heading_text(value) for value in _values(node.get(synonyms_key))
                    ),
                )
                break
    if foreign:
        logger.warning("%s: passed over %d nodes whose id is not in the publisher's form", scheme, foreign)


def _values(raw: object) -> list[str]:
    """The literal values of one JSON-LD property, served as a value object, a
    list of them or a bare string; id.loc.gov serves `altLabel` as either an
    object or a list depending on how many there are."""
    items = raw if isinstance(raw, list) else [raw]
    found = [item.get("@value") if isinstance(item, dict) else item for item in items]
    return [value for value in found if isinstance(value, str) and value.strip()]


def _written_aside(data_file: Path, entries: Iterator[Entry]) -> Release:
    # A name of its own per conversion, so two refreshes of one scheme never
    # write into one partial file and rename what the other is still writing.
    handle, name = tempfile.mkstemp(dir=data_file.parent, prefix=f".{data_file.name}.", suffix=".partial")
    partial = Path(name)
    digest = hashlib.sha256()
    count = written = 0
    try:
        with os.fdopen(handle, "wb") as out:
            for entry in entries:
                line = (vocabularies.entry_line(entry) + "\n").encode()
                written += len(line)
                if written > MAX_DATA_FILE:
                    raise ConversionFailed(
                        f"{data_file.name}: the release converts past {MAX_DATA_FILE} bytes"
                    )
                digest.update(line)
                out.write(line)
                count += 1
        if count == 0:
            raise ConversionFailed(f"{data_file.name}: the release yielded no entry")
        os.replace(partial, data_file)
    finally:
        partial.unlink(missing_ok=True)
    return Release(entries=count, sha256=digest.hexdigest())
