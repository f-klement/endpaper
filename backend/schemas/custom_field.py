from pydantic import BaseModel, Field, field_validator

from enums import CustomFieldKind
from models import CUSTOM_FIELD_NAME_MAX, CUSTOM_FIELD_VALUE_MAX
from schemas.common import (
    one_line_without_any_control_character,
    one_line_without_invisible_characters,
)


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
        """A name is one line, and a name of nothing is refused.

        The invisible characters go as well as the whitespace, because this is
        a label beside a value and it accepts a paste: a name of only invisible
        characters passes `min_length` and then renders as a row nobody can
        pick out of the list. **Not the value's rule**, which deletes a tab as
        well: a name is read rather than followed, so a tab in one separates
        two words like the space it is.
        """
        cleaned = one_line_without_invisible_characters(value)
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
        """The same rule and the same reason as `CustomFieldCreate.tidy`."""
        cleaned = one_line_without_invisible_characters(value)
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
        r"""One line, with the control characters removed **before** the
        collapse rather than after, which is load bearing here.

        A tab is a control character, so it vanishes rather than becoming a
        space. Collapsing first turned `https://a.example\t/x` into
        `https://a.example /x`, which `urlsplit` accepts as a host of
        `"a.example "` while `new URL()` throws, so the API answered **200 with
        an href no browser can follow**. Measured on the live route before this
        changed. `custom_fields.link_target` refuses whitespace outright as the
        second half of the same fix, because it also sees values this validator
        never touched: `backup.restore` writes through Core.
        """
        return one_line_without_any_control_character(value)
