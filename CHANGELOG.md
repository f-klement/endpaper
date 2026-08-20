# Changelog

## v0.4.0

Seven palettes, ten wallpapers, and a screen to choose them on.

**v0.3.0 was never released.** Its section below is a true record of what landed,
but no tag and no image were ever published for it, so there is nothing to
upgrade from. This release contains both, and upgrading from v0.2.1 goes
straight here.

**Two migrations run on start**, in this order: `c4d8e91a2f60` adds the three
appearance columns to `users`, and `e6f1a94b2d73` adds the flag that marks an
admin-created test account. Both are additive, both have a working downgrade,
and neither touches an existing row's data.

### Added

**Appearance is something you pick, at `/settings/appearance`.** A palette, light
or dark, and a wallpaper, applied the moment you choose and saved to your
account, so the look follows you from your laptop to your phone. Its own screen
rather than a row in the settings list, because the only honest preview of a
wallpaper is the page: the pattern is painted behind everything, so the picker is
the app with the controls laid over it. The preview on top of it is your own
first two books, not invented sample content.

**Seven palettes.** Endpaper, Catppuccin, Rose Pine, Gruvbox, Solarized,
Everforest and Nord, each in light and dark. The colours belong to their
projects; the lightness of each rung belongs to this app, so every palette clears
the same contrast floors rather than shipping whatever the upstream editor theme
happened to publish. Every correction, with the contrast that forced it, is
tabulated in `docs/theming.md`. Nord publishes no light theme, so its light
member is built here from Snow Storm and Polar Night, and the picker says so on
the tile rather than greying out a control every other palette leaves alone.

**Ten wallpapers, in two families.** Five after William Morris (Willow Bough,
Acanthus, Pimpernel, Strawberry Thief, Golden Lily) and five decorated papers
(Nonpareil, Seigaiha, Asanoha, Plait, Khatam). They are drawn rather than
shipped: every tile is generated in the browser from the palette's own ink, so a
pattern costs no download and follows whatever colours you chose. **None** and
**Surprise me** are tiles beside them, and a new account starts on Surprise me.

**Licences on the screen that offers them.** Six MIT notices and the note that
this project is not affiliated with Morris & Co.

**Test accounts an admin can switch into.** Sign in as any member from the
settings page to see the library as they see it, and come back the same way. The
query cache is dropped on every change of account, so nobody's private books
survive the switch.

**A top bar instead of a left rail**, and **lending to somebody who has no
account**: both landed before this release was tagged, and are described under
v0.3.0 below.

### Fixed

**The wallpaper no longer arrives a frame late.** The palette, the mode and the
pattern are applied together before React mounts, rather than the first two
synchronously and the third from an effect. Nobody noticed while the pattern was
faint and never changed; a picker makes it the first thing you watch for.

**Muted text on a light card was below AA.** `paper-400` and `paper-500` measure
2.35:1 and 3.83:1 against the card where WCAG wants 4.5, and were text in
fourteen places. A test now fails the build if either is used as light-mode text
again.

**One rose did both "want to read" and "delete".** They are separate colours now,
because a colour that means both a pleasure and a danger means neither.

**The green success message failed AA on every palette.** `text-green-600`
measured 2.79 to 3.22 against 4.5; it is `text-green-800` now, measured 6.19 to
7.13.

**Twenty-one controls drew their own focus ring**, at 2.24:1 against a page where
WCAG 1.4.11 wants 3:1, and sixteen of them killed the browser's own first. There
is one ring now, and a test that keeps it that way.

**More contrast was honoured on the default palette only.** The
`prefers-contrast: more` block was outranked by every palette block, so six of
the seven silently ignored it. It also turns the wallpaper off, and the picker
says why rather than showing an off state nobody chose.

### Changed

**Tag pills are no longer colour coded by category.** The category is written on
the pill, and the three hues cost fifteen tokens per mode to say the same thing
twice. A tag the household invented keeps the accent, which is the one
distinction with a reason.

## v0.3.0

Four bug reports, and what fixing them turned up underneath.

### Fixed

**No cover appeared on a German shelf.** Every stored cover was blocked by the
browser, with a 200 on the record and nothing in any log. `covers.py` resolves a
978-3 ISBN through the DNB's cover service, and that host was never added to the
Content-Security-Policy, which was a hand-written list beside it. The policy is
now derived from the one list of hosts, and a test walks the AST of every backend
module to keep cover URLs from being written anywhere else: `metadata.py` held six
of them, which is the door the same bug would have come back through.

**Google Books thumbnails could not render either.** Google serves them over plain
http, which is mixed content on an https page and blocked whatever the policy
says. They are upgraded on the way in, on every path that stores a cover, and a
one-shot migration upgrades the rows already stored.

**A cover that failed to load took the layout with it.** The old handler removed
the image from the flow, which collapsed the book page's header to nothing and
dropped the back button on top of the title. Every cover in the app now falls back
to the same placeholder, at the same size.

**The back button did nothing on a deep link.** It was `navigate(-1)`, and a
shared link, a reload or a PWA cold start has no prior entry to go back to. It now
goes back where there is somewhere to go, and to the library where there is not.

**Registration refused the attempt and charged you for it.** Under `ldap` and
`proxy` auth the rate limiter ran before the refusal, so an anonymous caller could
exhaust a real budget on a route that can never succeed. The refusal also told
proxy deployments their accounts were "managed by the directory", where there need
not be one.

**A backup restored covers the browser blocks.** A restore inserts through Core,
so the column validator never fired. It calls the upgrade itself now.

### Added

**Lend to somebody who has no account.** A neighbour, a colleague, a book club.
The borrower is either a member or a typed name, exactly one of the two, enforced
by a CHECK constraint rather than by the schema alone, because a restore and an
import do not go through the schema.

**A top bar instead of a left rail.** Library, scan and loans stay on the bar as
icons; everything else moved into a menu behind the account trigger, which still
names the person signed in. The rail spent 56px of a phone's width on every screen
and had nowhere to open a menu into. Under proxy auth the menu no longer offers
sign out or switch account: the upstream owns the session and both were inert.

**A network failure says so.** A rejected request used to print the browser's own
"Failed to fetch", untranslated, to whoever was standing in a tunnel.

### Security

A cover URL is now required to be `https://` or one of our own uploads. Nothing
was exploitable through the values this rejects, and all of them become
exploitable the day `img-src` gains a wildcard or a cover is rendered outside an
image tag.

### Tested

The login and registration flow through the HTTP routes and the UI in all three
auth modes, which had thorough unit tests for the backends and nothing for the
routes.

## v0.2.1

Documentation only. No code change, and the image is a rebuild of the same
source.

The README's feature list had fallen behind what v0.2.0 actually shipped. It
omitted **per-book privacy**, **series gap detection** and **duplicate merge**,
which are three of the things this project does that most alternatives do not,
and said nothing about rapid scanning, ratings and notes, due dates and overdue
loans, bulk edits, saved views, statistics or the health endpoint. It also still
said the first account to *register* becomes admin, which stopped being the
whole story once proxy and LDAP deployments got an admin bootstrap.

Rewritten and grouped, and it now links the changelog.

## v0.2.0

The first release that publishes both source and an image. v0.1.0 got half way:
GitHub received the source, Docker Hub received nothing.

### Added

**Metadata, four sources instead of two.** The DNB and K10plus are asked
concurrently and their answers merged, then Open Library, then Google Books.
Which is asked first is decided by the ISBN prefix, so a 978-3 goes to the DNB.
No key is required for any of the first three, and Google is optional.

**Covers are verified before they are stored.** A candidate URL is fetched and
answered three ways: present, definitely absent, or unknown. Unknown keeps the
URL, so a momentary 5xx at the image host does not throw away a cover that
exists.

**Import from anything, not just Goodreads.** Columns are guessed rather than
required, with a preview before anything is written. Measured against real
exports from Goodreads, StoryGraph, LibraryThing and Calibre, and a list
somebody typed by hand.

**Backup and restore.** The whole library plus every cover as one zip.

**Tags a household can invent for itself**, beside a curated vocabulary grown
from 32 to 105 and grouped by category in the picker.

**Trash.** Deleting a book is reversible, with a window to change your mind.

Also: saved searches, a wishlist view, overdue loans that say so, and format,
condition, price, purchase date and purchase source on a book.

### Fixed

**Proxy and LDAP deployments had no admin bootstrap.** Registration is 403 in
both modes and admin came only from a configured group, so deploying with
`AUTH_MODE=proxy` and no groups header produced a library nobody could
administer, and switching an existing local deployment to a directory demoted
the existing admin on their first page load.

**The cover cookie was a copy of the access token.** It is now scoped and
refused everywhere but the cover route, so a copy that escapes cannot be
replayed against the API. `POST /auth/logout` clears it; nothing did before, so
it outlived the session.

**A restore could hand a live session to the wrong person.** It replaces the
users table, so the id in an existing token may afterwards belong to somebody
else. Tokens now carry an epoch that a restore rerolls.

**Foreign keys were not enforced**, which made every `ON DELETE CASCADE` in the
schema decorative. Turned on, along with WAL and a busy timeout, and every
foreign key column is now indexed.

**One open loan per book is a database constraint.** Merging two records used to
leave both open, so a book could be out with two people at once.

**Uploads are refused before they reach the disk.** A 200 MB request aimed at
the 5 MB cover endpoint was spooled to a temporary file in full and only then
answered with a 413.

**A failed cover upload no longer destroys the cover that was there.**

**Rate limits** on library import and on the metadata fan-out, which reaches as
many as four public catalogues per call.

**Re-scanning a book you already own** offers to open it, rather than answering
with a sentence and no way forward.

**The account menu was unreadable on a phone**, folded into a 56px rail.

### Changed

- `POST /api/books/bulk/ownership` is removed. `POST /api/books/bulk` with
  `set_ownership` has the same body, the same permission rules and the same
  result.
- `GET /api/healthz` is the health endpoint. Container probes should point at
  it rather than `/`, which is answered from disk and stays healthy when the
  database is not.

## v0.1.0

Source published to GitHub. The image did not publish.
