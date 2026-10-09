"""`.env.example` is operator documentation, and it goes stale silently.

It documented **three** of thirty variables for four months, because nothing
connected it to the code: `config.py` grew `AUTH_MODE`, then eight `LDAP_*`,
then seven `MAIL_*` and two Telegram keys, and none of those changes had any
reason to touch a sample file.

So this reads `config.py` rather than restating it. A hand written list of
expected names would be the same defect one level up: a rule written as its
instances regenerates the hole the moment the instances change. That is the
lesson `conftest.py` learned when its masking guard went vacuous because it
popped one environment variable by name instead of reading `_ENV_OVERRIDES`.

**Names only.** The prose in the sample is free to change without breaking
this; only a variable appearing or disappearing does.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import config

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / ".env.example"
CONFIG = Path(config.__file__)

#: Read by `config.py` and deliberately absent from the sample, with the reason.
#:
#: Empty today, and that is the point: an entry here is a decision somebody made
#: on purpose, not a name that slipped through.
UNDOCUMENTED: dict[str, str] = {}


def _read_by_config() -> set[str]:
    """Every environment name `config.py` reads, from both places it reads them.

    Two sources, and missing either is how this test would pass while being
    wrong: a direct `os.getenv("X")`, and the `_ENV_OVERRIDES` table that maps a
    settings key to the variable that pins it.
    """
    tree = ast.parse(CONFIG.read_text())
    direct = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"getenv", "get"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.isupper()
        and len(node.args[0].value) > 3
    }
    return direct | set(config._ENV_OVERRIDES.values())


def _documented() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", SAMPLE.read_text(), re.M))


class TestTheSampleDocumentsWhatTheCodeReads:
    def test_every_variable_the_code_reads_is_in_the_sample(self):
        missing = _read_by_config() - _documented() - set(UNDOCUMENTED)
        assert not missing, (
            "These are read by config.py and absent from .env.example, so an "
            f"operator has no way to know they exist: {sorted(missing)}"
        )

    def test_the_sample_documents_nothing_the_code_ignores(self):
        """The other direction, and it is the quieter failure: a variable that
        was renamed leaves a line somebody will set and wonder about."""
        stale = _documented() - _read_by_config()
        assert not stale, (
            "These are in .env.example and read nowhere in config.py: "
            f"{sorted(stale)}"
        )

    def test_the_reader_finds_both_sources(self):
        """A tripwire. If `_read_by_config` ever returns only one of its two
        sources the tests above pass while enforcing half the rule, which is the
        shape of every guard defect this repository has found."""
        found = _read_by_config()
        assert "SECRET_KEY" in found, "the direct os.getenv pass found nothing"
        assert "MAIL_PASSWORD" in found, "the _ENV_OVERRIDES pass found nothing"

    def test_every_secret_carries_a_placeholder_that_states_its_requirement(self):
        """A secret with an empty value reads as optional, and a plausible fake
        is the kind of thing that gets shipped. Both are refused."""
        text = SAMPLE.read_text()
        for name in ("SECRET_KEY", "MAIL_PASSWORD", "TELEGRAM_BOT_TOKEN", "LDAP_BIND_PASSWORD"):
            match = re.search(rf"^{name}=(.*)$", text, re.M)
            assert match, f"{name} is not in the sample"
            value = match.group(1).strip()
            assert value.startswith("replace-with-"), (
                f"{name} should carry a placeholder naming what it needs, "
                f"not {value!r}"
            )
