"""`docker/notices.py`, which writes the image's third party notices file.

What it promises is that a package with no licence text fails the build and nothing is
written, so each failure arm checks the output file is absent as well as the exit code.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("notices", _REPO / "docker" / "notices.py")
assert _SPEC is not None
assert _SPEC.loader is not None
notices = importlib.util.module_from_spec(_SPEC)
# Registered before it runs: a dataclass looks its module up in `sys.modules`.
sys.modules["notices"] = notices
_SPEC.loader.exec_module(notices)


def _dist(site: Path, name: str, licence_files: dict[str, str], expression: str = "MIT") -> None:
    info = site / f"{name}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: 1.0\nLicense-Expression: {expression}\n"
    )
    for relative, text in licence_files.items():
        (info / relative).parent.mkdir(parents=True, exist_ok=True)
        (info / relative).write_text(text)


def _javascript(path: Path, entries: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps(entries))
    return path


_REACT: dict[str, object] = {
    "name": "react",
    "version": "19.0.0",
    "licence": "MIT",
    "texts": [{"file": "LICENSE", "text": "MIT react"}],
    "shipped": None,
}


@pytest.fixture
def inputs(tmp_path: Path) -> dict[str, Path]:
    site = tmp_path / "site-packages"
    _dist(site, "fastapi", {"licenses/LICENSE": "MIT fastapi"})
    _dist(site, "six", {"LICENSE": "MIT six"})
    yaz = tmp_path / "yaz-LICENSE"
    yaz.write_text("BSD yaz")
    extra = tmp_path / "extra.txt"
    extra.write_text("libwebp PATENTS")
    return {
        "site": site,
        "yaz": yaz,
        "extra": extra,
        "javascript": _javascript(tmp_path / "javascript.json", [_REACT]),
        "out": tmp_path / "out" / "third-party.txt",
    }


def _run(inputs: dict[str, Path]) -> int:
    return notices.main(
        [
            "--javascript", str(inputs["javascript"]),
            "--site-packages", str(inputs["site"]),
            "--yaz", str(inputs["yaz"]),
            "--yaz-version", "5.38.1",
            "--extra", str(inputs["extra"]),
            "--out", str(inputs["out"]),
        ]
    )  # fmt: skip


def test_every_package_its_licence_text_yaz_and_the_extra_file_reach_the_notices(inputs):
    assert _run(inputs) == 0

    written = inputs["out"].read_text()
    for expected in (
        "react 19.0.0 (MIT)",
        "MIT react",
        "fastapi 1.0 (MIT)",
        "MIT fastapi",
        "six 1.0 (MIT)",
        "MIT six",
        "YAZ 5.38.1",
        "BSD yaz",
        "libwebp PATENTS",
    ):
        assert expected in written


def test_a_python_package_with_no_licence_file_fails_and_writes_nothing(inputs, capsys):
    _dist(inputs["site"], "bare", {})

    assert _run(inputs) == 1
    assert not inputs["out"].exists()
    assert "bare 1.0: no licence file" in capsys.readouterr().err


def test_a_javascript_package_with_no_text_and_no_shipped_notice_fails(inputs):
    _javascript(inputs["javascript"], [_REACT, {**_REACT, "name": "bare", "texts": []}])

    assert _run(inputs) == 1
    assert not inputs["out"].exists()


def test_a_javascript_package_whose_notice_is_shipped_beside_the_file_points_at_it(inputs):
    shipped = {**_REACT, "name": "engine", "texts": [], "shipped": "/licences/tesseract.txt"}
    _javascript(inputs["javascript"], [_REACT, shipped])

    assert _run(inputs) == 0
    assert "served beside this file, at /licences/tesseract.txt" in inputs["out"].read_text()


def test_a_missing_yaz_licence_fails(inputs):
    inputs["yaz"].unlink()

    assert _run(inputs) == 1
    assert not inputs["out"].exists()


def test_an_empty_extra_file_fails(inputs):
    inputs["extra"].write_text("\n")

    assert _run(inputs) == 1
    assert not inputs["out"].exists()


def test_an_empty_virtualenv_fails_rather_than_crediting_nothing(inputs, tmp_path):
    inputs["site"] = tmp_path / "empty"
    inputs["site"].mkdir()

    assert _run(inputs) == 1


def test_the_licence_heading_falls_back_to_the_classifiers():
    assert notices._licence_of([], ["License :: OSI Approved :: BSD License", "Topic :: X"]) == "BSD License"


@pytest.mark.parametrize("body", ["", " \n\t\n"])
def test_an_empty_or_whitespace_only_licence_file_is_no_licence_text(inputs, capsys, body):
    _dist(inputs["site"], "hollow", {"LICENSE": body})

    assert _run(inputs) == 1
    assert not inputs["out"].exists()
    assert "hollow 1.0: no licence file" in capsys.readouterr().err


def test_a_copyright_file_is_licence_text_and_an_authors_file_is_not(inputs, capsys):
    _dist(inputs["site"], "credited", {"COPYRIGHT": "BSD credited"})
    _dist(inputs["site"], "named", {"AUTHORS": "A. Person"})

    assert _run(inputs) == 1
    err = capsys.readouterr().err
    assert "named 1.0: no licence file" in err
    assert "credited" not in err


def test_check_venv_passes_a_virtualenv_whose_every_distribution_has_licence_text(inputs, capsys):
    assert notices.main(["check-venv", str(inputs["site"])]) == 0
    assert "2 Python packages" in capsys.readouterr().out


def test_check_venv_fails_on_a_distribution_with_no_licence_text(inputs, capsys):
    _dist(inputs["site"], "bare", {})

    assert notices.main(["check-venv", str(inputs["site"])]) == 1
    assert "bare 1.0: no licence file" in capsys.readouterr().err
