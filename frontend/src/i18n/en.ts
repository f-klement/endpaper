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
  "nav.account": "Account",
  "nav.switchAccount": "Switch Account",
  "nav.exportLibrary": "Export Library",
  "nav.logout": "Logout",

  // ── Common ──────────────────────────────────────────────────────────────
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.saving": "Saving...",
  "common.edit": "Edit",
  "common.delete": "Delete",
  "common.done": "Done",
  "common.add": "Add",
  "common.close": "Close",
  "common.back": "Back",
  "common.tryAgain": "Try again",
  "common.loading": "Loading...",
  "common.somethingWentWrong": "Something went wrong.",
  "common.selectAll": "Select all",
  "common.clearSelection": "Clear selection",
  "common.selectedCount": "{count} selected",

  // ── Reading status ──────────────────────────────────────────────────────
  "status.unread": "Unread",
  "status.want_to_read": "Want to Read",
  "status.reading": "Reading",
  "status.read": "Read",
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
  "library.loaned": "Loaned",

  "sort.title_asc": "Title A to Z",
  "sort.title_desc": "Title Z to A",
  "sort.author": "Author",
  "sort.year_desc": "Year (newest)",
  "sort.year_asc": "Year (oldest)",
  "sort.newest": "Recently added",
  "sort.series": "Series order",

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
  "book.remove": "Remove from Catalog",
  "book.removeConfirm": 'Remove "{title}" from the catalog?',
  "book.noTags": "No tags yet",
  "book.addTag": "+ Add",
  "book.removeTag": "Remove {tag}",

  // ── Enrichment ──────────────────────────────────────────────────────────
  "enrich.button": "Find more details",
  "enrich.working": "Searching...",
  "enrich.updated": "Added: {fields}.",
  "enrich.nothingNew":
    "Nothing new found. The details here are already complete.",
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
  "goodreads.import": "Import from Goodreads",
  "goodreads.importExplain":
    "Goodreads retired its API in 2020, so there is no way to connect an account. Export your library from Goodreads (My Books, then Import/Export) and upload the file here.",
  "goodreads.chooseFile": "Choose export file",
  "goodreads.importing": "Importing...",
  "goodreads.createMissing": "Also add books that are not in the library yet",
  "goodreads.createMissingHint":
    "New books are marked as not confirmed, because an export says what you read, not what is on your shelf.",
  "goodreads.result":
    "{rowsRead} entries read. {matched} matched, {created} added, {statusesUpdated} statuses updated.",
  "goodreads.skipped":
    "{count} entries were on a shelf that does not map to a status.",
  "goodreads.unmatched": "Not found in your library:",
  "goodreads.confirmPrompt":
    "The books just added are not confirmed as being on your shelf. Review them now?",

  // ── Scan ────────────────────────────────────────────────────────────────
  "scan.title": "Scan Barcode",
  "scan.pointAtBarcode": "Point at barcode",
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
  "scan.addCover": "Add cover photo (optional)",
  "scan.replaceCover": "Replace cover photo (optional)",
  "scan.privateBook": "Private (only visible to me)",
  "scan.addToLibrary": "Add to Library",
  "scan.adding": "Adding...",
  "scan.tagsSelected": "({count} selected)",

  // ── Search (Google Books, before a book exists) ─────────────────────────
  "search.orSearchByTitle": "Or search by title:",
  "search.placeholder": "Title, author, or both",
  "search.label": "Search Google Books",
  "search.button": "Search",
  "search.searching": "Searching...",
  "search.noResults": "No matches. Try fewer words, or add the book by hand.",
  "search.pickHint":
    "Pick one to fill in the details. Nothing is saved until you confirm.",
  "search.disabled":
    "Search is switched off. An admin can enable it in Settings.",

  // ── Loans ───────────────────────────────────────────────────────────────
  "loans.title": "Loans",
  "loans.showAll": "Show all",
  "loans.activeOnly": "Active only",
  "loans.none": "No loans",
  "loans.noneActive": "No active loans",
  "loans.allAccountedFor": "All books are accounted for",
  "loans.loanedToBy": "Loaned to {to} by {by}",
  "loans.returnedOn": "Returned {date}",
  "loans.markReturned": "Mark Returned",
  "loans.updating": "Updating...",
  "loans.management": "Loan Management",
  "loans.loanTo": "Loan to...",
  "loans.loanToLabel": "Loan to",
  "loans.loanButton": "Loan",
  "loans.markAsReturned": "Mark as Returned",
  "loans.badge": "Loaned to {name}",
  "loans.couldNotLoad": "Could not load the loans.",

  // ── Notes ───────────────────────────────────────────────────────────────
  "notes.title": "Notes",
  "notes.none": "No notes yet",
  "notes.placeholder": "Add a note...",
  "notes.addLabel": "Add a note",
  "notes.editLabel": "Edit note",

  // ── Stats ───────────────────────────────────────────────────────────────
  "stats.title": "Collection Stats",
  "stats.booksInLibrary": "books in your library",
  "stats.byMember": "Books Added by Member",
  "stats.byType": "By Type",
  "stats.byGenre": "By Genre",
  "stats.byAge": "By Age",
  "stats.overTime": "Books Added Over Time",
  "stats.couldNotLoad": "Could not load your stats.",
  "stats.loading": "Loading stats",

  // ── Tags ────────────────────────────────────────────────────────────────
  "tags.type": "Type",
  "tags.genre": "Genre",
  "tags.age": "Age",

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

  "theme.label": "Appearance",
  "theme.hint": "Applies to you on this device.",
  "theme.light": "Light",
  "theme.dark": "Dark",
  "theme.system": "Follow system",
  "theme.systemHint": "Matches whatever your phone or computer is set to.",
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
  "rapid.added": "{count} added, {failed} could not be added.",
  "rapid.nothingScanned": "Nothing scanned yet",

  // ── Loan due dates ──────────────────────────────────────────────────────
  "loans.dueDate": "Due back",
  "loans.dueOn": "Due {date}",
  "loans.noDueDate": "No date",
  "loans.overdue": "Overdue",
  "loans.overdueSince": "Overdue since {date}",
  "loans.overdueOnly": "Overdue only",
  "loans.overdueBanner": "{count} loans are overdue.",
  "loans.chaseThem": "Show them",

  // ── Wishlist ────────────────────────────────────────────────────────────
  "nav.wishlist": "Wishlist",
  "wishlist.title": "Wishlist",
  "wishlist.empty": "Nothing on the wishlist",
  "wishlist.emptyHint":
    "A book you want but do not own yet: mark it as want to read and not owned.",
  "wishlist.explain": "Books you want to read that are not on the shelf.",

  // ── Help ────────────────────────────────────────────────────────────────
  "help.title": "What is this?",
  "help.aboutSearch": "About searching Google Books",
  "help.aboutEnrich": "About extra book details",

  "help.googleBooks.title": "Google Books lookup",
  "help.googleBooks.what":
    "Google Books fills in details a barcode does not carry: page count, language, categories, series and a description. It needs a free API key, which an admin sets up once for the whole household.",
  "help.googleBooks.notConfigured":
    "No key is set yet, so this is switched off. Here is how to get one.",
  "help.googleBooks.step1": "Create a project in the Google Cloud console.",
  "help.googleBooks.step2": "Enable the Books API for that project.",
  "help.googleBooks.step3": "Create an API key under Credentials.",
  "help.googleBooks.step4":
    "Paste it into Settings here, and switch the feature on.",
  "help.googleBooks.cost":
    "The Books API is free to use. A card is not required, and the daily allowance is far more than a family library will ever need.",
  "help.googleBooks.restrict":
    "The key is stored here and sent only from this server, so restricting it to the Books API is enough. It is never shown again once saved.",
  "help.googleBooks.toSettings": "Open Settings",
  "help.googleBooks.adminOnly":
    "Only an admin can save the key. If that is not you, send them this page.",

  "help.disabledSearch":
    "Search is off until an admin adds a Google Books key.",
  "help.disabledEnrich":
    "Extra details are off until an admin adds a Google Books key.",

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
  "error.backToLibrary": "Back to the library",
  "error.reload": "Reload the page",
} as const;

/** Every message key. Adding one here requires a German translation. */
export type MessageKey = keyof typeof en;

/** The shape every locale must satisfy, exhaustively. */
export type Messages = Record<MessageKey, string>;
