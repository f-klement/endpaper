/**
 * English messages. This file is the source of truth for the key set.
 *
 * `de.ts` is typed against it, so a key added here without a German
 * translation is a compile error rather than an English string appearing
 * mid-sentence in a German page.
 *
 * House style for these strings: no em dashes. They do not survive
 * translation cleanly, they are hard to type on the phone keyboards this app
 * is mostly used from, and German typography uses them differently. Commas,
 * full stops and parentheses instead.
 */

export const en = {
  // ── Navigation and shell ────────────────────────────────────────────────
  "nav.library": "Library",
  "nav.scan": "Scan",
  "nav.loans": "Loans",
  "nav.stats": "Stats",
  "nav.settings": "Settings",
  "nav.menu": "Menu",
  // The trigger names the signed-in member, so the top bar says who you are
  // without opening anything.
  "nav.menuFor": "Menu for {name}",
  "nav.switchAccount": "Switch Account",
  "nav.exportLibrary": "Export Library",
  "nav.logout": "Logout",
  // Not "Logout". Under proxy auth nothing here signs anybody out: it drops
  // the test account session, and the upstream names the admin again.
  "nav.returnToMyAccount": "Return to my account",

  // ── Common ──────────────────────────────────────────────────────────────
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.saving": "Saving...",
  "common.edit": "Edit",
  "common.delete": "Delete",
  "common.done": "Done",
  "common.add": "Add",
  "common.close": "Close",
  "common.undo": "Undo",
  "common.back": "Back",
  "common.tryAgain": "Try again",
  "common.loading": "Loading...",
  "common.somethingWentWrong": "Something went wrong.",
  "common.cannotReachServer":
    "The server could not be reached. Check your connection and try again.",
  "common.selectAll": "Select all",
  "common.clearSelection": "Clear selection",
  "common.selectedCount": "{count} selected",

  // ── Reading status ──────────────────────────────────────────────────────
  "status.unread": "Unread",
  "status.want_to_read": "Want to Read",
  "status.reading": "Reading",
  "status.read": "Read",
  // Named for what Openreads and BookLogr both call it, rather than
  // "Abandoned": a third spelling of the same shelf costs a reader a moment
  // every time, and matching the two apps that ship it costs nothing.
  "status.did_not_finish": "Did not finish",
  "status.all": "All",
  "status.mine": "My Reading Status",

  // ── Ownership ───────────────────────────────────────────────────────────
  "ownership.owned": "On the shelf",
  "ownership.not_owned": "Not owned",
  "ownership.unknown": "Not confirmed",
  "ownership.label": "Ownership",
  "ownership.filterAll": "Any",
  "ownership.explain":
    "Whether a copy is physically here. Separate from whether you have read it.",
  "ownership.confirmSelected": "Mark as on the shelf",
  "ownership.markNotOwned": "Mark as not owned",
  "ownership.bulkResult":
    "{updated} updated, {unchanged} already set, {skipped} skipped.",
  "ownership.unconfirmedBanner":
    "{count} books have not been confirmed as being on your shelf.",
  "ownership.reviewThem": "Review them",

  // The in app overdue reminder and the broken channel notice, both on the
  // library page because it is the screen somebody passes without going
  // looking. Neither has a plural form: this catalogue interpolates and does
  // not inflect, so every phrase has to read for one and for several.
  "library.overdueBanner": "{count} loans need chasing.",
  "library.overdueBannerAction": "See them",
  "library.channelBroken":
    "Overdue reminders are not getting through on {channels}.",
  "library.channelBrokenAction": "Check the settings",

  // ── Library ─────────────────────────────────────────────────────────────
  "library.title": "Library",
  "library.scanButton": "+ Scan",
  "library.search": "Search books...",
  "library.searchLabel": "Search books",
  "library.sortLabel": "Sort books",
  "library.tags": "Tags",
  "library.clear": "Clear",
  "library.loadMore": "Load more",
  "library.noBooks": "No books found",
  "library.adjustFilters": "Try adjusting your filters",
  "library.scanFirstBook": "Scan a barcode to add your first book",
  "library.couldNotLoad": "Could not load your library.",
  "library.select": "Select",
  "library.viewLabel": "How the library is shown",
  "library.viewGrid": "Covers",
  "library.viewTable": "Table",
  "library.viewList": "List",
  "library.loaned": "Loaned",

  "sort.title_asc": "Title A to Z",
  "sort.title_desc": "Title Z to A",
  "sort.author": "Author",
  "sort.year_desc": "Year (newest)",
  "sort.year_asc": "Year (oldest)",
  "sort.newest": "Recently added",
  "sort.series": "Series order",
  "sort.ddc": "Dewey number",
  "classification.section": "Classification",
  "classification.filter": "Classification",
  "classification.headings": "Subjects and numbers",
  "classification.divisions": "Dewey shelf",
  "classification.noneOnBook": "No classification yet.",
  "classification.noneToFilter": "Nothing in the library carries one yet.",
  "classification.filterBy": "Show only books carrying {heading}",
  "classification.scheme.ddc": "Dewey",
  "classification.scheme.lcc": "Library of Congress",
  "classification.scheme.gnd": "GND",
  "classification.scheme.lcsh": "Subject heading",

  // ── Book detail ─────────────────────────────────────────────────────────
  "book.uploadCover": "Upload Cover",
  "book.refreshMetadata": "Refresh Metadata",
  "book.refreshing": "Refreshing...",
  "book.by": "by {author}",
  "book.isbn": "ISBN: {isbn}",
  "book.pages": "{count} pages",
  "book.privateToggle": "Private (only visible to me)",
  "book.privateBadge": "Private",
  "book.description": "Description",
  "book.categories": "Categories",
  "book.notFound": "Book not found.",
  "book.remove": "Move to Trash",
  "book.movedToTrash": "Moved to the trash.",
  "book.noTags": "No tags yet",
  "book.addTag": "+ Add",
  "book.removeTag": "Remove {tag}",

  // ── Book detail sections ────────────────────────────────────────────────
  // Names for the collapsible groups. Two rules held while naming them.
  //
  // Each is deliberately different from every heading and control inside it: a
  // handle and the panel it opens must not answer to the same name, which is
  // why this is not "On the shelf" or "Lending", both of which are already
  // buttons in the sections that would have carried them. A test counts each
  // name and requires exactly one button to answer to it.
  //
  // Four of the six name an errand rather than a category of data, because a
  // handle is read by somebody looking for something to do. The other two do
  // not, and are named here rather than left as silent exceptions: "Notes and
  // quotes" and "About this book" are read for what is in them, and no verb
  // describes either better than its nouns do.
  "section.reading": "Your reading",
  "section.filing": "Filing this copy",
  "section.copies": "Your copies",
  "section.lending": "Lending this copy",
  "section.writing": "Notes and quotes",
  "section.about": "About this book",

  // ── Field names ─────────────────────────────────────────────────────────
  //
  // Shared by the card's fold out and the table view. Whole phrases, because
  // a table column header read on its own has no sentence around it.
  "field.title": "Title",
  "field.author": "Author",
  "field.publisher": "Publisher",
  "field.year": "Year published",
  "field.language": "Language",
  "field.pageCount": "Page count",
  "field.readingStatus": "Reading status",
  "field.rating": "Rating",
  "field.ownership": "Ownership",
  "field.addedBy": "Added by",
  "field.addedAt": "Date added",

  // ── The card's fold out ─────────────────────────────────────────────────
  "card.details": "Details",
  "card.detailsFor": "Details for {title}",

  // ── Enrichment ──────────────────────────────────────────────────────────
  "enrich.button": "Find more details",
  "enrich.working": "Searching...",
  "enrich.updated": "Added: {fields}.",
  "enrich.nothingNew":
    "Nothing new found. The details here are already complete.",
  "enrich.pickTitle": "Which edition is this?",
  "enrich.pickHint":
    "Pick the printing you are holding. Only empty fields are filled in, so nothing you typed is replaced.",
  "enrich.proposedClassifications": "Proposed classifications",
  "enrich.noClassifications": "No classifications proposed.",
  "enrich.notFound": "Google Books does not have a record for this book.",
  "enrich.disabled":
    "Google Books lookup is switched off. An admin can enable it in Settings.",
  "enrich.field.subtitle": "subtitle",
  "enrich.field.author": "author",
  "enrich.field.publisher": "publisher",
  "enrich.field.year": "year",
  "enrich.field.description": "description",
  "enrich.field.page_count": "page count",
  "enrich.field.language": "language",
  "enrich.field.categories": "categories",
  "enrich.field.cover_url": "cover",
  "enrich.field.google_books_id": "reference",

  // ── Goodreads ───────────────────────────────────────────────────────────
  "goodreads.lookup": "Look up on Goodreads",

  // ── Scan ────────────────────────────────────────────────────────────────
  "scan.title": "Scan Barcode",
  "scan.pointAtBarcode": "Point at barcode",
  "scan.torch": "Camera light",
  "scan.startScanning": "Start scanning",
  "scan.stopScanning": "Stop scanning",
  "scan.cameraIdle": "The camera is off",
  "scan.cameraIdleHint":
    "Nothing is recorded and the camera stays closed until you start it.",
  "scan.notABook":
    "Read {code}, which is not a book barcode. Look for the one above the ISBN.",
  "scan.tryAgain": "Try again",
  "scan.cameraUnavailable": "Camera unavailable",
  "scan.orEnterManually": "Or enter ISBN manually:",
  "scan.isbnLabel": "ISBN",
  "scan.lookUp": "Look up",
  "scan.lookingUp": "Looking up book...",
  "scan.invalidIsbn":
    "That does not look like a valid ISBN. Check the digits and try again.",
  "scan.notFoundManual":
    "No details found for ISBN {isbn}. You can still add it by hand.",
  "scan.titleRequired": "Title *",
  "scan.titlePlaceholder": "Book title",
  "scan.authorField": "Author",
  "scan.authorPlaceholder": "Author name",
  "scan.couldNotAdd": "Could not add the book.",
  "scan.openTheOneWeHave": "Open the copy already in the library",
  "scan.addCover": "Add cover photo (optional)",
  "scan.replaceCover": "Replace cover photo (optional)",
  "scan.privateBook": "Private (only visible to me)",
  "scan.addToLibrary": "Add to Library",
  "scan.adding": "Adding...",
  "scan.tagsSelected": "({count} selected)",

  // ── Search (Google Books, before a book exists) ─────────────────────────
  "search.orSearchByTitle": "Or search by title:",
  "search.placeholder": "Title, author, or both",
  "search.label": "Search by title or author",
  "search.button": "Search",
  "search.searching": "Searching...",
  "search.noResults": "No matches. Try fewer words, or add the book by hand.",
  "search.pickHint":
    "Pick one to fill in the details. Nothing is saved until you confirm.",
  "search.withoutKey":
    "Searching Open Library. A Google Books key adds descriptions and genres.",

  // ── Loans ───────────────────────────────────────────────────────────────
  "loans.title": "Loans",
  "loans.showAll": "Show all",
  "loans.activeOnly": "Active only",
  "loans.none": "No loans",
  "loans.noneActive": "No active loans",
  "loans.allAccountedFor": "All books are accounted for",
  "loans.loanedToBy": "Loaned to {to} by {by}",
  // Whole phrases, not "Loaned to" plus a name: German does not keep the
  // English word order, and the borrower here is a name rather than a member.
  "loans.loanedToExternalBy": "Loaned to {name} (no account) by {by}",
  "loans.returnedOn": "Returned {date}",
  "loans.markReturned": "Mark Returned",
  "loans.updating": "Updating...",
  "loans.management": "Loan Management",
  "loans.loanTo": "Loan to...",
  "loans.loanToLabel": "Loan to",
  "loans.loanButton": "Loan",
  "loans.markAsReturned": "Mark as Returned",
  "loans.badge": "Loaned to {name}",
  "loans.badgeExternal": "Loaned to {name}, who has no account",
  "loans.borrowerMember": "A member",
  "loans.borrowerExternal": "Someone else",
  "loans.borrowerKind": "Who is borrowing it",
  "loans.externalNameLabel": "Borrower's name",
  "loans.externalNamePlaceholder": "Who has it",
  "loans.couldNotLoad": "Could not load the loans.",

  // ── Notes ───────────────────────────────────────────────────────────────
  "notes.title": "Notes",
  "notes.none": "No notes yet",
  "notes.placeholder": "Add a note...",
  "notes.addLabel": "Add a note",
  "notes.editLabel": "Edit note",

  // ── Custom fields ───────────────────────────────────────────────────────
  // A fact the household keeps that the schema does not know about. The first
  // one, and the reason the feature exists, is a link to the same book in a
  // calibre-web instance.
  "customFields.title": "Custom fields",
  "customFields.explain":
    "Facts this library keeps about a book that Endpaper has no place for, like a link to the same book in another app.",
  "customFields.none": "No custom fields yet",
  "customFields.nameLabel": "Field name",
  "customFields.namePlaceholder": "Calibre-web",
  "customFields.kindLabel": "What it holds",
  "customFields.kindText": "Text",
  "customFields.kindUrl": "A web link",
  "customFields.addButton": "Add field",
  "customFields.renameLabel": "New name for {name}",
  // Named rather than "This will remove 12 values". A count of the books
  // carrying a field would have to be counted across books the reader may not
  // see, so the sentence says every book instead of a number that would be
  // wrong in the reader's favour.
  "customFields.deleteConfirm":
    "Delete {name}? Its value is removed from every book, and this cannot be undone.",
  "customFields.bookNone": "Nothing filled in yet",
  "customFields.editButton": "Edit details",
  "customFields.valuePlaceholder": "Leave empty to clear",
  // The link opens away from this app, so it says so before it is pressed.
  "customFields.opensElsewhere": "Opens in a new tab",

  // ── Quotes ──────────────────────────────────────────────────────────────
  "quotes.title": "Quotes",
  "quotes.none": "No quotes yet",
  "quotes.placeholder": "Copy out a passage...",
  "quotes.addLabel": "The passage",
  "quotes.editLabel": "Edit quote",
  "quotes.addButton": "Add quote",
  // Every field on this page needs a name of its own. The book page already
  // has a "Page" number field (reading progress) and an "Add" button (notes),
  // and two controls with one accessible name is a screen reader reading the
  // same label twice with no way to tell which is which.
  "quotes.pageLabel": "Page the quote is on",
  "quotes.editPageLabel": "Edit the page the quote is on",
  "quotes.pagePlaceholder": "Page",
  "quotes.noteLabel": "What you want to say about it",
  "quotes.editNoteLabel": "Edit what you said about it",
  "quotes.notePlaceholder": "Why this one (optional)",
  "quotes.onPage": "p. {page}",
  "quotes.empty": "No quotes saved yet",
  "quotes.emptyHint": "Open a book and copy out a passage worth keeping.",
  "quotes.couldNotLoad": "Could not load the quotes.",
  "quotes.pagination": "Quote pages",
  "quotes.pageOf": "Page {page} of {of}",
  "quotes.previous": "Previous",
  "quotes.next": "Next",

  // ── Stats ───────────────────────────────────────────────────────────────
  "stats.title": "Collection Stats",
  "stats.booksInLibrary": "books in your library",
  "stats.byMember": "Books Added by Member",
  "stats.byType": "By Type",
  "stats.byGenre": "By Genre",
  "stats.byAge": "By Age",
  "stats.byCustomTag": "By Your Tags",
  "stats.byCollection": "By Collection",
  "stats.finishedByMonth": "Finished, by Month",
  "stats.finishedTotal": "books finished",
  "stats.pagesByMonth": "Pages Read, by Month (books tracked by page)",

  "stats.averageRating": "average of {count} ratings",
  "stats.overTime": "Books Added Over Time",
  "stats.couldNotLoad": "Could not load your stats.",
  "stats.loading": "Loading stats",

  // ── Tags ────────────────────────────────────────────────────────────────
  "tags.type": "Type",
  "tags.genre": "Genre",
  "tags.age": "Age",
  "tags.custom": "Your tags",
  "tags.count": "{count}",
  "tags.countWithChosen": "{chosen} of {count}",
  "tags.newLabel": "New tag",
  "tags.newPlaceholder": "Holiday reads",
  "tags.add": "Add a tag",
  "tags.create": "Create",
  "tags.delete": "Delete {name}",
  "tags.deleteConfirm":
    'Delete the tag "{name}"? It comes off {count} books, for everybody, and cannot be undone.',
  "tags.builtInHint": "Built-in tags cannot be deleted.",

  // ── Login ───────────────────────────────────────────────────────────────
  "login.appName": "Endpaper",
  "login.tagline": "Your personal book catalog",
  "login.signIn": "Sign In",
  "login.createAccount": "Create Account",
  "login.switchToSignIn": "Switch to sign in",
  "login.switchToRegister": "Switch to registration",
  "login.username": "Username",
  "login.password": "Password",
  "login.usernamePlaceholder": "Enter username",
  "login.passwordPlaceholder": "Enter password",
  "login.pleaseWait": "Please wait...",
  "login.browseCatalogue": "Browse the public catalogue",
  "login.firstAccountAdmin": "The first account created becomes the admin.",
  "login.directoryHint":
    "Sign in with your directory account. Accounts are managed there, not here.",
  "login.failed": "Sign in failed.",
  "login.setBackground": "Set background image",
  "login.changeBackground": "Change background",
  "login.uploading": "Uploading...",
  "login.signingYouIn": "Signing you in",

  // ── Settings ────────────────────────────────────────────────────────────
  "settings.title": "Settings",
  "settings.saved": "Settings saved.",
  "settings.couldNotLoad": "Could not load the settings.",
  "settings.adminOnly": "Only an admin can change these.",

  // The settings index. A heading and one sentence per route: the sentences
  // are the whole value of that page, because six headings alone would make a
  // household open three screens to find one setting.
  "settings.appearance.title": "Appearance",
  "settings.appearance.summary":
    "The palette, light or dark, the wallpaper, and the language the app speaks.",
  "settings.account.title": "Your account",
  // Deliberately says nothing about other people's addresses, even though an
  // admin finds them behind this link. This sentence is on the settings index,
  // which every member reads, and `MemberAddresses.tsx` returns null rather
  // than a refusal for exactly the reason a summary must not announce the list
  // either. An admin meets the section on the page.
  "settings.account.summary":
    "The address a reminder addressed to you would be sent to.",
  "settings.catalogue.title": "Catalogue sources",
  "settings.catalogue.summary":
    "Where a book's details come from when you scan or search for one.",
  "settings.library.title": "Your library",
  "settings.library.summary":
    "Bringing books in from another service, the covers they arrived without, and facts this library keeps that Endpaper has no column for.",
  "settings.public.title": "Public catalogue",
  "settings.public.summary":
    "Library mode, and whether a reader with no account may search this catalogue. Both are off until you turn them on.",
  "settings.public.modeTitle": "Library mode",
  "settings.public.modeLabel": "Catalogue this library as a library",
  "settings.public.modeHint":
    "Shows the call number, the classification and the record status, and puts ownership and reading status away. It publishes nothing.",
  "settings.public.modeRepublishes":
    "Publishing is already switched on, so turning this back on republishes the catalogue immediately.",
  "settings.public.publishTitle": "Publishing",
  "settings.public.publishLabel": "Let anyone search this catalogue",
  "settings.public.publishHint":
    "Search and one record per book, readable without an account. Nothing else.",
  "settings.public.publishNeedsMode":
    "Turn on library mode first. A catalogue cannot be published without it.",
  "settings.public.liveNotice": "This catalogue is published.",
  "settings.public.liveLink": "See what a visitor sees",
  "settings.public.indexingLabel": "Let search engines index it",
  "settings.public.indexingHint":
    "Off by default. Publishing a catalogue and inviting a search engine to crawl it are different decisions.",
  "settings.public.confirmTitle": "Publish this catalogue?",
  "settings.public.confirmBody":
    "Anyone who can reach this server will be able to search it and read one record per book, with no account and no password.",
  "settings.public.confirmShown":
    "Shown: title, author, publisher, year, ISBN, language, pages, format, series, description, tags and classifications.",
  "settings.public.confirmWithheld":
    "Not shown: who owns a book, whether you will lend it, who has read it, where it is shelved, what it cost, and every note.",
  "settings.public.confirmPrivate":
    "Private books stay private, and so does everything in the trash.",
  "settings.public.confirmIndexing":
    "Search engines are told to stay away until you allow them separately.",
  "settings.public.confirmAction": "Publish",
  "settings.lending.title": "Lending",
  "settings.lending.summary":
    "Reminders for books that are late, and where they are sent.",
  "settings.data.title": "Data and accounts",
  "settings.data.summary":
    "The whole library out and back in again, and accounts for seeing it the way an ordinary member does.",
  "settings.about.summary":
    "Which version is running, where the source is, and how to support the project.",

  // ── Your account ────────────────────────────────────────────────────────
  // One field today, and the hint says what it is for rather than promising a
  // reminder: nothing sends to this address yet, so a sentence implying one
  // would be a lie the household finds out about a week later.
  "account.email.title": "Email address",
  "account.email.hint":
    "Where a reminder addressed to you would go. Nothing is sent to it yet: overdue reminders go to the household mailbox.",
  "account.email.yours": "Your address",
  "account.email.placeholder": "you@example.org",
  "account.email.none": "None set.",
  "account.email.fromDirectory":
    "This comes from your directory. Change it there.",
  "account.email.directoryRefused":
    "That address is the directory's to set, so it was not changed here.",
  "account.email.couldNotSave": "The address could not be saved.",
  "account.members.title": "Member addresses",
  "account.members.hint":
    "So you can find the empty one, or the typo, when somebody's reminders go nowhere.",

  "theme.hint": "Saved to your account, so it follows you between devices.",
  "theme.light": "Light",
  "theme.dark": "Dark",
  "theme.system": "Follow system",
  "theme.systemHint": "Matches whatever your phone or computer is set to.",
  "theme.wallpaperOff":
    "The wallpaper is off because your system asks for more contrast.",
  "theme.summary": "{palette}, {mode}, {wallpaper}",
  "theme.change": "Choose a palette, light or dark, and a wallpaper",

  "appearance.title": "Palette and wallpaper",
  "appearance.intro":
    "Everything here applies as you pick it and saves to your account.",
  "appearance.preview": "Your library, with this look",
  "appearance.previewEmpty":
    "No books are loaded on this device right now, so there is nothing real to preview. Visit your library and come back.",
  "appearance.mode": "Light and dark",
  "appearance.palette": "Palette",
  "appearance.attribution": "Colours from {source}.",
  "appearance.attributionOwn": "This project's own colours.",
  "appearance.constructedLight":
    "{palette} publishes no light theme. This one is built here from colours it does publish.",
  "appearance.constructedDark":
    "{palette} publishes no dark theme. This one is built here from colours it does publish.",
  "appearance.wallpaper": "Wallpaper",
  "appearance.wallpaperNone": "None",
  "appearance.wallpaperNoneHint": "A plain page.",
  "appearance.wallpaperSurprise": "Surprise me",
  "appearance.wallpaperSurpriseHint": "A different one every visit.",
  "appearance.family.morris": "William Morris",
  "appearance.family.papers": "Decorated papers",
  "appearance.licences": "Where these come from",
  "appearance.licencesPalettes":
    "The palettes below are used under the MIT licence, with their values taken from each project's own repository. None of these projects endorses this one.",
  "appearance.licencesMorris":
    "The Morris pattern names identify the historical designs the drawings are after. This project is not affiliated with, or endorsed by, Morris & Co.",
  "settings.language": "Language",
  "settings.languageHint": "Applies to you on this device.",
  "settings.defaultLanguage": "Default language for new visitors",
  "settings.language.en": "English",
  "settings.language.de": "German",

  "settings.googleBooks": "Google Books",
  "settings.googleBooksEnable": "Enable extra book details",
  "settings.googleBooksHint":
    "Adds a button on each book that fills in page count, language and categories.",
  "settings.apiKey": "API key",
  "settings.apiKeyPlaceholder": "Paste a new key to replace the stored one",
  "settings.apiKeySet": "A key is stored ({preview}).",
  "settings.apiKeyMissing": "No key stored yet.",
  "settings.apiKeyClear": "Remove stored key",
  "settings.apiKeyFromEnv":
    "This key is supplied by the server's configuration, so it cannot be changed or shown here. Change GOOGLE_BOOKS_API_KEY where the app is deployed.",
  "settings.apiKeyHelp": "How do I get a key?",
  "settings.apiKeyHint":
    "Create one in the Google Cloud console and enable the Books API for it. The key is never shown again after saving.",

  "settings.testAccounts": "Test accounts",
  "settings.testAccountsHint":
    "Accounts with a password you set, for seeing the library the way an ordinary member sees it. They are never admins, and they are not offered at the login screen.",
  "settings.testAccountsReturnProxy":
    "To come back, choose Return to my account in the menu.",
  "settings.testAccountsReturnToken":
    "To come back, sign in again with your own account.",
  "settings.testAccountsEmpty": "No test accounts yet.",
  "settings.testAccountsCreate": "Create test account",
  "settings.testAccountsCreateFailed": "Could not create that account.",
  "settings.testAccountsPasswordPlaceholder": "Password, at least 8 characters",
  "settings.testAccountsSwitch": "Switch",
  "settings.testAccountsSwitchTo": "Switch to {name}",
  "settings.testAccountsSwitchFailed": "Could not switch to that account.",
  "settings.testAccountsPasswordFor": "Password for {name}",

  // ── Overdue reminders ───────────────────────────────────────────────────
  //
  // A generic webhook rather than one chat service, so the strings name the
  // shape rather than a brand.
  "settings.overdue": "Overdue reminders",
  "settings.overdueEnable": "Send the reminder to a webhook",
  "settings.overdueHint":
    "Endpaper looks every hour and sends one message naming the loans it is chasing, on every channel switched on. An hour with nothing to chase sends nothing.",
  "settings.overduePrivacyNote":
    "Private books are never included, on any channel. Every channel here goes to a place with no single account behind it, so a private title would be readable by everyone who reads it. Overdue private books are still shown to their owner in the loans list.",
  "settings.overdueUrl": "Webhook address",
  "settings.overdueUrlPlaceholder": "https://example.org/hooks/books",
  "settings.overdueSecret": "Signing secret",
  "settings.overdueSecretPlaceholder":
    "Paste a new secret to replace the stored one",
  "settings.overdueSecretShow": "Show the signing secret",
  "settings.overdueSecretHide": "Hide the signing secret",
  "settings.overdueSecretSet": "A secret is stored ({preview}).",
  "settings.overdueSecretMissing":
    "No secret stored. Set one and the receiver can check the message really came from here.",
  "settings.overdueSecretClear": "Remove stored secret",
  "settings.overdueDays": "Days between reminders for the same loan",
  "settings.overdueDaysHint":
    "A loan is chased again once this many days have passed since the last reminder.",
  "settings.overdueUrlSave": "Save address",
  "settings.overdueSecretSave": "Save secret",
  "settings.overdueDaysSave": "Save interval",
  "settings.overdueSendNow": "Send now",
  "settings.overdueSending": "Sending...",
  "settings.overdueSent": "Sent, covering {count} loans.",
  "settings.overdueNothingSent": "Nothing was sent.",
  // One per reason the server can give. A refused webhook and a quiet week used
  // to be the same sentence here, which is the confusion the button exists to
  // clear up.
  "settings.overdueNotSentDisabled":
    "Nothing was sent: overdue reminders are switched off.",
  "settings.overdueNotSentNoUrl":
    "Nothing was sent: no webhook address is stored.",
  "settings.overdueNotSentNothingDue": "Nothing was sent: nothing is overdue.",
  "settings.overdueNotSentUnreachable":
    "The webhook could not be reached, so nothing was sent. The loans will be chased again on the next attempt.",
  "settings.overdueSkippedPrivate": "{count} private books were left out.",
  "settings.overdueNotSentMisconfigured":
    "Nothing was sent: a channel is switched on and its settings cannot be used. The message below says which.",
  "settings.overdueNotSentInAppOnly":
    "Nothing was sent outward: the in app notice is the only channel switched on, and every member reads it in the library.",
  // One line per channel that was tried, because "sent" over three channels
  // hides the one that failed, and the loans were still stamped.
  "settings.overdueSenderInApp": "In the app",
  "settings.overdueSenderWebhook": "Webhook",
  "settings.overdueSenderEmail": "Email",
  "settings.overdueSenderTelegram": "Telegram",
  "settings.overdueSenderSent": "{sender}: sent.",
  "settings.overdueSenderFailed": "{sender}: {detail}",
  // Fragments, not sentences. The whole-run wording above named the webhook in
  // every row, and pointed at "the message below" from inside it.
  "settings.overdueRowDisabled": "switched off.",
  "settings.overdueRowNoUrl": "no address is stored.",
  "settings.overdueRowNothingDue": "nothing to send.",
  "settings.overdueRowUnreachable":
    "could not be reached. It will be tried again.",
  "settings.overdueRowMisconfigured": "its settings cannot be used.",
  "settings.overdueRowInAppOnly": "nothing to send outward.",
  "settings.overdueRowNothingSent": "nothing was sent.",

  // ── In app reminders, and whether a channel is working ──────────────────
  //
  // The one channel that needs nothing obtained first, and the standing record
  // of what each of them last did. Before this, a broken channel lived only in
  // the container log, which for a household is not a worse form of alerting
  // but the absence of one.
  "settings.inApp": "In the app",
  "settings.inAppEnable": "Show overdue loans in the app",
  "settings.inAppHint":
    "A note on the library page, and the overdue loans page it links to. Switched off, that page stays empty and every other channel keeps running. This is the only channel that needs nothing set up, so it is on to begin with.",
  "settings.inAppPrivacyNote":
    "This one has a reader, so the rule above does not apply to it: each person sees the overdue loans they lent or borrowed, including their own private books, and never anybody else's.",
  "settings.senderHealthNotYet":
    "Not run yet. Reminders go out on the hour, and only when something is overdue.",
  "settings.senderHealthWorking": "Working. Last run on {when}.",
  "settings.senderHealthFailedOnce":
    "The last attempt failed: {detail} It will be tried again.",
  // No count in it. The refusal arm reports a channel as broken on its first
  // failure, so "1 attempts have failed in a row" was reachable and this
  // catalogue has no plural forms. What replaces it says more: when the run of
  // failures started, and when it was last tried, which is what tells a reader
  // whether the verdict is fresh.
  "settings.senderHealthBroken":
    "Not working since {since}. The last attempt was on {when}: {detail}",

  // ── Mail and chat reminders ─────────────────────────────────────────────
  //
  // The two channels a household has without building anything: a mailbox and
  // a group chat. The webhook is the third and stays where it was.
  "settings.senders": "Mail and chat reminders",
  "settings.sendersHint":
    "The same reminder, on channels a household already has. Each one is switched on by itself, and every one that is on gets the same message.",
  "settings.sendersPrivacyNote":
    "Both of these go to a mailbox or a chat that more than one person reads, so private books are left out of them exactly as they are left out of the webhook.",

  "settings.mail": "Email",
  "settings.mailEnable": "Send the reminder by email",
  "settings.mailHint":
    "One message to the household's own mailbox, listing the same loans.",
  "settings.mailServer": "Mail server",
  "settings.mailServerPlaceholder": "smtp.example.org",
  "settings.mailPort": "Port",
  "settings.mailUsername": "Mail username",
  "settings.mailUsernamePlaceholder":
    "Leave empty if the server needs no login",
  "settings.mailPassword": "Mail password",
  "settings.mailPasswordPlaceholder":
    "Paste a new password to replace the stored one",
  "settings.mailPasswordShow": "Show the mail password",
  "settings.mailPasswordHide": "Hide the mail password",
  "settings.mailPasswordSet": "A password is stored ({preview}).",
  "settings.mailPasswordMissing": "No password stored.",
  "settings.mailPasswordSave": "Save password",
  "settings.mailPasswordClear": "Remove stored password",
  "settings.mailSecurity": "Encryption",
  "settings.mailSecurityStartTls": "STARTTLS",
  "settings.mailSecurityTls": "TLS",
  "settings.mailSecurityNone": "None",
  "settings.mailSecurityHint":
    "Certificates and host names are always checked, and nothing here can switch that off. A password with no encryption is refused, because it would cross the network in the clear.",
  "settings.mailFrom": "From address",
  "settings.mailFromPlaceholder": "library@example.org",
  "settings.mailTo": "Send reminders to",
  "settings.mailToPlaceholder": "house@example.org",
  "settings.mailToHint":
    "One address, or several separated by commas. At most ten.",
  "settings.mailSave": "Save mail settings",
  "settings.mailFromEnv":
    "This deployment sets {fields} in its environment, so those fields are fixed here.",

  "settings.telegram": "Telegram",
  "settings.telegramEnable": "Send the reminder to a Telegram chat",
  "settings.telegramHint":
    "One message to one chat, not to each person. A bot cannot write to somebody who has never written to it first, so per person delivery would fail silently for anyone who skipped that step.",
  "settings.telegramToken": "Bot token",
  "settings.telegramTokenPlaceholder":
    "Paste a new token to replace the stored one",
  "settings.telegramTokenShow": "Show the bot token",
  "settings.telegramTokenHide": "Hide the bot token",
  "settings.telegramTokenSet": "A token is stored ({preview}).",
  "settings.telegramTokenMissing":
    "No token stored. Create a bot with @BotFather and paste the token it gives you.",
  "settings.telegramTokenSave": "Save token",
  "settings.telegramTokenClear": "Remove stored token",
  "settings.telegramChat": "Chat id",
  "settings.telegramChatPlaceholder": "-1001234567890",
  "settings.telegramChatHint":
    "The number of the group the bot was added to, or an @name for a public channel.",
  "settings.telegramChatSave": "Save chat id",
  "settings.telegramFromEnv":
    "This deployment sets this in its environment, so it is fixed here.",

  "settings.goodreads": "Goodreads",
  "settings.goodreadsEnable": "Show Goodreads lookup links",
  "settings.goodreadsHint":
    "Adds a link next to each title that searches Goodreads.",

  // ── Rating and reading dates ────────────────────────────────────────────
  "rating.label": "Your rating",
  "rating.clear": "Clear rating",
  "rating.setTo": "Rate {stars} out of 5",
  "rating.unrated": "Not rated",
  "rating.averageLabel": "Average rating",

  "reading.started": "Started {date}",
  "reading.finished": "Finished {date}",
  "reading.finishedThisYear": "Finished this year",

  // ── Reading progress ────────────────────────────────────────────────────
  //
  // Two units, and the strings say which one each number is in. A bare "64"
  // beside a bare "40" is two different claims that look like one.
  "progress.label": "Reading progress",
  "progress.none": "Nothing recorded yet.",
  "progress.onPage": "Page {page}",
  "progress.onPageOf": "Page {page} of {total}",
  "progress.atPercent": "{percent}% through",
  "progress.unit": "Record a page or a percentage",
  "progress.unitPage": "Page",
  "progress.unitPercent": "Percent",
  "progress.pagePlaceholder": "Page reached",
  "progress.percentPlaceholder": "Percent read",
  "progress.minutes": "Minutes read",
  "progress.minutesPlaceholder": "Minutes",
  "progress.minutesRead": "{minutes} min",
  "progress.record": "Record progress",
  "progress.removeEntry": "Remove this entry",

  // ── Series ──────────────────────────────────────────────────────────────
  "series.label": "Series",
  "series.title": "Series",
  "series.placeholder": "Series name",
  "series.numberPlaceholder": "No.",
  "series.partOf": "{name}, book {index}",
  "series.partOfUnnumbered": "Part of {name}",
  "series.bookCount": "{count} books",
  "series.missing": "Missing: {numbers}",
  "series.complete": "No gaps",
  "series.none": "No series yet",
  "series.noneHint": "Add a series to a book and it will show up here",
  "series.viewAll": "See the whole series",
  "series.couldNotLoad": "Could not load the series.",

  // ── Location ────────────────────────────────────────────────────────────
  "location.label": "Where it is",
  "location.placeholder": "Living room shelf 3",
  "location.unset": "Not recorded",
  "location.filterAll": "Anywhere",
  "location.hint": "Free text. Whatever you would say out loud.",
  "location.carriedOver":
    "Kept for the next book, so a whole shelf is typed once.",
  "location.batchLabel": "Shelf for everything in this run",

  // ── Collections ─────────────────────────────────────────────────────────
  "collections.title": "Collections",
  "collections.label": "Collection",
  "collections.none": "Not in a collection",
  "collections.filterAll": "Any collection",
  "collections.filterUnfiled": "Not in a collection",
  "collections.bookCount": "{count} books",
  "collections.empty": "No collections yet",
  "collections.emptyHint":
    "A collection splits the shelf: physical from ebook, kept from sold, yours from mine. A book is in one collection, so pick the split that matters most and use tags for the rest.",
  "collections.explain":
    "A collection groups books. It never hides them: who can see a book is still up to whether it is private.",
  "collections.newName": "Name",
  "collections.newPlaceholder": "Ebooks",
  "collections.create": "Add collection",
  "collections.creating": "Adding...",
  "collections.rename": "Rename",
  "collections.renamePrompt": "What should this collection be called?",
  "collections.delete": "Delete",
  "collections.deleteConfirm":
    'Delete "{name}"? The {count} books in it stay in the library, with no collection.',
  "collections.browse": "Show these books",
  "collections.couldNotLoad": "Could not load the collections.",
  "collections.saving": "Filing...",

  // ── Authors ─────────────────────────────────────────────────────────────
  "authors.title": "Authors",
  "authors.label": "Author",
  "authors.explain":
    "Everybody credited on the shelf. Names come from what each book says, so one person can appear twice: fold the spellings together and the books stay exactly as they are.",
  "authors.search": "Search authors",
  "authors.searchPlaceholder": "Name",
  "authors.bookCount": "{count} books",
  "authors.none": "No authors yet",
  "authors.noneHint": "Add a book with an author and they will show up here",
  "authors.noMatches": "No author matches that",
  "authors.couldNotLoad": "Could not load the authors.",
  "authors.alsoSpelled": "Also spelled: {spellings}",
  "authors.mergedFrom": "Folded in: {spelling}",
  "authors.undo": "Undo this merge",
  "authors.browse": "Show these books",
  "authors.wikipediaOn": "Read about {name} on Wikipedia",
  // Shown when the article we could reach is not in the reader's language. The
  // owner's rule on #89: a page they cannot read beats an absent button,
  // because it is still the right person. Naming the language is what stops
  // that being a surprise.
  "authors.wikipediaInOther": "Read about {name} on Wikipedia, in {language}",
  // The floor of the fallback chain: no Wikipedia edition holds an article, or
  // Wikidata could not be reached. The item page still names the right person.
  "authors.wikidataItem": "Look {name} up on Wikidata",
  "authors.select": "Select {name}",
  "authors.selectedCount": "{count} selected",
  "authors.keepNamed": "Keep {name}",
  "authors.suggestionsTitle": "Probably the same person",
  "authors.suggestionsExplain":
    "Uncheck anybody who does not belong, then pick the name to keep. Nothing in the books changes and you can undo it from the card afterwards.",
  "authors.keepThis": "Keep this name",
  "authors.merging": "Merging...",
  "authors.otherName": "Or a name none of them has",
  "authors.renameName": "A name to use instead",
  "authors.rename": "Rename",
  "authors.renameConfirm": 'Rename "{from}" to "{name}"?',
  "authors.otherNamePlaceholder": "Ursula K. Le Guin",
  "authors.mergeIntoOther": "Fold into this name",
  "authors.confirm": 'Fold {count} spellings into "{name}"?',
  "authors.foldedInto": 'That name is already "{name}", so they went there.',
  "authors.reasonSpelling": "same name, spaced differently",
  "authors.reasonInitials": "an initial against a full name",
  "authors.reasonFragment": "part of a longer name",
  "authors.include": "Include {name}",

  // ── Duplicates ──────────────────────────────────────────────────────────
  "duplicates.title": "Possible duplicates",
  "duplicates.none": "No duplicates found",
  "duplicates.noneHint":
    "Nothing in the library looks like the same book twice",
  "duplicates.explain":
    "These look like the same book under more than one entry. Pick the one to keep and the others fold into it.",
  "duplicates.keepThis": "Keep this one",
  "duplicates.merging": "Merging...",
  "duplicates.merged": "Merged into one entry.",
  "duplicates.confirm":
    'Fold {count} entries into "{title}"? This cannot be undone.',
  "duplicates.couldNotLoad": "Could not check for duplicates.",

  // ── Bulk actions ────────────────────────────────────────────────────────
  "bulk.more": "More actions",
  "bulk.addTag": "Add tag",
  "bulk.removeTag": "Remove tag",
  "bulk.setStatus": "Set reading status",
  "bulk.setLocation": "Set location",
  "bulk.setCollection": "Put in a collection",
  "bulk.clearCollection": "Take out of every collection",
  "bulk.delete": "Delete",
  "bulk.deleteConfirm": "Delete {count} books? This cannot be undone.",
  "bulk.chooseTag": "Choose a tag",
  "bulk.locationPrompt": "Where are these books?",
  "bulk.apply": "Apply",

  // ── Rapid intake ────────────────────────────────────────────────────────
  "rapid.title": "Rapid mode",
  "rapid.start": "Scan several",
  "rapid.stop": "Finish scanning",
  "rapid.explain":
    "Keep scanning. Each book is looked up and queued, and you confirm the whole batch at the end.",
  "rapid.queued": "{count} scanned",
  "rapid.lookingUp": "Looking up...",
  "rapid.notFound": "Not found: {isbn}",
  "rapid.duplicate": "Already scanned",
  "rapid.alreadyInLibrary": "Already in the library",
  "rapid.reviewTitle": "Review {count} books",
  "rapid.addAll": "Add all",
  "rapid.adding": "Adding...",
  "rapid.discard": "Discard",
  "rapid.added": "{count} added. {failed} still below, with the reason.",
  "rapid.removeFromQueue": "Remove {isbn} from the queue",
  "rapid.nothingScanned": "Nothing scanned yet",

  // ── Loan due dates ──────────────────────────────────────────────────────
  "loans.dueDate": "Due back",
  "loans.dueOn": "Due {date}",
  "loans.noDueDate": "No date",
  "loans.overdue": "Overdue",
  "loans.overdueSince": "Overdue since {date}",
  "loans.overdueOnly": "Overdue only",
  "loans.overdueBanner": "{count} loans need chasing.",
  "loans.chaseThem": "Show them",

  // ── The overdue page ────────────────────────────────────────────────────
  //
  // #102. The library page keeps the reminder and this holds the detail. The
  // delivery lines below describe a channel and never a loan: the health
  // record is written once per sender per run and carries no loan id, so a
  // sentence implying a receipt for one book would be one this app cannot
  // support. `overdue.deliveryNote` is what stops it being read that way.
  "overdue.title": "Overdue",
  "overdue.couldNotLoad": "The overdue list could not be loaded.",
  "overdue.none": "Nothing is overdue",
  "overdue.noneHint": "Every book that is out is still within its date.",
  "overdue.switchedOff": "The in app reminder is switched off",
  "overdue.switchedOffHint":
    "An admin can switch it back on under Lending. Only this page is affected: any channel that sends outward carries on, and the loans themselves are still on the loans page.",
  "overdue.capped": "Showing the {shown} most overdue of {total}.",
  "overdue.deliveryTitle": "Reminder channels",
  "overdue.deliveryNote":
    "Endpaper records what each channel did on its last run. It does not record which reminder reached which borrower, so these lines are about the channel and not about any one loan below.",
  "overdue.deliveryNone": "No channel sends these reminders anywhere.",
  "overdue.deliveryUnreadable":
    "The channel record could not be read, so this says nothing about whether reminders are going out.",

  // ── The copy itself ─────────────────────────────────────────────────────
  "copy.title": "This copy",
  "copy.hint": "What you own, rather than what the book is.",
  "copy.format": "Format",
  "copy.format.unset": "Not recorded",
  "copy.format.hardcover": "Hardcover",
  "copy.format.paperback": "Paperback",
  "copy.format.ebook": "Ebook",
  "copy.format.audiobook": "Audiobook",
  "copy.format.other": "Other",
  "copy.condition": "Condition",
  "copy.condition.unset": "Not recorded",
  "copy.condition.new": "As new",
  "copy.condition.good": "Good",
  "copy.condition.fair": "Fair",
  "copy.condition.poor": "Poor",
  "copy.condition.ex_library": "Ex-library",
  "copy.price": "Price paid",
  "copy.priceInvalid": "Write a price like 12.99, or leave it empty.",
  "copy.currency": "Currency",
  "copy.purchasedAt": "Bought on",
  "copy.purchaseSource": "Bought from",
  "copy.save": "Save copy details",
  "copy.purchaseSourcePlaceholder": "The Oxfam on the high street",

  // ── More than one copy of the same book ─────────────────────────────────
  "copies.title": "Copies",
  "copies.count": "{count} copies of this book",
  "copies.hint":
    "A second copy is a second object: its own shelf, its own condition, its own loan.",
  "copies.thisOne": "This one",
  "copies.open": "Open",
  "copies.noShelf": "No shelf recorded",
  "copies.onLoan": "Out on loan",
  "copies.add": "Add another copy",
  "copies.adding": "Adding...",
  "copies.fromScanHint":
    "A copy takes its tags, its cover and its privacy from the book already here.",
  "copies.addFailed": "That copy could not be added.",
  "copies.loadFailed": "The other copies of this book could not be loaded.",
  "copies.badge": "{count} copies",
  "format.filterAll": "Any format",

  // ── Willing to lend, and willing to talk ────────────────────────────────
  "lending.label": "Lending",
  "lending.unset": "Not recorded",
  "lending.filterAll": "Lending: any",
  "lending.happy": "Happy to lend",
  "lending.in_use": "Using it myself right now",
  "lending.never": "Never lent",
  "lending.neverWarning": "This book is marked as never lent.",
  "lending.lendAnyway": "Lend it anyway",
  "discuss.toggle": "I would like to talk about this book, ask me about it",
  "discuss.label": "Ask about it",
  "discuss.badge": "Talk about it",
  "discuss.others": "Ask {names} about this book.",

  // ── Importing a library ─────────────────────────────────────────────────
  "import.title": "Bring a library across",
  "import.explain":
    "A CSV or TSV export from Goodreads, LibraryThing, StoryGraph, Libib or anything else with a title column. The columns are worked out for you and shown before anything is saved.",
  "import.chooseFile": "Choose a file",
  "import.reading": "Reading the file...",
  "import.importing": "Importing...",
  "import.confirm": "Import {count} books",
  "import.previewTitle": "{count} rows read. Columns found:",
  "import.notFound": "Not found in this file: {fields}",
  "import.fieldTitle": "Title",
  "import.fieldAuthor": "Author",
  "import.fieldIsbn": "ISBN",
  "import.fieldStatus": "Reading status",
  "import.fieldRating": "Rating",
  "import.fieldDateRead": "Date read",
  "import.fieldPublisher": "Publisher",
  "import.fieldYear": "Year",
  "import.fieldPages": "Pages",
  "import.fieldFormat": "Format",
  "import.fieldTags": "Tags",
  "import.createMissing": "Add books that are not in the catalogue yet",
  "import.createMissingHint":
    "They arrive marked as not confirmed: an export says what somebody read, not what is on the shelf.",
  "import.applyTags": "Bring the tags across too",
  "import.applyTagsHint":
    "This file has {count} different tags. They are created here for everybody, under Your tags, and can only be removed one at a time.",
  "import.result":
    "{rowsRead} rows read, {matched} matched, {created} added, {statusesUpdated} statuses updated.",
  "import.skipped": "{count} rows had no title and were skipped.",
  "import.unmatched": "Not found in the catalogue:",

  // ── MARC (library mode) ─────────────────────────────────────────────────
  "marc.title": "Take a catalogue across",
  "marc.explain":
    "A MARCXML file another library exported. Records are matched on ISBN, then on author and title together, so importing the same file twice does not double the catalogue.",
  "marc.chooseFile": "Choose a MARC file",
  "marc.reading": "Reading the file...",
  "marc.importing": "Importing...",
  "marc.previewTitle":
    "{total} records in the file, {readable} this app can store.",
  "marc.alreadyHeld":
    "{count} are already on this shelf and will be filled in rather than added.",
  "marc.blocked":
    "{count} carry an ISBN that belongs to a book this account cannot see, and will be left alone.",
  "marc.skipped": "{count} records have no title and will be left out.",
  "marc.createMissing": "Add the {count} records this catalogue does not hold",
  "marc.createMissingHint":
    "They arrive marked as not confirmed: another library's record says that library holds the book, not this one.",
  "marc.confirm": "Import {count} records",
  "marc.confirmMatchedOnly": "Fill in {count} records already here",
  "marc.result": "{rowsRead} records read, {matched} matched, {created} added.",
  "marc.resultSkipped":
    "{count} records were left out: no title, or an ISBN that belongs to a book this account cannot see.",

  // ── Backup ──────────────────────────────────────────────────────────────
  "backup.title": "Backup",
  "backup.explain":
    "A full copy of the library: every book, account, note, loan, reading status and cover image. The CSV export is not this. It carries one row per book and drops the rest.",
  "backup.download": "Download a backup",
  "backup.downloadFailed": "The backup could not be made.",
  "backup.restoreTitle": "Restore from a backup",
  "backup.restoreWarning":
    "Restoring replaces everything in this library. Books added since the backup was taken are gone.",
  "backup.chooseFile": "Backup file",
  "backup.restoreAction": "Restore from {name}",
  "backup.restoreConfirm":
    "Replace every book, account and cover in this library with the backup? This cannot be undone.",
  "backup.restoreFailed": "That backup could not be restored.",
  "backup.restored": "Restored {books} books and {covers} covers.",

  // ── Covers ──────────────────────────────────────────────────────────────
  "covers.title": "Covers",
  "covers.explain":
    "Covers are fetched once and served from this library, so a book keeps its cover even when the image service that had it goes away. Books that arrived through an import have none yet.",
  "covers.backfill": "Fetch missing covers",
  "covers.backfillFailed": "The covers could not be fetched.",
  "covers.result":
    "Looked at {examined} books and stored {stored} covers. No image service has one for {missing}.",
  "covers.unreachable":
    "{count} of them have a cover somewhere that could not be downloaded from here. They keep their link and are tried again on the next pass through the library.",
  "covers.remaining":
    "{remaining} books still to go. Run it again to carry on.",
  "covers.allDone": "Every book that could have a cover has one.",

  // ── About ───────────────────────────────────────────────────────────────────
  "about.title": "About Endpaper",
  // The badge row's labels. Each is a whole phrase on its own rather than a
  // fragment of one, so a translator is never asked to guess word order. The
  // values are not here: a version string, "Apache 2.0" and "GitHub" are names
  // rather than language, and a catalogue entry that is byte identical in every
  // language is a translation nobody can make.
  "about.versionLabel": "Version",
  "about.licenceLabel": "Licence",
  "about.sourceLabel": "Source",
  "about.support":
    "If you like Endpaper and want to support my work, buy me a coffee. It helps pay for the public server that lets two copies of Endpaper reach each other. All features are free either way.",
  "about.kofiAlt": "Support Endpaper on Ko-fi",

  // ── Saved views ─────────────────────────────────────────────────────────
  "saved.saveThisView": "Save this view",
  "saved.nameLabel": "Name for this view",
  "saved.namePlaceholder": "Unread in the loft",
  "saved.forget": "Forget {name}",

  // ── Trash ───────────────────────────────────────────────────────────────
  "nav.trash": "Trash",
  "trash.title": "Trash",
  "trash.explain":
    "Deleted books wait here until you empty it. Nothing is removed on its own.",
  "trash.empty": "The trash is empty",
  "trash.emptyHint": "Books you delete land here, with everything on them.",
  "trash.deletedOn": "Deleted {date}",
  "trash.restore": "Put back",
  "trash.restored": "Back on the shelf.",
  "trash.deleteForever": "Delete for good",
  "trash.deleteForeverConfirm":
    'Delete "{title}" for good? This one cannot be undone.',
  "trash.emptyAll": "Empty the trash",
  "trash.emptyAllConfirm":
    "Delete all {count} books in the trash for good? This cannot be undone.",
  "trash.emptied": "{count} books deleted for good.",
  "trash.movedCount": "{count} books moved to the trash.",
  "trash.open": "Open trash",

  // ── Wishlist ────────────────────────────────────────────────────────────
  "nav.wishlist": "Wishlist",
  "wishlist.title": "Wishlist",
  "wishlist.empty": "Nothing on the wishlist",
  "wishlist.emptyHint":
    "A book you want but do not own yet: mark it as want to read and not owned.",
  "wishlist.explain": "Books you want to read that are not on the shelf.",

  // ── Help ────────────────────────────────────────────────────────────────
  "help.title": "What is this?",
  "help.aboutSearch": "About searching for a book",
  "help.aboutEnrich": "About extra book details",

  "help.googleBooks.title": "Google Books lookup",
  "help.googleBooks.what":
    "Google Books fills in details a barcode does not carry: page count, language, categories, series and a description. It needs a free API key, which an admin sets up once for everyone here.",
  "help.googleBooks.notConfigured":
    "No key is set yet, so this is switched off. Here is how to get one.",
  "help.googleBooks.step1": "Create a project in the Google Cloud console.",
  "help.googleBooks.step2": "Enable the Books API for that project.",
  "help.googleBooks.step3": "Create an API key under Credentials.",
  "help.googleBooks.step4":
    "Paste it into Settings here, and switch the feature on.",
  "help.googleBooks.cost":
    "The Books API is free to use. A card is not required, and the daily allowance is far more than a home library will ever need.",
  "help.googleBooks.restrict":
    "The key is stored here and sent only from this server, so restricting it to the Books API is enough. It is never shown again once saved.",
  "help.googleBooks.toSettings": "Open Settings",
  "help.googleBooks.adminOnly":
    "Only an admin can save the key. If that is not you, send them this page.",

  "help.disabledSearch":
    "Search works without a key. A key adds descriptions and genres to the results.",
  "help.disabledEnrich":
    "Extra details work without a key. A key adds descriptions and genres.",

  // ── Masked fields ───────────────────────────────────────────────────────
  "field.show": "Show",
  "field.hide": "Hide",

  // ── Errors ──────────────────────────────────────────────────────────────
  "error.404.code": "Error 404",
  "error.404.title": "Nothing here",
  "error.404.message":
    "We could not find that page or book. It may have been removed from the catalog.",
  "error.403.code": "Error 403",
  "error.403.title": "Not allowed",
  "error.403.message":
    "Your account does not have access to that. If it should, ask whoever set up the library.",
  "error.500.code": "Error 500",
  "error.500.title": "Something broke",
  "error.500.message":
    "That is our fault, not yours. Reloading usually clears it.",
  "error.sessionEnded.code": "Error 401",
  "error.sessionEnded.title": "Your session ended",
  "error.sessionEnded.message":
    "The sign-in portal ended this session, and reloading did not bring it back. Sign in again to carry on.",
  "error.sessionEnded.action": "Sign in again",
  "error.backToLibrary": "Back to the library",
  "error.reload": "Reload the page",

  // ── The published catalogue ─────────────────────────────────────────────
  //
  // Read by people with no account, so nothing here may assume the reader
  // knows what Endpaper is or who runs this library.
  "public.title": "Catalogue",
  "public.skipToContent": "Skip to the catalogue",
  "public.signIn": "Sign in",
  "public.search": "Search this catalogue...",
  "public.searchLabel": "Search this catalogue",
  "public.resultCount": "{count} books",
  "public.resultCountOne": "1 book",
  "public.noResults": "Nothing found",
  "public.noResultsHint": "Try fewer words, or a different spelling.",
  "public.emptyHint": "This catalogue has nothing in it yet.",
  "public.loadMore": "Show more",
  "public.backToCatalogue": "Back to the catalogue",
  "public.closedTitle": "Nothing here",
  "public.closedHint": "This library does not publish its catalogue.",
  "public.classifications": "Classification",
  "public.fact.isbn": "ISBN",
  "public.fact.publisher": "Publisher",
  "public.fact.year": "Year",
  "public.fact.language": "Language",
  "public.fact.pages": "Pages",
  "public.fact.format": "Format",
  "public.fact.series": "Series",

  // The provider list. Catalogue names are proper nouns and stay as they are in
  // both catalogues; only the sentences around them are translated.
  "providers.title": "Where book details come from",
  "providers.hint":
    "These are the catalogues this library asks about a book. Turn one off and it is not asked at all. The order is the order they are asked in, and it does not change which catalogue is believed when two disagree about the same field.",
  "providers.costHint":
    "Searching by title asks every catalogue that is on at the same time, so one more costs nothing unless it turns out to be the slowest. Scanning an ISBN asks the top two together and the rest one at a time, stopping at the first answer.",
  "providers.moveUp": "Move {name} up",
  "providers.moveDown": "Move {name} down",
  "providers.moved": "{name} moved to position {position} of {total}.",
  "providers.name.open_library": "Open Library",
  "providers.name.google_books": "Google Books",
  "providers.name.dnb": "German National Library",
  "providers.name.k10plus": "K10plus",
  "providers.name.oenb": "Austrian National Library",
  "providers.name.bnf": "National Library of France",
  "providers.name.loc": "Library of Congress",
  "providers.status.needsKey":
    "Needs an API key. Add one below, or it cannot answer.",
  "providers.status.switchedOffBelow":
    "A key is stored, but this catalogue is switched off in its own card below.",
  "providers.status.searchOnly":
    "Answers title searches only, so its position does not affect scanning.",
  "providers.status.askedFirst":
    "Asked on every scan, with the others at the top of this list.",
  "providers.status.askedAfter":
    "Asked only when the ones above it find nothing.",
  "providers.status.off": "Off. This catalogue is never asked.",
} as const;

/** Every message key. Adding one here requires a German translation. */
export type MessageKey = keyof typeof en;

/** The shape every locale must satisfy, exhaustively. */
export type Messages = Record<MessageKey, string>;
