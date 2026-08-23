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

from schemas.author import (
    AuthorMergeOut,
    AuthorMergeRequest,
    AuthorOut,
    AuthorSuggestionOut,
)
from schemas.book import (
    BookCreate,
    BookDetailsUpdate,
    BookDiscussUpdate,
    BookEnrichmentOut,
    BookLookup,
    BookMatch,
    BookOut,
    BookRatingUpdate,
    BookStatusUpdate,
    BulkRequest,
    BulkResult,
    CopyCreate,
    CoverBackfillOut,
    DuplicateGroup,
    LocationOut,
    MergeRequest,
    OwnershipUpdate,
    PrivacyUpdate,
    PurgeResult,
    SeriesOut,
)
from schemas.collection import (
    CollectionAssign,
    CollectionCreate,
    CollectionOut,
    CollectionUpdate,
)
from schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, MAX_ROW_ID, Page
from schemas.imports import ImportPreviewOut, ImportPreviewRow, ImportResultOut
from schemas.loan import LoanCreate, LoanOut
from schemas.note import NoteCreate, NoteOut
from schemas.progress import ProgressCreate, ProgressOut
from schemas.quote import QuoteCreate, QuoteOut, QuoteWithBookOut
from schemas.settings import (
    FeatureFlagsOut,
    LoginImageOut,
    OverdueNotifyResult,
    RestoreResult,
    SettingsOut,
    SettingsUpdate,
)
from schemas.stats import CollectionStat, MonthStat, PerUserStat, StatsOut, TagStat
from schemas.tag import TagCreate, TagOut
from schemas.user import (
    AppearanceOut,
    AppearanceUpdate,
    AuthConfigOut,
    LoginRequest,
    Token,
    UserCreate,
    UserOut,
)

# Resolve the BookOut <-> LoanOut forward references now that both are imported.
BookOut.model_rebuild()
LoanOut.model_rebuild()

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_ROW_ID",
    "AppearanceOut",
    "AppearanceUpdate",
    "AuthConfigOut",
    "AuthorMergeOut",
    "AuthorMergeRequest",
    "AuthorOut",
    "AuthorSuggestionOut",
    "BookCreate",
    "BookDetailsUpdate",
    "BookDiscussUpdate",
    "BookEnrichmentOut",
    "BookLookup",
    "BookOut",
    "BookRatingUpdate",
    "BookStatusUpdate",
    "BulkRequest",
    "BulkResult",
    "CollectionAssign",
    "CollectionCreate",
    "CollectionOut",
    "CollectionStat",
    "CollectionUpdate",
    "CopyCreate",
    "CoverBackfillOut",
    "DuplicateGroup",
    "ImportResultOut",
    "ImportPreviewOut",
    "ImportPreviewRow",
    "BookMatch",
    "LoanCreate",
    "LocationOut",
    "MergeRequest",
    "SeriesOut",
    "LoginRequest",
    "LoanOut",
    "FeatureFlagsOut",
    "LoginImageOut",
    "RestoreResult",
    "SettingsOut",
    "SettingsUpdate",
    "MonthStat",
    "NoteCreate",
    "NoteOut",
    "OverdueNotifyResult",
    "OwnershipUpdate",
    "Page",
    "PerUserStat",
    "PrivacyUpdate",
    "ProgressCreate",
    "ProgressOut",
    "PurgeResult",
    "QuoteCreate",
    "QuoteOut",
    "QuoteWithBookOut",
    "StatsOut",
    "TagCreate",
    "TagOut",
    "TagStat",
    "Token",
    "UserCreate",
    "UserOut",
]
