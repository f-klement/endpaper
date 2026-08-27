from pydantic import BaseModel, Field, field_validator

from enums import CustomFieldKind
from models import CUSTOM_FIELD_NAME_MAX, CUSTOM_FIELD_VALUE_MAX

#: Every code point removed before a value or a name is stored.
#:
#: C0 (0x00 to 0x1F), DEL, and C1 (0x80 to 0x9F). None of them is visible in a
#: text box and all of them survive a paste.
#:
#: **`str.split()` does not do this, which is what the paragraph here used to
#: claim.** It splits on whitespace, and NUL is not whitespace: measured
#: 2026-08-27, `"a\x00b"` survived unchanged through both fields, as did
#: `\x01`, `\x07`, `\x08`, `\x1b` and `\x7f`. A NUL is stored by SQLite,
#: serialised by JSON as `\\u0000`, and invisible everywhere a person could
#: notice it.
_CONTROL_CHARACTERS = dict.fromkeys(
    [*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0)]
)


def _one_line(value: str) -> str:
    """Whatever somebody pasted in, as the one line this is.

    Both of these are fields on a single line beside a label, and both accept a
    paste. Two things arrive that way and neither is visible in a text box.

    **Control characters are removed**, not collapsed: see
    `_CONTROL_CHARACTERS`, which also records why the sentence that used to be
    here was wrong.

    **A run of whitespace becomes one space**, for the reason `TagCreate.tidy`
    collapses it: a name of nothing but spaces passes `min_length` and then
    renders as an invisible row nobody can select or find again.

    **A tab is a control character here and therefore vanishes rather than
    becoming a space**, and that ordering is load bearing for a URL. Collapsing
    first turned `https://a.example\t/x` into `https://a.example /x`, which
    `urlsplit` accepts as a host of `"a.example "` while `new URL()` throws, so
    the API answered **200 with an href no browser can follow**. Measured on
    the live route before this changed. `custom_fields.link_target` refuses
    whitespace outright as the second half of the same fix, because it also
    sees values this function never touched: `backup.restore` writes through
    Core.
    """
    return " ".join(value.translate(_CONTROL_CHARACTERS).split())


class CustomFieldOut(BaseModel):
    """A field this Library has defined."""

    id: int
    name: str
    kind: CustomFieldKind
    model_config = {"from_attributes": True}


class CustomFieldCreate(BaseModel):
    """A field the Library is defining.

    The kind is chosen here and never afterwards. Changing it would reinterpret
    every value already under it: a TEXT field turned URL would start linking
    strings nobody wrote as links, and the other direction would silently
    unmake links people are using. Delete and redefine is the honest version of
    that, and it says out loud that the values go.
    """

    name: str = Field(min_length=1, max_length=CUSTOM_FIELD_NAME_MAX)
    kind: CustomFieldKind = CustomFieldKind.TEXT

    @field_validator("name")
    @classmethod
    def tidy(cls, value: str) -> str:
        cleaned = _one_line(value)
        if not cleaned:
            raise ValueError("A custom field needs a name.")
        return cleaned


class CustomFieldRename(BaseModel):
    """A new name for a field. The kind is deliberately absent: see
    `CustomFieldCreate`."""

    name: str = Field(min_length=1, max_length=CUSTOM_FIELD_NAME_MAX)

    @field_validator("name")
    @classmethod
    def tidy(cls, value: str) -> str:
        cleaned = _one_line(value)
        if not cleaned:
            raise ValueError("A custom field needs a name.")
        return cleaned


class CustomFieldValueOut(BaseModel):
    """One field a Book has something in.

    `href` is set only where the value is a link the browser may be pointed at,
    and it is decided on **this read** rather than trusted from storage:
    `custom_fields.link_target` owns why. A client renders `value` as text
    whenever `href` is null, so a value that was stored before a definition
    changed, or through a restore, degrades to text rather than to a link
    nobody checked.
    """

    field_id: int
    name: str
    kind: CustomFieldKind
    value: str
    href: str | None = None


class CustomFieldValueUpdate(BaseModel):
    """What one Book holds in one field.

    **An empty string clears it**, which is the whole of the delete half of the
    API: emptying the box and saving is what a person does, and a separate
    DELETE route would leave a client to decide which of the two verbs an empty
    box means. `custom_fields.write` deletes the row rather than storing an
    empty one, so a cleared field is absent rather than blank.

    `min_length` is therefore deliberately unset while `max_length` is not.
    """

    value: str = Field(max_length=CUSTOM_FIELD_VALUE_MAX)

    @field_validator("value")
    @classmethod
    def tidy(cls, value: str) -> str:
        return _one_line(value)
