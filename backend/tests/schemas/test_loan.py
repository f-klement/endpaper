"""Tests for `backend/schemas/loan.py`."""

import main


class TestTheResponseSchemaMarksEveryServedDefaultRequired:
    """`model_config` is the only thing that keeps these `required`, and nothing downstream notices it go.

    Drop `json_schema_serialization_defaults_required` and the generated client
    regenerates cleanly, the drift tests follow it, and `makeLoan` still type
    checks against an optional `to_patron`: a fixture or a component omitting
    it would render "Loaned to " with nobody after it.

    Read off the schema the app serves rather than off `LoanOut` itself: the
    app builds its own, and `separate_input_output_schemas=False` would make it
    emit the validation mode schema, where every defaulted field is optional
    again, while Pydantic's serialization schema still said required.
    """

    def test_the_patron_flag_the_patron_and_both_day_counts_are_required(self):
        required = set(main.app.openapi()["components"]["schemas"]["LoanOut"]["required"])

        assert {"to_patron", "patron", "days_out", "days_overdue"} <= required
