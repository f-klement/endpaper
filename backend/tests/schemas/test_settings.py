"""Tests for `backend/schemas/settings.py`.

One rule so far, and it is the one the wire cannot state for itself: the row the
settings screen is sent has to carry every fact `sources.describe` decided.
"""

import dataclasses

import sources
from schemas.settings import CatalogueSourceOut


class TestTheProviderRowCarriesEveryDerivedFact:
    """`routers/settings.py` builds this with `CatalogueSourceOut(**vars(described))`.

    **A splat past a pydantic model drops what the model does not declare, in
    silence.** `CatalogueSourceOut` sets no `model_config`, so pydantic v2's
    default `extra='ignore'` applies: a field added to `sources.Described` and
    forgotten here produces no error, no warning and no log line, and the screen
    simply never learns the fact. It happened in the round that added `slow`, and
    a test asserting on `sources.describe` rather than on the response passed
    throughout, because that test never crossed the boundary the defect was on.

    Equality in both directions rather than a subset, so a field removed from the
    dataclass and left on the wire fails too. That is the same class one step on:
    a row promising a fact the server has stopped deciding.
    """

    def test_the_two_field_sets_are_the_same(self):
        assert {
            field.name for field in dataclasses.fields(sources.Described)
        } == set(CatalogueSourceOut.model_fields)
