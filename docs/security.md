# Security

What is enforced, where, and why. Read [data-model.md](data-model.md) first for the
privacy rule this builds on.

## Authorization

Access to a book is decided in **one place**: `backend/dependencies.py`. Endpoints ask for
a book through a dependency rather than fetching one and writing their own checks.

| Dependency | Grants | Used by |
|---|---|---|
| `book_for_read` | The book is public, or the caller added it | reading a book, reading and adding notes and quotes, setting your own status |
| `book_for_write` | As above; public books are a shared shelf any member may curate | deleting, tagging, covers, metadata refresh |
| `book_for_owner` | As above, and the caller added it (or is an admin) | changing privacy |

Because "visible" already means *public or mine*, a private book that survives the read
check necessarily belongs to the caller. That is why the write rule needs no separate
private-book branch.

**This was previously broken.** Before the resolvers existed, only `get_book` and
`set_privacy` checked anything at all. Every signed-in member could delete, retag,
re-cover or metadata-refresh **any** book, including another member's private one, and
could read the notes on it by guessing its id. `backend/tests/test_dependencies.py` is the
regression suite for exactly that.

### Absent and forbidden look the same

A book the caller may not see reports **404, not 403**. A 403 would confirm that a book
with that id exists, which is precisely what privacy is meant to withhold. `403` is
reserved for cases where the thing is known to exist but the *decision* is not the
caller's: changing the privacy of a public book someone else added.

### Where the rule is applied

`visible_to()` is a query predicate, not a row-level policy, so **every query that returns
or counts books has to apply it**. That includes the statistics aggregations and the loans
list, which would otherwise disclose the title of a book the caller cannot see along with
who currently has it.

It is applied in exactly one module. `backend/shelf.py` is the only place that imports the
predicate and the only place that builds a query **naming** `Book`, so a new endpoint gets
the rule by asking for a shelf rather than by remembering a filter. "Naming" is the load
bearing word: `backup.py` reads every row of `books` through a loop variable, which no rule
of this shape can see, and it is covered below rather than by that sentence. Two named functions read
past a viewer and neither is a general escape: `whole_table_for_uniqueness()`, because the
ISBN and copy-group constraints span the table and a filtered check would miss the row
that collides, and `rereading_filtered_rows()`, which takes ids a caller already filtered.

Two modules are deliberately outside it. `notifications.py`: the overdue **digest** runs on
a schedule for the library and has no viewer, so it partitions on privacy (`is_(False)` for
the reminders it sends, `is_(True)` for a count of what privacy held back) rather than
filtering by it. `backup.py`: it reads every row of every table so that a restore cannot
produce a library missing rows, which is why it is admin only.

**The exemption covers the digest and nothing else in that module.** The in app channel
added for #86 has a viewer, so it does not inherit it: `notifications.overdue_for_viewer`
is rooted at `Shelf.seen_by(db, viewer.id)` and every clause it adds is about the loan
rather than the book. The overdue page added for #102 reads the same function rather than
a second query, which is what keeps the audience decided in one place as surfaces are
added to it. That is what lets it be the one channel that carries a member's own
private books, and it is `visible_to()`'s existing rule rather than an exception to it.

`backend/tests/test_shelf.py::TestTheShelfIsTheOnlyWayIn` enforces all of that and names
both rather than letting either pass quietly. `backup.py` needs naming most, because it
builds its query from a loop variable and no rule reading the arguments to `query()` can
see it at all.

A fourth pass covers the tables that hang off a book and carry no user of their own:
`classifications`, `custom_field_values` and `book_tags`. Their privacy is entirely the
book's, and an index over one of them ("every DDC number in the library, with a count")
publishes a name and a count over every member's private books while naming no `Book`
anywhere, so the three passes above cannot see it.

The pass reports **every** statement that reads one of those tables and decides nothing
about whether the query is scoped. `Shelf.select()` anchors the FROM at the filtered books
and has never claimed to supply the join condition, so an index written through it with no
join is a cartesian product: measured against a two-book database, it hands one member the
classification of another member's private book. Five successive versions of the rule tried
to recognise a correct join and each was shown to leak by the next review round, while the
list of statements a person had checked stayed put. So the judgement is a person's, recorded
once in an allowlist of ten statements across four modules with a reason beside each. Two of
those ten are correct indexes reported anyway, which is the cost of not guessing.

Which tables are children of `books` is derived from the foreign keys. Which of those
children have a viewer of their own is pinned by hand, because a foreign key to `users` is
not the answer: three tables here carry a `created_by_user_id` no query consults. A new child
fails a test until somebody classifies it, so it cannot default to unguarded. Every read is
counted, including the two written through the Shelf, so one more statement is a decision
rather than an edit.

### A reading record is private in a second, separate way

A book being visible says nothing about whose reading of it the caller may see. Two members
reading the same public copy is the ordinary case here, and the status, the rating and both
dates in `user_books` are one person's. That is a different rule from the visibility
predicate, not a consequence of it, so it has its own owner: `backend/reading.py`.

Every query there filters on `user_id`, applied by construction. A `Reading` is built from
a member id (`Reading.by(db, member_id)`) and no method on it takes a different one, so
there is no call site that can forget the filter. Two module functions read across members
and both say why in their own docstring: `discussers()`, because `wants_to_discuss` is the
one column on that table meant to be read by other people, and `resolve_merge()`, because a
book merge has to carry everybody's reading history onto the survivor or the rows are
cascade deleted with the losing book.

`backend/tests/test_reading.py::TestReadingIsTheOnlyWayIn` holds it the same way: only
`reading.py`, `shelf.py`, `backup.py` and `models.py` may import `UserBook`, and the two
ways past a member are counted by call site rather than by module, so a second call in a
module already on the list cannot appear quietly. That import check is a proxy for a query
over the table and its blind spots are listed in the file's docstring, the sharpest being
that a lazy read of the `book.user_books` relationship is invisible to it.

### A custom field value carries no privacy rule of its own, by construction

A value hangs off a book, so who may read it is decided entirely by who may read that book.
There is deliberately no second predicate, and no third table's worth of rule to forget.

What makes that structural rather than remembered is one signature choice: **every reader and
writer in `backend/custom_fields.py` takes `Book` objects, never book ids.** A `Book` can only
have been fetched, `shelf.py` owns every many-book query and `dependencies.py` owns the
single-book one, so a caller holding one has already passed `visible_to()`. A caller holding
an id off a URL has not, and the module gives it nothing it can do with one: mypy refuses
`int` where `Book` is declared, at the call site, before anything runs.

`Values.of(db, books)` therefore cannot be handed somebody else's private book, because
getting one is the thing that is impossible. A `values_of(db, book_ids)` beside it would
compile, run and answer with the values on every id passed.

`CustomField` carries no `values` relationship, so a definition cannot be walked to every
book's value for it, and the endpoint that lists definitions publishes **no usage count**:
a count is drawn across books the caller may not see, so it would have to be scoped to the
viewer, and a viewer-scoped number in a delete confirmation would understate what is about to
be destroyed. The confirmation says "every book" instead.

`backend/tests/test_custom_fields.py::TestOnlyABookReachesAValue` holds it in three passes. An
**import** pass, so no module but `custom_fields.py`, `models.py` and `backup.py` may hold
`CustomFieldValue`. A **touch** pass over the module's own AST, reporting any public function
whose body names the table and that takes no `Book`. And a **name** pass, so a parameter that
mentions a book is annotated with `Book`.

The touch pass is written that way because the version it replaced was not enforcement: it
enumerated the two functions that existed by hand, so adding `values_of(db, book_ids)` passed
it, and the module docstring named that exact function as the thing being prevented.

Two names are exempt and they are two different rules rather than one hatch. `remove` deletes
every value under one definition across the whole library, which is what deleting a field
means and cannot be scoped to a viewer, and is admin only for that reason. `resolve_merge`
rewrites rows for books nobody is holding, or a merge silently destroys them. Their call sites
are counted, so a third cannot appear inside a module already on the list.

The blind spots are listed in that file's docstring, the sharpest being that a lazy read of
`book.custom_field_values` is invisible to all three, which is the safe case because the book
it hangs off has already been through the Shelf.

### A custom field that holds a link is re-checked on every read

`<a href>` is one of the two places a browser turns a string into code, and a custom field
value is member supplied. Two mechanisms guard it, and the second is the one that matters.

**The kind is declared, never detected.** Only a field the library defined as `url` can
produce a link, so a member typing prose that begins with `http` into a text field gets text.

**The declaration is not the permission.** `custom_fields.link_target` re-reads the stored
value on every serialisation and returns a target only for `http` or `https` with a real host,
no credentials, and a port `urlsplit` can parse. **Seven** things a person can type are
refused, counted against that function:

1. whitespace or a backslash anywhere in the value
2. a value `urlsplit` cannot parse at all, which raises rather than returning
3. any scheme that is not `http` or `https`: `javascript:`, `data:`, `vbscript:`, and a
   scheme relative `//host`, which parses to no scheme at all
4. a username or password, which reads as the first host and navigates to the second
5. port zero, which is a link no browser will follow
6. a percent escape in the **host**
7. no host, or one with an empty label

So a row that reached the table without passing the write check is served as text, and there
is such a path: `backup.restore` inserts through Core, where neither a Pydantic model nor an
ORM validator fires. That is the same trap `Book.cover_url` records, answered at the read end
rather than by asking one more writer to remember.

### A link can name one host and go to another, and that is the sharpest thing here

The library is shared, so a member can store a link another member clicks. Python's `urlsplit`
and a browser's WHATWG parser read a **different host** out of some of the same strings, and
every such string is a phishing link that reads as somewhere this household trusts.

Three separators, measured 2026-08-27 against `new URL(...).host`. WHATWG maps U+3002
IDEOGRAPHIC FULL STOP, U+FF0E FULLWIDTH FULL STOP and U+FF61 HALFWIDTH IDEOGRAPHIC FULL STOP
onto `.` before splitting labels; Python does not. `https://calibre.example。evil.example/x`
is one host label here and a registrable domain of `evil.example` there.

These are **rewritten, not refused**. The value stored becomes
`https://calibre.example.evil.example/x`, so the link resolves where the browser was always
going to send it **and says so**, which is strictly better than a 422 that hides the trick
from the member who typed it.

**Percent escapes in the host are refused instead**, and refusing them is what makes the
mapping above worth anything. WHATWG percent-decodes the host *before* it runs IDNA, so `%2e`
is the same divergence one step earlier and the separator table never sees it. Measured, all
three resolving to `evil.example`:

    calibre.example%2eevil.example        -> calibre.example.evil.example
    calibre.example%2Eevil.example        -> calibre.example.evil.example
    calibre.example%ef%bc%8eevil.example  -> calibre.example.evil.example

It cannot be repaired the way a literal separator can, because decoding is recursive
(`%252e`) and encodes more than separators: `%00` and `%2f` in a host both stored as links a
browser then throws on. The path and the query are untouched, so `/book/12%20a` is a link.

**Whitespace and a backslash are refused for the same reason and cannot be rewritten at all.**
A browser ends the authority at a backslash and Python does not, so
`http://good.example\.evil.example/x` is one host here and `good.example` with a path of
`/.evil.example/x` there. `new URL()` throws outright on whitespace, so an href built from it
is a link nothing can follow. `schemas/custom_field.py` removes control characters before the
seam sees them, which is why a **tab** in a host is stored clean rather than refused; a
literal space survives that tidy and is refused here.

**The rewrite is what creates the sharpest case, and the read end is where it is closed.** The
anchor's text is the stored `value` and its destination is `href`, so serving a rewritten
target beside an unrewritten value names one registrable domain and resolves another: exactly
the deception, produced by the repair. `custom_fields.values_on` therefore serves `href` **only
when it equals `value`**, so a row this app wrote keeps its link and a row it did not write is
served as text. That is free rather than a trade, because `link_target` is idempotent: measured
over twelve accepted inputs, including a case folded scheme and a dropped empty query,
`link_target(link_target(x)) == link_target(x)` every time.

`frontend/src/lib/safeHref.ts` repeats both tests before handing a string to an `<a>`: the
value and the href must be one string, and the authority must carry none of the four
characters. Not belt and braces for its own sake. React 19 renders `href="javascript:..."` with
no warning and no error, so a component that interpolates a server value straight into `href`
is trusting the server for something the framework will not check, and this module exists for
the row the server never wrote.

**Its authority test reads the raw string, and getting that substring right is where two holes
have been**, both a step earlier than the pattern looked. WHATWG strips leading C0-or-space and
removes every tab and newline **before** parsing, so `^` is not the start of the URL; and after
a special scheme it consumes any run of `/` or `\`, so `https:/host`, `https:///host` and
`https:\\host` all have an authority. Measured against `new URL(...).host` rather than reasoned
from the spec, over seventeen refusals and eight acceptances. C0-or-space rather than `trim()`,
which leaves `\u0001`, `\u0007` and `\u001f` where a browser strips them.

It tests those characters rather than comparing `parsed.href` to its input, because the two
parsers normalise legitimately different things and a stored `https://a.example` compares
unequal to the browser's `https://a.example/`, which would break a working link on the first
trailing slash.

**One divergence is named and deliberately not closed.** UTS-46 **deletes** ignored code
points, so a host carrying a soft hyphen, a zero width space or a byte order mark stores as
typed and resolves without them. Deletion can only shorten a host, so it cannot reach a domain
the text does not already name, and the characters are invisible in the link text as well as
absent from the destination. That is the whole difference from `%2e` and U+3002, which
**lengthen** the host and put a different registrable domain behind the same text.

**A third piece of the declaration is guarded in the schema rather than at the read end.**
`custom_fields.kind` is a plain VARCHAR holding an enum, and `CustomFieldOut.kind` is typed,
so one row carrying anything else makes Pydantic raise while serialising the library wide
definitions route: one restored row, and every member's settings page answers 500 for good.
`ck_custom_fields_kind` refuses the insert, which is the only place it can be refused, since
`backup.restore` writes through Core. `custom_fields._kind_of` degrades an unrecognised kind
to text at the per book read end, for a database restored from an archive older than the
constraint, and it degrades in the safe direction: a text field never links whatever it holds.

`covers.is_renderable` is deliberately not reused. It exists to keep an `<img src>` inside
`COVER_HOSTS`, because a cover is fetched by the page; a custom field is a link a reader
chooses to follow, to a system this app has never heard of, so a host allowlist would refuse
the one URL the feature was built for. What is shared is one hard-won line: `urlsplit(...).port`
**raises** on a port past 65535, so a single stored `https://host:99999/x` would be a poisoned
row that 500s every read of that book, for good.

`http` is allowed as well as `https`, unlike a cover: a link is a navigation rather than a
subresource, so no browser blocks it as mixed content, and the calibre-web instance this
exists for is on a LAN with no certificate. **This is an outbound link and not a fetch**: the
server never requests the URL, so it is not an SSRF surface, and nothing about it reaches the
CSP.

### Deleting a custom field is admin only

The same split `delete_tag` makes, and the sharper case of it. Defining a field is additive,
changes no book and is open to any member, exactly as inventing a tag is. Deleting one
destroys, in one request with no undo, content every member typed by hand, on books the caller
cannot necessarily see, and a `CustomField` records nobody as its author.

## Authentication

Stateless JWT, HS256, seven-day expiry. There is no refresh token and no server-side
session, so **there is nothing to revoke**: a token stays valid until it expires. Changing
`SECRET_KEY` invalidates every outstanding token at once and is the only revocation
mechanism available.

### The app refuses to boot with a guessable key

`config.validate_secret_key()` runs before anything else in `init_db()`. Outside
`APP_ENV=dev`, a `SECRET_KEY` that is one of the shipped placeholders, or shorter than 32
bytes, is a **startup failure**. Booting with the example key means every session token is
forgeable by anyone who has read the repository, and the alternative to failing loudly is
an app that looks healthy while being trivially impersonable.

### Login does not enforce the registration password policy

`UserCreate` requires 8 characters; `LoginRequest` does not. Two reasons, both real:
accounts created before the policy existed have shorter passwords and would be locked out
of their own library, and a 422 "too short" is a *different* response from a 401 "wrong",
which tells an attacker something about the stored password.

Login also reports the same message for an unknown username as for a wrong password.
Differing responses let an attacker enumerate accounts.

### An empty password is refused everywhere it could mean "anonymous"

An LDAP bind with a DN and an **empty** password is not a failed login. Most directories
accept it as an *unauthenticated bind*, which succeeds and returns nothing useful, so the
caller sees "connected" while every subsequent check silently misbehaves. It is guarded at
three layers, deliberately redundant:

1. `has_password()` treats empty **and whitespace-only** as absent.
2. `_connect()` refuses to bind as a named user without one, with a message naming the
   variable to set.
3. `validate_auth_config()` **fails at startup** if `LDAP_BIND_DN` is set without
   `LDAP_BIND_PASSWORD`, so this is a deployment error rather than a runtime surprise.

The same rule applies to local accounts: a password field that is empty or blank never
reaches the hasher.

### Directory filters are escaped

Usernames are inserted into LDAP filters through `escape_filter_chars`. An unescaped `*` or
`)` in a username is the LDAP equivalent of SQL injection.

### Proxy auth trusts headers, and is safe only behind a proxy that sets them

`AUTH_MODE=proxy` takes the identity from request headers. That is safe **only** if the
proxy sets those headers itself and strips any arriving from the client; otherwise anyone
can name themselves admin. The module says so in a docstring that is deliberately hard to
miss, and the mode is not the default.

### An admin can be signed in as a test account, and as nothing else

`POST /auth/switch` exchanges a password the admin supplies for a token on another
account. It is a login performed on that account's behalf, not impersonation, and two
things keep it that way.

**The target must be an admin-created test account** (`users.is_test_account`, which
implies a local `auth_source` and a stored hash). `models.is_switch_target` is that rule,
in one function, and a **directory-backed account is never a target, in any mode**. An
admin able to mint a session for an LDAP or proxy member could read that member's private
books, and per-book privacy is the single promise the data model makes. A local account
from before a deployment moved to a directory is excluded by the same rule: it belongs to
a real person, and under `ldap` or `proxy` its old password is not an authentication path
any more.

**The password is required and checked** with the ordinary `verify_password`. The admin
knows it because the admin set it. Removing that check is what would turn this into
impersonation.

Everything else follows from those two. A name that is not a test account is a 404 and a
wrong password is a 401, which does not help anyone enumerate accounts, because the caller
is an admin who can already list them all. The switch is logged at WARNING naming both
accounts. The token is an ordinary session token with the scoped cover cookie beside it,
so nothing downstream has to know how the session began.

Getting back: under `local` and `ldap` the admin's own token was replaced, so they sign in
again, and the UI says so before the switch rather than after. Under `proxy` nothing was
replaced, so discarding the token is enough.

### Under proxy auth, a token overrides the header only for a switch

`AUTH_MODE=proxy` ignored tokens entirely until test accounts existed. It cannot now: a
switched session has to win over the header until it is dropped.

The acceptance is deliberately narrow. `auth._switch_session` takes a token only when the
account it names is **still** a switch target, so it is not a claim inside the token that
somebody has to remember to set, and it stops mattering the moment the flag comes off the
row. Accepting any valid token would also revive tokens minted before a deployment moved
to proxy auth, and those name real members with real libraries.

A token that is expired, forged or no longer a switch target falls back to the header
rather than failing. The header is the identity the deployment has already authenticated,
so falling back is never a gain in privilege, and failing closed would strand whoever
holds a stale token behind an error page with no control on screen to clear it.

The cover route applies the same rule to the cover cookie, and only there: an `<img>` sends
no Authorization header, so without it a switched session shows the test account's library
with a hole where every cover only it can see should be. `POST /auth/logout` deletes that
cookie, which is what the "return to my account" control calls.

**A switched session survives the tab being closed.** The token lasts seven days and the
cookie a day, both in the browser, so under proxy the next person at that machine is served
the test account rather than themselves until somebody uses "Return to my account": books
they add are attributed to the test account, and they see its private books. Ending a
switch is a deliberate act, and on a shared machine it is the one that matters.

**And there is no way to end one from the server.** Nothing clears `is_test_account`, so
"the acceptance narrows the moment the flag comes off the row" describes a hand-edited row,
not an operator control. The only revocations that exist are that edit and a `SECRET_KEY`
rotation, which ends every session in the deployment.

### A directory identity never adopts a test account

`upsert_directory_user` matches on **username**. A directory identity named like a test
account would otherwise inherit its row, its books, its loans and its notes, and the test
account would silently stop being a valid switch target. It is renamed aside instead, at
WARNING and naming both names. See [decisions.md](decisions.md) for why renaming rather
than refusing the sign-in.

### A member's address is served only where it is named

`users.email` is deliberately not a field on `UserOut`, which is served inside every book
payload and by the member list: a field there would disclose an address to every member who
can see a book. It is served by `GET /api/users/me/email` (the caller's own, no member id
in the route so there is nothing to authorize) and by the two admin routes, and nowhere
else, four routes in all. `tests/test_house_rules.py::TestAnAddressIsServedOnlyWhereItIsNamed`
walks every Pydantic model this app builds and fails if **any** other one puts an address in
front of a caller, because the rule is worth more than an intention.

It asks pydantic for each model's **wire** names rather than reading Python field names, and
takes a fixed point over field annotations. Its first version did neither, and a reviewer got
two evasions past it: `mailbox: str = Field(serialization_alias="email")` on `UserOut`, which
`from_attributes` fills from `User.email` and FastAPI serialises `by_alias=True`, so every
book payload would have carried it; and a model with a `MemberEmailOut` field, which carries
the whole address model and has no address field of its own. Both are caught, along with four
more spellings of the same two families.

A value arriving from a directory or an upstream header is checked with
`mailer.looks_like_address` before it is stored, which is the same rule the household
recipient list passes. It refuses whitespace anywhere, a **trailing** newline included,
every control and non printing character, and the comma and semicolon that turn one `To`
header into two. The trailing newline is named because it is the one spelling the rule used
to accept: it was anchored with `$` under `match`, and `$` matches before a final newline,
so for a while three docstrings and this paragraph claimed a property the function did not
have. Nothing exploited it, because four independent `.strip()` calls stood in front of it,
and a control that holds only because of its callers is not a control. It is `fullmatch`
plus a Unicode category test now, and `tests/test_mailer.py` pins the newline and the NUL.

It is bounded at `mailer.MAX_ADDRESS` first, because SQLite does not enforce a column
width: the 2026-08-18 incident was a 4000 character `Remote-User` writing a 4000 character
account.

Where a directory owns the address the app refuses a write with **409** rather than
accepting one the next sign in would revert. The log line records that an address was set
or cleared and never the address itself, for the reason `mailer._deliver` logs a count of
refused recipients rather than a list.

### The Google Books API key is never returned

`GET /api/settings` returns a masked preview plus a boolean, never the key. The masking is
**presentation, not storage**. Masking the stored value instead would break every lookup
while still looking correct in the settings screen, which is why a test pins the stored
value directly. The 400 raised when the key is missing does not echo it either.

### The overdue digest is the one path that *pushes* catalogue content out unauthenticated

The overdue digest goes out on a timer with no member behind it and no session on the
receiving end, on any of three channels: a webhook, mail over SMTP, and a Telegram chat.
Two things bound all three.

**It is no longer the only unauthenticated path, and the distinction is push against
pull.** The published catalogue below answers a request from a stranger; this one hands
book titles to a destination nobody asked. Both exclude private books, in the query rather
than by a filter afterwards, and that is the property they share.

A **fourth** sender exists and is outside this section entirely, which is the point of it:
the in app notice is read by a member holding a session, so it sends nothing out and has a
viewer. `notifications.pushes_outward` is where the difference is decided. Two endpoints
serve it, `GET /api/loans/overdue/mine` for the count and `GET /api/loans/overdue` for the
loans, and both are `notifications.overdue_for_viewer` so the two cannot disagree about
who may see what.

**Private books are excluded, on every channel that pushes**, in the query rather than by a
filter afterwards. Each of the three lands where everyone here reads, so a private title on
one is readable by everyone in it, which is exactly what `is_private` exists to prevent.
The digest reports `skipped_private` as a count and never names one, per channel as well as
once at the top. The owner is still chased in the app, where the overdue view is per member
and already scoped.

**A per borrower mail is the one audience that could carry a private book**, because being
reminded of a book you borrowed is not a disclosure. **It is still not built, and the fact it
was blocked on has changed.** `models.User` now carries an `email` column and the LDAP
backend requests an attribute where one is configured, so an address can exist. Nothing in
the reminder path reads it: `send_mail` takes its recipients from `mailer.checked_config`,
which reads `overdue_mail_to` and nothing else. Mail therefore still goes to the household's
own mailbox, which is a channel like the other two, and a member who has filled the field in
is in exactly the position of one who has not.

**Nothing else is in the payload.** One entry per loan: the book's title, the borrower's
username or free-text name, the due date and the days overdue. No ISBNs, no notes, no
member ids beyond the borrower's name, no private books at any privacy setting. The mail
**subject** carries a count and no title, because a subject line is stored unencrypted by
every hop and shows in a notification on a locked phone.

The webhook body is signed with HMAC-SHA256 in `X-Endpaper-Signature: sha256=<hex>` when a
secret is set, over the raw bytes that go on the wire. That authenticates the sender to the
receiver; it is not confidentiality, and an `http://` destination sends book titles in
clear. **Redirects are not followed**, unlike the metadata lookups, because a 302 from the
configured host would send the library's book titles somewhere nobody approved.

### The public catalogue

**The first surface in this application reachable without a session**, off by default,
and the only place five separate rules apply at once. They are enforced in five places on
purpose, because a single check doing all five would be a single check to get wrong.

| Question | Answered by |
|---|---|
| Is anything published at all? | `settings_store.public_catalogue_is_published` |
| Which **rows** may be shown? | `Shelf.seen_by_the_public` |
| Which **columns** may be shown? | `backend/schemas/public.py` |
| How fast may a stranger ask? | `ratelimit.public_catalogue_limiter` |
| May a crawler index it? | `middleware.SecurityHeadersMiddleware` |

**Two switches, nested, and the conjunction is enforced on the server.** Library mode
changes what a cataloguer sees and publishes nothing. The publish switch is separate and
means only "an unauthenticated reader may search". `public_catalogue_is_published` reads
both rows, so a publish row left on while library mode is off serves nothing: flipping
library mode back off cannot leave a catalogue public. Disabling a control in a browser is
advice to one client; this is the guarantee. Both are runtime settings rather than
environment variables, because an environment variable takes a redeploy to correct and
that is the wrong property for the switch most likely to be turned on by mistake.

**`Shelf.seen_by_the_public(db)` has no ownership arm at all**, and that absence is the
whole design rather than an implementation detail. `visible_to(viewer_id)` is
`deleted_at IS NULL AND (is_private IS false OR added_by_user_id = :viewer)`, and a public
reader has no id for the second disjunct. A sentinel id was refused: `added_by_user_id = 0`
is a real comparison against a real column and is safe only while no account holds that id,
which nothing enforces, and the leak would be silent and answer 200. The public constructor
is that predicate with the disjunct **removed**, so no value any input can take makes a
private book match, and an authenticated request wrongly routed through it sees *less*
rather than more. `tests/test_shelf.py::TestThePublicShelfHasNoOwnershipArm` pins it two
ways: an AST pass over everything the constructor can call, and an assertion on the
compiled SQL. Neither alone is enough, and both assert the two surviving clauses are still
there, because "the owner column is absent" is also true of a query with no predicate at
all.

**A row filter is necessary and not sufficient.** A public book still carries what the
household paid for it, which room it is in, who added it, whether they will lend it and
whether anybody has read it. So the public payload is a **separate model** rather than
`BookOut` with an exclusion list, and the difference is which way the default falls: an
exclusion list publishes every field somebody forgets to add to it. The rule that decided
each field is that a field is public when it is a fact about the work or about the object
as a catalogue record, and withheld when it is a fact about a member, the household, or
the transaction. A test fails until every field on `BookOut` is classified, so a new field
cannot default to either answer.

**A locally uploaded cover is dropped from the payload**, keeping only an https URL a
metadata source supplied. `/covers/<id>` is served behind `book_for_read`, so publishing
that path would advertise an image a public reader cannot fetch, and serving those bytes
publicly is a new file route with its own authorization rather than a column decision.

**Not published is 404, never 403**, which is the house rule applied where it matters most:
a 403 would confirm to anybody that this deployment holds a catalogue it is withholding.
The item route answers 404 for a book that does not exist, one in the trash and one marked
private alike, so a stranger cannot count through ids to learn how many private books a
library holds.

**Nothing under `/api/public` writes.** There is no POST, PUT, PATCH or DELETE in that
router, and the gate is a dependency on the **router** rather than on each handler, so a
route added there cannot be added without it.

**`noindex` by default, and it is set in the middleware rather than on the routes.**
Publishing a catalogue and inviting a search engine to crawl it are different decisions.
`SecurityHeadersMiddleware` puts `X-Robots-Tag: noindex, nofollow` on **every** response
this application sends, and the published catalogue paths are what lift it once indexing is
allowed. That direction is the safe one: a response nobody thought about stays out of the
index, and the signed in application is now noindex too, which it always should have been.

It was on the routes for a round and was wrong twice over. A header set from a route
dependency merges onto the **success path only**, so measured it was on the 200 and absent
from the gate's 404, the item 404, a 429 and a 500 while two documents said otherwise; and
a dependency cannot reach the `StaticFiles` mount at all, so the HTML a crawler actually
indexes never carried it.

`/robots.txt` allows `/catalogue`, the **client** route, and not `/api/public/`. The first
version allowed the JSON prefix and disallowed everything else, which invited a crawler to
the one path with nothing readable at it and barred the two the catalogue is read at. Not a
bare `Allow: /` either, which would invite it into the signed in application where every
path answers 401.

**The published `id` is the insert order, and that is a disclosure.** `order_for` appends
`Book.id.asc()` to every ordering, so the catalogue comes back in acquisition order with no
`sort` parameter at all, and `max(id)` against the number of rows returned gives the count
of rows the shelf withheld: measured on ten rows, three private and one trashed,
`max(id) - count` is exactly 4. It is accepted rather than fixed, because the id is the URL
a record is read at and an opaque public id is a schema change with its own ticket. It is
also why `PublicBookSort` excluding `newest` is a narrower guarantee than it reads: see
`docs/decisions.md`.

### Telegram's host is a constant, and SMTP always verifies

**`api.telegram.org` is not configurable**, and that absence is the control. The webhook
posts wherever an admin typed; this posts where the app chose. A host setting would give
that property away and buy nothing, since a different host would not be Telegram.

The **bot token is a path segment** in every Telegram call, which makes the request URL a
secret and makes a token containing `/` or `..` a way to choose the method being called.
It is matched against `<digits>:<secret>` before it reaches a URL, and the failure log
names `api.telegram.org` rather than the URL. Nothing logs the exception's own message
either: `httpx.HTTPStatusError` renders the request URL.

**The SMTP TLS context is built in `mailer.send` and takes no parameter.** There is no
setting, no environment variable and no request field that relaxes certificate or hostname
checking, which is what makes "verification cannot be switched off" a property rather than
a default. Three configurations are refused before a socket is opened: a password with
neither STARTTLS nor implicit TLS, which would put a household's mail credential on the
wire in the clear; both TLS flags at once, which is two protocols on one socket; and an
address carrying a newline, which is header injection into `From` or `To`. A server that
does not offer STARTTLS when STARTTLS was asked for fails rather than continuing in the
clear.

**Both new credentials join the masked set.** `MAIL_PASSWORD` and `TELEGRAM_BOT_TOKEN` sit
beside the Google Books key and the webhook secret in `settings_store.SECRET_KEYS`, and a
test walks that set rather than naming fields, so a fifth is covered the moment it is
added. `MailConfig.password` is `repr=False` for the same reason: a frozen dataclass prints
every field, so one `logger.exception` would put the mail password in a log.

**`MAIL_DEBUG` is deliberately not honoured**, though it is one of the eight standard
`MAIL_*` names this app reuses. smtplib's debug output writes the AUTH exchange to stderr,
so supporting it would be a supported way to print the mail password into the container
log.

### The webhook URL is an admin-to-admin capability, and a blocklist would not fix it

An admin can point it at an address inside the cluster, and a request will be made to it
from the app's own network position. That is real, and it is the same class of capability
as restore, which replaces every account in the database: an admin is already trusted with
the library.

A blocklist of private ranges is deliberately **not** implemented. It would look like a
control without being one: DNS resolves after the check, so a name that answers with
`127.0.0.1` walks straight through it, and the check would still have to be repeated at
connect time to mean anything. What is enforced instead is the scheme, `http` or `https`
only, at the point the URL is saved and again before every send.

The failure log names the **host** and never the URL. Slack, Discord and every "post here"
integration put the credential in the path or the query string, so logging the destination
is how a secret reaches a log aggregator.

## Rate limiting

**Seven counters, for four different reasons.** Counted 2026-08-28 against
`SlidingWindowLimiter(` in `backend/ratelimit.py`; this table used to say five
and list four of them, omitting the authority and cover backfill limits
entirely. The number is now derived rather than written:
`tests/test_ratelimit.py::TestTheRateLimitTableInTheDocsIsTheModule`
reads the sentence and the table out of this file and counts the module, so a
counter added without a row here is a failing test rather than a stale
paragraph.

| Route | Limit | Keyed on | Why |
|---|---|---|---|
| `/auth/login` | 10 / min | username + address | Bounds guesses at a token |
| `/auth/switch` | 10 / min | username + address | The same counter: a password check that returns a session on another account |
| `/auth/register` | 5 / hour | address | Bounds account creation |
| `/api/imports/*` | 3 / min | username | `/csv` writes thousands of rows in one transaction, holding the single SQLite writer against the library. `/preview` writes nothing and is limited for the other half of the cost: parsing a 5.02 MB, 20,000 row export is 3.081 seconds of CPU, measured, and `MAX_UPLOAD_BYTES` caps the body without capping the rate. One window covers both, so the ordinary flow of a preview then an import spends two of the three |
| metadata lookup, search, refresh, enrich | 60 / min | username | Each call fans out to as many as eight public catalogues that this library neither runs nor pays for |
| `GET /api/books/authors/authority`, `POST /api/books/authors/identifiers`, `GET /api/books/authors/wikipedia` | 10 / min | username | **Three paths, one counter**, because all three reach an authority service on a member's behalf; sharing it means a member reloading the authors page cannot also spend the confirmation budget. Sized for the search rather than the confirmation: the supplier's published figures are 6,000 simple lookups a minute and **30 complex searches**, and this counter cannot tell the two apart, so three members searching flat out at ten each are exactly at that thirty. **Which of the two is "more expensive" depends on the unit, and this row has stated it in the wrong one twice.** Since 2026-08-28 a confirmation is one lobid request, four to Wikidata and up to three to VIAF: **8 requests, about 1.08 MB, three hosts**; where VIAF produces no cluster, six more Wikidata calls replace the VIAF ones rather than joining them, so the ceiling is **14 requests** and the bytes fall, the six measuring 1,942 together. A lookup reaches two hosts and no VIAF, and is the **larger of the two in requests**: its name search branch is 1 + 2 per candidate capped by `MAX_CANDIDATES`, so **11 requests and about 43 KB**, and its resolve branch is a full `resolve` per stored identifier under the same cap, so **25 requests and about 93 KB**. At ten a minute that is up to 250 outbound requests for lookups against 140 for confirmations. **In bytes the comparison inverts**: a confirmation is about 25x a name search and 12x a resolve, because the VIAF fallback record alone can be 781,687 bytes. **The third path is the one to read before re-sizing this, for two reasons this row did not previously have to state.** It is the first consumer of this counter that fires on a **page render** rather than on a deliberate act, so it is spent by navigation rather than by intent; and it spends the whole of that budget at **Wikidata**, which this row is not sized against, while the 30-complex-search figure above is lobid's. It is at most 10 requests per call (five filtered, five unfiltered), so a member with 201 or more confirmed authors reaches 100 Wikidata requests a minute at this ceiling, against a measured tolerance of roughly 50 `wbgetclaims` in two minutes from one address. The resulting 429 is not seen by the reader: it degrades to a link to the Wikidata item, and it lands on the confirmation path as well, silently, because both routes reach Wikidata from one address. The shared counter is what **bounds** the combined spend rather than what causes the collision, so splitting it raises the total and makes the collision more likely, not less. A client is expected to cache: Endpaper's own asks once an hour per locale and not at all for a library that has confirmed nobody. Totals measured live 2026-08-28; the per-call figures are in `backend/authority.py` and are not repeated here so they cannot drift against it. VIAF publishes no figure to size against, and serves no `robots.txt` |
| `POST /api/books/covers/backfill` | 6 / min | username | One run fetches up to a hundred images from the same services the metadata limit protects, and it is the call a member would press twice while the first is still running |
| `GET /api/public/books`, `GET /api/public/books/{id}` | 120 / min | address | The fourth reason, and the only counter here whose caller holds no session: this is the published catalogue, so it is the first surface a stranger can reach. **Keyed on the weakest key in the module**, because there is no username to key on and `X-Forwarded-For` is not trusted, so behind a proxy this is closer to a global cap than a per client one. 120 a minute is far above a person turning pages. **It does not stop a bulk copy of the listing and is not meant to**: `MAX_PAGE_SIZE` is 200, so a 3,000 record catalogue is 15 requests, and a published catalogue is a public document. What it bounds is the record by record read, one request per book, which is where the per query cost is and which is the path an indiscriminate crawler takes |

The last three of the first six are the ones that are not about this deployment: spending somebody else's
quota is a way to get this deployment's address rate-limited upstream, which loses
metadata for everyone. Sixty a minute is far above scanning a shelf by hand.

Everything else needs a valid token, so the thing worth bounding is guesses at getting
one. All of it was unbounded before. The public catalogue is the exception to that
sentence and is the reason it now has one: see [The public catalogue](#the-public-catalogue).

`backend/ratelimit.py` is hand-rolled rather than slowapi, and the reason is load-bearing:
**the useful key for a login limit is the username being attempted**, and a
middleware-style limiter cannot see it, because its key function runs before the request
body is parsed. Keying on the source address instead is worse than it looks here, since
the app sits behind a reverse proxy: every request appears to come from the proxy, so the
limit is either effectively global or depends on `X-Forwarded-For`, a header the client
sets and can rotate to evade the limit. A username cannot be rotated: it *is* the thing
being attacked.

A successful login clears the count, so someone who mistypes twice and then gets it right
is not left rationed.

Storage is in-process, which suits a single container with a single worker. Restarting
clears the windows, an accepted tradeoff for not adding Redis to a catalogue this size.

## Uploads

`backend/uploads.py` decides the format from the file's **leading bytes**, never its name.
A filename is caller-controlled, so the previous extension check decided nothing: anything
at all could be stored as `12.png` and then served back from this app's own origin.

- Accepted: JPEG, PNG, WebP. JPEG is stored as `.jpg` so a book has one predictable cover
  filename.
- **SVG is refused.** It can carry script, and these files are served from our origin.
- 5 MB cap. The body is read into memory before it is written, so an unbounded upload is a
  denial-of-service, not just an untidy file.
- A RIFF container that is not WebP (a WAV, say) is refused rather than accepted on the
  strength of its first four bytes.

### The two catalogue uploads, which are not images

`POST /api/imports/csv` and `POST /api/imports/marc` take a file that is parsed
rather than stored, so magic bytes decide nothing and the bounds are different
ones. Both go through `_read_upload`, so both are capped at `MAX_UPLOAD_BYTES`
and both spend one of `/api/imports/*`'s three a minute.

**MARC adds two refusals a byte cap cannot make, and both are about a parser
whose cost is not the body's size.**

* **A doctype anywhere in the file.** `xml.etree` expands internal entities, so
  a body carrying one can define an entity worth a thousand times its own bytes:
  measured on this project's Python, ten characters nested six deep expand to a
  million. This is `metadata._parsed`'s refusal applied where the surface is
  larger, since an upload is chosen by the caller and a catalogue response is
  not.
* **A NUL byte in the first kilobyte**, which is a UTF-16 or UTF-32 file. The
  doctype check is a byte scan, so it is exact for the ASCII compatible
  encodings and blind to the rest; refusing the rest is what makes the scan a
  guarantee rather than a guess. Measured over every encoding pyexpat's
  unknown-encoding handler accepts: all of them are ASCII compatible and none
  maps a byte above 0x7F onto a character of `<!DOCTYPE`, and the two codecs
  that would, `mac_arabic` and `mac_farsi`, expat refuses by name.
  `tests/test_marc.py` carries the evasion this exists for: the same entity
  bomb, encoded UTF-16 so that `<!DOCTYPE` is not a byte substring of it,
  **referencing the entity from a real `245 $a`** and asserting the refusal by
  message. That fixture was written twice: the first was an empty
  `<collection/>` with a bare `pytest.raises`, and it passed with the guard
  deleted because the reader then fell through to "no MARC records". Both
  critic seats found that independently.

**A record count cap on top of the byte cap**, 20,000, refused rather than
truncated. Both bounds are needed and neither substitutes for the other: minimal
MARCXML records are small, so a body well inside the cap can still be tens of
thousands of records, each of which costs a parse, a match against an in memory
index and possibly an insert.

**The writer drops what XML 1.0 cannot carry.** `ElementTree` serialises a
control character verbatim, so one `\x0c` in a member typed description would
produce an export no parser will read, this app's own included. Nothing upstream
refuses them: a description is `Text` with no character class, and a catalogue's
`520` is whatever that catalogue sent. This is an availability guard on the
export rather than an injection one; MARCXML has no executable construct and
`ElementTree` escapes the rest.

**A declared multi-byte encoding is a 400, not a 500.**
`ElementTree.fromstring` raises `ValueError` rather than `ParseError` for an XML
declaration naming `EUC-JP`, `Shift_JIS`, `gb2312`, `big5` or `UTF-7`, and a
handler catching only the second answered a 92 byte body with a traceback. Both
are caught.

**A MARC record is held to the bounds `POST /api/books` applies.** It was not,
and the cost was measured rather than imagined: one 3.7 MB upload of a single
record stored a 3,000,000 character title into a `String(500)` column and made
`GET /api/books` answer with 3.8 MB. SQLite does not enforce a `VARCHAR` length,
so nothing failed; on an engine that does, the flush aborts the whole transfer.
The sharper one is `series_index`, which the API bounds at 1000: a ten character
`245 $n` stored `1e9`, and `GET /api/books/series` computes
`set(range(1, max(held) + 1))`, which at a measured 70.5 bytes and 0.624 seconds
per million elements is roughly 70 GB and ten minutes, again on every request
until the row is found. `importing.within_bounds` reads the bounds off
`BookCreate.model_fields` and the column widths off `Book.__table__`, so a field
added later inherits them.

**The MARC preview publishes an ISBN existence oracle, and it is accepted
rather than closed.** `MarcPreviewOut.blocked` counts records whose ISBN belongs
to a book the caller cannot see. The **fact** is not new: it has been readable
off `ImportResultOut.skipped` since the CSV importer, which
`backend/importing.py` argues for, since the alternative is letting the insert
reach the unique index, raise, and write nothing for the whole file. What is new
is the price. The import pays for each probe by writing a book for every ISBN
that does not collide; a preview writes nothing: measured, 20,000 records and
3,860,064 bytes answered 200 in 1.08 seconds with zero books written, against a
rate limit of three a minute.

It is kept because no arithmetic hides it. `readable`, `already_held` and
`blocked` are the three numbers the screen exists for, and publishing any two
publishes the third; removing the screen removes the answer to "will this double
my catalogue", which is the accident this whole feature is shaped around. What
it discloses is that **some** book in this house carries an ISBN, never whose,
never its title, and never anything about the book. `docs/decisions.md` carries
the decision.

**Library mode gates both**, on the server, at 403. See
[api.md](api.md#marc21-in-and-out).

## Downloaded covers

A cover resolved from an image service is **fetched by the server and stored here**, and
`cover_url` becomes `/covers/<id>.<ext>`. That is a privacy change as much as a reliability
one.

**What it stops.** A hotlinked cover made every reader's browser request an image from
`covers.openlibrary.org`, `portal.dnb.de` or Google, once per book, on every render of the
grid. Those requests carry the reader's address, and the URL carries the ISBN, so the image
service learned which books the library holds and roughly when they were being looked at.
Measured on the running deployment before the storage outage, the covers directory held zero
files, so this described every cover in the library.

The bytes are untrusted input from a third party, and are treated as such:

- The extension comes from the **magic bytes**, through the same `uploads.sniff_image_extension`
  an upload goes through. Never from the URL, which has no extension in the DNB's case anyway.
- Capped at `MAX_UPLOAD_BYTES` and read in chunks, so a service answering with an endless body
  is refused at the cap rather than filling the container's memory.
- Written through `uploads.replace_image`, so a failure mid-write cannot leave a book pointing
  at a file that is no longer there.
- Served by the authenticated cover route, which applies `visible_to()`. Storing covers does
  not widen who can see one.
- Deleted when a book is purged and when a merge discards the loser's, because a cover file
  outliving its row is not only clutter: SQLite reuses an id, so the next book to take it
  would inherit somebody else's cover.

`COVER_HOSTS` and the CSP's `img-src` are unchanged: a failed download keeps the remote URL,
so the policy still has to permit it.

### The server fetches a URL a member chose, so the host is checked

`cover_url` arrives on `BookCreate` from any signed-in member, and registration is open by
default. Adding a book makes the server fetch it. Without a host test that is an
authenticated caller choosing which address the pod connects to, being redirected into
private space and down to plain http, and reading an image-shaped answer back out.

`covers.is_fetchable` is the gate, derived from `COVER_HOSTS`, applied in **both**
`covers.download` and `covers._check` before every request. `follow_redirects=False` in both
clients: redirects are walked by hand with a limit of two hops and `is_fetchable` re-run on
each `Location`, because a client that follows them turns one allowed host into a way to
reach any other. Refused with it: any scheme but https, any host not on the list, a
non-default port, and a URL carrying credentials (`https://covers.openlibrary.org@evil.test/`
reads as a listed host to a person and resolves to `evil.test` in every client).

**The blind version of this was open long before covers were stored.** `covers.resolve` has
put a supplied URL at the front of its candidate list and called `_check` on it since the
check existed, and `_check` streamed a GET with redirects followed. Storing the bytes is what
turned a blind request into a read primitive. Both call sites are fixed; fixing only the
newer one would have left the older hole open and looked closed.

`is_fetchable` is deliberately **not** `storable`. `storable` governs what a browser may be
pointed at and must keep admitting any `https://` URL, because a hotlinked cover is the
fallback when a download fails. What may be rendered and what this server may connect to are
different questions with different answers.

`POST /api/books/covers/backfill` is scoped to the books the caller can see. It is not
admin-only, because `visible_to()` has no admin bypass and an admin-only backfill could
therefore never repair another member's private books. It is rate limited instead.

## Catalogue requests

Nine third party catalogues are asked for records: Open Library, the DNB, K10plus, the
BnF, the Library of Congress, the Austrian National Library, the National Library of
Greece, the Czech National Library and Google Books. `backend/fetch.py` is the only place an HTTP
client for them is built, and `backend/tests/test_fetch.py` enforces that with an AST pass
over the tree, because the defect that produced the module was ten hand built clients that
agreed on the timeout and agreed on nothing else.

**There is a second transport, and it asks nothing today.** `backend/z3950.py` speaks
Z39.50 to national library catalogues, which is the only protocol several of them offer.
No source in the chain reaches it yet, so nothing is asked during a lookup. It carries the
same bounds by construction rather than by resemblance: `MAX_RESPONSE_BYTES` is the same
2 MiB, counted on the records rather than on chunks; the record count is bounded because
the protocol answers a search with a hit count and hands over records only for the
positions asked for; and one absolute deadline covers the open, every search and every
record on an association. It has no host allowlist for the reason above, and the reason
holds only while a `Target` is built from module constants: the day one is built from
stored configuration or a request body, that changes.

**There is no host allowlist here, and that is the difference from a cover.** A cover URL is
member input, so `covers.is_fetchable` has to decide whether this server may connect at all,
per redirect hop. A catalogue URL is a module constant plus a query string, so an attacker
cannot choose the host and there is nothing an allowlist would refuse. Merging the two would
mean adding nine catalogue hosts to `COVER_HOSTS`, which is what the CSP's `img-src` is
generated from: the browser policy would be widened to pay for a fetch policy.

**Redirects are walked here, and only to the same host.** Measured live with redirects off,
Open Library is the only source that redirects at all, once, and to its own host. So
following a redirect **off** host was never something a source needed, and it was the whole
of the exposure: a compromised catalogue, or one substituted on the wire, could otherwise
send this server to a host of its choosing. `fetch.get` therefore sets
`follow_redirects=False` and walks hops itself, matching scheme, host and port with the
implicit 443 and 80 filled in, at most `MAX_REDIRECTS` of them. Anything else raises
`RedirectedOffHost`.

That matters most at the three catalogues with no TLS endpoint, the Library of Congress,
the National Library of Greece and the Czech national library, where an on path attacker
could answer for the catalogue:
`docs/decisions.md`, "The Library of Congress is fetched over plaintext HTTP, knowingly"
and "The National Library of Greece is plaintext too, and the identity check is what that
costs". Substituting a record is still open to such an attacker; turning one request into a
request against an arbitrary internal address is not.

**The National Library of Greece answers on two paths and only one of them can check what
comes back.** On an ISBN lookup a record has to name the ISBN that was scanned, because
`metadata._marc_claims_isbn` refuses one that does not, so a substituted record chooses the
metadata for the book in hand rather than the book. On a title search there is no
identifier to check against, so a substituted body can offer any row it likes and a member
picks one from a list. That second path is exactly the Library of Congress's exposure,
which is title search only: the Greek source's search surface is **not** narrower than it,
and its lookup surface is the half that is checked.

**A `Location` naming an unusable host is refused the same way**, and it is worth knowing
why it needed separate handling. httpx builds the redirect request inside `send()` **even
with `follow_redirects=False`**, to populate `response.next_request`, so `idna.decode` runs
on the header value before this module sees the response and the hop check never runs.
`http://xn--a.gov/x` raises `IDNAError`, which is a `UnicodeError` and therefore a
`ValueError` and **not** an `httpx.HTTPError`, so it escaped the handler eight of the
thirteen `try` blocks around a `fetch` call use, and took a whole search down with a 500
instead of dropping one source. It is converted to `RedirectedOffHost` at the boundary.

**A second `ValueError` reached the same gap from inside the parser**, and the cap could
not help with it. `_pages_from_extent` matched an unbounded digit run and called `int()`
on it; CPython refuses a conversion over 4,300 digits and raises `ValueError`, so a single
MARC record with 4,301 digits in its `300 $a` turned both `GET /api/books/search` and
`GET /api/books/lookup` into a 500 for **every** MARC source at once. The poisoned envelope
is 4,870 bytes, 0.23% of `MAX_RESPONSE_BYTES`, and more to the point it is **larger than the
smallest honest response that source sends**, whose measured floor is 4,585 bytes over 50
live lookups. No cap that still admits a real lookup could have refused it, which is what
makes this the clearest case that a transport bound and a parser bound are not substitutes. The digit run is now
bounded and range checked, and an over-long run is refused rather than having its tail read
as a page count.

**The response body is bounded whichever host answers**, which is the half that does not
depend on trusting anybody. `fetch.MAX_RESPONSE_BYTES` is 2 MiB and **the count is over raw
wire bytes**: compression is never requested, and a `content-encoding` other than `identity`
is refused on the header.

**Counting decoded bytes instead does not work, and the first version of this module did
exactly that.** `aiter_bytes()` hands the decoder a whole raw chunk before yielding
anything, so the decompressed allocation happens *before* the running total is compared to
the limit. Measured: **65,250 wire bytes reached 67,108,864 counted and 148.3 MB allocated**,
and across the six sources `metadata.search` asked at once when that was measured, 463.8 MB
peak in a pod limited to 512Mi. It asks eight now, so that figure is the shape it was taken
at rather than today's. The cap was advertised at 1 MB throughout. Reading `aiter_raw()` under
`accept-encoding: identity` brings the same payload to 0.1 MB.

Measured live across eight worst case queries at each source's record ceiling, the largest
honest body was K10plus `pica.all=geschichte deutschland` at 687,481 bytes, so the cap sits
3.05x over it. The eighth source, the NLG, measured 604,964 bytes and did not move that.
Parsing retains a measured 15.28x the wire bytes, giving a worst case of about 256 MB
against 512Mi, which a test asserts. That test reads the source count off
`metadata.search` rather than restating it, because it was written as a literal 6 and went
on passing when a seventh source was added. The margin is deliberately generous rather
than tight: the same quantity measured 587,810 bytes three days earlier, so the tail is being
sampled and not bounded.

Going over raises `fetch.ResponseTooLarge`, which is an `httpx.HTTPError`, so it lands in
the handler every caller already has for a timeout: that source is unavailable and the
other seven answer. `metadata._parsed` is the other half of the same bound, refusing a doctype so
that an honest looking body cannot expand past the cap after it has been let through.

**The whole request is bounded in time, not each read.** `TIMEOUT_SECONDS` is a budget for
one call including its redirects and its body, enforced by an `asyncio.timeout` around the
whole walk. A per read timeout bounds nothing useful: measured, a body trickled 20 bytes at a
time under a 1.0 second read timeout completed in **18.0 seconds**, and at the shipped
settings that is roughly 109 days of held request. The same trickle now raises
`DeadlineExceeded` at 1.001 seconds.

## Response headers

`backend/middleware.py` sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, a `Permissions-Policy` allowing only the camera (the
barcode scanner needs it), and a CSP.

In the CSP, `script-src` is `'self'` with **no** `unsafe-inline`. That is the half that
blunts XSS. `style-src` does allow `'unsafe-inline'`, and that is deliberate: React
applies the login background through an inline `style` attribute, and inline styles cannot
be nonced the way scripts can.

HSTS is sent **only** when the request arrived over HTTPS (directly or per
`X-Forwarded-Proto`). Sending it unconditionally on a LAN deployment with no certificate
would lock members out of their own library after one visit.

## CORS

Off by default. The API and the compiled frontend are served from one origin, so no
cross-origin request happens in a normal deployment.

This replaced `allow_origins=["*"]` with `allow_credentials=True`, which let **any site on
the internet** make authenticated calls to the API on a signed-in member's behalf. Set
`CORS_ORIGINS` (comma-separated) only for a genuinely separate frontend host.

## Errors

A crash returns a generic 500 and **never** a traceback: a traceback names internal paths
and can quote request data back to whoever triggered it. The detail is logged instead.

Error pages are content-negotiated (a browser gets HTML, a `fetch()` call gets
`{"detail": ...}`) and the wording comes from a fixed table, so an internal exception
message cannot be reflected into a page.

## Container

Runs as **uid 1000, non-root**. `pip` and `setuptools` are deleted from the runtime image:
nothing uses them (uv's virtualenv has its own), and a scanner cannot tell a package you
ship from one you run.

For a `readOnlyRootFilesystem` deployment, `/tmp` must stay writable: FastAPI spools an
uploaded cover into a `SpooledTemporaryFile` that rolls over to disk. Nothing else needs a
writable path outside `DATA_DIR`.

## The one cookie

An `<img src>` cannot carry an `Authorization` header, so under `AUTH_MODE=local` every
cover request would arrive anonymous and 401. `endpaper_cover` is what fixes that, and four
properties keep it from being a hole rather than a fix:

| Property | What it buys |
|---|---|
| `scope: covers` in the token | It is **not** the access token. Every route but the cover route refuses it, so a copy that escapes cannot be replayed against the API |
| `Path=/covers` | The browser never sends it to a route that changes anything |
| `HttpOnly` | Script cannot read it |
| `SameSite=Lax` | Another site embedding `/covers/1.jpg` gets a 401, not a picture |

The scope is the one that does not depend on the browser behaving. Path and SameSite
constrain what the browser sends; the scope constrains what the value is worth to anyone
who has it by other means.

`POST /auth/logout` deletes it. Without that it outlived the session, and on a shared
machine the next person's first page load fetched covers as whoever left.

## Sessions and restore

A restore replaces the users table wholesale, so the id a live token names may afterwards
belong to somebody else: the token for user 3 comes back as a different person, with their
books and, if that row is an admin, their powers. Nothing in the token notices, because the
id is still an id and the signature is still ours.

Every token therefore carries an epoch, and a restore rerolls it, ending every pre-restore
session. The epoch is a random value rather than a counter because the settings table is
itself part of the backup: a counter would be restored to an older number, and tokens
stamped with that number would start verifying again.

### An identity change drops the in-memory cache

React Query's client is created once per page load and does not care who is signed in, and
**none** of the ways the identity changes reloads the page:

| How | What happens in the browser |
|---|---|
| Signing out | `localStorage` is cleared and the app stays put |
| "Switch account" | A router link to `/login`, deliberately reachable while signed in |
| Switching into a test account | A button in Settings, then a router navigation home |
| The proxy names somebody else | Nothing at all happens in this app |

So without help the next member gets the previous one's cached answers back under identical
keys, and at the default `staleTime` nothing refetches for another thirty seconds.

What that leaks is the whole shelf. `visible_to()` is "public or mine", so a cached listing
carries **private** books, and `my_status`, `my_rating` and `active_loan` are computed per
caller; `/api/stats` and `/api/loans` are the same shape.

`useSession` therefore clears the cache in an effect keyed on the **account id**, not at
each of those four places. Three of them have a call site here and the fourth does not:
under proxy auth the identity arrives from the server, and a change in it is not an event
this app takes part in. Keying on the id is what covers the one that cannot be covered by
remembering, and what makes a fifth path free.

Two properties of that effect are load-bearing:

- It fires only between **two known accounts**. `null` means both "nobody" and "not known
  yet", and the identity is itself two cached queries, so clearing produces a null:
  treating that as a change is an app that clears and refetches for as long as it is open.
- `signOut` clears for itself, because a known account becoming nobody is exactly what the
  effect cannot distinguish, and signing out is deliberate enough to say so.

`houseRules.test.ts` holds the surrounding rule: nothing outside `pages/hooks.ts` and
`api/mutator.ts` writes the session at all, so every identity change passes in front of the
effect watching it. `mutator.ts::endSession` reaches the same place on the 401 path by
doing a full navigation instead, which is why it is the exemption.

## Known limits

Worth knowing before exposing this beyond a private network:

- **No CSRF protection**, and none needed as built: the access token lives in
  `localStorage` and is attached explicitly, so it is not sent automatically with a
  cross-site request. Moving *it* to a cookie would change that and require CSRF tokens.
  There is one cookie, and it is not that token. See below.
- **No account lockout or password reset.** A forgotten password needs a hand-edited
  database row.
- **No endpoint deletes or renames an account**, test accounts included. Removing a member
  means deciding what happens to the books they added, the loans they are part of and the
  notes and quotes they wrote, which is a larger decision than this feature. The cost is
  that every test account ever made is permanently in the **"Loan to…" picker**, which is
  the member list and which every member uses, so a typo made once is a name everybody
  picks past forever.
- **A renamed test account tells nobody.** The automatic rename above is a WARNING in the
  log and nothing in the app. Under proxy a session switched into it corrects itself,
  because `/auth/me` is the identity; under `ldap` and `local` it does not, since the top
  bar reads the account stored beside the token, so it keeps saying `alice` until that
  person signs in again. Pre-existing for any username change, and this is the first
  username change nobody asked for.
- **Username matching is case-sensitive**, in SQLite and in this app. A test account
  `Alice` and a directory identity `alice` are two accounts, so they coexist without the
  rename ever firing. Nothing is merged and nothing leaks; the two simply sit side by side
  in the member list.
- **Two directory identities signing in at the same instant** can both pick the same freed
  name and one of them gets an `IntegrityError`, which is a 500 and a retry, not a wrong
  answer.
- **Behind a reverse proxy the login limiter keys on `username|<proxy address>`**, so an
  anonymous caller who guesses a test account's name can spend that key's budget and leave
  an admin unable to switch to it for a minute. Denial only, and the shape is the one
  `/auth/login` has always had.
- **No audit log.** Deleting a book leaves no trace of who did it, and on a shared shelf
  any member can.
- **Any member can exhaust the custom field allowance, and only an admin can undo it.**
  Defining a field is additive and open to everyone, deleting one is admin only, and there
  are 25 of them: 25 requests deny the whole feature library wide, the 26th answers 409, and
  the member who made them gets 403 on the delete. Renaming has the same shape without the
  ceiling, since any member may rename any field. That is **denial, not disclosure**, and it
  is a different question from the define/delete asymmetry argued above, which is about who
  may destroy content. Anybody who would do it can also delete every book on the shelf, which
  is the bullet above; it is here because a reader auditing the asymmetry will ask.
- **The overdue reminder is not retried with a backoff.** A run where nothing delivered
  leaves `notified_at` alone and the next hourly tick tries again, so a receiver that is
  down for a day sees one attempt an hour and no queue. There is no dead-letter, and the
  standing record is `SettingKey.SENDER_HEALTH` rather than a retry policy.
- **One channel delivering stamps the loan for all of them.** `notified_at` records that
  the loan was chased, and it was, so a broken webhook beside a working Telegram chat means
  that batch never reaches the webhook. The alternative, stamping only on a clean sweep,
  repeats the identical list hourly on the channels that work, which is the behaviour
  people switch off. The failed channel is named in `senders` and in the health record.
  **Only a sender that pushes may stamp it**, which is why the in app channel does not: it
  is on by default and delivers nothing, so counting it would stamp every loan on every run
  and cut the three that do push from one attempt an hour to one per reminder interval,
  seven days by default.
- **A channel that has been failing is reported, and the bar for interrupting somebody is
  deliberately high.** This used to be a gap and was the wrong disposition: for a household
  running the published image, "read the container log" is not a worse form of alerting, it
  is the absence of one. `run_digest` now records the last outcome per sender into one
  settings row, so a failure survives the run that produced it and the record does not
  depend on an admin pressing "Send now" before the ticker gets there. What is still a
  judgement rather than a fact is when to say a channel is **broken**: a refusal the app
  decided itself (`NO_URL`, `MISCONFIGURED`, all raised before a socket is opened) is
  reported at once, and a transport failure only after 24 hours and at least two
  consecutive failures. One failed send is a network; every send failing for a day is a
  configuration, and a design that cannot tell them apart is one a household switches off.
  A channel failing once every reminder interval therefore takes two intervals to be called
  broken, which is the price of not crying wolf.
- **A channel's record is cleared by any write to that channel's settings.** Not by the
  on/off switch alone: `notifications._CONFIGURED_BY` owns every row that configures a
  sender, and `routers/settings.py`'s `_store` drops the record whenever one of them is
  written. That is the exit from a standing failure, and it is the only one, so it has to
  cover the write that actually repairs the channel. Replacing an expired bot token, or
  correcting a mail server, port or encryption choice, is not a toggle. The reminder
  interval is deliberately outside it: it says how often a loan is chased, not whether a
  channel works.
- **A record is not cleared by time, and nothing else clears it.** A run only records the
  senders it **attempted**, and a run with nothing overdue attempts none, so a household in
  its steady state produces no evidence either way. `_is_broken` measures against a
  `failing_since` that only grows. So a channel that failed and then silently recovered goes
  on being reported until somebody writes to its settings; the line under the switch names
  the date of the last attempt so a reader can see how old the evidence is. There is no
  "test this channel" button, and adding one is a feature rather than a fix.
- **The health record is a settings row, so a restore brings back an older one.**
  `SENDER_HEALTH` lives in `settings`, which `backup._TABLES` already covers, so it needs no
  new table and no new manifest entry. What it inherits is the archive's age: a restore can
  reinstate a record describing runs that happened before the backup was taken. Writing to
  the channel's settings clears it; a later tick overwrites it only if that tick had
  something to send.
- **The health record holds a failure's own sentence, and those sentences are curated.**
  `detail` is either a fixed string ("The destination could not be reached.") or the message
  from a refusal, and every refusal in `mailer.py` and `notifications.py` names the shape of
  what is wrong rather than the value: "The Telegram bot token is not a bot token", never
  the token. It is admin only regardless.
- **The backup carries every stored secret in plaintext.** `backup._TABLES` includes
  `settings`, so `endpaper.json` holds `mail_password`, `telegram_bot_token`,
  `overdue_webhook_secret` and `google_books_api_key` in full, unmasked. That is not an
  escalation: a backup is admin only and an admin already sets those values. It matters
  because of what they are rather than who can read them, and a household mail account is
  usually the same account as everything else that household owns, so the archive deserves
  the handling a password file gets. A deployment that would rather not carry them can pin
  them through the environment instead, where they are never written to a settings row and
  so never reach the archive.
- **A hung mail server costs a worker thread, not the ticker.** `asyncio.to_thread` cannot
  be cancelled, so `MAIL_DEADLINE_SECONDS` bounds the coroutine and leaves the thread to
  expire on its own socket timeout. What it guarantees is that the hourly run and
  `POST /api/loans/overdue/notify` are never held by it.
- **Reading progress is not hidden by a private book's owner from themselves.** The log is
  personal and filtered on `user_id`, so nobody sees anybody else's, but a member's own
  entries on a book they later lose access to (a book somebody else made private) are
  excluded from `pages_by_month` along with the book. The rows stay.
- **`/api/users` is readable by every member**, exposing usernames and the admin flag. It
  has to be, for the "Loan to…" picker. Test accounts appear in it like any other account,
  because that is what they are; the list of which accounts are test accounts is admin only.
- **Rate limits reset on restart**, and are per-process.
