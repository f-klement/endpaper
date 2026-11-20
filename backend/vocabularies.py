"""The subject vocabularies this application knows, as ADR 0009 declares them.

A **declaration** names each vocabulary, where a refresh fetches its release
(`origin`), which readers turn that release into entries (`origin-format`),
whether a local copy may be kept at all (`licence`) and which catalogue source
answers live until the copy is complete (`suggest`). The format is
InvenioRDM's subject declaration with those four keys added, so a file written
for InvenioRDM loads here once its operator adds `licence`.

An **entry** is one heading of one vocabulary: `id`, `scheme`, `subject` and
`synonyms`, and nothing else. Identity is the pair (`scheme`, `id`), and `id`
takes the form an imported record stores as its first `$0`
(`stored_identifier`), so where that form is known, a heading picked from a
vocabulary and the same heading arriving on an imported record compare equal
as strings.

What converts an upstream release into entries is `vocabulary_dumps.py`. Where
the copy is stored and when it is refreshed belong to the local copy's own
module, which this one does not know about.
"""

import csv
import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

import yaml

#: The declaration this application ships: the vocabularies it treats as first
#: class, GND subject headings and LCSH (owner, 2026-11-20).
DECLARATION: Final = Path(__file__).with_name("vocabularies.yaml")

#: The `licence` values under which a copy may be kept. A value outside this set
#: refuses the `data-file` and leaves the scheme to `suggest`, because a source
#: that may be queried is not automatically one that may be copied, and the
#: loader does not guess.
LICENCES_PERMITTING_A_COPY: Final = frozenset({"CC0-1.0", "public-domain"})

#: InvenioRDM reader names a release may be wrapped in, and the ones a converter
#: here parses. `origin-format` lists containers first and ends on the
#: serialisation; any other name is refused, which is the subset rule ADR 0009
#: decided: a name InvenioRDM knows but no converter here reads would load and
#: then fail at the first refresh.
CONTAINERS: Final = frozenset({"gzip"})
SERIALISATIONS: Final = frozenset({"json", "jsonl"})

_ENTRY_KEYS: Final = ("id", "scheme", "subject", "synonyms")

#: What the digest pass reads of a data file at a time, in bytes.
_CHUNK: Final = 1024 * 1024


class DeclarationRefused(ValueError):
    """A declaration this application cannot load, with the reason."""


class EntriesRefused(ValueError):
    """A data file that is not the copy its converter recorded, or not entries."""


@dataclass(frozen=True, slots=True)
class Scheme:
    """One declared vocabulary. `id` is lower cased, as `$2` is stored."""

    id: str
    name: str
    uri: str | None
    data_file: Path | None
    origin: str | None
    origin_format: tuple[str, ...]
    licence: str | None
    suggest: str | None


@dataclass(frozen=True, slots=True)
class Entry:
    """One heading of one vocabulary, in the four keys ADR 0009 keeps."""

    id: str
    scheme: str
    subject: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Release:
    """What a converter recorded on a clean exit: the entry count and the
    SHA-256 of the data file it wrote. A load checks the file against these,
    never against a count taken from the file itself, because a file cut at a
    line boundary is well formed and counts as many entries as it holds."""

    entries: int
    sha256: str


def load_declaration(text: str, suggesters: Iterable[str] = ()) -> tuple[Scheme, ...]:
    """The schemes `text` declares, or `DeclarationRefused` naming what is wrong.

    `suggesters` names the catalogue sources able to answer suggestions; that
    capability is the source's own, so the caller passes it rather than this
    module repeating it. A scheme naming any other source is refused.

    A scheme whose `licence` does not permit a copy loses its `data-file` and
    `origin` rather than being refused, and is refused only if that leaves it
    with neither a copy nor a live source.
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as failure:
        raise DeclarationRefused(f"not YAML: {failure}") from failure
    raw_schemes = _schemes_list(document)
    capable = frozenset(suggesters)
    schemes = tuple(_scheme(raw, capable) for raw in raw_schemes)
    ids = [scheme.id for scheme in schemes]
    if len(set(ids)) != len(ids):
        raise DeclarationRefused(f"a scheme id is declared twice: {sorted(ids)}")
    return schemes


def _schemes_list(document: object) -> list[object]:
    subjects = document.get("subjects") if isinstance(document, dict) else None
    schemes = subjects.get("schemes") if isinstance(subjects, dict) else None
    if not isinstance(schemes, list) or not schemes:
        raise DeclarationRefused("no `subjects.schemes` list")
    return schemes


def _scheme(raw: object, suggesters: frozenset[str]) -> Scheme:
    if not isinstance(raw, dict):
        raise DeclarationRefused(f"a scheme is not a mapping: {raw!r}")
    scheme_id = _text(raw, "id")
    if scheme_id is None:
        raise DeclarationRefused(f"a scheme has no id: {raw!r}")
    scheme_id = scheme_id.lower()
    licence = _text(raw, "licence")
    data_file, origin, origin_format = _copy(raw, scheme_id, licence)
    suggest = _suggest(raw, scheme_id, suggesters)
    if data_file is None and suggest is None:
        raise DeclarationRefused(
            f"{scheme_id}: nothing can answer it, no `suggest` and no `data-file` its licence permits"
        )
    return Scheme(
        id=scheme_id,
        name=_text(raw, "name") or scheme_id,
        uri=_text(raw, "uri"),
        data_file=Path(data_file) if data_file else None,
        origin=origin,
        origin_format=origin_format,
        licence=licence,
        suggest=suggest,
    )


def _copy(
    raw: Mapping[str, object], scheme_id: str, licence: str | None
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """The scheme's `data-file`, `origin` and `origin-format`, each dropped
    where `licence` permits no copy."""
    copyable = licence in LICENCES_PERMITTING_A_COPY
    data_file = _text(raw, "data-file") if copyable else None
    origin = _text(raw, "origin") if copyable else None
    # Checked whatever the licence, so a wrong value is refused now rather than
    # on the day somebody corrects the licence.
    declared_format = _origin_format(scheme_id, raw.get("origin-format"))
    origin_format = declared_format if copyable else ()
    if (origin is None) != (not origin_format):
        raise DeclarationRefused(
            f"{scheme_id}: `origin` and `origin-format` are declared together or not at all"
        )
    return data_file, origin, origin_format


def _suggest(raw: Mapping[str, object], scheme_id: str, suggesters: frozenset[str]) -> str | None:
    suggest = _text(raw, "suggest")
    if suggest is not None and suggest not in suggesters:
        raise DeclarationRefused(f"{scheme_id}: `suggest` names {suggest!r}, which cannot answer suggestions")
    return suggest


def _text(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DeclarationRefused(f"`{key}` is not text: {value!r}")
    return value.strip() or None


def _origin_format(scheme_id: str, value: object) -> tuple[str, ...]:
    """The reader names in reading order: a single name is the list of one."""
    if value is None:
        return ()
    names = [value] if isinstance(value, str) else value
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise DeclarationRefused(f"{scheme_id}: `origin-format` is not a list of names: {value!r}")
    *containers, last = names or [""]
    unknown = [name for name in containers if name not in CONTAINERS]
    if unknown or last not in SERIALISATIONS:
        raise DeclarationRefused(
            f"{scheme_id}: `origin-format` {names!r} is not containers from {sorted(CONTAINERS)} "
            f"ending on one of {sorted(SERIALISATIONS)}"
        )
    return tuple(names)


# ── Identity ─────────────────────────────────────────────────────────────────

#: Per scheme, the publisher's URI for an entry and the form an imported record
#: stores in its first `$0`. The GND form is measured: `(DE-588)` stands first in
#: every field carrying it (`marc_fields.Subfields.subject_identifier`). An LCSH
#: entry's id is its id.loc.gov URI (owner, 2026-11-20), the publisher's own
#: spelling and what a catalogue writes in `$0` when it writes one: no import
#: here stores one to copy, since the Library of Congress MODS reader stores no
#: identifier and 117 of 117 LCSH fields in LC MARC records measured 2026-11-20
#: carried no `$0`.
_URI_TO_STORED: Final[dict[str, tuple[re.Pattern[str], str]]] = {
    "gnd": (re.compile(r"https?://d-nb\.info/gnd/(?P<number>[0-9X-]+)"), "(DE-588){number}"),
    "lcsh": (
        re.compile(r"https?://id\.loc\.gov/authorities/subjects/(?P<number>[a-z]+[0-9]+)"),
        "http://id.loc.gov/authorities/subjects/{number}",
    ),
}


def stored_identifier(scheme: str, raw: str) -> str:
    """`raw`, an entry id as a publisher or an InvenioRDM file spells it, in the
    form `scheme`'s imported records store. A spelling the scheme has no rule
    for is returned unchanged, so an unmeasured scheme is not rewritten into a
    form nobody chose."""
    rule = _URI_TO_STORED.get(scheme)
    match = rule[0].fullmatch(raw.strip()) if rule else None
    return rule[1].format(number=match["number"]) if rule and match else raw.strip()


def is_publisher_identifier(scheme: str, raw: str) -> bool:
    """Whether `raw` is an entry id as `scheme`'s publisher spells one. Any id
    is, for a scheme with no rule in `_URI_TO_STORED`."""
    rule = _URI_TO_STORED.get(scheme)
    return rule is None or rule[0].fullmatch(raw.strip()) is not None


def heading_text(raw: str) -> str:
    """A label as an import stores it: NFC, whitespace collapsed.

    The DNB serves its dumps decomposed and the MARC reader composes what it
    reads (`marc_fields._marc_text`), so without this a picked `Müll` and an
    imported one render alike and compare unequal.
    """
    return " ".join(unicodedata.normalize("NFC", raw).split())


# ── A data file ──────────────────────────────────────────────────────────────


def read_entries(path: Path, scheme: Scheme, release: Release) -> Iterator[Entry]:
    """The entries of `scheme`'s data file at `path`, checked against `release`.

    **Streamed, so a caller loads them beside the copy in use** and discards
    what it took when this raises (ADR 0009, section 4). The SHA-256 is checked
    before the first entry and the count after the last, both over one open
    handle, so a file replaced between the two passes is not read. JSON Lines
    and CSV are read a line at a time; YAML has no streaming reader here and is
    parsed whole.

    Refused when the file's SHA-256 or entry count is not what its converter
    recorded, when a line or a value is malformed, or when an entry names
    another scheme. Read by extension as InvenioRDM reads it: `.jsonl`, `.csv`
    or `.yaml`. Keys beyond the four are dropped, `scheme` is lower cased and
    `id` is mapped by `stored_identifier`.
    """
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
        if digest.hexdigest() != release.sha256:
            raise EntriesRefused(f"{path.name} is not the file its converter recorded")
        handle.seek(0)
        count = 0
        for raw in _raw_entries(path.suffix, handle):
            yield _entry(raw, scheme.id)
            count += 1
    if count != release.entries:
        raise EntriesRefused(f"{path.name} holds {count} entries where {release.entries} were recorded")


def _raw_entries(suffix: str, handle: IO[bytes]) -> Iterator[object]:
    if suffix not in {".jsonl", ".csv", ".yaml", ".yml"}:
        raise EntriesRefused(f"a data file is read by its extension, and {suffix!r} is not one of them")
    try:
        if suffix == ".jsonl":
            yield from (json.loads(line) for line in handle if line.strip())
        elif suffix == ".csv":
            yield from csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
        else:
            loaded = yaml.safe_load(handle)
            yield from loaded if isinstance(loaded, list) else [loaded]
    # Bad UTF-8 and bad JSON are each a `ValueError`; a value nested past the
    # decoder's depth is a `RecursionError`.
    except (ValueError, RecursionError, csv.Error, yaml.YAMLError) as failure:
        raise EntriesRefused(f"a data file is not well formed: {failure}") from failure


def _entry(raw: object, scheme: str) -> Entry:
    if not isinstance(raw, dict):
        raise EntriesRefused(f"an entry of {scheme} is a {type(raw).__name__}, not a mapping")
    kept = {key: raw.get(key) for key in _ENTRY_KEYS}
    _check_scheme_named(kept["scheme"], scheme)
    entry_id, subject = _id_and_subject(kept, scheme)
    listed = _synonyms(kept["synonyms"], scheme)
    return Entry(
        id=stored_identifier(scheme, entry_id),
        scheme=scheme,
        subject=heading_text(subject),
        synonyms=tuple(heading_text(synonym) for synonym in listed if synonym.strip()),
    )


def _check_scheme_named(named: object, scheme: str) -> None:
    """Refused unless `named`, where the entry names a scheme at all, is `scheme`."""
    named = named or scheme
    if not isinstance(named, str):
        raise EntriesRefused(f"an entry of {scheme} names a scheme that is not text")
    if named.lower() != scheme:
        raise EntriesRefused(f"an entry of {scheme} names the scheme {named.lower()!r}")


def _id_and_subject(kept: Mapping[str, object], scheme: str) -> tuple[str, str]:
    entry_id, subject = kept["id"], kept["subject"]
    if not isinstance(entry_id, str) or not isinstance(subject, str):
        raise EntriesRefused(f"an entry of {scheme} needs a text id and subject")
    return entry_id, subject


def _synonyms(synonyms: object, scheme: str) -> list[str]:
    # InvenioRDM's CSV reader has no list type, so a synonyms column arrives as
    # one string and is kept as one synonym, as ADR 0009 says it is read there.
    listed = [synonyms] if isinstance(synonyms, str) else synonyms or []
    # Refused rather than passed to `str`: YAML aliases are shared references,
    # so a few hundred bytes of nested aliases spell out to millions of
    # characters once a list is turned into text.
    if not isinstance(listed, list) or not all(isinstance(synonym, str) for synonym in listed):
        raise EntriesRefused(f"an entry of {scheme} has a synonym that is not text")
    return listed


def entry_line(entry: Entry) -> str:
    """One entry as a line of a JSON Lines data file, the converters' output."""
    return json.dumps(
        {"id": entry.id, "scheme": entry.scheme, "subject": entry.subject, "synonyms": list(entry.synonyms)},
        ensure_ascii=False,
    )
