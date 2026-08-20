# Security

What is enforced, where, and why. Read [data-model.md](data-model.md) first for the
privacy rule this builds on.

## Authorization

Access to a book is decided in **one place**: `backend/dependencies.py`. Endpoints ask for
a book through a dependency rather than fetching one and writing their own checks.

| Dependency | Grants | Used by |
|---|---|---|
| `book_for_read` | The book is public, or the caller added it | reading a book, reading and adding notes, setting your own status |
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

### Where the rule must be applied by hand

`visible_to()` is a query predicate, not a row-level policy, so **every query that returns
or counts books has to apply it**. That includes the four statistics aggregations and the
loans list, which would otherwise disclose the title of a book the caller cannot see along
with who currently has it. Forgetting it in a new endpoint leaks data and nothing else in
the stack will notice.

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

### The Google Books API key is never returned

`GET /api/settings` returns a masked preview plus a boolean, never the key. The masking is
**presentation, not storage**. Masking the stored value instead would break every lookup
while still looking correct in the settings screen, which is why a test pins the stored
value directly. The 400 raised when the key is missing does not echo it either.

## Rate limiting

Five things are limited, for three different reasons:

| Route | Limit | Keyed on | Why |
|---|---|---|---|
| `/auth/login` | 10 / min | username + address | Bounds guesses at a token |
| `/auth/switch` | 10 / min | username + address | The same counter: a password check that returns a session on another account |
| `/auth/register` | 5 / hour | address | Bounds account creation |
| `/api/imports/*` | 3 / min | username | One call writes thousands of rows in one transaction, holding the single SQLite writer against the household |
| metadata lookup, search, refresh, enrich | 60 / min | username | Each call fans out to as many as four public catalogues that this household neither runs nor pays for |

The last is the one that is not about this deployment: spending somebody else's quota is a
way to get this deployment's address rate-limited upstream, which loses metadata for
everyone. Sixty a minute is far above scanning a shelf by hand.

Everything else needs a valid token, so the thing worth bounding is guesses at getting
one. All of it was unbounded before.

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
clears the windows, an accepted tradeoff for not adding Redis to a household bookshelf.

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
  notes they wrote, which is a larger decision than this feature. The cost is that every
  test account ever made is permanently in the **"Loan to…" picker**, which is the member
  list and which every member uses, so a typo made once is a name everybody picks past
  forever.
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
- **`/api/users` is readable by every member**, exposing usernames and the admin flag. It
  has to be, for the "Loan to…" picker. Test accounts appear in it like any other account,
  because that is what they are; the list of which accounts are test accounts is admin only.
- **Rate limits reset on restart**, and are per-process.
