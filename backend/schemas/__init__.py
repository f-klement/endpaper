"""Request and response contracts.

This was a single `schemas.py` until it outgrew it. Everything is re-exported
here, so `from schemas import BookOut` keeps working exactly as before and no
call site had to change when the file became a package.

The import order at the bottom matters: `BookOut` and `LoanOut` reference each
other, and each declares the other as a string forward reference. Neither can
resolve it alone, so `model_rebuild()` runs here, the one place where both
modules are guaranteed to be loaded. Without it, building either model's schema
raises `PydanticUndefinedAnnotation`, and FastAPI would fail at startup rather
than at request time.
"""

from schemas.book import (
    BookCreate,
    BookDetailsUpdate,
    BookEnrichmentOut,
    BookLookup,
    BookOut,
    BookRatingUpdate,
    BookStatusUpdate,
    BulkOwnershipResult,
    BulkOwnershipUpdate,
    BulkRequest,
    BulkResult,
    DuplicateGroup,
    GoogleBooksMatch,
    LocationOut,
    MergeRequest,
    OwnershipUpdate,
    PrivacyUpdate,
    SeriesOut,
)
from schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from schemas.imports import GoodreadsImportOut
from schemas.loan import LoanCreate, LoanOut
from schemas.note import NoteCreate, NoteOut
from schemas.settings import (
    FeatureFlagsOut,
    LoginImageOut,
    SettingsOut,
    SettingsUpdate,
)
from schemas.stats import MonthStat, PerUserStat, StatsOut, TagStat
from schemas.tag import TagOut
from schemas.user import AuthConfigOut, LoginRequest, Token, UserCreate, UserOut

# Resolve the BookOut <-> LoanOut forward references now that both are imported.
BookOut.model_rebuild()
LoanOut.model_rebuild()

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "AuthConfigOut",
    "BookCreate",
    "BookDetailsUpdate",
    "BookEnrichmentOut",
    "BookLookup",
    "BookOut",
    "BookRatingUpdate",
    "BookStatusUpdate",
    "BulkOwnershipResult",
    "BulkOwnershipUpdate",
    "BulkRequest",
    "BulkResult",
    "DuplicateGroup",
    "GoodreadsImportOut",
    "GoogleBooksMatch",
    "LoanCreate",
    "LocationOut",
    "MergeRequest",
    "SeriesOut",
    "LoginRequest",
    "LoanOut",
    "FeatureFlagsOut",
    "LoginImageOut",
    "SettingsOut",
    "SettingsUpdate",
    "MonthStat",
    "NoteCreate",
    "NoteOut",
    "OwnershipUpdate",
    "Page",
    "PerUserStat",
    "PrivacyUpdate",
    "StatsOut",
    "TagOut",
    "TagStat",
    "Token",
    "UserCreate",
    "UserOut",
]
