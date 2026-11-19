"""Write the image's one third party notices file.

Run in the Dockerfile's `notices` stage, standard library only, over three
inputs the other stages leave:

- the JavaScript packages the browser is served, as JSON from
  `frontend/scripts/collect-notices.ts`, which says how they are chosen;
- every distribution installed in the runtime virtualenv, read from its
  `.dist-info` directories, so what is credited is what was installed rather
  than what a lockfile meant to install;
- YAZ's licence text, which `docker/build-yaz.sh` keeps aside for this;
- any `--extra` file, appended whole: `docker/ocr-engine-notices.txt` carries
  what the OCR engine's notice in `frontend/public/licences/` points at and does
  not reproduce, libwebp's patent grant and OpenLibm's per file notices.

`check-venv <site-packages>` runs the Python half's refusal alone, for CI on a
merge request, which needs neither the JavaScript nor YAZ.

**A package with no licence text fails the build**, and nothing is written. A
silent gap is the failure this file exists to close: MIT, BSD and Apache each
ask for their notice to travel with copies, and the image is a copy.

The bound: the base image's own software (CPython, musl, the Alpine packages)
is not credited here. Alpine ships those under its own terms, outside the
application this file describes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from email.parser import HeaderParser
from pathlib import Path

#: A licence or notice file in a distribution's metadata, outside `licenses/`.
#: Wheels built before PEP 639 put `LICENSE` beside `METADATA`. Not `AUTHORS`: it
#: names people and grants nothing, so a distribution carrying only that still fails.
_LICENCE_NAME = re.compile(r"^(un)?(licen[cs]e|copying|copyright|notice)([.-][\w.-]*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Notice:
    """One package's heading and the texts that follow it."""

    name: str
    version: str
    licence: str
    texts: tuple[tuple[str, str], ...]
    #: Where the image serves a notice this repository wrote for the package.
    shipped: str | None = None


def venv_notices(site_packages: Path) -> tuple[list[Notice], list[str]]:
    """Every distribution in `site_packages`, and the ones with no licence text."""
    notices: list[Notice] = []
    missing: list[str] = []
    for info in sorted(site_packages.glob("*.dist-info")):
        metadata = HeaderParser().parsestr((info / "METADATA").read_text(encoding="utf-8"))
        files = sorted(path for path in (info / "licenses").rglob("*") if path.is_file())
        files += sorted(path for path in info.iterdir() if path.is_file() and _LICENCE_NAME.match(path.name))
        expressions = metadata.get_all("License-Expression") or []
        notice = Notice(
            name=metadata["Name"],
            version=metadata["Version"],
            licence=_licence_of(expressions, metadata.get_all("Classifier") or []),
            texts=_texts(info, files),
        )
        if not notice.texts:
            missing.append(f"{notice.name} {notice.version}: no licence file in {info.name}")
        notices.append(notice)
    if not notices:
        missing.append(f"no distribution at all in {site_packages}")
    return notices, missing


def _texts(info: Path, files: list[Path]) -> tuple[tuple[str, str], ...]:
    """Each licence file's path and text, leaving out any that is empty or only whitespace.

    Counted, an empty file would let a distribution with nothing to show pass the
    check that fails the build.
    """
    read = ((path.relative_to(info).as_posix(), _read(path)) for path in files)
    return tuple((name, text) for name, text in read if text.strip())


def _read(path: Path) -> str:
    """A licence file's text; a stray byte is replaced rather than failing the build over it."""
    return path.read_text(encoding="utf-8", errors="replace")


def _licence_of(expressions: list[str], classifiers: list[str]) -> str:
    """The SPDX expression when the metadata carries one, else the licence classifiers.

    The free text `License` field is not read: several packages put the whole
    licence text in it, which is a heading nobody can read.
    """
    if expressions:
        return expressions[0]
    named = [c.split("::")[-1].strip() for c in classifiers if c.startswith("License ::")]
    return " / ".join(named)


def javascript_notices(document: str) -> tuple[list[Notice], list[str]]:
    """The packages the collector wrote, and any it wrote with nothing to show."""
    notices = [
        Notice(
            name=entry["name"],
            version=entry["version"],
            licence=entry["licence"],
            texts=tuple((text["file"], text["text"]) for text in entry["texts"]),
            shipped=entry["shipped"],
        )
        for entry in json.loads(document)
    ]
    missing = [f"{n.name} {n.version}: no licence text" for n in notices if not n.texts and n.shipped is None]
    if not notices:
        missing.append("the JavaScript collector wrote no package at all")
    return notices, missing


_RULE = "=" * 78
_THIN = "-" * 78


def _entry(notice: Notice) -> str:
    heading = f"{notice.name} {notice.version}" + (f" ({notice.licence})" if notice.licence else "")
    parts = [_THIN, heading, _THIN]
    if notice.shipped is not None:
        parts.append(f"Its notice is served beside this file, at {notice.shipped}.\n")
    parts += [f"[{file}]\n\n{text.strip()}\n" for file, text in notice.texts]
    return "\n".join(parts)


def render(javascript: list[Notice], python: list[Notice], yaz: Notice, extras: list[str]) -> str:
    """The notices file: a short preface, one section per runtime, then each extra file whole."""
    sections = [
        ("JavaScript served to the browser", javascript),
        ("Python packages in the server", python),
        ("YAZ, the Z39.50 client library the server links", [yaz]),
    ]
    out = [
        "Third party notices for Endpaper",
        "",
        "This image carries the software below, each part under its own licence,",
        "whose text follows its name.",
        "",
    ]
    for title, notices in sections:
        out += [_RULE, title, _RULE, ""]
        out += [_entry(notice) for notice in notices]
    for extra in extras:
        out += [_RULE, extra.strip(), ""]
    return "\n".join(out).rstrip() + "\n"


def _report(missing: list[str]) -> int:
    """Name every gap on stderr; 1 when there is one."""
    if missing:
        print(f"notices: {len(missing)} package(s) without a licence text", file=sys.stderr)
        for line in missing:
            print(f"  {line}", file=sys.stderr)
    return 1 if missing else 0


def _check_venv(argv: list[str]) -> int:
    """`check-venv <site-packages>`: the Python half's refusal alone, writing nothing.

    CI runs it on a merge request over a runtime virtualenv, so a lockfile bump that
    adds a distribution with no licence text fails there rather than in the image
    build on `main`, after the merge.
    """
    parser = argparse.ArgumentParser(prog="notices.py check-venv")
    parser.add_argument("site_packages", type=Path)
    site_packages = parser.parse_args(argv).site_packages
    if not site_packages.is_dir():
        return _report([f"{site_packages} is not a directory"])
    python, missing = venv_notices(site_packages)
    if not missing:
        print(f"notices: {len(python)} Python packages, each with a licence text")
    return _report(missing)


def main(argv: list[str] | None = None) -> int:
    """Write the notices file, or name every gap on stderr and write nothing."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["check-venv"]:
        return _check_venv(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--javascript", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, required=True)
    parser.add_argument("--yaz", type=Path, required=True)
    parser.add_argument("--yaz-version", required=True)
    parser.add_argument("--extra", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.site_packages.is_dir():
        print(f"notices: {args.site_packages} is not a directory", file=sys.stderr)
        return 1
    javascript, js_missing = javascript_notices(args.javascript.read_text(encoding="utf-8"))
    python, py_missing = venv_notices(args.site_packages)
    yaz_text = args.yaz.read_text(encoding="utf-8") if args.yaz.is_file() else ""
    yaz = Notice("YAZ", args.yaz_version, "", (("LICENSE", yaz_text),) if yaz_text.strip() else ())
    extras = [path.read_text(encoding="utf-8") if path.is_file() else "" for path in args.extra]
    missing = js_missing + py_missing + ([] if yaz.texts else [f"YAZ: no licence text at {args.yaz}"])
    pairs = zip(args.extra, extras, strict=True)
    missing += [f"{path}: missing or empty" for path, text in pairs if not text.strip()]
    if _report(missing):
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(javascript, python, yaz, extras), encoding="utf-8")
    print(f"notices: {len(javascript)} JavaScript and {len(python)} Python packages and YAZ, in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
