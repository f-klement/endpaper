"""Tests for `backend/schemas/settings.py`.

One rule so far, and it is the one the wire cannot state for itself: the row the
settings screen is sent has to carry every fact `sources.describe` decided.
"""

import dataclasses

import credentials
import sources
from enums import CatalogueSource
from routers import settings as settings_router
from schemas.settings import CatalogueSourceOut


class TestTheProviderRowCarriesEveryDerivedFact:
    """`routers/settings.py` builds this row from **two** splats, not one.

    **A splat past a pydantic model drops what the model does not declare, in
    silence.** `CatalogueSourceOut` sets no `model_config`, so pydantic v2's
    default `extra='ignore'` applies: a field added to a source of facts and
    forgotten here produces no error, no warning and no log line, and the screen
    simply never learns the fact. It happened in the round that added `slow`, and
    a test asserting on `sources.describe` rather than on the response passed
    throughout, because that test never crossed the boundary the defect was on.

    **There are two sources of facts now**, and asserting against one of them
    would leave the other exactly as unguarded as `slow` was.
    `sources.describe` decides what can be known without a database;
    `routers.settings._credential_view` decides what a stored login looks like,
    which needs one. So the assertion is over the union, and it is still equality
    in both directions: a field removed from either and left on the wire fails
    too, which is a row promising a fact the server has stopped deciding.

    **The second assertion is the one the first splat cannot make.** Two splats
    into one model can collide, and the later wins in silence. Disjointness is
    what says they cannot.
    """

    def test_the_two_field_sets_are_the_same(self, db):
        described = {field.name for field in dataclasses.fields(sources.Described)}
        credential = set(
            settings_router._credential_view(
                db, CatalogueSource.BNE, credentials.key_state()
            )
        )
        assert described | credential == set(CatalogueSourceOut.model_fields)

    def test_and_neither_splat_can_overwrite_the_other(self, db):
        described = {field.name for field in dataclasses.fields(sources.Described)}
        credential = set(
            settings_router._credential_view(
                db, CatalogueSource.BNE, credentials.key_state()
            )
        )
        assert described & credential == set()
