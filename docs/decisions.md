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

### The fourth reading status is "Did not finish", not "Abandoned"

Started, not finished, and not going to be. The two self-hosted apps that ship this shelf
were both checked rather than taken on trust: **Openreads** describes its fourth list as
"books you didn't finish", and **BookLogr** ships a predefined list called "Did not finish".
**Neither calls it "Abandoned"**, so that name was rejected: a third spelling of the same
shelf costs a reader a moment every time they meet it, and matching the two apps costs
nothing.

The enum member is `DID_NOT_FINISH = "did_not_finish"`, which also keeps the existing
convention (`want_to_read` is already a three-word value in that column). The German label is
**"Abgebrochen"**, not a literal rendering of the English: it is what a German reader says
about a book they gave up on, and it fits a pill.

The importers accept `did not finish`, `dnf`, `abandoned`, `gave up`, `unfinished`,
`stopped reading`, `abgebrochen` and `nicht beendet`, because Goodreads users file this as a
custom shelf and StoryGraph as a status and both spellings turn up in the same export folder.
"finished" stays READ and "unfinished" is DID_NOT_FINISH: the match is exact after
normalising separators, so no prefix rule has to get that pair right.

**Recording progress promotes it to READING.** `add_progress` promotes from UNREAD and
WANT_TO_READ and deliberately does not promote from READ, which is a re-read. Did not finish
is the third case and it promotes, because it is a claim about the past and a new position
contradicts it: leaving it alone would have the shelf say "gave up on this" while the log
says "reached page 240 this morning". Picking an abandoned book back up is the case the
status exists for. The earlier progress rows are untouched, and `finished_at` is already null
and stays null, because READING is not READ.

**It needed no new rule in `_stamp_reading_dates`**, and that was checked rather than
assumed. It is a claim that reading started, so it joins READING and READ in stamping
`started_at`; it is not a finish, so the existing `else` already clears `finished_at`. What
it must never do is fall into the UNREAD/WANT_TO_READ branch, which clears `started_at`:
that would erase the fact the book was ever picked up. It deletes no `reading_progress` row
either, because how far somebody got before giving up is the interesting part.

**No migration.** `user_books.status` is a plain `String(20)`, so a new enum member is a new
value in a text column and every existing row is untouched. Confirmed against `models.py`,
not assumed from "it is a StrEnum".

The status pill is drawn from the **paper ramp**, not from `bloom` or `danger`. Giving up on
a book is neither an error nor an achievement, and a rose pill would make the shelf look like
it was reporting a problem.

`paper-800` on `paper-200` rather than the `paper-600` the `unread` pill uses. Measured across
all seven light palettes with the same formula `tests/theme/palettes.test.ts` uses:

| Pair | Worst | Where | Best |
|---|---|---|---|
| `paper-600` on `paper-200` | **3.55:1** | solarized (then 3.56 nord, 3.87 catppuccin) | 4.71 default |
| `paper-700` on `paper-200` | 4.19:1 | solarized | 7.32 default |
| `paper-800` on `paper-200` | **4.57:1** | catppuccin | 11.35 default |
| `paper-200` on `paper-800`, dark | 5.57:1 | everforest (then 6.31 catppuccin, 6.43 gruvbox, 7.09 nord) | 11.35 default |

Only the 800 pairing clears 4.5 on every palette, so that is the one, and
`tests/theme/palettes.test.ts` holds it there in both modes.

**Two figures in earlier drafts of this table were wrong, and the corrections are worth
keeping.** The first claimed 4.19:1 for `paper-600` on `paper-200`, which is in fact the
`paper-700` figure; the 600 pairing is 3.55:1. The second attributed the dark row's 5.57:1 to
nord, where it belongs to everforest (`#d3c6aa` on `#3d484d`); nord is 7.09:1, three rungs up
the sorted list. Neither changed a conclusion, and that is the point: a number in a table like
this one is a thing the next person re-measures, and one that corresponds to nothing costs
them the time to find out why. A row is not finished when the figure is right, only when the
figure and the palette it came from are both right.

**The `unread` pill is under the floor and this change did not put it there.** As it actually
draws, `paper-600` on `paper-200` at 70% over the `paper-0` card, it measures **3.97:1 on
solarized**, 4.02 on nord and 4.27 on catppuccin. It is left alone deliberately: a status
pill's colour is one decision across five values, and a change that owns one of them should
not quietly restyle the other four. Recorded here so it is a known debt rather than something
to be rediscovered, and the test added with `did_not_finish` pins that pill only.

### The built files state a cache lifetime, and only hashed names get a long one

Starlette's `StaticFiles` sends an ETag and a Last-Modified and no `Cache-Control` at all
(measured: every path, shell and asset alike). That leaves each file to the browser's
*heuristic* freshness, which is a guess, and it is the wrong thing to leave the app shell
to.

`main.CachePolicyStaticFiles` sets one header per file, on one rule: **a name that changes
with its content may be cached, and a name that does not must be revalidated.** Only
Vite's `assets/` is content addressed, so it gets `public, max-age=31536000, immutable`
and everything else gets `no-cache`: index.html, manifest.json, sw.js, registerSW.js and
the icons all keep their names across builds while their bytes change.

The reason for the shell is a deploy, not a session. A heuristically fresh index.html
names its scripts by content hash, and a deploy deletes the hashes it no longer builds, so
a reader holding yesterday's shell requests `assets/index-<hash>.js` and gets a 404: a
blank page after a release with nothing wrong on the server. It is **not** a second
instance of the endless-spinner bug, and claiming it would be would not survive scrutiny:
both recovery paths there already reach the network, since signing out navigates to
`/login`, a URL no cache entry answers, and a reload navigation is fetched with cache mode
`"reload"`, which skips the freshness check by specification. The service worker fault was
worse precisely because the precache answered the reload as well.

`no-cache`, not `no-store`. `no-cache` means "ask before reusing", not "do not keep": the
copy stays and the ETag turns the next request into a 304 with no body. `no-store` would
throw a working conditional request away for nothing.

Three details worth keeping. The policy is set on whatever `file_response` returns, so the
304 carries it too; Starlette copies only a fixed set of headers onto a 304, and one that
dropped the policy would leave the next request reading a cache entry with nothing on it.
It is a `StaticFiles` subclass rather than middleware, because middleware on this app would
see every response including the API's and would have to re-derive which came off the disk.
And the mount goes through `mount_spa()` so the suite drives the wiring production uses:
swapping the class back for a plain `StaticFiles` has to fail a test, and it only does if
there is one mount.

### The mount serves the shell for a client route, because `html=True` does not

`html=True` answers `/` and a directory with `index.html`, and answers everything else 404.
It was taken for `main.py`'s comment, `docs/architecture.md` and this file all to say the
mount was a catch-all, and it never was. Measured in the running container with a valid
session: `/` and `/index.html` 200, `/book/12`, `/settings` and `/quotes` **404**. A
bookmark, a refresh anywhere but home, and a shared link to a book were all broken, and the
published documentation promised they worked.

`CachePolicyStaticFiles.get_response` answers an unmatched path with the shell under three
conditions, each of which is a way this could have gone wrong:

| Condition | What it prevents |
|---|---|
| Not `/api/*` or `/auth/*` (`wants_html` refuses them) | An API typo answering 200 with HTML, which is what `_fallback` was written for |
| The request accepts `text/html` | Code asking for a missing path being handed a page instead of a 404 |
| Not under `assets/` | A stale shell's missing chunk arriving as HTML inside a script tag, which is a parse error rather than a clean failure |

The shell goes out through `file_response`, so a deep link carries the same `no-cache` that
`/` does; without that it would be cached under its own URL.

Not keyed on the path having a file extension, which is the usual shortcut for this:
`/authors/J.R.R. Tolkien` is a real client route.

**The fallback cannot serve a requested path, by construction**, and that is a better
guarantee than the obvious one. It looks up `SHELL`, a module constant; the requested
`path` reaches the method only to be tested for the `assets/` prefix, and is never looked
up, joined or opened. So even a total failure of `lookup_path`'s containment check could
not turn this branch into a file read. The containment argument is true as well, verified
on the real mount with twelve escape shapes and three symlinks pointing out of the tree,
all fifteen answering the shell and none the planted sentinel, and the symlinks are the
sharper half of it because `realpath` plus `commonpath` reject a file that genuinely
exists. But it depends on Starlette continuing to behave that way, and the structural
argument depends on nothing outside the six lines.

Three consequences worth writing down.

A `POST` to an unmatched path is **405**, not 404: Starlette's answer for any method the
mount does not serve, which predates this and which the `except` re-raises, so a write
never reaches the shell branch. Behind the real error handlers that 405 *is* an HTML page,
this app's error template. What matters is that it is not the shell.

A path that tries to escape the root (`/%2e%2e%2fmain.py`) now answers 200 with the shell
where it used to answer 404. It is an unmatched path like any other, and the standard SPA
trade.

**Every probe now answers 200 where it used to answer 404**, so the status differential a
scanner reads is gone for this host, and so is the 404 burst a rate-based detector keys on:
CrowdSec will stop seeing them from this app. That is detection, not containment, and it is
inherent to serving an SPA fallback rather than anything specific to this one. Recorded so
that nobody reads the silence as quiet.

Two smallest-fixes were held rather than taken, because they treated the symptom of this
one. `endSession()` sends the browser to `/login`, which was a 404 in `local` and `ldap`
mode, the default and what the published image runs (behind a forward-auth portal the
portal answers `/login` first, which is why it never showed up in the deployment this was
diagnosed against); `LOGIN_PATH = "/"` would have worked, since the signed-out shell
renders the login page for `path="*"`. And `reauthenticateAtEdge`'s `reload()` would have
had to become `assign("/")` for the same reason. Both are unnecessary now, and `reload()`
is better than `assign("/")` because the reader lands back where they were.

### The health probe touches the database, and that was not enough

The original reasoning stands and is left here because it is right as far as it goes. The
Kubernetes probes used to request `/`, which the SPA mount answers from disk, so a pod whose
data volume never mounted stayed Ready and kept taking traffic while index.html was still
readable. Touching the database is the whole point, so `healthz` runs `SELECT 1`.

**It does not detect the failure it was written to detect.** Measured on the running
deployment during a total NFS outage on 2026-08-22: `/api/healthz` answered 200 continuously
and the pod stayed 1/1 Ready for **39 hours** while the data volume was unresponsive to every
new namespace operation. Verified at 12:35:11 +02:00, mid-outage.

The shallow reason is that `SELECT 1` on an already-open SQLite handle is served from the
page cache and issues no RPC, so the query crosses no wire.

The reason worth keeping is larger: **the probe could not fail in the mode that matters.** A
hung NFS call blocks in uninterruptible sleep and never returns an error, so storage death can
only ever reach a probe as a *timeout*. A handler that never reaches the mount never times
out. Readiness built on a long-lived handle measures the process, not its storage. An
unmounted volume was catchable; a hung one was not, by construction.

Both halves of the fix are needed:

1. **A `stat` of the data directory**, which is a namespace operation and therefore has to
   cross the wire. The query stays: it catches a corrupt or missing database, which the stat
   does not.
2. **Its own timeout**, `STORAGE_TIMEOUT_SECONDS`, at 2 seconds, which must stay comfortably
   under the deployment probe's `timeoutSeconds`. Without it the endpoint simply stops
   answering, and some probe configurations treat that as a hang rather than a failure, which
   makes the diagnosis harder rather than easier.

**The chart is not in this repository, and it currently defeats this.** The deployment sets no
`timeoutSeconds`, so both probes use the Kubernetes default of **1 second**, which is shorter
than the handler's own 2. The kubelet gives up while the handler is still waiting, which is
precisely the hang-instead-of-failure this exists to prevent. `docs/api.md` states the numbers
a deployer has to set (`timeoutSeconds: 5`) rather than only the direction of the inequality,
because that is the document they will be reading.

**It is the liveness probe as well as readiness, and that is intended.** A hung mount now
restarts the pod, and the restarted pod blocks in `init_db()` on the same mount, so it stays
down and visible. That is the right outcome: a container in `CrashLoopBackOff` reaches every
alert a household has, where a pod that is 1/1 Ready and serving nothing reaches none of them,
which is the 39 hours this entry is about. It recovers by itself when the mount does.

The stat runs in a **dedicated single-thread executor that is never joined**, and that is not
tidiness. The thread that made a hung call is gone for the life of the process, and running
the stat inline would leak a thread from FastAPI's own pool on every probe until the app
answered nothing at all: a worse failure than the one being detected. A stat that has not
come back is also not re-queued behind itself, because a backlog of calls that will never run
is not a second opinion.

Recording the incomplete version beside the correction is the point of the entry. The record
of why a plausible fix turned out to be insufficient is worth more than a tidy one.

### The covers that "stopped appearing" were a service worker cache, not the server

This is the answer to the question the earlier entries recorded as unmeasured, and it is
worth stating plainly: **nothing server side was wrong.** Measured on the live deployment
once storage came back:

| Checked | Result |
|---|---|
| Books in the library | 4, **all four with a `cover_url` stored** |
| Those URLs fetched from inside the pod | 3 of 4 answer `200 image/jpeg` (8 KB, 21 KB, 30 KB); the fourth is a genuine 404 |
| The live CSP | `img-src` permits `covers.openlibrary.org`, `portal.dnb.de`, `books.google.com`, `*.googleusercontent.com` |
| DNS | Both resolvers answer for `covers.openlibrary.org` identically to a public one |

So the record was right, the network was right, the policy was right, and the images existed.
The failure was in the browser, in five lines of `frontend/vite.config.ts`.

Three faults, and the first is what made it stick:

1. **`CacheFirst` never revalidates.** Whatever landed in the `book-covers` runtime cache was
   served for **thirty days** with the network never consulted. That is why this reads as
   "they have all gone" rather than as something intermittent, and why it did not recover.
2. **No `cacheableResponse`.** A cross-origin `<img>` is not a CORS request, so the response
   is **opaque**: a 404 and a real image cannot be told apart by status. `CacheFirst` then
   pinned the 404 for a month.
3. **`cleanupOutdatedCaches: true` does not help**, and it is easy to think it does. It
   cleans *precaches* from earlier Workbox builds. A runtime cache survives every deploy
   under its own name, so shipping a fix would have helped nobody who already had the bad
   entries, which is precisely the person who reported this.

All three are fixed: `StaleWhileRevalidate` so a bad entry heals itself on the next view,
`cacheableResponse: { statuses: [200] }` so an opaque or error response is never stored, and
the cache renamed to `book-covers-v2` so what is already poisoned is orphaned rather than
inherited. Orphaned is not deleted, so `public/sw-cleanup.js` drops `book-covers` on activate;
`importScripts` is how a `generateSW` build reaches into the worker.

The rule now matches **all four** hosts in `COVER_HOSTS` rather than Open Library alone. There
was never a reason for the other three to be uncached; the pattern simply predated them.

That makes the service worker's pattern a **third** copy of the host list, after `COVER_HOSTS`
and the CSP that is derived from it, and unlike the CSP nothing ties it to the tuple. That is
a considered trade rather than an oversight: the two that are tied together are tied because
drifting apart **breaks covers**, silently and with nothing in any log, which is the incident
recorded further up. A host missing from this third list costs a cache miss. The cover still
loads, from the network, every time. A test to hold a build-time config file against a Python
constant would cost more than the failure it prevents.

**Two things this says about storing covers locally.** A `/covers/<id>.<ext>` is same origin,
so it is not matched by this rule at all and its responses carry a real status: fault 2
cannot happen to it. That is a reason to store covers beyond the ones already recorded, and
it is the reason the entry above no longer has an unanswered question at the end of it.

### A cover is stored here, not hotlinked

Every cover in the library used to be a URL on somebody else's server, and five separate
things had to keep working for a reader to see one: the image service being up, the URL not
rotting, the pod being able to reach it, the reader's own browser being able to reach it, and
the CSP permitting it. Four of the five are outside this application, so the grid can go
blank for a reason nothing here can see, log or fix. That is not hypothetical: it is the
reported failure this change answers.

**Measured on the running deployment before the storage outage: `/app/data/covers` held zero
files** (link count 2, unchanged since 18 August), so every cover the library rendered
depended on a third party being reachable from every reader's browser. There was no
half-migrated state to reconcile, which is why nothing here tries to.

So `covers.resolve_and_store` fetches the bytes once, and `cover_url` becomes
`/covers/<id>.<ext>`, served by the authenticated route that already applies `visible_to()`.

Four consequences worth writing down.

* **The remote URL stays as the fallback.** A failed fetch degrades to what the app did
  before, not to no cover. A URL the pod cannot reach may still load from a reader's browser.
* **The extension comes from the magic bytes**, never from the URL and never from the
  response's `Content-Type`. A cover from a third party is untrusted input, neither of those
  is evidence about the bytes, and `portal.dnb.de/opac/mvb/cover?isbn=` has no extension in
  it at all. Same rule and the same function as an upload.
* **The download is capped at `MAX_UPLOAD_BYTES`** and read in chunks, so a service answering
  with a stream that never ends is refused at the cap rather than filling the container.
* **`COVER_HOSTS` and the CSP are unchanged.** The fallback still renders remote URLs, so
  removing a host from the policy would break exactly the case this fallback exists for.

### The cover bytes are files on the volume, not a column

**Decided by the owner on 2026-08-22, after both sides were put to them twice.** Covers are
files under `COVERS_DIR`, named `<book id>.<ext>`. A `books.cover_blob` column was built and
withdrawn, so the alternative is not hypothetical: it was measured on this schema.

What decided it:

* **A BLOB on `books` is loaded by every `query(Book)` unless it is deferred.** That is a
  permanent hazard managed by a test (listing, export, stats, duplicates, series, backup)
  rather than one that does not exist.
* **The database sits on the NFS mount that deadlocked earlier today.** Measured, 40 KB
  covers at the default `page_size` of 4096: 100 books is 4.1 MB, 1,000 books is 39.8 MB and
  3,000 books is 119.2 MB, against 176 KB today. A 176 KB file is trivially copyable and
  recoverable; a 120 MB one mid checkpoint is the worst thing to own when that mount wedges.
* **A backfill writes the payload roughly twice**, through the WAL, all of it over NFS.
* **`FileResponse` can hand off to sendfile.** Reading a column pulls every image through the
  Python heap of a pod limited to 512Mi.

What it costs, which is real and is handled rather than waved at:

* **Orphan files.** A row delete does not delete a file. `_purge` calls `covers.forget`, so
  purging a book and emptying the trash both take the cover with them, and a merge moves the
  loser's file to the keeper when the keeper absorbed its `cover_url` and deletes it
  otherwise. `_trash` deliberately does not: a trashed book can be restored, and restoring
  one to a placeholder is a delete that half happened. All four paths have a test in
  `tests/routers/test_books_covers.py::TestTheDirectoryDoesNotDriftFromTheDatabase`.
  Getting this wrong is not only clutter: SQLite reuses an id once the highest row goes, so a
  leftover file becomes the next book's cover.
* **The column and the directory can drift.** So nothing trusts `cover_url` to decide whether
  a cover exists. `_store_cover` and the backfill ask the filesystem, via `covers.stored_ids`
  (one directory read for the whole library, not a `stat` per book), and a `/covers/<id>.<ext>`
  with no file behind it is treated as missing and re-fetched. That is also what makes the
  backfill safe to press twice.

`FORMAT_VERSION` stays at **1**: the backup envelope did not change, covers are the same
files under `covers/` in the same zip, and bumping it would refuse every archive a household
already holds for no reason.

### The cover backfill is every member's own, not the admin's

`POST /api/books/covers/backfill` is what repairs a library that already exists. Storing
covers on the way in only ever helps books added afterwards, and the books that need it most
are the ones that arrived through a CSV import, which never resolved a cover at all.

It is **not** admin-only, and that is deliberate rather than an oversight of the request that
asked for an admin action. `visible_to()` has no admin bypass, so an admin running a
privacy-scoped backfill could never repair another member's private books, and those books
would then have no way to be repaired at all. Bending the privacy rule to make an operator
action work is the worse of the two, so each member repairs the shelf they can see, and the
run is rate limited (`COVER_BACKFILL_LIMIT`, six a minute) rather than gated on a role.

The run is **bounded at 100 books** because it holds an HTTP request open while it fetches,
and it is a **cursor**, which is the part that makes "press again" mean anything. The batch is
the first hundred candidates by book id, and a book that could not be fixed is still a
candidate on the next run, so without carrying `next_after_id` back it would sit at the front
of every run for ever. Measured across ten ISBNs, only eight resolved to an image, so roughly
a fifth of any batch is permanently unfixable and accumulates; a pod with no egress produces
the same shape on the first run, where every book is unfixable and the counter never moves at
all. `next_after_id` comes back as 0 at the end of the library, so the next press starts over
and re-tries the failures, which a service that was down may since have made fixable.

The reply counts **`unreachable` separately** from `still_missing` for the same reason. A
cover that resolved to a URL this server could not download is neither stored nor absent from
the world, and folding it into either produced "looked at 100 books and stored 0. No image
service has one for 0", which reads as a clean no-op in exactly the situation the feature
exists for. It is concurrent
(`covers.MAX_CONCURRENT_FETCHES`, six at a time) because serial would be one round trip per
book. Only the fetch runs in the pool: the SQLAlchemy Session is not thread safe, so the
assignment happens on one thread. The results are matched to their books **positionally**,
which is correct because `ThreadPoolExecutor.map` yields in the order it was given its
inputs rather than in completion order. That is the property the `zip(..., strict=True)`
depends on, and it is worth naming, because a switch to `as_completed` would silently give
every book somebody else's cover.

**Threading the backfill made a correct helper elsewhere wrong**, which is the kind of
consequence worth recording where the decision was taken rather than only where it landed.
`uploads.replace_image` named its temporary file after the pid, and its comment said the pid
was what stopped two writes of the same book colliding. That held while the only concurrency
here was separate processes. It stopped holding the moment this pool existed: two overlapping
requests for the same book id in one process built the same path, one `os.replace` won and
the other failed ENOENT. The name now carries the thread id as well. Two members repairing a
shared book reach it, and so does one member inside their own rate limit.

The upper bound on `after_id` belongs to the same family. A Python int has no ceiling and
SQLite's does, so an unbounded `int` query parameter is a 500 out of the unhandled-exception
handler, which classes a bad request as a bug in our own code. Every other numeric query
parameter in this tree was already bounded at both ends; this one was new and was not.

It targets books whose `cover_url` is NULL or points at a third party, which is exactly the
set that rots. A locally stored cover is bytes on this volume. Running it twice is therefore
cheap and idempotent: the second run examines nothing it fixed on the first.

### The CSV import does not fetch covers inline

Every other add path stores a cover on the way in. The import does not, because it runs over
thousands of rows inside a single request and a fetch per row would be thousands of round
trips holding that request open until a proxy gives up on it. The books arrive without covers
and the backfill fills them in afterwards, concurrently and in bounded batches, which is the
same work with nothing waiting on it.

### The server checks which host it may fetch a cover from

`covers.is_fetchable`, derived from `COVER_HOSTS`, is applied in both `covers.download` and
`covers._check`, and both clients run with `follow_redirects=False` and walk redirects by
hand with `is_fetchable` re-run per hop.

The reason is that `cover_url` is member input on `BookCreate` and adding a book makes the
server fetch it: without the test, any account could point the pod at an address of its
choosing, be redirected into private space and down to plain http, and read an image-shaped
answer back out. `COVER_HOSTS` already existed as the source of the CSP's `img-src` and was
**never applied at fetch time**, which is the same drift the tuple exists to prevent, one
door along.

It is deliberately not `storable`. `storable` governs what a **browser** may be pointed at
and has to keep admitting any https URL, because a hotlinked cover is the fallback when a
download fails. This governs what **this server** may connect to. Two questions, two answers.

**The blind version predates covers being stored.** `resolve` has put a supplied URL at the
front of its candidate list and called `_check` on it since the check existed; storing the
bytes turned a blind request into a read primitive. Both call sites are fixed, because
fixing only the newer one would have left the older hole open and looked closed. Full detail
in `docs/security.md`.

### Five cover outcomes are counted, because they used to be indistinguishable

The only trace this area left was one WARNING in `Book._store_covers_over_https` for a URL it
refused. "Covers stopped appearing" could be the image service being down, the pod having no
egress, the browser blocking the request, the stored URL having rotted, or nothing being
resolved in the first place, and the log said the same thing about all five.
`covers.CoverOutcome` names them (verified, unverified, no candidate, downloaded, download
failed), each is logged at INFO with the ISBN or URL, and `covers.outcome_counts()` is
reported in the backfill's log line.

This was written while the deployment's storage was unresponsive, when the cause could not be
measured and nothing here would guess at one. It has since been measured: see *The covers
that "stopped appearing" were a service worker cache, not the server*. The counters stay,
because they are what will answer the next one without a browser in the loop.

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

### Lending willingness is a third axis, and it is on the book

`books.lending` answers "would we lend this copy", and it is neither `ownership` nor a
loan. A loan is a fact about right now; this is a standing intention that outlives it. A
book can be marked happy to lend while it is at somebody's house, and one marked never lent
can still be out with a sibling. Putting the answer on the loan would mean it existed only
while the book was somewhere else, which is precisely when nobody needs to read it.

Three values rather than a boolean, and `in_use` is the reason. "I need it myself at the
moment" is a real answer and is not a refusal: it means come back later, which yes-or-no
cannot express. It arrived that way from the household that asked for the feature, in three
sentences rather than a tick box.

Nullable rather than defaulted, like `format` and `condition`: an unanswered question is
not an answer, and a guess written into every imported book at once is worse than a blank,
because nobody re-checks a field that looks filled in.

### A book marked never lent is refused once, not forbidden

`POST /api/loans` answers a **409** carrying `code: not_lendable` for a book whose
`lending` is `never`, and creates the loan when the same request comes back with
`acknowledge_not_lendable: true`.

Neither extreme is right. Allowing it silently makes the field decorative: a household that
took the trouble to mark a copy would find the app had quietly ignored them. Forbidding it
outright is worse, because the same household lends that book to a sibling anyway, and an
app that will not let them record what actually happened gets a loan kept in somebody's
head instead. That is the one thing this table exists to replace.

So the refusal costs one deliberate extra step and nothing more. `in_use` and `happy` are
not checked at all: the first means "come back later", which is a conversation between two
people rather than a rule, and the second is a yes.

The acknowledgement is **not stored**. It says something about one request, not about the
book, and a household that lent a never-lent book once has not changed its mind about
lending it to anybody else. Pinned by a test: lending it, returning it and lending it again
asks again.

The code sits beside the message rather than replacing it because the client has to
**branch** on this one, and matching on prose would break the moment it was reworded or
translated. The two 409s this endpoint raises mean entirely different things to the reader,
and only one of them has a way past it.

### "Ask me about this book" is on the member, and everybody can see it

`user_books.wants_to_discuss` is per member, for the same reason the rating is: two people
can hold the same copy and feel entirely differently about it.

It is also the **one** field on that table meant to be read by other people. The status,
the rating and both dates are private and reach the API only as the caller's own `my_*`
fields; this one is served to everybody as `discuss_with`, a list of the members who set
it. That is not a leak of a private field, it is the feature: a marker only its owner can
see is not a way to be asked about anything. It discloses usernames and nothing else, and
in particular says nothing about whether those members have read the book.

It costs one statement per page, which is why `discuss_with` is filled by a single grouped
query rather than a lazy relationship read inside the serialisation loop. `books_to_out`
went from 5 statements to 6 and `GET /api/books` from 10 to 11, both measured and both flat
in the size of the page.

`?discuss=true` matches **anybody's** offer rather than the caller's, so the filter selects
exactly the books that carry the marker the grid draws. Scoped to the caller it would hide
half of what it claims to select.

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

### Reading progress is a log, not a `current_page` column

A column on `user_books` answers "where am I" and nothing else, because every save
destroys the previous answer. The questions this feature exists for, "how much did I read
in March" and "how long did that one take", are questions about the history.

BookLogr keeps a current page and is the reference for the position itself; it cannot
answer either question. Jelu keeps a log, and its events are per status transition, which
is a different fact from a position in a book. `reading_progress` takes the log shape from
one and the position from the other. MyBibliotheca's daily log stores `pages_read`, a
delta, which was rejected here: a delta cannot be reconciled against the book, so a
mistyped one is uncorrectable, and the deltas this app reports are computed from positions
instead.

### Two units on `reading_progress`, exactly one per row

`(page IS NULL) <> (percent IS NULL)`, as a CHECK constraint.

An audiobook has no pages, and neither has a book whose `page_count` no metadata provider
supplied, which is most of a freshly scanned shelf. So a percentage has to be recordable.
Carrying both units on one row would need a rule for which one wins when they disagree,
and a rule like that is one somebody eventually gets backwards. Carrying exactly one needs
no such rule.

In the database rather than only in `ProgressCreate`, for the same reason
`ck_loans_one_borrower` is: a restore inserts through Core and never sees a Pydantic
model.

### The displayed percentage is derived, never stored

`page / books.page_count` when the page count is known, else the recorded `percent`, else
nothing. `serialisation.derived_percent` is the single definition, and the frontend does
not repeat it: `ProgressOut` deliberately omits a percentage per row.

Storing it alongside the page would be the same fact twice, and the two would part company
the first time a metadata refresh corrected a page count. Clamped at 100 because a
provider's page count is off by one often enough that the last page computes to 101.

### Recording progress promotes to `reading` and never to `read`

Saying where you are in a book is the same claim the READING button makes, arrived at from
the other direction, so a first entry on an unstarted book promotes it and stamps
`started_at`. The transition goes through `_stamp_reading_dates`, which owns those rules;
duplicating them in the progress endpoint is how the two would drift.

It never sets `read`, however high the page number. `page_count` is a provider's figure and
is wrong often enough that "reached the last page" is not a reliable finish signal, and
finishing already has an explicit control.

### A status change never deletes progress rows

Deliberately unlike `started_at` and `finished_at`, which are cleared on the way back to
unread. Those two are *derived* from the current status and would otherwise claim something
false about now. A progress row claims nothing about now: it records that somebody was on
page 64 on a Tuesday, which stays true. A re-read is a real thing, and its earlier passes
are worth keeping.

The asymmetry is stated in the endpoint's docstring so it does not read as an oversight.

### The progress endpoints sit beside `/{book_id}/status`, not before `/{book_id}`

The route-order rule in this repository is about a **literal** first segment losing to
`/{book_id}`, which is why `/export`, `/search` and `/bulk` are declared above it.
`/{book_id}/progress` has a path parameter in that position and cannot lose to
`/{book_id}` at all: they differ in segment count. So they are declared where they belong
conceptually, next to the status endpoint they cooperate with, alongside `/{book_id}/notes`
and `/{book_id}/tags`, which are placed the same way for the same reason.

`POST /api/loans/overdue/notify` **is** declared before `/{loan_id}/return`, because that
one is the shape the rule is about.

### `pages_by_month` is computed in Python, and covers page-tracked books only

The figure is a difference between *consecutive* rows per book. SQL that expresses that is
a window function feeding a conditional sum feeding a group, and nobody would be able to
check it against its description a year later. What bounds the Python version is the input:
one row per recorded sitting per member, so it is the size of one person's reading, not of
the library.

Percent-unit entries are excluded rather than converted. A book with no page count has no
page figure to convert to, and inventing one would produce a number that adds up with the
others while meaning something else. The scope is stated where each audience meets it: in
`docs/api.md` for a caller, and inside the `stats.pagesByMonth` heading string itself for a
reader, who otherwise has no way to find out why the total is lower than they expect.

Two rules inside it drop something on purpose. The first entry on a book counts in full,
because crediting nothing would mean a single sitting per book never appears. A backwards
step counts nothing, which covers both a re-read and a corrected typo: those are
indistinguishable from here, and crediting the lower page in full would let a typo of 400
followed by its correction to 40 report 440 pages read. Missing a re-read's first sitting
is the better of the two errors, because the other one invents reading that never happened.

### Overdue reminders are a generic webhook, not email and not one chat service

A self-hosted app that other households run should not carry an integration with a service
nobody else runs, and email means SMTP credentials, deliverability and a second failure
mode. A webhook is the shape every receiver already speaks: a chat bridge, a home
automation flow, or a five-line script.

Handy Library's named differentiator in this space is **configurable reminder timing**, and
that is the part worth copying: a week is nagging in one house and silence in another, so
`overdue_reminder_days` is the household's to set.

Koha's `overdue_notices.pl` was read for the scheduling shape and **not** adopted. Its
`--triggered` mode fires only when a loan is overdue by exactly the configured number of
days, so a run that is missed sends nothing at all, ever, for those loans. State on the
loan (`notified_at`) plus an interval is robust to a skipped tick, which matters here
because the ticker lives in the web process and dies with a restart.

### The overdue digest excludes private books

A webhook has no member identity behind it and lands in a channel the whole household
reads, so shipping a private book's title through it defeats the single promise the data
model makes. The exclusion is in the query, not a filter afterwards, so a counting mistake
downstream cannot put one in the payload.

The owner is still chased: the in-app overdue view is per member and already scoped. The
digest reports `skipped_private` as a count so a household that expects five entries and
receives four can see why, and the settings screen says so in words rather than leaving it
to the docs.

### `notified_at` is a timestamp on the loan, stamped after a delivery that succeeded

Without any state the digest has two behaviours and both are wrong: send once and forget a
book that is still out, or repeat the same list into the channel every hour.

Stamped after the POST rather than before it, so a failure leaves the loans to be retried
on the next run. That is why it is a timestamp rather than a "sent" flag: the interval
question ("has this been chased recently") and the retry question ("did the last attempt
land") are the same question, and one column answers both.

### The digest result carries a `reason`, and it is null exactly when it sent

`sent: false` on its own made four different outcomes one answer on the screen: switched
off, no address stored, nothing overdue, and a webhook that refused the request. A person
pressing "Send now" to check their configuration was told "nothing was sent" by a broken
setup and by a quiet week alike, which is the whole thing the button exists to tell apart.

`detail` was already there and is not enough. It is a sentence, and a client cannot branch
on a sentence or translate one. `reason` is the closed set beside it, so the frontend keys a
`Record` off the generated union and adding a fifth reason on the server is a compile error
in the catalogue rather than a silent fall through.

**Nullable rather than total.** A `sent` member would make `reason` and `sent: bool` two
spellings of one fact, which is the duplication this repository treats as a defect. So the
invariant is stated instead: null exactly when `sent` is true, and `_outcome()` in
`notifications.py` is the only thing that builds a not-sent result, so a new exit cannot
forget it. The frontend still carries a fallback for the pair the type allows and the server
never produces, because a screen that renders nothing is worse than one that is vague.

### `count_private_overdue` takes no reminder interval

It answers "how many overdue loans did privacy hold back", and that does not depend on when
anything was last sent.

It used to restate `due_for_reminder`'s predicate clause for clause, including the
`notified_at` one, and had already diverged in the only case where the two differ: a private
book is never sent, so nothing in this feature ever stamps its `notified_at`, and the only
way one carries a value at all is a book that was public when it was chased and was made
private afterwards. Filtering on it hid exactly those from the count for the length of the
interval, so the number under-reported the thing it exists to report.

`_overdue_clauses()` now holds what the two share and each query adds only what it owns. The
parameter is gone rather than ignored: one nothing reads is one the next caller passes
wrongly.

### A measured number lives in one place, and the other places point at it

`books_to_out`'s statement count was stated in its own docstring, in `docs/data-model.md`
and in `docs/architecture.md`. All three were wrong, twice, and the second time was a diff
that rewrote both sentences without re-measuring: a number is easy to edit and hard to
check, so an edit that looks like a correction is the likeliest way one goes wrong.

The docstring holds the measurement now, with what it was measured against, and both
documents reference it. The measurement itself is worth keeping in mind: five statements
constant in the page size, **plus one per distinct `added_by` author**, and that last one
belongs to the caller rather than to this function, because `BookOut` reads a relationship
that lazy loads unless the caller fetched it. Every listing in `routers/books.py` passes
`joinedload(Book.added_by)` and so pays none of it.

### `SECRET_KEYS` is enforced by a test that walks it, not by being read

Nothing in the application reads that set. Masking is written by hand per field in
`_read_settings`, so the set was a list beside the code rather than a rule over it: a third
secret added to it would have been masked by nothing, returned in full to every admin page
load, and no test would have failed.

The fix is a test rather than machinery. Making `_read_settings` iterate the set would mean
generating a field name per key and lose the per-field decisions that are the point: the
Google Books key reports whether the environment supplied it, and the webhook URL beside the
secret is deliberately **not** masked. So the set stays a list, and a test stores a known
value for every key in it and asserts none of them appears in the response body.

### The webhook URL is returned in full; the signing secret is masked

The two are not the same kind of secret. A destination an admin cannot read back is a
destination nobody can proofread, and spotting a wrong one is the entire reason to show
it; an admin who can read it is an admin who can change it. The signing secret has no use
in a browser at all, so it follows the Google Books key exactly: masked on the way out,
absent means "leave alone", an empty string clears.

The URL's scheme is checked twice, in `SettingsUpdate` and again in `notifications.py`
before every send. The first gives the caller a 422 naming the field; the second still runs
for a row a restore wrote.

### The ticker is one asyncio task, and assumes one process

The Dockerfile's CMD is a single uvicorn with no `--workers`, so there is exactly one
ticker and no double-send. That is the assumption that breaks first: `--workers 4` would
give four tickers racing on the same rows, and the fix then is `ENABLE_OVERDUE_TICKER=false`
plus an external cron calling `POST /api/loans/overdue/notify`, not a lock inside the app.

It is off under test. A background task waking on a timer inside a suite that drops and
recreates every table between tests produces failures that depend on how long the run took.

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

### Every row id a caller supplies is bounded at both ends

A Python int has no ceiling and SQLite's does. An id past 2**63-1 passes
validation, reaches the driver and raises `OverflowError` from inside the query,
which lands in the unhandled-exception handler and answers **500**: the app
calling its own code buggy over a value the caller chose. 422 is the honest
answer.

This has now been found four times, in four different places, because each fix
closed one door and the reviewer had to find the next one by hand:

| Door | Where the bound lives |
|---|---|
| Query parameter (`?after_id=`, `?collection_id=`) | `Query(ge=..., le=MAX_ROW_ID)` at the parameter |
| Path parameter (twelve of them) | `dependencies.RowId`, one alias |
| Request body field (`book_ids`, `keep_id`, `book_id`, `year`) | `schemas.common.RowIdField` |
| A loosely typed body value (`BulkRequest.value`) | the handler, per verb |

**Two lints, not one, and they are not redundant.**
`TestEveryIntParameterFromTheOutsideIsBounded` covers route handlers and
dependency functions, which is where path and query parameters are declared;
`TestEveryRequestBodyRowIdIsBounded` covers pydantic fields on the models a
route accepts as a body, which the first cannot see at all. The older
`TestEveryNumericQueryParamIsBoundedBothWays` is kept beside them because it
still catches a floor-without-ceiling on a non-int parameter.

**Both lints resolve their tables to a fixed point**, and that is the same hole
one hop further out rather than a flourish. `Loose2 = Loose` carries no `int` of
its own, so a collector that registers only what mentions one literally never
learns the second name and skips every parameter annotated with it;
`CollectionUpdate(CollectionCreate)` names no `BaseModel`, so a literal test for
that base leaves a real request body out of the rule entirely. Neither was live
when it was found, which is the point: the rule exists so the fifth instance of
this class is caught by a test rather than by a reviewer.

**The alias has to bring a parameter into scope, not just satisfy the check.**
The first version of the parameter lint tested for the literal name `int`, so
`book_id: RowId` was skipped before boundedness was ever asked about: the alias
branch was unreachable, and loosening `RowId` itself to `ge=1` left the lint
green across twelve routes. The scope test now admits a parameter that mentions
`int` **or** names an int alias, and the guard test that discriminates is the
one that loosens an alias rather than the one that bares a parameter.

**`BulkRequest.value` is the one deliberate exemption.** It is `str | int | None`
because which field it fills depends on the verb, so it cannot be typed as a row
id; the handlers that read it as one range-check it themselves before it reaches
the database. That is why `_checked_collection` carries an explicit range check
that looks redundant beside its schema bounds, and it is not.

### A book belongs to one collection, not many

A household separates physical from ebook, kept from sold, and one person's shelf from
another's. All three are **partitions**: a book is in exactly one side of each. So the
collection is a column on `books` and not a join table.

A join table would answer "which collection is this in" with a list, and every filter,
sort, export cell and payload field downstream would then need a rule for a book that is in
three of them at once. It would also be a second tag system with a worse picker, because
tags are already the many-to-many axis here and they are where an overlapping label
belongs. If a household wants "Ebooks" and "Holiday reads" on the same book, the second one
is a tag.

The cost of the column, stated plainly, and it is two costs rather than one.

**Two objects: use two rows.** A household that wants the paperback in Physical and the
epub in Ebooks has two objects, and says so the way the data model already says it. That is
the copies feature, and it is the right answer.

**One object on two axes: use a tag.** This is the one the feature's own pitch creates and
it is not answered by copies. Collections are sold on three splits (physical from ebook,
kept from sold, one person's from another's), each of which is a separate axis, and one
column holds one axis. An epub that is both "Ebooks" and "Sold" is a **single object**, so
there is no second row to put it in: the household picks one axis for the collection and
puts the other on a tag, which is what tags are and why this column is not a join table.
Somebody who instead makes four collections will discover the swap by using the picker,
which is the worst possible place to learn it, so it is said in the empty state as well as
here.

### Every book that existed before collections is unfiled, and no default was invented

`books.collection_id` is nullable and the migration backfills nothing. The alternative was a
default collection created by the migration and every existing row moved into it, which
sounds tidier and is worse in three ways. It needs a name chosen here, in one language,
for a household that has not asked for the feature. It puts a concept in front of everybody
who never wanted it. And renaming a seeded string later means a migration, which this
repository has already had to write once (`95b6a61d6668`).

So "in no collection" is a permanent, ordinary state, in the same family as a null
`format`, `condition` or `lending`: an unanswered question is not an answer. The API says
so out loud rather than leaving it implicit: `GET /api/books?unfiled=true` is its own
parameter, and the library filter offers it as its own option, because "what have I not
filed yet" is the question the feature creates.

### A collection is per household, and is never a privacy boundary

Any member may make one, rename it, and file any book they can write to into it. Filing a
book changes **nothing** about who can see it.

This is the decision with the sharpest failure mode in the batch, which is why it is
recorded rather than left obvious. `visible_to()` is already a scoping predicate, and a
second scoping axis that looks like it but is not enforced everywhere is how a privacy rule
gets weakened by accident: the moment a collection sometimes hides rows, somebody will read
it as permission, and the first "private collection" feature request would arrive with half
an implementation already in the tree.

So the separation is kept mechanical rather than intended. `visible_to()` is not given a
collection to consult. `Collection.created_by_user_id` is recorded for provenance and no
query reads it, which is what keeps the previous sentence true rather than merely meant.
Every count served with a collection applies `visible_to` (`routers/collections._counts`,
the `by_collection` statistic), because the count is the one thing a household-wide label
could disclose: a member who files a private book onto a shared shelf must not thereby
announce it to everybody as a number.

A member who wants a shelf nobody else sees already has one: mark the books private. That
is one rule, enforced in one predicate, tested by an AST walk over every module.

Two asymmetries follow the tag rules exactly, for the reasons recorded there. Creating and
renaming are open to any member: both are additive or reversible. **Deleting is admin
only**, because it strips a label off every book in the house at once with no undo.

### Deleting a collection unfiles its books, and the database is what says so

`ON DELETE SET NULL`, not a cascade, and not a handler loop. A shelf label is not the books
on it, so destroying the label must never destroy them.

It is a database rule rather than application code because a restore and a hand-edited row
both reach the table without passing any handler, and a row left pointing at a destroyed
collection is a dangling foreign key. That also makes `PRAGMA foreign_keys=ON` load bearing
here in a way it was not before: without it the clause is decorative.
`tests/test_models.py` exercises it through Core, so the ORM's own nulling of loaded
children cannot be what passes the test.

### A copy carries its own collection, and the group spans them

Two copies of one title are two objects, and which part of the shelf each lives on is
exactly the kind of fact that differs between them: the paperback in the living room and the
epub on a reader are the household's physical and ebook collections respectively. So
`collection_id` is per row, like `location`, and `POST /api/books/{id}/copies` does **not**
inherit it: the new copy starts unfiled unless the payload says otherwise.

That is deliberately unlike `is_private`, which a copy does inherit, and the difference is
the test for any future per-copy field. Privacy is inherited because getting it wrong
discloses a book. A collection is not, because getting it wrong files a book on the wrong
shelf, which is visible and one press to correct, and because the household that owns both
formats wants them apart.

Two consequences worth having written down.

`copy_count` still counts the whole group, across collections. It answers "how many do we
own", not "how many are on this screen", so a library filtered to Ebooks can show a book
whose card reads 2. The alternative, scoping the count to the current filter, would make the
same book report different numbers on different screens and would require `BookOut` to know
what was being asked, which it deliberately does not.

A **merge** does absorb it, unlike `copy_group`. `collection_id` is in `_MERGEABLE_FIELDS`
for the same reason `location` is: merging two entries for one book, one of them filed,
should leave the survivor on that shelf. It fills a gap and never overrides, so a keeper
already in a collection stays where its owner put it. That is safe in a way absorbing
`copy_group` is not, because a collection makes no claim about other rows.

`/duplicates` ignores collections entirely. Two ungrouped rows naming the same book are
still offered for merge even when they sit in different collections, because a collection is
not a statement that a second row was deliberate: the `copy_group` token is, and it is the
only thing that is. The unique ISBN index is table-wide for the same reason, and is
**not** scoped per collection: making it per collection would let "add this book to Ebooks
too" quietly create a second ungrouped row with the same ISBN, which is precisely the state
the constraint exists to refuse.

### A collection is not an import option, and not a grant scope

Two places it deliberately does not appear.

**The CSV importer does not take one.** Filing an import into "Ebooks" is a real wish, and
it is already served: the import lands, the result links into the library, and the bulk verb
`set_collection` files the selection in one press. A second path to the same state would be
a second thing to keep in step with the first.

**Peer sync does not carry it.** A collection is shelf taxonomy, which `implementation_plan.md`
§9 already refuses to send for `location`, and a collection named after a member would leak
a household member's name besides. It is also not a *scope* for a grant: scopes come from
the stored grant and there are exactly two, and a third keyed on a household-wide label that
any member can rename or delete would silently widen or narrow what a peer sees through an
edit made for shelving reasons. The amendment recording this is A5 in that document.

### A copy is a row, not a count column

`books.isbn` was `unique=True`, so a household that owned two paperbacks of one title could
not say so. Three models were on the table.

**A `copies` count column.** One integer, no query multiplied, the constraint untouched.
This is what Libib does, and Librarika's "2000 items including copies" implies something
similar. **Refused**, and for a specific sentence rather than on principle: a count cannot
say *one is lent out and one is on the shelf*. Nor which one is in the loft, nor that the
battered one cost 2 euro at a jumble sale. Every one of those facts is already a column on
`books`, written per object, and a count would have been a second, weaker way of describing
the same objects. The loan rule is the sharper half: `uq_loans_one_open_per_book` would have
had to become "at most `books.copies` open loans", which is a cross-row aggregate SQLite
cannot express as a CHECK. It would have moved a rule the database enforces into application
code, in an app where that rule is an index precisely because three code paths had to agree
on it and one of them did not.

**A separate `copies` table.** The textbook normalisation: `books` becomes the work,
`copies` the objects. **Refused** on cost and on fit. `location`, `condition`, `format`,
`lending`, `ownership` and the four purchase columns would all have had to move, which is
every filter, sort, export, statistic, bulk action and CSV column in the app, plus the whole
frontend, to express something the existing shape already expresses. The model comments in
`models.py` have said "this copy" about those columns since they were written: a `Book` row
already **is** a copy.

**A copy is a second row, joined by a shared `copy_group` token.** Adopted. Every existing
query keeps working because a copy is a book; the loan rule needed no change at all because
one open loan per row already means one per copy; and the four call sites the feature
investigation warned about (the scan flow, the duplicate detector, the merge logic, the CSV
importer) are exactly the four that changed, which is what "high blast radius" meant.

What it cost, stated so nobody has to rediscover it: the unique ISBN became **partial**,
over the rows whose `copy_group` is null. Those are the rows nobody has declared a copy, so
a re-scan still collides and still answers 409, which is the mistake that constraint has
always been catching. Dropping it outright would have turned the commonest mistake in this
app into a silent second row.

### Deliberate copies and accidental duplicates are told apart by a token

They are otherwise indistinguishable, and getting it wrong in either direction is bad: a
duplicate finder that offers two copies for merge invites somebody to destroy a book they
own, and a scan flow that quietly adds a copy on a mis-scan is the bug the unique ISBN was
put there to prevent.

The token is written by exactly one endpoint, `POST /api/books/{id}/copies`, reached by
pressing something that says "add another copy". Nothing infers it. In particular the CSV
importer never mints one: an export listing a book twice is an artefact of the export, and a
copy is a thing a person says they own, one press at a time.

Three places read it. `uq_books_isbn_single_copy` skips grouped rows. `/duplicates` collapses
each group to one row before matching, so a group can never be reported against itself.
`_MERGEABLE_FIELDS` deliberately omits it: absorbing a loser's group would make the survivor
a copy of the loser's siblings, which the survivor's owner never agreed to.

### The copy group is a shared label, not a self-referencing foreign key

"Is a copy of" is symmetric. Two paperbacks of one title are peers and neither is the
original, so a `copy_of_id` would have invented a distinguished row. Every distinguished row
needs a rule for what happens when it is destroyed, which here is a promote-a-sibling step
that `_purge`, `_create_book`, emptying the trash, merging and any future delete path
would each have to remember, and it has to run in the right order against the unique index
or the promotion is what raises. A shared label has no such row and therefore no such rule.

It is deliberately not a foreign key either, so purging any member of a group leaves the
rest exactly as they were rather than dangling.

The one piece of housekeeping it does need is `_normalise_copy_group`: a group that shrinks
to a single row has its token cleared, because the token is what suspends the unique index
for that ISBN and a group of one should be exclusive again. It runs on a **purge**, never on
a trash, and that is not a detail. A trashed copy can be restored, and clearing the token
underneath it would leave two formerly grouped rows with the same ISBN and no token, which
is precisely what the index refuses. The restore would fail on a button that has nothing to
do with copies.

### The copy's cover file is copied, not shared

Covers are files named by book id, and `covers.forget` deletes by id. Two rows pointing at
one file would mean purging either copy blanks the other's cover while leaving a `cover_url`
pointing at nothing. `covers.duplicate` is `adopt` without the delete, used only for a cover
this app already holds; a remote URL is inherited by assignment, and a book with neither is
resolved from its ISBN like any other new row.

### `_create_book` frees every holder of the ISBN, not the first one

That query returned one arbitrary row, which was correct while `books.isbn` was unique and
stopped being correct the moment several rows could hold one ISBN. Both failures were
measured through the API rather than reasoned about, and they differ by group size, which is
why the smaller-looking fix was refused:

| Set-up | Then scanning the ISBN | Why |
|---|---|---|
| Two copies, **both trashed** | **500**, `IntegrityError: UNIQUE constraint failed: books.isbn` | One row purged, the group shrank to one, `_normalise_copy_group` cleared the survivor's token, and that trashed survivor re-entered the partial index just as the insert reclaimed the ISBN |
| Three copies, **all trashed** | **201**, and a stray fourth row | One row purged, the group still had two members so nothing was normalised, and the insert simply succeeded against rows that still held the ISBN |

Guarding `_normalise_copy_group` against a trashed survivor fixes the first row of that table
and does nothing at all for the second, so the fix is at the cause: fetch **all** holders in
the same live-first order, refuse on the first one that cannot be freed, and free the rest
only if none refused.

Live-first is what decides which row a 409 names: the one on the shelf, not one in the
trash. Deciding in full before destroying anything is the other half, and it is not
tidiness. `_purge` is not undone by the request failing, so a 409 raised part way through a
group used to leave a member holding a book whose cover file had been unlinked.

### A cover file is unlinked after the commit, never before it

`_purge` used to call `covers.forget` first thing. A rollback after that point undoes the
DELETE and not the unlink, so the member still has the book and its `cover_url` now names a
file that does not exist. Nothing logged it.

It predates copies and copies made it reachable, through the ordinary scan flow, for the
reason above. `_purge` therefore returns the id and the caller unlinks after its commit:
`purge_book`, `empty_trash` and `_create_book` all do. Reordering inside `_purge` would have
bought nothing, because `db.delete` only marks the row in the session, and flushing per book
to get closer would put back the 3801 statements the "does not commit" note exists to avoid.

In `_create_book` the unlink sits **after the commit and before `_store_cover`**. SQLite
reuses the id of a deleted row, so the new book may well have taken one of the purged ids:
unlinking later would delete its own cover, and not unlinking at all would hand it somebody
else's.

That window is three lines wide and pinned by
`test_a_reused_id_keeps_the_new_book_s_own_cover`, because a comment saying so is what this
codebase had the first time a cover unlink was ordered wrong. Moving the loop below
`_store_cover` passes all thirty-six other tests in that file: the refusal path never runs
it, so only a test that forces the id reuse and stores a real cover can tell the two orders
apart.

**No instance is left, including the one that looked forced.** A merge lets the keeper
absorb the loser's `cover_url`, so it needs the new URL before it commits, and the first
version of this entry claimed that meant the file had to move before the commit too. It does
not: the URL is `local_url(keeper.id, extension)` and the extension is readable off the
source file without touching a byte. `covers.adoption_url` answers it, `covers.adopt` still
performs the move, and the merge does one on each side of the commit.

Which failure that chooses is the point. Moving first, a raise between the loop and the
commit, which `_normalise_copy_group`'s flush makes reachable and which is the exact shape of
the bug above, left the keeper's row naming a file that had already moved somewhere else.
Deferred, the same raise leaves every file where it was.

**Deferring moved the failure rather than removing it, and the first version of this got the
new one wrong.** With the move after the commit, `covers.adopt` can fail on its own with the
row already saved. That code discarded its answer and swept the loser's id anyway, which
destroyed the bytes and committed a `cover_url` naming a file nobody wrote: strictly worse
than the pre-commit ordering it replaced, which at least stored an honest "no cover". So
`adopt`'s return is **load bearing**. It answers None only when `replace_image` re-raised,
and that function is atomic and removes nothing but its own temporary file, so None means the
source is still the only copy and must not be swept. The row is corrected to "no cover" in
the same breath.

The backfill is **not** the escape hatch here, and leaning on it was the mistake underneath
the mistake: a hand-uploaded cover has no remote source, so `resolve_and_store` has nothing
to re-fetch. It repairs a cover that came from a metadata provider and cannot repair the
files a household cared enough about to upload.

The invariant is therefore worth stating on its own, in the half where it holds: **no cover
file is moved or unlinked before the transaction has committed.** Creation is deliberately
the other way round, in all five paths that write one (`upload_cover`, `_create_book`, both
in `add_copy`, and the backfill), and two things hold that up rather than one.

The asymmetry: a committed `cover_url` with no file behind it is a broken image every reader
sees, while an orphan file is bytes no row references. **An orphan is not harmless, though,
and an earlier draft of this entry said it was.** Nothing sweeps them: `backfill_covers` reads
`stored_ids()` only to skip books that already have a file, and deletes nothing anywhere. So a
file sitting under an id makes that id a permanent non-candidate, and a book landing on it
would show a placeholder the backfill can never repair.

What actually makes creating early safe is narrower and is the sentence to keep: **no path
writes a cover for a row that has not committed.** `_store_cover` and `covers.duplicate` both
run after the insert's own commit and refresh, and `upload_cover` writes for a row that
already exists. An orphan under an id with no row is therefore unreachable, which is why the
window between the write and the commit costs nothing here.
`upload_cover` makes the same trade one level down, writing before it deletes the book's
other formats, because the old order left a book with no cover at all when the write failed.
Do not "fix" either of them to match the moving half.

Two places unlink outside all of this, and neither falsifies the rule. `uploads.replace_image`
removes the base's **other** formats once the atomic replace has landed, before the upload
route commits: a genuine exception, and a narrow one, since what it can lose is a stale
duplicate format of the same book rather than its cover. `backup.restore` clears the covers
directory, but only after its own commit, and by then there is no transaction left to roll
back: it is destroying the previous library on purpose, which is what a restore is.

### Duplicate detection matches on title and author, not ISBN

An accidental exact repeat is already refused by `uq_books_isbn_single_copy`. The case left
to catch is a hardback and a paperback, which are the same book and two legitimately
different ISBNs. Deliberate copies are collapsed out first: see *Deliberate copies and
accidental duplicates* above.
Matching is deliberately lossy because it is a suggestion a person confirms, not an
automatic merge.

### An author is a name on a book, not a row

`books.author` stays what it has always been: one free text `String(500)`, comma separated
when a book credits more than one person. There is no `authors` table and no join table,
and an author page is a `GROUP BY` over that column, exactly as a series page is a
`GROUP BY` over `series_name`.

The reference implementation was read rather than guessed at. **Jelu** (MIT, the closest
architectural sibling) does the opposite: `AuthorTable` is a UUID row with a name,
biography, dates, image and six link fields, and `book_authors`, `book_translators` and
`book_narrators` join books to it. Its merge repoints every book from the losing author to
the surviving one and deletes the loser's row. That is the right design **for Jelu**,
because it has somewhere to put a biography and a portrait, and this repository does not:
the shelf knows a name and nothing else about a person, and Wikipedia enrichment is
deliberately out of scope. A table whose only column is the name it is keyed by buys a
join, an orphan-cleanup rule and a write path on every importer, and answers no question
that grouping does not.

What normalising **would** have bought is identity, and this design does not buy it back.
An author is addressed by `authors.author_key(name)`, a normalised form of the name itself,
so it is not durable: merging "Le Guin" and "Ursula K." into "Ursula K. Le Guin" leaves an
index keyed `ursula k le guin` and neither old key names an entry. An old link keeps working
because the alias row **redirects** it, which is the same treatment a display name gets, so
the key is no more stable than the name it came from and the API takes either.

Stated plainly because it is the cost of the design rather than a detail of it: if a
biography, a portrait or a birth date is ever wanted, the only thing to hang them on is a
key that moves under an ordinary tidy-up, and that is the point at which a real `authors`
table earns its join. What this design buys instead is the thing that argument does not
touch: a merge that writes **zero rows to `books`**, is undone by deleting one row, and
keeps folding the same split every time an import re-creates it.

### Two spellings are one person because somebody said so, not because the strings changed

The rejected alternative is the one the derived design appears to force: make the merge
**rewrite `books.author`** everywhere the folded spelling appears. It was refused for four
reasons, in order of how badly each one bites.

**It is not reversible.** Rewriting is a destructive edit to the field that records what the
cover says, and nothing is left to say what it said before. Undo would need a second table
holding the old strings, which is the alias table with worse ergonomics.

**It does not stay repaired.** `flip_catalogue_name` cannot save a name a source hands over
in catalogue order without marking it (see below), so the same CSV imported twice re-creates
the same split. An alias row folds it again the moment it reappears; a rewrite has to be
done again by hand, and nothing tells anybody it is needed.

**It cannot express a name no book carries.** "Le Guin, Ursula K." splits into two people,
neither of them spelled correctly. The repair is a name typed by a person, which a rewrite
would have to write into every affected book, editing the credit line on books whose
printed credit is not wrong.

**It multiplies across peer sync.** Every rewritten row takes a new `updated_at`, so one
tidy-up re-pushes every affected book to every peer, and two instances that tidy the same
names independently produce two rewrites of the same strings with no way to tell they were
the same decision.

So `author_aliases` stores the decision, `books` is never touched, and undoing a merge is
deleting one row. That is also what licenses the deduplication suggestions to guess: a
wrong suggestion accepted costs one row and one click to undo, which is why
`authors.suggest_merges` is allowed to be lossy in the way `_duplicate_key` already is.

### Three keys, and only the conservative one folds without asking

| Key | Folds | Decides |
|---|---|---|
| `author_key` | case, accents, punctuation (which becomes a space) | automatically, nobody asked |
| `squashed_key` | the above plus every space | a suggestion, somebody confirms |
| an alias row | anything at all | a person, reversibly |

The line between the first two is a counter-example rather than a principle:
`author_key` folds `J.R.R. Tolkien` into `J. R. R. Tolkien`, and the rule that would also
reach `JRR Tolkien` folds `Ann Aker` into `Anna Ker`. An automatic fold has no row to
delete to undo it, so it has to be a difference nobody would call a decision.

### The credit line is split on commas, and the importers' flip rule is not reused

`books.author` is comma separated. Every writer of it says so: `metadata._marc_authors`,
`_bnf_authors` and `google_books` all join with `", "`, and every import path runs a single
name through `flip_catalogue_name` first, so a catalogue-order name is flipped **before**
it reaches the column.

This is a different decision from the one `categories` made, and the two must not be swapped.
Categories are semicolon joined *because* Google's category names contain commas
("Fiction, general"). Author names contain commas too, and the field is comma separated
anyway, because a comma in it means "and" far more often than it means a name in catalogue
order.

`flip_catalogue_name` therefore cannot be reused on a stored credit line. It flips on
exactly one comma, which is also what "Terry Pratchett, Neil Gaiman" has, so applying it
here would mangle every two-author book on the shelf. What is left is a residue: a name
that reached the column in catalogue order anyway splits into two people. That residue is
exactly what merging exists to repair, and the `fragment` suggestion rule is aimed at it.

### The author page is the library, filtered

There is no `/authors/{key}` page. The index at `/authors` lists everybody with their book
count, spellings and merges, and following one goes to `/?author=<key>`, which is the
library grid with a removable chip: the same route `/series` already takes.

The alternative was a page of its own rendering the books itself, which means a second book
grid in a second page folder, kept in step with the first through every later change to a
book card. "Everything by this person" is a filtered library, and the library is already the
thing that renders a filtered library well: it sorts, pages, filters further and shows the
same cards as everywhere else.

### Deduplication has two entry points, and the suggestions are the smaller one

The suggestion rules catch a spelling, an abbreviated given name and a fragment. A
**misspelling** is none of those. `Tolkein` against `Tolkien` shares no word, no surname and
no squashed key. `Fyodor Dostoyevsky` against `Fyodor Dostoevsky` does share a word, and
still produces nothing: the fragment rule wants one name's words to sit *inside* the other's
and neither is a subset, while the initials rule buckets on the last word, which is the word
that is misspelled. Both were run against `suggest_merges` and both return `[]`. They are
exactly what an alias row is for, and the first thing `models.AuthorAlias` names as its
purpose.

So the authors page also folds names by hand: select any two, keep one of their names or type
a third. One name selected on its own is a **rename**, which is the same write and was
unreachable for the same reason. Shipping only the suggested path would have made
deduplication reachable exactly where a heuristic had already guessed for you, which is the
opposite of what the feature is for.

The rules are not therefore redundant. They are what turns "I know these two are the same" into
"here are the six pairs worth looking at", which is the part a person cannot do by scrolling.

### Merging is any member's, and so is undoing it

The same rule as creating and renaming a collection, and for the same reason: it is
reversible, and a shelf only an admin may tidy is a shelf nobody tidies. Deleting a
collection is admin only because it strips a label off every book at once with no undo;
nothing here has that shape.

### The alias mapping is household wide; the shelf is what `visible_to` filters

The same shape as a collection, shipped the day before: **the name is everybody's, the count
is yours.** Every alias applies to every member, so one book is filed under the same person
for all of them, `?author=` resolves identically for all of them, and a `canonical_name` is
not withheld from anybody.

**The privacy rule is one line and it is not on the mapping.** An author entry exists only
because `counts` was populated, and `counts` is populated only from rows a query filtered
with `visible_to`. So an author whose every book is private appears for nobody else: no book
the other member can see is credited to a spelling that resolves to that person, so no entry
is built. The mapping says who a name means; it never says a book exists. A row proves even
less than it looks like it does, because it outlives the book it was created for: an alias
whose spelling nothing carries any more is an orphan that maps a name nothing is credited
with.

**Filtering the mapping per caller was built, reviewed and withdrawn**, and the reasons are
worth keeping because the idea is an attractive one:

* It made **identity** per member. One book resolved to a different key *and* a different
  display name depending on who asked, which is not a narrower view of one catalogue, it is
  two catalogues.
* It **broke an old link**. A spelling in the middle of a chain is on no book at all, so a
  per-caller gate dropped it for everybody and `?author=` answered "nothing by her" for a
  name that had just been merged.
* The merge endpoint gates on a different set (`reachable`, which is keyed on canonical
  names), so **the two gates disagreed**, and `list_authors` handed a member a string that
  the merge endpoint would then answer questions about. The narrow gate leaked what the wide
  one withheld, with no guessing required.

What is still filtered is what a member has evidence for. `AuthorOut.merged` lists a folded
spelling only where it appears on a book the caller can see, and `DELETE
/authors/aliases/{id}` refuses one that does not: **undo what you can see the effect of.**
That is authority rather than secrecy, and its cost is the orphan above, which is unreachable
and therefore undeletable. Accepted: it changes no view, and it starts working again by
itself if an import re-creates the spelling, which is the property the whole design is for.

`POST /api/books/authors/merge` still answers 404 for an author that exists only on somebody
else's private book, exactly as an invisible book is 404 rather than 403: that question is
about the shelf, and any other answer confirms a book is on it.

### Author aliases never cross to a peer

`implementation_plan.md` A6. The peer payload carries `author` as the string on the book, and
that does not change: a peer receives the credit line as printed and applies its own
household's decisions to it, if it has any. An alias is shelf taxonomy in the same class as
`location` and a collection name, and it is one household's reading of its own shelf.

This is the property the rewrite alternative could not have had. Since merging writes nothing
to `books`, a merge changes no `updated_at` and produces no sync traffic at all.

### Merging repoints through the ORM, not a bulk UPDATE

A bulk `UPDATE ... synchronize_session=False` leaves the session's loaded collections
stale, and the `db.delete()` that follows cascades straight through them, deleting exactly
the notes, quotes, loans and statuses just moved to the survivor. The rows are reassigned
object by object and the losers are expired before deletion.

Relatedly, the losers release their ISBN in **its own flush** before the keeper absorbs it.
Doing both in one flush puts them in a single `executemany` where the set lands before the
clear and trips the unique index.

### A quote is its own table, not a page number on a note

BookLogr, the Apache-2.0 reference for this feature, has no quotes table: it adds a
nullable `quote_page` to its notes table, and a saved quote is a note that happens to
carry one. That was the cheaper option here too and it was refused, for a reason that
shows up the first time anybody asks a question of the data: nothing in that shape can
tell a quote from a note whose author remembered the page.

The sharper reason is what the two fields are for. `quotes.text` is meant to be a
**faithful transcription** of somebody else's sentence; `notes.content` is the member's
own words about the book. One column holding both is the column where the verbatim
promise quietly stops being true, and it is also the column somebody will later want to
render as a blockquote and be unable to.

So `quotes` carries `text`, an optional `page`, and an optional `note` for the remark. The
excerpt and the remark are separate columns for the same reason the table is separate.
**BookWyrm** does the same, and it is the best worked example of quotes from books
anywhere; it is also **ACSL v1.4**, which is compatible with neither GPL nor MIT, so it
was read and not borrowed from. Nothing here is derived from its code.

### What was left off a quote, and why

Four fields that a reference implementation has and this one does not. Recorded so nobody
adds one back thinking it was an oversight.

| Field | Where it exists | Why not here |
|---|---|---|
| `endposition` | BookWyrm | It stores a **range**, needed because it also renders percentages and ebook locations in a federated post. There is no reader here and no range to draw. |
| `position_mode` (page or percent) | BookWyrm | Same reason. `reading_progress` carries a percent because an audiobook has no pages; a quote is copied out of something with a page or out of nothing at all. |
| per-quote `visibility` | BookLogr | It has a **public profile**, so a row-level visibility is what decides whether the world sees a quote. Nothing here is public, and privacy in this schema is a property of the book. |
| a favourite flag | BookWyrm has social `favorites` | That is other people liking a post. There is no social layer here, and "my favourite of my own quotes" is a second ranking beside the shelf's tags. |

### The page is an integer, so a preface has no page

`quotes.page` is an `Integer` bounded 1 to 100,000, where BookWyrm's equivalent is free
text. Free text would take "xiv", "loc. 3312" and "about a third in", all of which somebody
will want; what it would not do is sort, and a book's quotes coming back in reading order
is the only ordering that makes the list worth reading down.

The cost is real and is accepted rather than worked around: a passage from a roman-numbered
preface is saved unpaged, and unpaged quotes sort to the end. If free-text positions are
ever wanted, they are a second nullable column, not a widening of this one, because
widening it silently unsorts every list that exists by then.

`ck_quotes_page_bounds` states the same rule in the database, because a restore inserts
through Core and never sees `QuoteCreate`. The number lives once, in
`models.MAX_PAGE_NUMBER_IN_A_BOOK`, and `schemas/progress.py`, `schemas/book.py` (twice)
and `csv_import._int` now read it from there: it was written out **four** times before
this change, and a CHECK that disagreed with a schema bound would answer 500 for exactly
the values between them. `csv_import` was the one that stayed behind on the first pass,
found on review, and it is the one that matters most: an importer admitting a page count
the API refuses is a second answer to the same question.

The **length** ceilings are enforced the same way and were nearly not.
`quotes.text` is `String(2000)`, and SQLite ignores VARCHAR width entirely: a Core insert
of 50,000 characters stored 50,000, measured. So the model and the migration both carry
`ck_quotes_text_bounds`, covering `text` and `note`, and the docstrings that said the
ceiling was "in the database and not only in the schema" are now true rather than
aspirational. Nothing member-facing could reach it (only `backup.restore` bypasses
`QuoteCreate`, and it is admin-only), so this closed a false claim rather than a live
hole, which is exactly the kind of thing that becomes a live hole two features later.

### A quote is visible to whoever can see the book

Two precedents in this codebase point opposite ways. `get_notes` returns **every member's**
notes on a book anyone may read; `list_progress` returns **only the caller's own** rows,
because a reading log is a diary about a person rather than a fact about the book.

Quotes follow the notes. A passage is a fact about the book, and copying one out is the
household saying "this is worth reading", which is the whole pleasure of the feature. The
alternative would be a per-row privacy flag, and that is the expensive part: privacy in
this schema is a property of the **book**, expressed once in `visible_to()`, and a second
rule that every query has to remember is the one that eventually gets forgotten.

The copyright argument cuts the way it first appears not to. A quote is a verbatim excerpt
of somebody else's work, but showing it to the four people who share the shelf the book
sits on is not publication: this app has no public profile, no feed and no federation, and
a quote leaves the instance only in the member's own backup. That is what makes "follows
the book" safe here and would not make it safe in BookWyrm, which is federated and
therefore has per-status privacy. What the argument does buy is the length ceiling:
`QUOTE_TEXT_MAX` is 2,000 against `MAX_NOTE_LENGTH`'s 10,000, so the table cannot hold a
chapter.

The consequence to state plainly: a quote from a private book is invisible to everybody
but its owner, because the book is, and an invisible book is 404 rather than 403.

### A quote belongs to a copy, not to a work

Multiple copies shipped first, so a book row can be one of several joined by a
`copy_group`, and a quote from "the paperback" is arguably a quote from the work. It hangs
off the **book row** anyway, for one concrete reason: the page number is a fact about an
edition. Page 214 of the paperback is not page 214 of the hardback, and a quote promoted to
the work would carry a page number that is wrong for most of the rows it then appears
under.

Everything else per copy already lives this way (notes, loans, reading progress), so this
is the existing shape rather than a new one, and `_repoint_relations` moves quotes to the
survivor on a merge exactly as it moves notes. Merging two rows that were two printings
does leave their page numbers describing a printing that is no longer named; the
alternative is refusing the merge, which is worse.

`POST /{id}/copies` deliberately copies **no** quotes, for the same reason it copies no
notes or reading state: they belong to a person and an object, and the copy is an object
nobody has read yet.

**The cost this pays on `/quotes`**, which the first version of this entry left out: two
copies of one title render identically there. `QuoteCard` shows the title, the author, the
cover, the page and who saved it, and every one of those is the same for the paperback and
the hardback; only the link target differs. Accepted rather than fixed, because the fix is
`format` and `location` in the card footer and that is metadata about the object on a card
whose subject is a passage. It is the right thing to add the first time somebody actually
cannot tell two rows apart, and the schema is ready for it: `QuoteWithBookOut` already
takes its book fields as flat scalars, so it is two more columns in the same `SELECT`.

### There is a cross-book quotes page, and it is a book listing

`GET /api/books/quotes` and `/quotes` in the app exist because a quote saved and never
re-read is a write-only field. It is the feature's main pleasure in BookWyrm and it is
cheap here: one endpoint, one page folder.

It is also **a second book listing wearing a different hat**. Every row carries a title, an
author and a cover, so `visible_to()` filters the rows *and* the count, and a quote on
somebody's private book is neither listed nor counted.

**The count is spelled `count(Book.id)`, not `count(Quote.id)`, and that is a decision.**
The two are identical over an inner join on a primary key that is never null. The
difference is that `TestEveryBookQueryIsFiltered` identifies a book query by the arguments
to `query()`, so the `Quote.id` spelling put the count outside the guard entirely: removing
its filter was measured to produce **no** offender, while removing the row half's filter
correctly reported the file. Both critics found this independently, which is the strongest
signal that review process produces. The alternative, teaching the rule about
`.join(Book, ...)`, was measured too and refused: 30 inspected statements to 39, three of
them correct code needing fresh exemptions. The rule's own docstring now records the
join-only blind spot, because the class is wider than this one instance.

Editing is deliberately **not** offered there. A quote is corrected on the book it came
from, where the page number and the passage can be checked against the book in somebody's
hand, and a second editor would be a second place for the same rules to be got wrong.

**It pages with numbered Previous/Next, which is a third idiom in this app**, and the
reason is the row height. Home uses `useListBooksInfinite` with a "Load more" button; the
loans and trash lists ask for one large `page_size` and offer no controls at all. Neither
suits this one. A quote is up to 2,000 characters, so a page of fifty is a column of
unpredictable height that an infinite list makes unnavigable: with "Load more" there is no
way back to something seen two screens ago except scrolling past everything added since.
One large page is worse again, because the ceiling here is a household's entire history of
saved passages rather than its shelf. Numbered pages give a stable position to return to.
That is three idioms in one app, which is one more than anybody wants; the honest reading
is that Home's infinite list is the odd one out and the others should converge on this,
not that this should have copied one of them.

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

### The test suites were slow for reasons nobody had measured

Both suites were profiled rather than guessed at, and every intuition about
where the time went was wrong.

**The backend was not CPU bound.** Two xdist workers used **0.68 cores between
them**: the suite was waiting on fsync, not computing. Every test drops and
recreates nine tables and seeds 105 tags, so a run performs tens of thousands
of DDL statements and inserts against a database deleted microseconds later.
`PRAGMA synchronous=OFF` in tests and the database on `/dev/shm` took it from
**710s to 133s**. `SQLITE_SYNCHRONOUS` defaults to `FULL` and is whitelisted,
because it reaches a statement that cannot be parameterised; production keeps
FULL, which is what makes a commit survive a power cut on somebody's only copy
of a hand built catalogue.

Before that, `pytest-xdist` at `-n 2` had already halved it from 1370s. `-n 2`
and not `-n auto`: the CI pod is capped at two cores, and `auto` spawns one
worker per core only to be throttled back, which is the same work done slower
and makes the pod look like it needs a bigger limit.

**The frontend was not slow because of its tests.** `environment` was **168s of
a 245s run**, building a jsdom once per test file, and 11 of 78 files touch no
DOM at all. Those carry `@vitest-environment node`. The larger win was swapping
jsdom for **happy-dom**, which took the run to 178s.

**happy-dom does not inherit CSS custom properties down the tree.** A
`--color-*` token set on `documentElement` reads back on that element and
resolves to `""` on every descendant, measured with a two line probe. The
wallpaper resolves its ink, bloom and page from a child, so `isColour()` sees
empty strings and nothing is painted. Three files are pinned back to jsdom with
`@vitest-environment jsdom` for that reason alone; if happy-dom ever fixes it,
the pin comes off.

**Then the tests themselves.** 29 of 40 `user.type` calls became a single
`fireEvent.change`. Typing thirteen characters costs thirteen async round trips,
and a field with no per keystroke behaviour tests the same thing either way.
That took 178s to **140s**. Two calls keep `user-event` deliberately, because
`"{Enter}"` and `"{Escape}"` are keyboard semantics rather than text.

**What was refused: `deps.optimizer`.** It would pre-bundle dependencies with
esbuild and take a bite out of the 51s `import` bucket. It also produces a third
module graph, neither the dev server's nor Rollup's production build, and
`vi.mock` cannot intercept an import already inlined into a bundled chunk. Two
of the four mock sites here target `react-router-dom`. The failure mode is a
silent false pass, which is the one this repository is least willing to buy
speed with.

Net: a full local gate went from about 27 minutes to about 4.

### The per-test reset deletes rows, and two faster designs were refused

Measured in the CI pod, database on tmpfs, `synchronous=OFF`, warm:

| Reset strategy | Per test |
|---|---|
| drop, create and seed (what this replaced) | 58.8ms |
| **delete every table, reseed the tags in bulk** | **3.1ms** |
| keep the seeded tags, delete the rest | 1.0ms |
| open a transaction and roll it back | 0.8ms |

The suite went from 134s to **92s** on the second row. The two faster rows were
both refused, and the reasons matter more than the milliseconds.

**Rolling back a transaction per test** was built, reviewed by three seats and
abandoned. Binding every session to one connection means savepoints form **one
stack, not one per session**: a session that opened its savepoint first and rolls
back destroys the committed work of every session that committed after it.
Measured against the running application, that makes a privacy test vacuous, and
silently: a test asserting "another member gets 404" gets its 404 just as readily
when the book was never written at all. Sixty five privacy tests assert an
absence with nothing proving the row survived to the assertion, so a broken
`visible_to()` under a wiped fixture is a **green** run.

It had a second fault of its own. It held a write lock for a whole test rather
than a statement, and one unguarded `connection.close()` in its teardown could
leave a connection checked out holding that lock for the life of an xdist
worker. Observed once in thirty runs as 423 failures and 121 errors; twenty one
later runs could not reproduce it, and no seat could name what made the rollback
raise in the first place. The guard is worth having; the design is not, when a
row delete is three milliseconds slower and cannot fail that way at all.

**Keeping the seeded tags** is wrong for a duller reason: `backup.restore`
deletes and reinserts the tags table and `_repair_seeded_tags` rewrites
`is_predefined`, so a test can legitimately mutate a predefined tag and the next
test would inherit it.

The reset calls no `seed_tags()`. That helper opens its own session, which is a
second connection, and the point of this shape is that a reset never needs one.
Ids still restart at 1, which `covers_dir` depends on, because nothing here uses
`AUTOINCREMENT` and SQLite reuses the highest free rowid.

**One number in this file was wrong for a whole day and is worth naming.** The
rebuild cost was derived as 40.6s over 3236 rebuilds, giving 12ms. 40.6s was a
two worker wall clock, so the division halved a figure that direct measurement
puts at 58.8ms. A derived number that nobody measured is the kind this
repository is meant to catch.

### The remote test runner was reporting on a tree nobody had

It ships the working tree by piping `tar` into `tar -xf` on a **persistent
hostPath**. Extraction adds and overwrites and never deletes, so a file removed
locally lived on in the runner's copy indefinitely. A reviewer's scratch test,
deleted an hour earlier, still failed `ruff check .` and contributed two pytest
failures against a tree that no longer contained it.

`rm -rf` before extracting fixed that and created a worse fault: two runs share
the hostPath, so the second deleted the first's working directory mid run. The
symptom named neither cause, being `Module not found .../vitest/dist/workers/
forks.js` followed by a rolldown panic reading "Failed to get current dir". Two
runs were spent blaming a vitest config.

Each run now extracts into `/work/repo-$POD` and removes it in the exit trap.
The dependency caches stay shared at `/work/cache`, which is the reason the
hostPath exists. This matters more than it did: the runner serving this project
is at `concurrent: 2`, so two real CI jobs can now land together.

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

### Every request declares `Accept`, and a download declares something else

A browser `fetch` with no `Accept` sends a wildcard, and a forward-auth portal reads
exactly that header to decide whether an unauthenticated request gets an answer it can
handle or a redirect to a login page. Measured against the live deployment, same URL and
same expired cookie:

| Request `Accept` | Portal answer |
|---|---|
| `application/json` | 401 |
| `*/*` | 302 |
| absent | 401 |

The third row is the portal being consistent rather than a third case to design
for: a browser `fetch` never sends no `Accept`, it sends `*/*`, which is row two.
It is written down because the first measurement of it was taken with curl, which
sends `*/*` unless told otherwise, so the wildcard was measured twice and one of
the two was recorded as "absent". Re-measured with the header genuinely removed:
401.

`customFetch` therefore sends `application/json`, which is also simply true: every
operation in the schema declares a JSON response.

`downloadFile` sends `application/octet-stream, application/zip, text/csv,
application/json` instead. Its two callers fetch a CSV or JSON export and a ZIP backup, so
`application/json` would be a lie, and a wildcard would put the request back on the
redirecting side of the same negotiation.

### The endless spinner was two faults, and neither was wrong on its own

Reported by the owner, reproduced against the deployment: a page that reloaded for ever
behind a spinner. The mechanism needed both halves.

1. The request had no `Accept`, so an expired portal session arrived as a **302**, not a
   401. Under `redirect: "manual"` that is an opaque redirect, which `mutator.ts` handles
   by clearing the session and reloading, because only a top-level navigation is followed
   across origins.
2. The reload could not reach the portal. `workbox.globPatterns` included `html`, so
   `index.html` was in the precache, and `precacheAndRoute` applies a `directoryIndex`
   that defaults to `"index.html"`: a request for `/` was rewritten, matched, and answered
   from the cache with no network involved. The app booted looking signed in, made a
   request, was redirected, and reloaded again.

Both are fixed. The second is fixed by dropping `html` from the glob rather than by
setting `directoryIndex: null`, which removes the class instead of the instance: with no
HTML precached there is no cached shell for any route, rewritten or exact, to serve. The
cost is that there is no offline app, and there never usefully was one, because every
screen's content comes from an API behind the same portal.

**A client that already has the bug cannot be fixed by deploying this**, and the way out
follows from the mechanism above. Such a browser is served `/` from its old precache, so
it never makes a navigation the portal can answer, and `registration.update()` fetches
`/sw.js` with redirect mode `"error"` by specification, so the portal's 302 fails the
update: the old worker and the old bundle both stay. The escape is that only `/` and
`/index.html` are rewritten by `directoryIndex`. **Any other path** (`/settings`,
`/book/1`) misses the precache, reaches the network, and gets the portal, after which the
worker updates normally. That escape only became true with the SPA fallback below: until
then those paths reached the network and were answered **404** by the server, so the
reader got an error page rather than the portal.

The trap worth remembering is the previous fix. `navigateFallback: undefined` was added
for this exact bug and its comment described it as solved. It removed the NavigationRoute
and left the precache route, and the config kept saying "fixed" from v0.2.0 to v0.5.0
while the build kept shipping it. Hence `frontend/scripts/check-build.ts`, which
builds the app and reads `dist/sw.js`: the config was never the thing that was wrong.

### `isRedirect()` is `opaqueredirect` only

It also accepted `status === 0`, on the grounds that missing a redirect put the spinner
back. That was the wrong trade to make: a false positive here is not a wrong message, it
is `clearSession()` plus a page reload, which is the most destructive thing this client
does.

Under `redirect: "manual"` and the default request mode there is no other resolved
response with status 0. The spec gives an opaque-redirect filtered response
`type: "opaqueredirect"` and `status: 0` together, the only other zero-status response is
an opaque one, which needs `mode: "no-cors"` and nothing here sets it, and a transport
failure rejects rather than resolving, which is the `NetworkError` path.

### The reload is counted, and an uncountable one is not taken

`window.location.reload()` with no guard is a loop waiting for its next trigger, and this
one had one. `mutator.ts` records a timestamp in `sessionStorage` before reloading, and a
second edge sign-out within 30 seconds dispatches an event instead: the shell swaps in
`SessionEndedPage`, which says what happened and offers the same navigation as a button.
An infinite loop degrades to a sentence rather than to a spinner.

**The guard counts page loads, not calls, and the distinction is a bug that was in it.**
The library screen has six requests in flight (four in `useLibrary`, the `useListBooks`
inside `useUnconfirmedCount`, and the auth config; seven under proxy auth), so an expiry
resolves six opaque redirects in one batch. Counting calls, the first reloaded and the
other five read a marker aged about zero milliseconds, concluded they were looping, and
put up a screen saying reloading had not helped before the reload had happened at all. A module-level
`reloadRequested` closes it: the rest of a batch is the same event, and module state dies
with the document, which is the boundary wanted.

**What bounds the 30 second window**, since the next reader will be tempted to tune it:
it must exceed one loop cycle, which is a cache-served navigation plus a boot plus the
first request, so seconds; and it must fall short of a person signing in again at the
portal and coming back. Nothing in between distinguishes them. A slow portal makes the
window *safer* rather than riskier: no script of ours runs during the navigation, so a
slower round trip lengthens the measured interval and makes the loop branch less likely
to fire.

`sessionStorage`, not `localStorage`: this is one tab's own reload and should die with the
tab. Storage access is wrapped, because a private window or blocked site data can throw,
and failing to *record* the marker is treated as "do not reload" rather than as "reload
blindly", since a reload nothing can count is exactly the loop being guarded.

### The dead-end branch is the one place that must empty the query cache

Every other way a session ends leaves the document, and memory dies with it: `signOut`
clears the client itself, and `endSession` navigates to `/login`. The edge branch does
neither, so it is the only path that ends a session while the tab lives on. Without
`queryClient.clear()` in `useSessionEndedAtEdge` the client would go on holding every
book, loan, quote and setting the reader had fetched, behind a screen telling them their
session is over.

### `clearSession()` leaves the saved searches and the last location behind, and that is accepted

It removes `token` and `user`. A reader's saved searches and their last shelf position
(`lib/savedSearches.ts`, `lib/lastLocation.ts`) survive in `localStorage`, and `signOut()`
does not clear them either, so on a shared browser profile the next person to sign in
inherits both. What that discloses is what somebody searched for and one book id, never a
book's contents, and every read still goes through `visible_to()`.

Accepted rather than fixed, because it is per device by design: these exist so that a
browser remembers where you were, and clearing them on sign-out would also clear them for
the one person on their own laptop who is the common case. The cost is stated so the next
reader can weigh it rather than discover it. If it is ever fixed, both stores have to be
cleared in `clearSession()`, not in `signOut()`, or the edge path will keep them.

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

### The theming series is one changelog entry, under v0.4.0

Four phases landed separately (the token repair, seven palettes, ten wallpapers, the
picker) and only the last of them is a thing a reader can do anything with, so the entry
was written once, when the picker shipped.

**v0.3.0 was never tagged.** Its section stays as written, because its contents are in
`main` and the section is a true record of them; the next tag is v0.4.0 and carries both.
A version in the changelog with no tag beside it is a fact about git, not a hole in the
record, and folding the bug fixes into the theming release would have lost which was which.

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

### The wallpaper picker is a route, and the wallpaper is not a switch

`/settings/appearance`, not a section of the settings list and not a dialog. The reason is
the one the design turns on: the only honest preview of a wallpaper is the page. The
pattern is painted on `body`, so the picker is the app surface with the controls laid over
it, a choice shows itself the moment it is made, and there is no Save button because there
is nothing to defer. A dialog would have covered the thing being previewed.

The preview is the reader's **own first two book cards**, taken from the query cache and
never fetched. Invented sample content is not the real page, and a request made to fill a
preview would put a book on screen that the reader did not ask for. Where the cache holds
nothing, the picker says so rather than drawing a placeholder book.

**Off is a value in `wallpaper`, not a flag beside it.** The field already answered two
questions (which pattern, or a different one every visit) and a boolean next to it would let
the two disagree: off with a pattern named, or on with none. `WALLPAPER_OFF` is the third
answer, and `patternFor` is the one place that reads it. It is the only id that does not
degrade to a random pattern, because an off that came back as a wallpaper would be a choice
the app declined to keep.

Two off states, and they are not the same thing. A chosen off is `pattern === null`; the
system asking for more contrast is `wallpaperOff`. Both clear the body, only one is worth
explaining, and the picker says which happened. The choice stays recorded and stays marked
underneath the explanation, because it is what comes back when the system stops asking.

### The swatches read the stylesheet rather than restating it

A palette tile draws page, card, ink and the two accents in that palette's own values, and
none of them is a hex in TypeScript. `readPaletteColours` puts each palette on the document
in turn and reads the computed custom properties back, which is what `wallpaperColours`
already does for the wallpaper's ink and for the same reason: thirty five values restated
would be the same eleven ramps written twice, and a tile that disagrees with the palette it
applies is a preview that lies.

The read is wrapped in `withPalette`, which restores the attribute in a `finally`. It runs
from a **layout** effect, so the intermediate states never reach a paint. A passive effect
would paint them.

**`ThemeProvider` applies from a layout effect too**, and that changed when the picker
shipped. It was a passive effect, which was invisible while the only appearance change was
the one `main.tsx` had already painted before React mounted. From a picker, where a choice
is made with the page open, a passive effect shows one frame of the previous look. The
component that applies cannot offer a weaker guarantee than the components that read.

`withPalette` is also what keeps the wallpaper tiles honest, for a different reason: a
child's effect runs before its parent's, so a component that read the tokens after asking
for a palette change would read the previous palette every time and show a grid one choice
behind.

**The wallpaper swatches are drawn at true opacity, and are large instead.** A swatch at
three times the page's opacity is a lie about what is being chosen, and somebody picks
khatam and finds nothing there. `background-size: contain` with four columns inside
`max-w-6xl`, less the page's padding and the section's, is a 257px cell, against tiles that
repeat at 240px to 300px, so nine of the ten are drawn at 86% to 107% of the size they have
on the page. Asanoha, at 420px, is the one that shrinks, to 61%.

### The front door does not shuffle

A device with nobody on it paints Endpaper, the system's mode and **Willow Bough, fixed**.
`readCachedAppearance` returns that when no account is named and the cache is empty, and the
new-account default, which is Surprise me, when one is. Asking for an account is what tells
the two apart, so no caller has to know which is which.

`LoginPage.tsx` calls itself "the first screen anyone sees, so it is the one that decides
whether the app looks made or assembled", and a door that is a different pattern every visit
reads as a slot machine. Randomness is a pleasure once you are inside. An admin-set login
image, where there is one, covers it anyway.

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

### The book detail page is six collapsible groups under an identity block

Seventeen panels in one column, three of them free text forms. Nothing caused it and
every feature added one panel, which is how a page becomes a form. The groups are
`reading`, `filing`, `copies`, `lending`, `writing` and `about`, and they collapse.

Collapse rather than tabs: a tab hides that content exists at all, while a collapsed
section keeps a labelled handle visible, which is the whole point for a panel that is
empty on most books. What stays outside every group is chosen as deliberately as what
goes in: the cover, title and author; the loan badge, which is the one thing a member
scans a shelf for; the privacy control, because a control over who can see a book must
not be somewhere you go looking for; the delete button, because a destructive action
hidden in a fold is a worse surprise than a long page; and `EnrichPanel`, for the reason
below.

`DiscussToggle` sits in `reading` rather than in `lending`, against the grouping first
proposed. Its own docstring is the argument: it is a fact about a reader, not about
where the object is.

**The four handles that can name an errand do; the two that hold content name the
content.** "Your reading", "Filing this copy", "Your copies" and "Lending this copy" say
what you came to do. "Notes and quotes" and "About this book" do not, and the exception is
written down rather than left for a reader to notice: both are read for what is in them,
and no verb describes either better than its nouns do. An earlier draft called the second
one "Organisation", which is a label over a drawer rather than something a person arrives
wanting to do, and the third "Copies and condition", which is two errands joined by "and"
and stopped being two the moment `CopyPanel` lost its own disclosure. No title may repeat
a heading or control inside its own section, which is why this is not "On the shelf" (an
ownership button) or "Lending" (the willingness label): a test counts each name and
requires exactly one button.

**`about` is the one group that is not always drawn.** The other five keep their handle
on a book that has nothing in them, because an empty group still offers its act: lending
a book nobody has borrowed is the reason the lending section exists. `about` offers no
act at all, so with no blurb and no categories its handle would open onto nothing and it
is left out.

**`EnrichPanel` is outside every section**, at the foot with the two dialogues it raises.
It was briefly inside `about`, which is exactly wrong: `about` is drawn only when the
catalogue already knows something, so the button that fetches what the catalogue knows
would have been hidden on precisely the books that need it. That is the same fault as the
bug its own comment records, reached by a different route.

**Five panel headings dropped from `h2` to `h3`.** `ReadingPanel`, `ProgressPanel`,
`OwnershipPicker`, `ShelfPanel` (twice) and `CollectionPicker`. Flat `h2`s were correct
on a flat page; inserting a section heading above them is what made them wrong, and a
heading list that shows twelve `h2`s in a row shows no grouping at all. This is the one
place the "no panel changes" scope rule bent, and it bent because that rule exists to
keep a diff reviewable, not to preserve a heading level whose meaning the change removed.
Each site carries a comment saying why, or the next reader repairs it back.

Six panels label themselves with a bold `<p>` rather than a heading at all
(`StatusPicker`, `TagEditor`, `LoanPanel`, `NoteList`, `QuoteList`, `CopiesPanel`), so
they appear in no outline either way. That predates this change and is left alone here:
promoting them is a separate pass with its own reasons, and doing it in this diff would
have hidden the six demotions among a dozen edits. `CopyPanel` was the seventh and is not
left alone, for the reason below: its label is the one this change itself demoted, from a
`<summary>`.

**`CopyPanel` lost its own `<details>`.** It opened itself on a copy with a condition or
a price recorded. Nested inside the `copies` section that signal was swallowed (on a
single copy book the section arrives closed) and the fields sat two clicks deep. One
disclosure idiom per page.

Its label became an `h3` rather than the bold `<p>` six other panels use, and that is not
cosmetic: it was a `<summary>`, which is focusable and announced, and a `<p>` is announced
as nothing. Dropping the wrapper without this would have traded a redundant disclosure for
a lost landmark and left "Your copies" the one section with no heading inside it.

### A section's stored state is three values, and absence is one of them

Which sections open is conditional on the book (`sectionDefaults` in
`pages/BookDetail/hooks.ts`), so "closed" and "nobody has said" cannot be the same
stored value. If they were, closing the loan section on a borrowed book would last until
the next visit, when the condition would win again and open it. Absence therefore means
"use the book", and `resolveOpen()` in `lib/sectionState.ts` is the only place that rule
lives.

The defaults are frozen per book, not once. Left live, marking a loan returned would flip
the lending default to closed and fold the section away under the hand that had just used
it. Keyed on the book id rather than on the ref being empty, because `routes.tsx` renders
`/book/:id` with no `key` and the copies section links straight to a sibling copy: a
freeze that armed once would hand the second book the first one's loan, copy count and
blurb, and it is one click away from the section this change added.

### Section state is per device and per section

`localStorage`, like `libraryView` and the saved searches, and for the same reasons: a
habit rather than household data, no endpoint, no schema, no migration, and the cost of
getting it wrong is one tap. Per member would be a settings round trip and a backend
change for a preference that differs between a phone and a laptop anyway.

Per section rather than one state for the page, because a single flag could only ever
mean "collapse everything", which throws the conditional defaults away. One entry per
section id, and an id no section answers to any more is kept rather than pruned: nothing
renders it, and a section that comes back finds what the reader last said. Only a value
that is neither `open` nor `closed` is dropped. Every read and write is wrapped, and a
page with no stored value at all is the conditional default, which is the state the whole
design is written for.

**The consequence of those two decisions together, and it is load bearing: an entry is
per section and not per book, so the first tap on a section ends its book-conditional
default for every book on that device, permanently.** Somebody who folds the loan section
away on one borrowed book will not see it open itself on the next one. That is the
intended reading of "a reader's own choice wins", the alternative being a page that
re-opens what they closed, but it does mean the conditional defaults are a first-visit
behaviour rather than a permanent one. Clearing site data is the only way back.

### `writing` is fixed closed because the data to decide it is not on the page

`BookOut` carries `active_loan` and `copy_count`, so lending and copies decide their own
default from the book the page already has. It carries no note or quote count: those
arrive from `/notes` and `/quotes`, which are separate requests, so a conditional default
there could only open the section after they landed. That is a flicker, and a fixed
default is better than one. Closed is also the honest guess, because notes and quotes are
empty on most books in a household catalogue. Put a count on `BookOut` and this becomes
conditional like the rest.

`about` is fixed too, open, for the opposite reason: it is drawn only when it has a blurb
or a category, so by the time the default is asked for, the answer cannot be no. It still
collapses, because a blurb is long and somebody who never reads them should be able to
fold it away once and for good.

### A collapsed section is hidden, not unmounted

`aria-controls` has to point at an element that exists, or the relationship it names is a
dangling id. Unmounting would also throw away whatever is half typed inside the section,
so collapsing by accident would lose a note. The `hidden` attribute keeps the panel out of
the accessibility tree and out of the tab order, which is the part that matters, and the
page holds no more DOM than the flat column it replaced.

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

### Each test runs in a transaction, and pysqlite is not allowed to open it

Every test used to drop nine tables, recreate them and reseed 105 tags. That was about
1690 rebuilds a run, and the dominant cost once the database moved to tmpfs and
`synchronous` went OFF. It is now one rebuild per xdist worker, with each test inside a
transaction that is rolled back. Measured on the CI host at `-n 2`: 134.44s for 1683 tests
before, 93.99s to 101.01s for 1689 after, over four runs.

Two pieces of it are load-bearing and fail silently. `join_transaction_mode="create_savepoint"`
is what survives the application committing constantly: without it the first `db.commit()`
in a request ends the outer transaction. And pysqlite has to be taken off transaction duty
(`isolation_level = None`, plus a `begin` listener that emits `BEGIN`), because it opens a
transaction before an INSERT, UPDATE or DELETE and before nothing else, so `SAVEPOINT`
would stand alone in autocommit. Measured before writing the fixture: two tests writing two
rows each left **4** rows behind, and 0 with the listeners in place, on the real engine.

Neither failure breaks the test it happens in. It leaves rows for whoever runs next, which
is why `tests/test_conftest.py` asserts the isolation with an ordered pair of tests rather
than trusting it.

`@pytest.mark.real_database` opts a test out and restores the old behaviour, for DDL, a
second connection, or state that has to outlive a commit. The list and the reason per entry
are in [testing.md](testing.md). The rule is to opt out and say why rather than to force a
file into the transaction: a test that passes alone and fails in a suite costs more than
the seconds it saves.

## Reference implementations: what may be read, and what may not be copied

Endpaper's features were designed against prior art rather than invented, and
two of those sources carry licences that make copying a legal problem rather
than a stylistic one. Recorded here because the document that held it was a
session plan and session plans are deleted.

**BookWyrm is ACSL v1.4**, which is not OSI approved and is compatible with
neither GPL nor MIT. It is the best worked example of quotes from books in the
field, and it is the one that must not be borrowed from literally. Read it for
design; do not copy code without checking the terms. The quotes feature here was
argued in its own words for exactly this reason.

**Koha is GPL.** This project is not, so Koha is a source to read for behaviour
and not a source to lift from. Its value was always the holds queue and
notification model, which is the part deliberately scoped out.

**Reusable, and used as such:** Jelu (MIT) for author pages and merging, BookLogr
(Apache-2.0) for quotes beside notes. Where a design here departs from Jelu, the
departure is argued in the author entries above rather than assumed.

**Two features had no useful reference.** Collections and multiple copies are
shaped by this codebase rather than by the field: what decides them is
`visible_to()`, the sync payload in `implementation_plan.md`, and `books.isbn`
being unique. Reading a competitor will not tell you what breaking that
constraint costs here.
