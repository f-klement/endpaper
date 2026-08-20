# Decisions

Things that look wrong, redundant or old-fashioned until you know why. Read the relevant
entry before "fixing" one.

## Backend

### `bcrypt` directly, not `passlib`

`passlib` is unmaintained and its last release predates modern `bcrypt`, which is why the
dependency list used to pin `bcrypt==4.0.1`. That pin blocked every security update to the
library doing the actual hashing.

`auth.py` now calls `bcrypt` directly. The hash format is unchanged (passlib was only ever
delegating), so **existing passwords keep working**, proved by a regression test holding a
hard-coded pre-migration hash.

One wrinkle this exposed: bcrypt hashes at most the first 72 bytes. The C implementation
truncates silently, the Python binding raises. `auth.py` truncates explicitly, reproducing
the old behaviour rather than turning long passwords into 500s.

### Settings are functions, not module constants

`config.py` exposes `secret_key()`, `registration_enabled()` and friends rather than
constants. `ALLOW_REGISTRATION` used to be read once at import, which made it untestable
without reimporting and meant closing signups needed a restart. Reading per call costs
nothing at this scale.

`DATA_DIR` is the deliberate exception: resolved once at import, because the directory must
exist before the app starts serving from it.

### `DATA_DIR` exists at all

Paths were hard-coded to the in-container `/app/data` in three modules, which made the
backend impossible to run or test outside a container.

### `visible_to()` is a function

It must be applied by every query that returns or counts books, and a predicate retyped at
six call sites is one that will eventually be forgotten at one of them. Note the
`.is_(False)` rather than `not Book.is_private`: the latter evaluates the Column's Python
truthiness and collapses to a constant, quietly matching every row. It looks more idiomatic
and is completely wrong.

### Book access lives in dependencies, not in handlers

See [security.md](security.md). Endpoints ask for a book through `book_for_read` /
`book_for_write` / `book_for_owner` rather than fetching one and writing their own checks,
because when they wrote their own checks, fourteen of them wrote none at all.

### Login has its own schema

`LoginRequest`, not `UserCreate`. Registration's 8-character floor must not apply to
sign-in, or every account created before the policy is locked out. A 422 "too short" also
leaks that the stored password is short.

### `covers.py` is the only module that knows an image host

`COVER_HOSTS` in `covers.py` is a tuple of hosts, and `middleware.py` builds the CSP's
`img-src` by joining it. That looks like indirection for its own sake until you know the bug
it comes from: the two used to be written separately, `covers.py` learned to resolve German
ISBNs through `portal.dnb.de`, the policy never did, and **every cover on a German shelf was
blocked by the browser** while the stored record looked perfectly correct. Nothing appeared
in any log.

Deriving one from the other is only half of it. `metadata.py` also held six hard-coded cover
URLs, five of them `open_library_url()` copied verbatim, so a new source could have
reintroduced the same bug through a door the CSP change did not close. Every builder now
lives in `covers.py`, and `tests/test_covers.py` walks the AST of every backend module and
fails on a `cover_url` assigned from a URL literal anywhere else.

### A stored cover must be https, or one of ours

`covers.https_url` upgrades `http://` on the way in, because Google Books serves its
thumbnails over plain http and an http image on an https page is mixed content: the browser
blocks it whatever the CSP says, so the book gets a cover that is correct in the database
and invisible in the app.

`covers.is_renderable` then refuses anything that is neither `https://` nor `/covers/`.
Nothing in the app can be exploited through the values that rejects (`javascript:` is inert
in an image tag, an SVG rendered through one cannot run script, and `//host` is refused
because `img-src` lists no bare-host wildcard). It is refused anyway, because all three
become live the day `img-src` gains a wildcard or a cover is rendered anywhere but an
`<img src>`, and neither of those changes would remind anybody of this one.

Both rules together are `covers.storable`, and that function exists because they were three
copies of the same two steps. Two of the three repaired the upgrade half of a bug and left
the acceptance half open, which is a gap that looks closed from either end: the two reviewers
of this change found exactly that, independently, and neither found it by reading the code
that had it. One function, three callers, three different reactions to the same answer:
`BookCreate` refuses with a 422, the `Book.cover_url` ORM validator drops and logs (the
backstop for the five writers with no schema in front of them), and `backup.restore` calls it
directly because a Core insert does not fire `@validates` at all.

Migration `b8e2f04c17aa` applies the same match to the rows already stored, for the reason
the migration exists at all: nothing rewrites an old row, so nothing else would ever refuse
one. `data:` is still listed in `img-src`, so a legacy row carrying one does not merely fail
to load.

### A test account is a column, not "auth_source is local"

An admin can create a local account with a password to see the library the way an
ordinary member sees it, and can exchange that password for a session on it. Two things
decide whether an account is one of those, and both hang off `users.is_test_account`
rather than off `auth_source`.

**What may be switched into.** `models.is_switch_target` is the rule, in one function,
applied where a switch is granted and again where a token is allowed to override a proxy
header. A directory-backed account is never a target in any mode: an admin who could mint
a session for an LDAP or proxy member could read that member's private books, and per-book
privacy is the single promise the data model makes.

A local account from before a deployment moved to a directory is also `auth_source =
local`, belongs to a real person, and must not be reachable this way. Under `ldap` and
`proxy` a local password is not an authentication path at all (`/auth/login` refuses), and
a switch that accepted any local row would quietly revive it. Hence the column: it says
"an admin made this for testing", which is the thing being asked about.

**What a directory identity may adopt.** `upsert_directory_user` matches on **username**,
so a directory identity named like a test account would inherit its row: `auth_source`
flips, and the test account's books, loans and notes become that member's. That is the
collision this feature would have introduced, and never adopting is the rule.

What to do instead is the part with no free answer. Reserving a prefix for test accounts
was considered and is not one: a naming convention has nothing enforcing it, and it does
not close the collision either, since nothing stops a directory identity being named with
the prefix. Whatever the names look like, the backstop is still needed.

Refusing the directory sign-in reads as the stricter choice and is the one that hurts: the real member is locked out of their
own library (under proxy, every request 401s), and this app has no endpoint that renames
or deletes an account, so the remedy is a hand-edited database row. So the test account is
renamed aside, `alice` becoming `alice-2`, at WARNING and naming both. It keeps its id,
its data and its flag, so a session already switched into it keeps working and it is still
a switch target under the new name. The disposable half of the collision is the half that
moves.

A test account is never an admin, and nothing in this app grants that flag afterwards.

### The rate limiter is hand-rolled

Not slowapi. The useful key is the *username being attempted*, and a middleware-style
limiter cannot see it: its key function runs before the body is parsed. Full reasoning in
[security.md](security.md).

### Lending *to* an external is a loan; lending *from* one is not

A loan can name somebody with no account (`loans.loaned_to_name`), because the people most
likely to keep a book are exactly the ones who will never have a login here.

The other direction, a book the household has borrowed **from** somebody, is deliberately
not modelled as a loan, and the reason is that it is not the same relation. `loans` answers
"our book is with X, chase it": the row is created by a member, the book is one this
library already holds, and the whole point is the overdue calculation running against
somebody we can nag. A borrowed-in book inverts every one of those. It is not our copy, the
deadline is one imposed on us, and the useful reminder is "give this back", which is a
different sentence, a different notification and a different half of the loans page.

Most of what that direction actually needs already exists on a different axis:
`ownership = not_owned` says the copy is not ours, `location` says where it came from, and a
note carries the rest. That is the answer for now, and it costs nothing to have made it.

Building it properly means a second relation with its own verb, not a nullable lender column
bolted onto this one: a `loaned_to_name` that sometimes means the lender would make every
query about loans ambiguous, and the CHECK constraint that currently says "exactly one
borrower" could no longer say anything useful.

### Loans are ordered by `(loaned_at DESC, id DESC)`

The `id` tiebreak is not decorative. SQLite's `CURRENT_TIMESTAMP` has second resolution, so
two loans recorded in the same second tie and come back in whatever order the planner
chooses. Found by a test that lent two books in a row.

### `/export` is declared before `/{book_id}`

FastAPI matches in declaration order. Reversed, `/api/books/export` is a request for the
book with id `"export"`. Moving route definitions around in `routers/books.py` is not the
free reordering it appears to be.

### A unique *index*, not a unique constraint, on `user_books`

SQLite cannot add a constraint to an existing table without rebuilding it, but it can
create an index, which is applicable to a live database. It deduplicates existing rows
first, or the creation would fail.

### `generate_unique_id_function`

FastAPI's default operationId mangles the path in, so `list_books` becomes
`list_books_api_books_get` and the generated client turns that into
`useListBooksApiBooksGet()`. Using the handler name instead requires those names to be
unique, which `assert_unique_operation_ids()` enforces at startup.

That guard's first version iterated `app.routes` filtering on `APIRoute` and found
**nothing**: `include_router()` does not splice child routes in, it appends a wrapper. The
check passed while inspecting zero routes. It now descends into the wrappers and fails
loudly if it ever finds none again.

### Alembic, adopted rather than more hand-written ALTERs

Schema changes used to be hand-written steps in `migrate_schema()`. That is exactly the
failure mode migration tools exist to prevent, so Alembic runs at startup instead. The
adoption path for an existing database (stamp the baseline, then upgrade) is in
[architecture.md](architecture.md). `render_as_batch=True` is mandatory for SQLite.

### Ownership is a separate axis from read status

`books.ownership` answers "is a copy physically here"; `user_books.status` answers "has this
person read it". They are independent claims about different things: a library borrowing is
read and not owned. Collapsing them is what makes an imported reading history look like a
catalogue of possessions. `unknown` exists because a Goodreads export cannot answer the
ownership question at all, and guessing either way would assert something nobody checked.

### `categories` is joined with a semicolon, not a comma

Google's own category names contain commas ("Fiction, general"), so a comma-joined list
cannot be split back apart. `google_books.join_categories` / `split_categories` are the only
two places that know the delimiter, and the API serves the field as a **list** so no client
has to know it at all.

### The Goodreads integration is a CSV import and a link

Goodreads shut its public API to new developers in December 2020 and has issued no keys
since. There is no supported way to authenticate an account or read a shelf live, so
"connect your Goodreads account" is not an option that could be built. It is one that could
be built and never work.

### Reading dates are derived, not entered

Nobody fills in a date field. Everybody moves a book to "reading" when they start it, so
the transition is the signal. The rules and the reasons are in
[data-model.md](data-model.md); the one worth repeating is that only unset dates are
stamped, because a UI with pressable buttons makes re-selecting the current status easy.

### Series is two columns, not a table

A series has no attributes here beyond a name, and both questions asked of it are answered
by grouping on that name. A table would add a join and an orphan-cleanup problem to buy
nothing. `series_index` is a float because omnibus editions really are numbered 2.5.

### Location is free text

Nobody knows their own shelf taxonomy before they start, and a vocabulary imposed up front
is worse than a slightly untidy one that grows. `GET /api/books/locations` returns what is
actually in use, which the UI offers as suggestions, because free text with *no*
suggestions becomes six spellings of "living room" inside a week.

### Duplicate detection matches on title and author, not ISBN

The unique ISBN already makes exact repeats impossible. The case left to catch is a
hardback and a paperback, which are the same book and two legitimately different ISBNs.
Matching is deliberately lossy because it is a suggestion a person confirms, not an
automatic merge.

### Merging repoints through the ORM, not a bulk UPDATE

A bulk `UPDATE ... synchronize_session=False` leaves the session's loaded collections
stale, and the `db.delete()` that follows cascades straight through them, deleting exactly
the notes, loans and statuses just moved to the survivor. The rows are reassigned object by
object and the losers are expired before deletion.

Relatedly, the losers release their ISBN in **its own flush** before the keeper absorbs it.
Doing both in one flush puts them in a single `executemany` where the set lands before the
clear and trips the unique index.

### One bulk endpoint, not six

Every verb shares the same three steps: resolve the ids the caller may actually touch,
apply, report. Six handlers would be six copies of the permission walk, and the fifth one
added would be the one that forgot it.

### `unrated` names its correlation explicitly

`.correlate(Book)` is not decoration. When the status filter has added its own `UserBook`
join, SQLAlchemy otherwise auto-correlates `UserBook` out of the subquery too, leaving it
with no FROM clause and raising rather than filtering. Found by a test that combined the
two filters.

### Python 3.14 is a hard requirement, and PEP 649 is why

`schemas/book.py` and `schemas/loan.py` reference each other under `TYPE_CHECKING`, with
unquoted annotations naming types that do not exist at runtime. That works only because
3.14 defers annotation evaluation. On 3.13 it raises `NameError` at import.

## Frontend

### Page-centric colocation

One page goes in that page's folder, several pages in `pages/components/`, general and
domain-free in `src/components/`. See [frontend.md](frontend.md).

### Types are generated, not hand-written

`src/types.ts` used to mirror `backend/schemas.py` by hand, with nothing enforcing the
mirror. Orval now generates the DTOs from the OpenAPI schema, so a backend field rename is
a compile error rather than a runtime surprise. The generated output is committed so a
fresh clone needs no Python toolchain.

### No top-level `query` block in `orval.config.ts`

**The most dangerous configuration line in this project, by omission.** Setting one applies
to every operation including DELETE, which orval then generates as `useQuery`. A query runs
on mount and on retry, so `useDeleteBook(id)` would delete the book as soon as a component
rendered. Scope query options per operation.

### `includeHttpResponseReturnType: false`

Orval's built-in fetch client returns `{ data, status, headers }`; our mutator returns the
parsed body and throws on non-2xx. Leaving the envelope on would make every generated type
describe a shape the code never produces.

### `api/mutator.ts` throws on 401, except on the credential endpoints

It previously returned `undefined` after redirecting, so callers rendered with missing data.
Treating a 401 from `/auth/login` as an expired session also cleared the stored session and
replaced "Incorrect username or password" with "Your session has expired": wrong, and
nonsense for someone who was never signed in.

`/auth/switch` is on that list too, and is the sharpest of the three because its caller is
already signed in: an admin who mistypes a test account's password would be signed out of
their own session and sent to the login screen, having changed nothing. Measured on the
first run of the settings test, not predicted.

### The multipart path does not set `Content-Type`

The browser must set it itself to include the multipart boundary. Adding it by hand
produces a request the server cannot parse.

### `--color-paper-0` exists, and its value is `#ffffff`

A token whose value is plain white looks like a token for the sake of one. It is
not: it is the *card*, and a card is white only in this palette. Written as
`bg-white` at forty sites across nineteen files, every card, field and panel
asserts that the top surface is white, which stops being true the moment a
palette with a cream ground is offered. The value is a coincidence of the
default theme and the name is the fact.

`src/index.css` carries the same note beside the token.

### `bloom` and `danger` hold the same five hexes

Two ramps, identical values, and neither is redundant. One rose used to do both
"want to read" and "delete this", which works only because this particular rose
reads as both. It does not survive a palette change: map bloom to a candy pink
and Delete turns cheerful, or keep delete dark enough to alarm and the wishlist
badge becomes a warning.

They are equal here so that nothing changed on screen when they were split. The
split is what has to exist before a palette can move one without the other, and
deleting either ramp because it duplicates the other puts the problem straight
back.

Two call sites keep `bloom` deliberately: the "want to read" badge on a book
card, and the books-finished bar on the statistics page. Everything else that was
rose is `danger`.

### `TAG_PILL_CLASSES` is a four-key table with two values in it

Type, genre and age were a blue, a purple and a green, which was the one place in
this app where a colour was chosen at random. There is no mnemonic that makes
genre purple, so the hue had to be looked up, and the pill has the word written
on it. All four selected chips also failed AA, the green at 2.28:1.

The three now share one neutral and custom keeps the accent, because a tag the
household invented reading as theirs is a distinction with a reason behind it.
The table stays keyed by category rather than collapsing to a default and one
exception, so a category added to the backend enum is a compile error here
instead of an unstyled pill.

### The palettes are CSS, and the catalogue is TypeScript

`palettes.css` holds every hex; `palettes.ts` holds the list, the attributions and which
member was constructed. Splitting them looks like indirection and is the only arrangement
where the values exist once.

Tailwind generates `bg-paper-0` only because `--color-paper-0` is declared literally in
`@theme`, so the default palette has to be in CSS whatever else happens. Putting the other
six in TypeScript and applying them as inline custom properties would mean the same eleven
ramps in two places, with nothing able to compare them: the test suite runs with CSS
handling scoped to a raw read, so a TypeScript table could be asserted and the stylesheet
could not.

So the stylesheet is the authority and `tests/theme/palettes.test.ts` reads it as text,
resolves the cascade the way a browser does, and measures the result. A palette is then a
block of declarations and a catalogue row, and neither can drift from the other without a
test failing.

### Every palette block repeats tokens that look identical to the block above it

`:root.dark` in `index.css` and `:root[data-theme="x"]` in `palettes.css` are both
specificity (0,2,0), and the palettes are imported first, so in the dark Endpaper's
overrides beat a palette's light block. Only the palette's own dark block, at (0,3,0), beats
them back. A dark block that omits a token because it matches the light block above it
therefore gets **Endpaper's** value, silently, in that one mode. The completeness is
asserted rather than trusted.

### The wallpaper's opacity is solved from a weight, not written down

A layer used to be drawn at a fixed alpha per mode. That stopped being possible the moment
the ink started following the palette, because one alpha over seven inks is seven different
weights on the page. Measured at the shipped alphas, the mean tile weight ran **0.00984 to
0.01252 in light (1.27x) and 0.01435 to 0.01899 in dark (1.32x)**, against an agreed budget
band of 0.0070 to 0.0092, which is 1.31x wide. **The palette alone consumed the entire
budget**, and the dimmer inks landed up to 30% under target on the dark page (0.0427 against
0.061).

The choice was one alpha with a stated tolerance, or an alpha solved per palette. Solved,
and not from a table: `TARGETS` in `patterns.ts` states what one mark of each layer should
do to the page as an OKLab lightness delta, and `wallpaperWeights` bisects for the alpha
that gets there, against the page and ink read off the document's own tokens.

What that buys, measured across the seven shipped palettes:

| | one alpha | solved per palette |
|---|---|---|
| light, spread of the tile's weight | 1.27x | **1.052x** |
| dark | 1.32x | **1.030x** |
| light, in continuous colour | | 1.002x |
| alpha the dark ground needs | 0.075 everywhere | 0.078 to 0.109 |

The residual is not the palette. In continuous colour the seven agree to 1.002x, which is
the bisection's own precision; what is left is the compositor rounding the blend to 8 bits
per channel, and a table of hand-solved alphas would carry the same residual.

Three consequences worth knowing before touching any of it.

- **A table of 56 numbers was the alternative and is worse than it looks.** Seven palettes,
  two modes, four weights, and every one of them wrong the moment a palette moves a hex.
  Solving at runtime means an eighth palette needs nothing here at all.
- **The alpha ceiling had to move**, from 0.15 to 0.30. That number guarded "make it
  visible" from becoming a page that competes with a book cover, and it guarded it in the
  wrong unit: five of the seven palettes need more than 0.15 in dark to reach the weight
  Endpaper reaches at 0.13. The weight ceiling is `TARGETS` now, identical for every
  palette; the alpha ceiling is a guard against an ink so close to its own page that no
  reasonable alpha reaches it. The highest solve that ships is Solarized dark's bloom at
  0.2082.
- **The ink budget changed units with it.** `patterns.test.ts` budgets mean tile dL rather
  than mean alpha, and the two cannot be compared. Under the old unit the budget was a
  budget on the palette as much as on the pattern.

The OKLab in `src/theme/oklab.ts` composites in **gamma-encoded sRGB**, which is what the
compositor does and not the more principled of the two options. Blending in linear light
puts a teal mark on the light page at 0.0443 where sRGB puts it at 0.0715, so a solve done
the principled way would ship the light wallpaper at 1.61x the weight it asked for; on the
dark page the two disagree by 2.28x, in the other direction.

### A pattern is admitted by measurement, not by looking at it

Two designers rejected a woven girih on the same ground: fine interlaced strapwork
collapses into an even grey at wallpaper opacity, and the khatam was respecified coarser
because of it. That judgement is now `frontend/tests/theme/rasterise.ts` and two assertions,
both read off the generated tile rather than off the source.

**Tint contrast.** The tile's ink, blurred, as RMS contrast against its own mean. The floor
is 0.196, which is not chosen: it is what a field of parallel lines at exactly the 12px mark
pitch measures through the same filter. At 4px, the grey wash, the same field measures
0.018; at 30px, 1.140. The ten shipped patterns run 0.354 (Nonpareil) to 1.696 (Pimpernel).

**The floor is a measurement and not a formula**, which matters more than it sounds. The
blur is three passes of a width 7 box, a cascade with a standard deviation of 3.46px whose
response at a 12px period is 0.1515. It was documented as a true Gaussian of sigma 2.25,
chosen so that `exp(-2 pi^2 sigma^2 / p^2)` is 0.5 at 12px, which describes a filter 1.54x
narrower than the one that runs. Nothing was wrong with the floor, because the floor came
from putting a 12px grating through the real filter; but anyone moving the pitch floor by
re-deriving a sigma from that formula would get the wrong filter, so the numbers are stated
in `rasterise.ts` and the formula is not offered.

A single box was the first attempt and is unusable, instructively so. A box of width `w` has
a zero in its response at every period dividing `w`, so a 12px box annihilates a 12px
grating: measured, it puts the pattern the rule **admits** at **0.0035** and the 4px grating
the rule **refuses** at **0.0177**, five times higher. The ordering is inverted, and by the
filter rather than by the patterns. Widening the box to 13 does not fix it, it moves the
zero: 4px then reads 0.0788 and 12px 0.1349. A cascade has no zeros and the problem goes
away.

**Peak coverage.** The most inked pixel of a layer, which must reach 0.9. A pattern of
sub-pixel hairlines can have all the structure in the world and still be invisible, because
nowhere does it lay down a mark that reaches the weight its layer was solved for. That
failure is drawn too thin rather than too faint, and the fix for it is stroke width rather
than opacity.

**Nothing measures a seam in a rendered tile**, and the reasoning that used to sit here is
worth keeping as a record of how a defect got through it.

It said a shape crossing an edge is seamless for free from the nine offsets, which is true,
and then that a quantity laid out across the tile has exactly two ways of going wrong,
`lattice`'s pitch and `flow`'s cycle count, both guarded by a throw at module load. There is
a third, and it is the one that shipped broken: **the parity of a staggered lattice**.
Asanoha offset every other row by half a column across seven rows, so the last row and the
first were on the same phase and the honeycomb broke in a 60px band on every 420px tile,
14% of the page.

Two things that paragraph got wrong, beyond missing the third case. The pitch check was
named as the guard on seamlessness and is **vacuous for Asanoha**, which derives its extent
from its own pitch and so satisfies it by construction. And the deleted seam test was
presented as vindicated: it could not detect a deliberately broken Asanoha, which was read
as the measurement being hopeless rather than as that test being the wrong instrument.

What is true now. The stagger parity is a third throw in `lattice`, so all three run at
module load and a wrong constant fails every test in the file rather than one. The seam is
asserted as a **property of the layout** rather than looked for in a picture, at
`frontend/tests/theme/patterns.test.ts:344`, which walks the cells and requires the last
row's phase to differ from the first's. And the vacuity is itself a test, so nobody cites
the pitch check as a guarantee it does not give.

The general lesson, since it cost a shipped defect: an invariant belongs in the constructor
that can enforce it, and a constructor invariant is only worth what it constrains. Both
halves have to be checked.

### The plait was verified by rendering, and not on a real screen

The condition on shipping the plait was that its over and under survives at true opacity on
a real 2x display, because two designers independently predicted it would not. What was
actually done: the tile was rasterised at 1x at the solved opacity over the light page, and
the image inspected at two tiles square. The break at a crossing is 20px of interrupted
2.2px outline and it reads. The tint contrast is 0.477, which is 2.43x the floor and the
second lowest of the five decorated papers: only Nonpareil resolves less, and Nonpareil is
a field of parallel lines.

**That is a rendering, not a screen.** Nobody has looked at this in a browser on a 2x
display, and the difference is real: subpixel rendering, the browser's own antialiasing of a
scaled data URI, and a viewing distance are all outside what was measured. The objective
half of the condition is met and recorded above; the subjective half is not, and is the
first thing to check when this is next in front of somebody.

### No veins on the leaves

Veining the four large motifs was on the intricacy list and was built before being taken
out. A midrib costs about fifty bytes as a closed sliver inside the leaf's own outline,
knocked out by `fill-rule="evenodd"`. Measured on Pimpernel, it removes **4.4%** of the
foliage's ink and moves the tile's tint contrast by **0.35%**, from 1.696 to 1.690, against
an admission floor of 0.196. On Willow it moves it 2.0%.

It is real ink that changes nothing anybody can see at the scale it is drawn at, which is
the definition of detail that does not survive. The mechanism is left described in
`filled()` so the next person does not have to rediscover that evenodd is what a vein needs.

Three other items from the same list did not ship and are not deferrals either. **Tendrils**
would be Willow-only decoration and the budget has no room for them on the other four.
**More cubics per branch** is what arc-length placement was for, and the branches do not
need refining to prove it. **Piecewise stem width** via `ribbon` was measured against the
underfoliage plane and moves nothing the plane does not, while changing all five silhouettes
at once.

### The ink budget is measured analytically, and that is not free

`coverage` in `rasterise.ts` sums lengths and areas. It therefore counts ink laid twice on
one pixel twice, and counts no ink at all for the round cap on a stroke, and the two errors
run in opposite directions. Against the same tiles rasterised, weighted identically:

```
lily +17.7%   acanthus +10.1%   asanoha +6.5%   willow +3.3%
plait -1.1%   seigaiha -2.6%    nonpareil -12.7%
```

All ten sit inside 0.0070 to 0.0092 under either measure, so nothing is mis-admitted. What
is not measure independent is the **spread**: 1.122x analytically and **1.235x** from the
field, and the error runs systematically toward the dense foliage tiles. Wherever that
spread is quoted it is quoted with the measure.

Budgeting from the field instead is the better instrument and is deferred on purpose: it
moves every tile's number at once and is therefore a retune, not an edit.

### The underfoliage plane is on two patterns, not five

Willow measured 0.00485 mean tile dL against a floor of 0.0070: the only tile under the
band, by 31%, and under because it is the sparsest of the five rather than because it is
drawn faint. Adding ink to its foliage would have made it denser. A third plane behind the
foliage makes it deeper, which is the same number and a different tile.

It is on Willow and Strawberry and nowhere else because the band forbids the rest. Acanthus,
Pimpernel and Golden Lily are already inside it, so a plane there would mean taking the same
ink out of the foliage to pay for it, which is a different pattern rather than a deeper one.

### A dark hover state is stated at every call site, and the rule has no exemptions

Every ramp runs the other way in the dark, so `text-accent-700 hover:text-accent-800`
written once is legible at rest and illegible while pointed at: measured across the seven
palettes those pairings land between **1.36 and 2.85** on a dark card, because `accent-800`
in a dark ramp is nearly the card itself.

Twelve sites were like that and all twelve were repaired, which is why
`frontend/tests/houseRules.test.ts` states the rule with **no allowlist**. That is a claim
rather than an omission. The alternative shape was available, and this repository does ship
it where a rule arrives before its repair (`api/mutator.ts` in the session rule,
`.field:disabled` in the paper rule), but a frozen list of twelve is a list of twelve things
nobody comes back to.

The rule covers `hover:text-` and not `hover:bg-` or `hover:border-`. A surface a shade off
in the dark looks slightly wrong; text a shade off is text nobody can read, and WCAG 1.4.3
has a number for the second and not the first.

### The theming work is not in the changelog yet

Three phases of it have landed (the token repair, seven palettes, ten wallpapers) and
`CHANGELOG.md` mentions none of them. That is deliberate and worth writing down rather than
leaving to be discovered: the entry gets written once, when the appearance picker ships,
because until somebody can choose a palette there is nothing a reader of a changelog can do
with the news. Whoever ships the picker writes the whole of it.

### `warn`, `ok` and `loan` stay raw Tailwind, for now, minus one repair

They are amber, green and orange at 29 lines across 16 files, so six of the seven palettes
ship a success message and an overdue badge in colours belonging to none of them. Tokenising
them is three ramps times seven palettes times two modes, which is a phase of its own and
not this one.

**One repair landed anyway, because it was a live AA failure and needed no token.**
`text-green-600` on the card measured **2.79 (Nord) to 3.22 (Endpaper)** for text that needs
4.5, and it is the success message on four screens. It is now `text-green-800`, measured
**6.19 to 7.13**. `green-700` was the obvious step and does not clear: 4.29 on Nord, 4.37 on
Catppuccin, 4.49 on Gruvbox.

That measurement is also the argument for the token job. A raw hue is a bet on seven
different card colours at once, and the only green that wins it is two steps darker than the
one anybody would reach for.

### `:root:root` in the `prefers-contrast` block

Doubled deliberately, and not a typo. The rule has to outrank `:root[data-theme="x"]`, which
is (0,2,0); written once, at (0,1,0), the preference would be honoured on the default
palette and silently ignored on the other six. The dark half is `:root:root.dark` for the
same reason.

### Appearance is three columns on `users`, and is not on `UserOut`

The columns rather than a `user_preferences` table: a one-to-one with no history, where a
side table buys a join on every read and a row that both shadow-account paths would have to
remember to create.

Not on `UserOut` because that schema is served inside every book payload and the member
list, so a field there would tell everyone in the household what everyone else's library
looks like. `/api/users/me/appearance` takes no member id, so there is no object to
authorize and no way to ask for somebody else's.

### The appearance cache is keyed by account, and the login screen shows the last one

The server is the authority; `localStorage` is a write-through cache, read before React
mounts. Keyed by account because a household shares devices. The `last` pointer is what the
login screen paints with, which does disclose to anyone holding the device that somebody
here uses Gruvbox. That is a decision rather than an oversight: the alternative is a front
door that looks like a different app every visit.

An inline blocking `<script>` would remove the reconciliation entirely and is not available:
`middleware.py` sets `script-src 'self'` with no nonce, so it would need a per-build hash
and the security middleware would have to be generated from the frontend bundle.

### `useSession` clears the query cache on a change of account id, not per call site

The client outlives an identity change, the cached listings are member-scoped by
`visible_to()`, so they carry private books, and none of the ways the identity changes
reloads the page. See [security.md](security.md).

This used to be a `queryClient.clear()` in `signIn` and another in `signOut`, which was
two of the four ways it changes. "Switch account" is a router link rather than a
navigation; switching into a test account is a button in Settings; and under proxy auth
the identity can change **with nothing happening in this app at all**, which is the case
no call site could ever have covered. So the clear is an effect keyed on `user?.id`, and a
path added later gets it without knowing it exists.

Two details that are not caution and cannot be simplified away:

- **Only a change between two known accounts.** `null` is both "nobody" and "not known
  yet", and the identity is itself two cached queries, so clearing produces a null.
  Treating that as a change clears again, which produces another null: an app that
  refetches for as long as it is open. Reproduced by the proxy test with a stale
  `localStorage` entry.
- **`signOut` still clears for itself**, because it is the one known-account-becomes-nobody
  that matters and it is deliberate, so it can say so where the effect cannot tell.

`tests/houseRules.test.ts` no longer counts clears against session writes. That question
was the right one while three call sites each had to remember; against one effect it asks
for a redundant call per writer. It now asserts that nothing outside `pages/hooks.ts` and
`api/mutator.ts` writes the session at all, which is what keeps every identity change in
front of the effect watching it.

### Under proxy auth a token beats the header, but only a switch token

`AUTH_MODE=proxy` used to ignore tokens entirely. It cannot any more: an admin switching
into a test account needs a session that wins over the header until it is discarded.

Accepting any valid token there would also revive tokens minted before a deployment moved
to proxy auth, and those name real members. So `auth._switch_session` accepts one only
when the account it names is still a switch target, which is narrow by construction rather
than by a claim somebody has to remember to set, and narrows further the moment the flag
comes off the row. An expired or forged token falls back to the header rather than
failing: the header is the identity the deployment already authenticated, and failing
closed would strand whoever holds a stale token behind an error page with no control on
screen to clear it.

The cover cookie follows the same rule on the cover route alone, because an `<img>` sends
no Authorization header and a switched session would otherwise show the test account's
library with a hole where every cover only it can see should be.

### Tailwind 4 has no config file

`tailwind.config.js` and `postcss.config.js` are gone; configuration is `@theme` in
`src/index.css` and `@tailwindcss/vite` runs the pipeline.

### `/login` is routable while signed in

So "Switch Account" can show the form without destroying the current session first.

### The scanner filters barcodes before reporting

Only Bookland EAN-13 and 10-digit ISBNs, or any barcode in view triggers a lookup.

### No i18n library

Two languages and a flat key set. The whole mechanism is an object lookup plus placeholder
substitution; a library would add a dependency, a bundle and a plural-rules engine nothing
here needs. The one property worth having is kept by the type system instead: `de.ts` is
typed as `Messages`, so a missing translation is a compile error.

### No dashes as punctuation, anywhere

Not in UI strings, docs or comments. Em and en dashes do not survive translation cleanly,
they are awkward on the phone keyboards this app is mostly used from, and German typography
uses them differently. Use a colon, a comma, parentheses or a full stop. A test asserts it
for the message catalogues, because a dash is easy to paste in and invisible when skimming.

Related: translate **whole phrases, never fragments**. `"Loaned to {to} by {by}"` is one key
rather than three concatenated pieces, because German does not keep that word order.

### The Google Books search is submitted, not debounced

The library search box debounces; this one does not. Each search is a billed call against
somebody's Google Books quota, and typing "the hobbit" would spend ten of them to answer one
question. Different cost, different interaction.

### `mutate`, not `mutateAsync`, for fire-and-forget writes

`mutateAsync` rejects on failure, so `void save(...)` leaves an unhandled promise rejection
in the console on every failed request. The error is already in the mutation's state, which
is what the UI renders. Found by a vitest unhandled-error report on an otherwise passing
test.

### A selected card is a checkbox, not a disabled link

In selection mode `BookCard` renders as `role="checkbox"` rather than as a `Link` with its
navigation suppressed. At that moment it genuinely is a checkbox, and announcing it as a
link that goes nowhere is worse than useless to anyone using a screen reader.

### The login tabs have `aria-label`s that differ from their text

The tab and the submit button below it show the same words ("Sign In"). Without distinct
accessible names a screen reader announces two identical buttons and neither says which one
switches the form. The labels say "Switch to sign in" / "Switch to registration".

### Debounce tests use `fireEvent`, not `user-event`

`user-event` deadlocks against fake timers. See [testing.md](testing.md).

## Tooling

### Bun, not npm

`bun.lock` is the lockfile. The Docker build uses `oven/bun` for the frontend stage only:
the shipped image is a Python image with no JavaScript toolchain in it.

### `bunfig.toml` configures a security scanner

`bun install` screens packages before any package code executes, the only moment a
supply-chain check is worth anything. Two consequences. If the scanner package is missing,
**`bun install` fails closed** rather than skipping the check. And the scan is an outbound
call made during the Docker build's frontend stage, so a sandbox with no egress fails the
install. Allow the host rather than removing the config.

### `--import-mode=importlib` for pytest

Required by the mirrored layout, not a preference. See [testing.md](testing.md).

### Alpine, and the musl bar for new dependencies

Both stages are Alpine. The runtime moved off Debian because its userland is findings
waiting to happen against software the container never executes.

This matters when adding a Python dependency. **A C-extension package with no musllinux
wheel does not fail politely:** uv tries to build it from source and dies for want of a
compiler, in CI, at image-build time. The current native set (bcrypt, pydantic-core, uvloop,
httptools, watchfiles, greenlet, sqlalchemy) was verified to install from musllinux wheels
*and* to run on musl before the switch.

### TypeScript's strictest options are on

`noUncheckedIndexedAccess` in particular, which is why array access reads `tags[1]!` in
places. That is honest about the fact that an index may miss.
