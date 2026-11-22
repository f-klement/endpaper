"""The curated catalogue registry: its refusals, its age, and what a pick records."""

import dataclasses
from datetime import timedelta
from enum import StrEnum
from typing import Any

import pytest

import metadata
import registry
import settings_store
import targets
from enums import CatalogueSource, Disposition, RegisteredCatalogue, SettingKey

_NLS = registry.ENTRIES[RegisteredCatalogue.NLS]


def _with_target(**changes: Any) -> registry.Entry:
    """The NLS entry with its target changed, so one rule at a time is broken."""
    return dataclasses.replace(_NLS, target=dataclasses.replace(_NLS.target, **changes))


def _with_evidence(**changes: Any) -> registry.Entry:
    return dataclasses.replace(_NLS, evidence=dataclasses.replace(_NLS.evidence, **changes))


class TestTheSnapshot:
    def test_every_entry_resolves_as_the_boot_resolves_it(self):
        # `main.seed_catalogue_targets` fails the boot on an entry that does not.
        for entry in registry.ENTRIES.values():
            metadata.resolve(entry.target)

    def test_the_shipped_snapshot_breaks_none_of_its_rules(self):
        assert registry._refusals() == []

    def test_an_entry_not_probed_answering_is_refused(self):
        silent = _with_evidence(disposition=Disposition.UNREACHABLE)
        assert registry._entry_refusals(RegisteredCatalogue.NLS, silent) == ["not probed answering"]

    @pytest.mark.parametrize(
        ("entry", "refusal"),
        [
            (_with_target(source=RegisteredCatalogue.NLI), "keyed under another member"),
            (_with_evidence(isbn="978-1-4262-2439-3"), "evidence names no normalised ISBN-13"),
            (_with_target(metered=True), "bespoke, metered or credentialled"),
            (_with_target(needs_key=True), "bespoke, metered or credentialled"),
            (_with_target(answers_lookup=False), "answers no lookup, so nothing can test it"),
        ],
    )
    def test_an_entry_breaking_one_rule_is_refused_for_that_rule_alone(self, entry, refusal):
        assert registry._entry_refusals(RegisteredCatalogue.NLS, entry) == [refusal]

    @pytest.mark.parametrize(
        ("seeded", "refusal"),
        [
            # `targets.Target` lets only the DNB waive the claim, so only its row can carry a waiver here.
            (CatalogueSource.DNB, "waives the ISBN identity check"),
            (CatalogueSource.GOOGLE_BOOKS, "bespoke, metered or credentialled"),
        ],
    )
    def test_a_seeded_row_in_an_entry_is_refused_for_what_it_is(self, seeded, refusal):
        entry = dataclasses.replace(_NLS, target=targets.SEEDED[seeded])
        assert refusal in registry._entry_refusals(RegisteredCatalogue.NLS, entry)

    def test_a_member_with_no_entry_is_refused(self, monkeypatch):
        monkeypatch.setattr(registry, "ENTRIES", {RegisteredCatalogue.NLS: _NLS})
        assert [found for found in registry._refusals() if "members and entries differ" in found]

    def test_a_member_spelled_like_a_seeded_source_is_refused(self, monkeypatch):
        monkeypatch.setattr(registry, "CatalogueSource", StrEnum("Clashing", {"NLS": "nls"}))
        assert registry._refusals() == ["spelled like a seeded source: ['nls']"]

    def test_a_snapshot_dated_after_its_newest_probe_is_refused(self, monkeypatch):
        monkeypatch.setattr(registry, "TAKEN_ON", registry.TAKEN_ON + timedelta(days=1))
        assert registry._refusals() == [
            f"TAKEN_ON is {registry.TAKEN_ON}, the newest probe {registry.TAKEN_ON - timedelta(days=1)}"
        ]

    def test_an_entry_probed_after_the_snapshot_is_refused(self, monkeypatch):
        later = _with_evidence(probed_on=registry.TAKEN_ON + timedelta(days=1))
        monkeypatch.setattr(registry, "ENTRIES", {**registry.ENTRIES, RegisteredCatalogue.NLS: later})
        newest = later.evidence.probed_on
        assert registry._refusals() == [f"TAKEN_ON is {registry.TAKEN_ON}, the newest probe {newest}"]


class TestAged:
    def test_fresh_on_the_last_trusted_day(self):
        assert not registry.aged(registry.TAKEN_ON + registry.RECHECK_AFTER)

    def test_aged_the_day_after(self):
        assert registry.aged(registry.TAKEN_ON + registry.RECHECK_AFTER + timedelta(days=1))


class TestPicking:
    def test_nothing_is_picked_on_a_fresh_install(self, db):
        assert registry.picked(db) == frozenset()

    def test_a_pick_is_remembered_and_picking_twice_is_one_pick(self, db):
        registry.pick(db, RegisteredCatalogue.NLS)
        registry.pick(db, RegisteredCatalogue.NLS)
        assert registry.picked(db) == {RegisteredCatalogue.NLS}
        assert settings_store.get_json(db, SettingKey.PICKED_CATALOGUES) == {"picked": ["nls"]}

    def test_a_dropped_pick_is_forgotten_and_the_others_kept(self, db):
        registry.pick(db, RegisteredCatalogue.NLS)
        registry.pick(db, RegisteredCatalogue.CSIC)
        registry.drop(db, RegisteredCatalogue.NLS)
        assert registry.picked(db) == {RegisteredCatalogue.CSIC}

    def test_a_stored_name_this_snapshot_does_not_hold_is_ignored(self, db):
        # A restore from a build whose snapshot held another entry.
        settings_store.set_json(db, SettingKey.PICKED_CATALOGUES, {"picked": ["nlw", "csic"]})
        assert registry.picked(db) == {RegisteredCatalogue.CSIC}

    def test_a_row_that_holds_no_list_reads_as_nothing_picked(self, db):
        settings_store.set_json(db, SettingKey.PICKED_CATALOGUES, {"picked": "csic"})
        assert registry.picked(db) == frozenset()
