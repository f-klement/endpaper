# The Endpaper handbook

How to use Endpaper, by task, in the order a new member meets it. The first part is for every
member; the second is for whoever administers the library.

This handbook teaches tasks. Whether Endpaper does something at all, and what it deliberately
does not do, is [the feature list](featurelist.md). Installing it, environment variables and
everything else an operator sets outside the app is [the configuration reference](configuration.md).
The words it uses (member, book, copy, loan, private book) mean what [the glossary](../GLOSSARY.md)
says they mean.

Labels in this handbook are the ones the English interface shows. The interface also speaks
German; this handbook is English only.

## Contents

**For members**

- [Signing in](#signing-in)
- [Installing on a phone](#installing-on-a-phone)
- [Adding a book](#adding-a-book)
- [Bringing a library in](#bringing-a-library-in)
- [Private and shared books](#private-and-shared-books)
- [Reading](#reading)
- [Lending and overdue loans](#lending-and-overdue-loans)
- [Finding books](#finding-books)
- [Trash and undo](#trash-and-undo)
- [Appearance](#appearance)
- [Reading the shelf from an ebook reader](#reading-the-shelf-from-an-ebook-reader)

**For admins**

- [The first admin and accounts](#the-first-admin-and-accounts)
- [Confirming new accounts](#confirming-new-accounts)
- [Catalogue sources and logins](#catalogue-sources-and-logins)
- [Reminder channels](#reminder-channels)
- [Library mode and the public catalogue](#library-mode-and-the-public-catalogue)
- [SRU and Z39.50 for other libraries](#sru-and-z3950-for-other-libraries)
- [Seeing the library as a member](#seeing-the-library-as-a-member)
- [Backup and restore in the app](#backup-and-restore-in-the-app)
- [Folding author spellings and duplicates](#folding-author-spellings-and-duplicates)

## For members

### Signing in

How you sign in depends on how the library was set up, and the operator chose that when
installing it ([sign-in modes](configuration.md#sign-in-modes)).

| The library signs you in with | What you do |
|---|---|
| Its own accounts | Sign in with a username and password. **Create Account** on the same screen makes one, if the library allows new accounts. |
| A directory (LDAP) | Sign in with your directory account. Your password is managed there, not in Endpaper. |
| A sign-in portal in front of it | Nothing: the portal signs you in, and Endpaper shows no login screen at all. |

**The first account created becomes the admin**, whichever way the library signs people in.

**Forgotten your password?** on the login screen asks an admin to let you back in. The admin
approves the request and reads you a one time code; you type it with a new password under
**Get back in**. Nobody can start a reset for you: only you can ask. This is offered only where
the library keeps its own accounts, since a directory or a portal owns the password otherwise.

If the library confirms new accounts, registering asks for an email address and sends a code to
it. Type it under **I have a confirmation code**, or ask an admin to confirm the account for you
([Confirming new accounts](#confirming-new-accounts)).

Your top bar menu, under your name, holds **Switch Account** and **Logout**. Behind a sign-in
portal neither is shown, because the portal owns your session.

**Settings, Your account** shows your email address, which is optional. No reminder is sent
to it: reminder mail goes to the addresses under **Send reminders to**. Below it is the history
of your account: who approved a password reset and how your address was confirmed. A KOReader
device signs in with a separate password made on the same screen
([Reading the shelf from an ebook reader](#reading-the-shelf-from-an-ebook-reader)).

### Installing on a phone

Endpaper is a progressive web app. Open it in your phone's browser and choose **Add to Home
Screen** (the browser's own menu names it), and it gets its own icon and its own window. There
is no app store and nothing to sign.

It is still the web interface talking to your library, so it needs the library reachable from
where you are. There is no offline mode. On iPhone, iPad and Mac this is the only way to install
Endpaper: there is no Apple build ([the feature list](featurelist.md#deliberately-not-built)
says why).

**Scanning a barcode needs the camera, and a phone browser gives a page the camera only over
HTTPS.** If the Scan page says **Camera unavailable**, ask whoever runs the library; it is the
first item under [before you expose it](configuration.md#before-you-expose-it).

### Adding a book

Everything here starts on **Scan** in the top bar.

**Scan a barcode.** Press **Start scanning** and point the camera at the barcode above the ISBN.
The camera stays closed until you press it, and **Camera light** turns on the torch. If nothing
reads, hold the book further back so the camera can focus. Endpaper looks the ISBN up in the
library's catalogues and shows the record before saving anything.

**Type the ISBN** under **Or enter ISBN manually** and press **Look up**, when the barcode is
damaged or there is no camera.

**Search by title or author** under **Or search by title**, for a book whose ISBN you do not
have. Pick a result to fill in the details; nothing is saved until you confirm. Some catalogues
are too slow for a quick search, and **Search harder** asks them too.

**By hand.** When no catalogue knows the book, **Add it by hand** opens a form that needs only a
title.

Before saving, the confirm card shows the record with what you can set for this copy: tags,
collection, ownership, where it is shelved, format, condition, and where and when you bought
it. **Private (only visible to me)** keeps the book to yourself
([Private and shared books](#private-and-shared-books)). **Add to Library** saves it.

Endpaper starts the next book's shelf, collection, ownership, condition and purchase details
from the last book you added, under **Carried over from the last book**, so a whole shelf is
typed once. Change or
clear any of them for the book in hand. If the last book was private, the next one starts
private too, and the card says so.

**A second copy.** Scanning a book the library already holds says **This book is already in the
library: same ISBN**, and offers **Open the copy already in the library** or **Add another
copy**. A copy is a separate object with its own shelf, condition and loan; it takes its tags,
cover and privacy from the book already there. On a book's page, **Your copies** lists every
copy and has the same **Add another copy** button.

**Rapid intake.** **Scan several** keeps the camera running: each barcode is looked up and
queued without stopping. **Finish scanning** ends the run, and **Add all** saves the batch once
you have reviewed it. A misread barcode is caught in the queue rather than becoming a book.
**Shelf for everything in this run** sets one location for the whole batch.

After saving, a book's page holds everything else. **Find more details** asks the catalogues
for fields the book is missing and fills only empty ones; **Refresh Metadata** in the header
asks again for the whole record. **Upload Cover** replaces the cover with a photo. The page
edits what the library says about its copy (shelf, series, tags, collection, copy details,
custom fields) and offers no form for the title or the author, which come from the record.

### Bringing a library in

Most of these are on **Settings, Your library**. Choosing files from a folder is on **Scan**.

**From the book files themselves.** Under **Add from a file** on the Scan page, pick book files
or **A whole folder of books**. Endpaper reads what each file says about itself (title, authors,
series, publisher, year, language) and queues one row per book, which you review and save with
**Add all**. **The files are read in your browser and are never uploaded.** Only what a file
said reaches the library. For a file picked from a folder, so is its name, the folders above it
and a fingerprint computed from up to 12 KiB of it; everyone who can see the book can see those.
The formats read are listed in [the feature list](featurelist.md#bringing-a-library-in).

- A folder of audiobook chapter files becomes one audiobook, not one book per chapter. The row
  says how many files it was made of, and **Add them as separate books instead** undoes that.
- A file whose metadata says nothing useful is offered a catalogue lookup under its own name. The
  button counts the rows waiting for one, as in **Look up 3 in the catalogues**. It is paced so
  one large folder does not use up the catalogues' allowance, and it sends the file names, never the files.
- A file that states its ISBN is offered the same lookup a scanned barcode gets. Where the
  catalogue's record names a different title, both are shown and you choose.
- Picking the same folder again checks which saved files are still there and lists the ones not
  found, which **Mark these as missing** marks on their books. Nothing is removed.

**From a Calibre library.** Calibre keeps its index in `metadata.db` at the top of the library
folder. **Copy that file first and choose the copy** under **Bring a Calibre library across**: a
Calibre library has one writer, and reading the live file while Calibre writes to it gives a
half written copy. Endpaper reads the copy in your browser and shows the counts before writing
anything. **Pick the library folder** as well, and the `metadata.opf` beside each book fills in
what the index left empty, and each book's files are recorded on it as above. Picking a folder
with `metadata.db` at its top on the Scan page reads it through the index the same way.

**From another app's export.** **Bring a library across** takes a CSV or TSV export from
Goodreads, LibraryThing, StoryGraph, Libib, Openreads or anything with a title column. Unlike a
book file, this file is uploaded and read on the server. A review in the export arrives as
a private note unless you already have a note on that book
([Private and shared books](#private-and-shared-books)). The columns are worked out and shown
before anything is saved, rows the old app marks as deleted are left out, and **Add books that
are not in the catalogue yet** decides whether unmatched rows become new books.

**From a device or a store.** **Bring a library across from a device or a store** reads the
library file of Kobo, Google Play Books (a Takeout archive), Apple Books, Kindle for PC, Adobe
Digital Editions and Moon+ Reader. Each card says which file to pick and where the app keeps
it. The file stays in your browser. A store often knows only a title and its own identifier, so
books from Google Play Books arrive without an ISBN; **Look up books by their store id** under
**Books from a store** fills them in afterwards.

**KOReader highlights.** **KOReader highlights** takes the metadata files KOReader keeps beside
each book (such as `metadata.epub.lua` in the book's `.sdr` folder) and matches each to the book
holding the same file. Highlights arrive private
([Private and shared books](#private-and-shared-books)).

**MARC records** from another library (**Take a catalogue across**) are offered in library mode
only ([Library mode and the public catalogue](#library-mode-and-the-public-catalogue)).

**Covers.** Covers are downloaded and kept by the library. Books that arrived through an import
have none yet; **Fetch missing covers** finds them.

A self hosted OPDS server (Calibre-Web, Komga, Kavita and the like) can be synced into the
library as well: an admin adds the feed once and any member syncs it. The app has no screen for
this: it is reachable only through Endpaper's API.

Any import that finds a book already on the shelf matches it rather than adding it twice, and
one that finds a book only in the trash says so rather than adding a second.

### Private and shared books

**Every book is shared with the other members unless you make it private.** A shared book's
existence, who has it and whether it is lent out are visible to everybody in the library.

**Private (only visible to me)**, on the confirm card or at the top of a book's page, makes a
book yours alone in the app: no other member sees it in the library, in search, in the stats,
or by guessing its address. Only the member who added a book can change its privacy. Filing a
book in a collection changes nothing about who sees it.

A private book stays private in every mode, library mode and the public catalogue included, and
overdue reminders sent by email, Telegram or webhook leave it out.

A note written on a book's page is visible to every member who can see the book, and cannot be
made private afterwards. A review brought in with another app's export arrives as a private
note, marked **Only visible to me**, unless you already have a note on that book. Quotes are
visible to every member who can see the book. Highlights arrive private and are shared one at a
time with **Share**.

**Private means private in the app.** Everything this section and [Reading](#reading) call
private or yours alone is in an admin's backup
([Backup and restore in the app](#backup-and-restore-in-the-app)) and in the database whoever
runs the server keeps.

### Reading

Your status, rating, dates and progress are yours alone in the app
([Private and shared books](#private-and-shared-books)): two members reading the same copy do
not overwrite each other. They are in the **Your reading** section of a book's page.

| What | How |
|---|---|
| Status | **Unread**, **Want to Read**, **Reading**, **Read** or **Did not finish**. A book you gave up on keeps the date you started it and never counts as finished. |
| Rating | One to five stars, cleared with **Clear rating**. |
| Dates | Set by the status: **Reading** records the day you started and **Read** the day you finished, shown as **Started** and **Finished**. |
| Progress | **Record progress** logs a page reached or a percentage, with the minutes read if you like. Recording progress on a book you had abandoned returns it to Reading. |
| Talking about it | **I would like to talk about this book, ask me about it** tells the others; the book then shows **Talk about it**. |

**Notes and quotes** has three lists. A note is free text. A quote is a passage copied out, with
the page it is on and a line about why (**Add quote**); every quote the library can see is on
**Quotes** in the menu, newest first. Highlights come from a reading device: from KOReader
([Bringing a library in](#bringing-a-library-in)), or from Readwise once a day if you save your
Readwise access token under **Settings, Your account, Readwise highlights**. Nothing from the
library is sent to Readwise.

To keep your place across KOReader devices and have your progress fill itself in, see
[Reading the shelf from an ebook reader](#reading-the-shelf-from-an-ebook-reader).

### Lending and overdue loans

On a book's page, **Lending this copy** records a loan. Under **Who is borrowing it**, choose
**A member**, or **Someone else** and type their name: the borrower needs no account. Set **Due
back** if you like, press **Loan**, and **Mark as Returned** when it comes back.

**Lending** on the same section says whether you would part with the book: **Happy to lend**,
**Using it myself right now** or **Never lent**. Lending a book marked never lent asks first.

A digital copy is not lent, because Endpaper holds no file. **Request access** asks its holder,
who answers with **Grant** or **Decline** and hands the file over outside the app.

**Loans** in the top bar lists every loan on a book you can see, with how long each book has been out and how far a
late one is past its date. **Active only** and **Overdue only** narrow it.

**Overdue** loans have a page of their own, linked from the library page when any are late.
Each member sees the overdue loans they lent or borrowed, their own private books included; in
library mode, and for an admin, it shows every overdue loan on a book they can see, since a
volunteer still has to chase a book somebody else lent out. The page also says whether each reminder channel is working
([Reminder channels](#reminder-channels)).

### Finding books

**Library** in the top bar is the whole shelf.

- **Search books** looks in the title, the author and the ISBN.
- The filters narrow by tag, collection, series, author, where a book is shelved, format,
  reading status, ownership, willingness to lend and classification. **Save this view** keeps a
  combination under a name. **Wishlist** in the menu is one such view, ready made: books you
  want to read and do not own.
- **Covers**, **List** and **Table** are three ways to show the same shelf. **Columns** picks
  what the table shows. Your choice is remembered in this browser.
- **Select** turns on selection, for tagging, re-shelving, setting a status, filing in a
  collection or deleting many books at once (**More actions**).

The menu holds the other ways in:

| Page | What it shows |
|---|---|
| **Series** | Every series, with the volumes missing from it. |
| **Authors** | Everybody the shelf credits, each linking to their books ([Folding author spellings and duplicates](#folding-author-spellings-and-duplicates)). |
| **Collections** | Named parts of the shelf, such as physical against ebook. A book is in one collection or none; use tags for the rest. |
| **Quotes** | Every quote the library can see. |
| **Stats** | What is on the shelf, who added it, what got finished when and the pages read. Every count leaves out what you cannot see. |

**Tags** are shared by every member. A set is built in; **Add a tag** on a book creates a new
one, which then belongs to everybody. Deleting a tag is for an admin, and takes it off every
book.

**Custom fields** hold a fact the library keeps that Endpaper has no column for, such as a
link to the same book in another app. They are defined under **Settings, Your library, Custom
fields** and filled in on a book's page with **Edit details**. A field declared as **A web
link** opens as one. Deleting a field is for an admin, and takes its value off every book.

**Export Library** in the menu writes the shelf out as a spreadsheet, plain text or a web page
that opens without a connection.

### Trash and undo

**Move to Trash** at the bottom of a book's page deletes it, and the message that follows
offers **Undo**. Deleting a selection moves every book in it to the trash too, and offers
**Open trash**.

**Trash** in the menu holds deleted books, with everything on them, until somebody empties it.
Nothing is removed on its own. **Put back** returns a book to the shelf. **Delete for good**
cannot be undone, and only the member who added a book can do it; a book nobody is recorded as
adding is an admin's to delete. **Empty the trash** deletes for good every book you added and, for an admin, those nobody
added.

A book in the trash still holds its ISBN. Scanning or importing it again says so instead of
adding a second; put it back, or have it deleted for good first.

### Appearance

**Settings, Appearance** holds the language the app speaks on this device, and **Choose a
palette, light or dark, and a wallpaper**, which opens a preview of your own library. **Follow
system** matches your phone or computer. **Surprise me** picks a different wallpaper each
visit. The palette, mode and wallpaper are saved to your account, so they follow you to another
device; the wallpaper is switched off when your system asks for more contrast.

### Reading the shelf from an ebook reader

Endpaper keeps no book files and serves no catalogue feed to a reader. What it does connect to
is KOReader's progress sync.

1. Under **Settings, Your account, KOReader sync**, press **Make a sync password**. Copy it: it
   is shown only once.
2. In KOReader, open **Progress sync**, choose a custom sync server, and log in with the
   **Server**, **Username** and **Password** the account page shows.

Your devices then keep each other's place, and the book's reading log fills itself in, one row
a day, with the book marked read when you reach the end. A file whose fingerprint was recorded
when you added it from a folder is matched to its book by itself. Any other waits: the account
page counts the documents waiting for a book, and **This book** under **KOReader** on the
book's page links one. **Make a new sync password** or **Sign out every device** ends every
device's session.

If the library sits behind a sign-in portal, KOReader has to reach it past the portal; that is
for whoever runs it ([sign-in modes](configuration.md#sign-in-modes)).

## For admins

An admin sees four more screens under **Settings**: **Catalogue sources**, **Public catalogue**,
**Lending** and **Data and accounts**. Everything below is on one of those, unless it says
otherwise.

### The first admin and accounts

The first account created becomes the admin. **Keep its password.** A password reset is
approved by another admin, so a library with exactly one admin has nobody to approve a reset of
that account from inside the app. The way back is a command run in the container, described in
[recovering the only admin](configuration.md#recovering-the-only-admin).

Whether anybody else may create an account is set by the operator
([before you expose it](configuration.md#before-you-expose-it)). Under a directory or a portal,
the operator can name a group whose members are admins
([sign-in modes](configuration.md#sign-in-modes)).

**Password reset requests**, under **Data and accounts**, lists members who asked to be let back
in. **Approve** produces a one time code, shown once and valid until the time beside it, which
you read out to the member; **Decline** refuses. Each account keeps a record of who approved
its reset, which the member can see. This list exists only where the library keeps its own
accounts.

**Member addresses**, under **Settings, Your account**, lists every member's email address, so
you can find the empty one or the typo when somebody's reminders go nowhere.

### Confirming new accounts

Off by default. Under **Data and accounts, Account confirmation**, turn on **Accounts are open to
people outside the household**, and a new account must confirm the address it registered with
before it can sign in. A code is mailed to that address when a mail server is set up
([Reminder channels](#reminder-channels)). Without one, or when mail does not arrive, **Confirm**
beside the account in the same list confirms it, recorded with your name.

Accounts that already exist are unaffected: confirmation is decided when an account is made. An
account a directory signs in has no address for Endpaper to confirm.

### Catalogue sources and logins

**Catalogue sources** decides where a book's details come from.

**Where book details come from** lists every catalogue this build can ask, each with a switch
and a position. Off means never asked. The order is the order they are asked in; it does not
decide which catalogue is believed when two disagree. The line under each one says what it
answers (scans, title searches or both) and which ISBNs it is asked about. Which catalogues there
are, and which need a login, is in [the feature list](featurelist.md#the-catalogue).

**Catalogue logins** stores the username and password a catalogue needs. Logins are encrypted
with a key that is never written to the database:

1. Press **Create an encryption key**. Endpaper shows a **recovery phrase** of 24 words, once.
2. Write it down and press **I have written it down**. Restoring a backup on another machine
   needs the phrase, under **Enter a recovery phrase**.
3. Under **Add a login for**, choose the catalogue and save its login.

Where a catalogue publishes a login for everybody, Endpaper already uses it; **Use this
library's own login** replaces it with your own. A login the operator set in the environment is
shown as fixed. Where each stored credential lives and how the key is held is in
[catalogue logins](configuration.md#catalogue-logins).

**Google Books** needs an API key: **How do I get a key?** walks through making one in the Google
Cloud console. Paste it under **API key**, and **Enable extra book details** puts **Find more
details** on every book. **Goodreads**, on the same screen, adds a link beside each title that
searches Goodreads.

### Reminder channels

**Lending** sends a digest of overdue loans. Endpaper looks every hour, and an hour with nothing
to chase sends nothing. **Days between reminders for the same loan** sets how often one loan is
chased again.

| Channel | Set up | Private books |
|---|---|---|
| **In the app** | Nothing; on to begin with. A note on the library page and the Overdue page. | Each member sees their own; never another member's. |
| **Email** | **Mail server**, **Port**, **Encryption**, the login, **From address** and **Send reminders to** (one address or several). | Left out, counted. |
| **Telegram** | A bot made with @BotFather: its **Bot token**, and the **Chat id** of the group it was added to. One message to one chat. | Left out, counted. |
| **Webhook** | **Webhook address**, and a **Signing secret** so the receiver can check the message came from here. | Left out, counted. |

Every channel switched on gets the same message. **Send now** sends at once and reports what each
channel did. A channel that stops working says so under its switch, on the Overdue page and,
after a day of failing, on the library page. Mail refuses a password with no encryption, and
certificates are always checked.

### Library mode and the public catalogue

**Public catalogue** holds two switches, and both are off until you turn them on.

**Library mode** (**Catalogue this library as a library**) is for a library or an archive. It
shows the call number and the subject headings, puts ownership and reading status away, opens
the shelf on the dense list, and turns on MARC import (**Take a catalogue across**) and MARC
export. Every member sees every overdue loan on a book they can see, not only their own. It publishes
nothing.

**Publishing** (**Let anyone search this catalogue**) is a second decision, refused while library
mode is off. Before it publishes, Endpaper shows exactly what a visitor will see and what they
will not:

- Shown: search, and one record per book with its bibliographic facts, tags and classifications.
- Not shown: who owns a book, whether it is lent, who has read it, where it is shelved, what it
  cost, and every note.
- Private books and the trash stay private
  ([Private and shared books](#private-and-shared-books)).

Once published, the login page links the catalogue as **Browse the public catalogue**. **See what a visitor sees** opens it. Search engines are
told to stay away until **Let search engines index it** is turned on separately. Turning library
mode back off withdraws the catalogue.

### SRU and Z39.50 for other libraries

**SRU** is how another library's software searches a catalogue. A published catalogue answers
it at `/sru` on the same address: a CQL query in, MARCXML records out, and `operation=explain`
tells a client which indexes exist. It exposes exactly what the public catalogue does, behind the
same two switches. With either switch off it does not answer.

**Z39.50 is not served.** It is a binary protocol over raw TCP, and the
[feature list](featurelist.md#deliberately-not-built) says why it is left out. Give another
library the SRU address instead.

### Seeing the library as a member

An admin sees more than a member does. To check what an ordinary member sees, make a test
account under **Data and accounts, Test accounts**, with a password you set, and press
**Switch** beside it.

Test accounts are never admins, and a switch accepts nothing else, so nobody can be signed in
as a real member this way. They work under every sign-in mode, which is how an admin whose
directory owns every password still sees a member's view. They are not offered at the login
screen. To come back, choose **Return to my account** in the menu behind a portal, or sign in
again with your own account otherwise.

### Backup and restore in the app

**Data and accounts, Backup**: **Download a backup** writes a full copy of the library, every
book, account, note, loan, reading status and cover. The spreadsheet export is not this: it
carries one row per book.

**A backup is not filtered by privacy.** It carries every member's private books, private
notes, unshared highlights, a key for each highlight they deleted (not its text), reading
status, ratings, dates, progress and talk offers, KOReader positions and Readwise book matches,
so whoever holds the file can read them all. Passwords for signing in here are in it only as
hashes. The mail password, the Telegram bot token, the webhook secret and the Google Books key
are in it as typed.

**Restore from a backup** replaces everything in the library with the file, and cannot be
undone; books added since the backup was taken are gone. Saved logins in a backup (a
catalogue's, an OPDS server's, a member's Readwise token) are sealed, and readable only with the
recovery phrase
([Catalogue sources and logins](#catalogue-sources-and-logins)). A restore drops every OPDS
server's login all the same, recovery phrase or not, so type each one again afterwards.

Backing up the data directory from outside the app is in
[data and backups](configuration.md#data-and-backups).

### Folding author spellings and duplicates

Both pages are in the menu, and any member can use them.

**Authors.** Names come from what each book says, so one person can appear under two spellings.
**Probably the same person** suggests groups, with the reason for each. Untick anybody who does
not belong, pick the name to keep, and fold; **Fold the ticked groups** does many groups at once.
Search, tick two names yourself and **Fold into this name** for a pair nobody suggested. **No
book is edited**: a fold is a decision recorded beside the books, survives a re-import, and
**Undo this merge** on the author takes it back.

**Possible duplicates** lists books that look like the same title entered twice, matched on the
title and author rather than the ISBN, so different printings are caught. **Keep this one**
folds the others into it. **This cannot be undone.** Any member can choose which one is kept;
only the member who added a book, or an admin, can fold it into another. A real second copy is
not a duplicate: keep both and they show under **Your copies**.
