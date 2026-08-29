"""The catalogue as a reader with no account sees it.

**This is the first surface in the application reachable without a session**,
and everything unusual about this module follows from that one fact.

Five rules apply here that apply nowhere else, and each is enforced in a
different place on purpose, because a single check that did all five would be a
single check to get wrong:

| Question | Answered by |
|---|---|
| Is anything published at all? | `settings_store.public_catalogue_is_published` |
| Which **rows** may be shown? | `Shelf.seen_by_the_public` |
| Which **columns** may be shown? | `schemas/public.py` |
| How fast may a stranger ask? | `ratelimit.public_catalogue_limiter` |
| May a crawler index it? | `middleware.SecurityHeadersMiddleware` |

**The fifth is in the middleware and not here, and that placement was a
correction.** A header set from a route dependency merges onto the success path
only, and cannot reach the SPA mount at all, so the pages a crawler actually
indexes never carried it. It is unconditional in the middleware now and the
published paths lift it, which fails in the safe direction.

The second and third are separate because the first is not the second: a row
filter is necessary and not sufficient. A Book that is public still carries what
the household paid for it, which room it is in and who added it, and
`seen_by_the_public` filters rows rather than columns. `schemas/public.py` is
the column boundary and states the rule that decided each field.

**Publishing takes two switches, and the conjunction is enforced on the server.**
`public_catalogue_is_published` reads library mode as well as the publish row,
so turning library mode off cannot leave a catalogue public with nothing on
screen saying so. Disabling a control in the browser is advice to one client;
this is the guarantee.

**Not published is 404, not 403**, which is the house rule applied where it
matters most. A 403 would confirm that this deployment has a catalogue it is
withholding, and would do it to anybody who asked.

**Nothing here writes.** There is no POST, PUT, PATCH or DELETE in this module
and there is not meant to be: a public reader has no account to attribute a
write to, and every write path in this app resolves a member first.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

import settings_store
from dependencies import DbSession, Paging, RowId, TagIdList, row_ids
from enums import BookFormat
from models import Book
from ratelimit import client_address, public_catalogue_limiter
from schemas import Page, PublicBookOut, PublicBookSort
from serialisation import books_to_public_out
from shelf import BookFilters, Loading, Shelf, order_for

#: Where a published catalogue lives, as one string.
#:
#: Read by the route decorators and by `robots_txt`, so the `Allow:` line and
#: the paths it allows cannot drift apart. That drift is not hypothetical: a
#: robots file that allows a path nothing serves is merely untidy, and one that
#: forgets a path the catalogue does serve silently keeps it out of the index a
#: library asked to be in.
PUBLIC_PREFIX = "/api/public"

#: Where a reader actually reads the published catalogue, as a client route.
#:
#: **Not `PUBLIC_PREFIX`, and the difference is the whole of `robots.txt`.** A
#: crawler indexes the HTML at `/catalogue` and `/catalogue/<id>`; the JSON under
#: `/api/public/` is what that HTML fetches and is not a page anybody lands on.
#: The first version of this file allowed the JSON prefix and disallowed
#: everything else, so a library that switched indexing on invited a crawler to
#: the one path with nothing readable at it and barred the two with the
#: catalogue on them.
#:
#: `middleware._INDEXABLE_PATHS` is the other half and carries both, because
#: the `X-Robots-Tag` has to reach the HTML as well, and the HTML is served by a
#: `StaticFiles` mount that no route dependency can touch.
PUBLIC_PAGE_PREFIX = "/catalogue"


def public_reader(
    request: Request,
    db: DbSession,
) -> None:
    """Everything a public request has to pass before a handler sees it.

    Two things rather than three, and the ordering is the reason for the pair
    being one dependency: the rate limit runs **first**, so probing the gate is
    bounded too. Two separate dependencies would be two chances to attach one.

    **The `X-Robots-Tag` used to be set here and is not any more.** A header set
    from a dependency merges onto the success path alone, so measured it was on
    the 200 and absent from the gate's 404, the item 404, a 429 and a 500, while
    this module and `docs/security.md` both said every public response carried
    it. Worse, a dependency cannot reach the SPA mount at all, so the HTML a
    crawler actually indexes never had it. It is now unconditional in
    `middleware.SecurityHeadersMiddleware` and lifted for the published paths,
    which is the safe direction and covers both.
    """
    public_catalogue_limiter.check(client_address(request))

    if not settings_store.public_catalogue_is_published(db):
        # 404, never 403. A 403 confirms that this deployment holds a catalogue
        # and is declining to show it, which is exactly what an unpublished
        # catalogue withholds, and it confirms it to anybody at all.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )


#: The catalogue routes, every one of them gated.
#:
#: **The dependency is on the router, not on each handler**, and that is the
#: only arrangement where a route added here cannot be added without the gate.
#: Three handlers each carrying their own `Depends` is three chances to write
#: the fourth without one, on the one surface in this application where that
#: mistake publishes the catalogue.
#: `tests/routers/test_public.py::TestEveryPublicRouteIsGated` asserts it
#: against the live route table rather than against this comment.
catalogue = APIRouter(
    prefix=PUBLIC_PREFIX, tags=["public"], dependencies=[Depends(public_reader)]
)

#: `robots.txt` hangs off the app root and must answer whether or not anything
#: is published, so it is outside the gated router rather than inside it.
router = APIRouter(tags=["public"])


@catalogue.get(
    "/books",
    response_model=Page[PublicBookOut],
    summary="Search the published catalogue",
)
def list_public_books(
    db: DbSession,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=200)] = None,
    tags: TagIdList = None,
    format: Annotated[BookFormat | None, Query()] = None,
    series: Annotated[str | None, Query(max_length=255)] = None,
    sort: Annotated[PublicBookSort, Query()] = PublicBookSort.TITLE_ASC,
) -> Page[PublicBookOut]:
    """One page of the published catalogue.

    **The filters here are a subset of the signed in listing's, and the ones
    left out are left out by construction rather than by omission.** `status`,
    `unrated` and `discuss`, and `ownership` and `lending`, are all facts about
    a member or about the household's relationship to the object. The first
    three would raise on this shelf anyway, because it has no viewer to read
    them against; the last two are columns this payload does not carry, and a
    filter over a column nobody can see is a way to read that column one query
    at a time.

    `collection_id` is **not** accepted, although it was in the first draft on
    the argument that a library wants to link to one shelf. It was cut: the ids
    are consecutive, so the filter is enumerable, and what it enumerates is the
    household's own grouping of its shelves, which `PublicBookOut` withholds. A
    public way to link to one shelf wants a published name to link by.

    **`sort` is `PublicBookSort`, a subset**, for the same reason the filters
    are a subset: `BookSort.NEWEST` orders by `added_at`, which is withheld, and
    a sort over a withheld column hands back the whole ordering of that column
    in one request. See `schemas/public.py`.
    """
    filters = BookFilters(
        q=q,
        tag_ids=row_ids(tags, field="tags"),
        format=format,
        series=series,
    )

    books, total = (
        Shelf.seen_by_the_public(db)
        .matching(filters)
        .page(
            paging.offset,
            paging.limit,
            *order_for(sort.as_book_sort()),
            load=Loading.PUBLISHED,
        )
    )

    return Page[PublicBookOut](
        items=books_to_public_out(books),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@catalogue.get(
    "/books/{book_id}",
    response_model=PublicBookOut,
    summary="One record from the published catalogue",
)
def get_public_book(
    book_id: RowId,
    db: DbSession,
) -> PublicBookOut:
    """One record, or 404.

    **404 for every reason**, and that is the house rule rather than laziness:
    a Book that does not exist, one somebody trashed, and one a member marked
    Private are all the same answer, because a 403 on the third would confirm
    the id exists and let a stranger count through the catalogue to learn how
    many private books this library holds.

    `dependencies.book_for_read` is the signed in counterpart and cannot be
    reused: it depends on `get_current_user`, so it 401s before it ever reaches
    a Book. This is the same shape written against the shelf that has no viewer.
    """
    book = (
        Shelf.seen_by_the_public(db)
        .where(Book.id == book_id)
        .first(load=Loading.PUBLISHED)
    )
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
    return books_to_public_out([book])[0]


@router.get("/robots.txt", include_in_schema=False, response_class=PlainTextResponse)
def robots_txt(db: DbSession) -> PlainTextResponse:
    """What a crawler is told about this deployment.

    Three states, and the middle one is the whole reason this file is generated
    rather than shipped in the build:

    * **Nothing published**: disallow everything. The app is a private
      catalogue and there is no page a crawler should hold.
    * **Published, indexing not allowed**: still disallow everything.
      Publishing a catalogue and inviting a search engine to crawl it are
      different decisions, and the default answer to the second is no. Every
      response carries `X-Robots-Tag: noindex, nofollow` as well, because a
      robots file asks a crawler not to fetch a page and does not stop it
      indexing one it heard about elsewhere.
    * **Published and indexing allowed**: allow the catalogue **pages** and
      nothing else. `PUBLIC_PAGE_PREFIX`, not `PUBLIC_PREFIX`: a crawler indexes
      the HTML, and allowing the JSON while disallowing the two paths the
      catalogue is read at is what the first version of this did.
      Not a bare `Allow: /` either, which would invite a crawler into the signed
      in application, where every path answers 401 and a few thousand requests
      achieve nothing for either side.

    Not in the OpenAPI schema: it is a file a crawler fetches, not an operation
    a client calls, and generating a typed hook for it would be noise.

    Registered on the app **before** the SPA mount, which would otherwise answer
    this from disk if a build ever emitted one. Today none does, so this is the
    only `/robots.txt` there is.
    """
    if not settings_store.public_catalogue_may_be_indexed(db):
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return PlainTextResponse(
        "User-agent: *\n"
        f"Allow: {PUBLIC_PAGE_PREFIX}\n"
        "Disallow: /\n"
    )


router.include_router(catalogue)
