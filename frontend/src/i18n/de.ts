import type { Messages } from "./en";

/**
 * German messages.
 *
 * Typed as `Messages`, so leaving a key out is a compile error. Without that,
 * a missing translation shows up as an English sentence in the middle of a
 * German page, which is exactly the sort of thing nobody notices until a guest
 * does.
 *
 * Two conventions here:
 *
 * * **No em dashes.** House style for all UI strings, and German typography
 *   uses them differently from English anyway.
 * * **Informal address (du, dein).** This is a household bookshelf, not a bank.
 *   Mixing du and Sie reads badly, so it is du throughout.
 */
export const de: Messages = {
  // ── Navigation und Rahmen ───────────────────────────────────────────────
  "nav.library": "Bibliothek",
  "nav.scan": "Scannen",
  "nav.loans": "Ausleihen",
  "nav.stats": "Statistik",
  "nav.settings": "Einstellungen",
  "nav.account": "Konto",
  "nav.switchAccount": "Konto wechseln",
  "nav.exportLibrary": "Bibliothek exportieren",
  "nav.logout": "Abmelden",

  // ── Allgemein ───────────────────────────────────────────────────────────
  "common.cancel": "Abbrechen",
  "common.save": "Speichern",
  "common.saving": "Wird gespeichert...",
  "common.edit": "Bearbeiten",
  "common.delete": "Löschen",
  "common.done": "Fertig",
  "common.add": "Hinzufügen",
  "common.close": "Schließen",
  "common.back": "Zurück",
  "common.tryAgain": "Erneut versuchen",
  "common.loading": "Wird geladen...",
  "common.somethingWentWrong": "Etwas ist schiefgelaufen.",
  "common.selectAll": "Alle auswählen",
  "common.clearSelection": "Auswahl aufheben",
  "common.selectedCount": "{count} ausgewählt",

  // ── Lesestatus ──────────────────────────────────────────────────────────
  "status.unread": "Ungelesen",
  "status.want_to_read": "Möchte ich lesen",
  "status.reading": "Lese ich gerade",
  "status.read": "Gelesen",
  "status.all": "Alle",
  "status.mine": "Mein Lesestatus",

  // ── Besitz ──────────────────────────────────────────────────────────────
  "ownership.owned": "Im Regal",
  "ownership.not_owned": "Nicht im Besitz",
  "ownership.unknown": "Nicht bestätigt",
  "ownership.label": "Besitz",
  "ownership.filterAll": "Beliebig",
  "ownership.explain":
    "Ob ein Exemplar wirklich hier steht. Unabhängig davon, ob du es gelesen hast.",
  "ownership.confirmSelected": "Als im Regal markieren",
  "ownership.markNotOwned": "Als nicht im Besitz markieren",
  "ownership.bulkResult":
    "{updated} geändert, {unchanged} bereits gesetzt, {skipped} übersprungen.",
  "ownership.unconfirmedBanner":
    "Bei {count} Büchern ist nicht bestätigt, ob sie in deinem Regal stehen.",
  "ownership.reviewThem": "Jetzt prüfen",

  // ── Bibliothek ──────────────────────────────────────────────────────────
  "library.title": "Bibliothek",
  "library.scanButton": "+ Scannen",
  "library.search": "Bücher suchen...",
  "library.searchLabel": "Bücher suchen",
  "library.sortLabel": "Bücher sortieren",
  "library.tags": "Schlagwörter",
  "library.clear": "Zurücksetzen",
  "library.loadMore": "Mehr laden",
  "library.noBooks": "Keine Bücher gefunden",
  "library.adjustFilters": "Versuche es mit anderen Filtern",
  "library.scanFirstBook":
    "Scanne einen Barcode, um dein erstes Buch hinzuzufügen",
  "library.couldNotLoad": "Deine Bibliothek konnte nicht geladen werden.",
  "library.select": "Auswählen",
  "library.loaned": "Verliehen",

  "sort.title_asc": "Titel A bis Z",
  "sort.title_desc": "Titel Z bis A",
  "sort.author": "Autor",
  "sort.year_desc": "Jahr (neueste)",
  "sort.year_asc": "Jahr (älteste)",
  "sort.newest": "Zuletzt hinzugefügt",
  "sort.series": "Reihenfolge der Reihe",

  // ── Buchdetails ─────────────────────────────────────────────────────────
  "book.uploadCover": "Cover hochladen",
  "book.refreshMetadata": "Angaben aktualisieren",
  "book.refreshing": "Wird aktualisiert...",
  "book.by": "von {author}",
  "book.isbn": "ISBN: {isbn}",
  "book.pages": "{count} Seiten",
  "book.privateToggle": "Privat (nur für mich sichtbar)",
  "book.privateBadge": "Privat",
  "book.description": "Beschreibung",
  "book.categories": "Kategorien",
  "book.notFound": "Buch nicht gefunden.",
  "book.remove": "Aus dem Katalog entfernen",
  "book.removeConfirm": '"{title}" aus dem Katalog entfernen?',
  "book.noTags": "Noch keine Schlagwörter",
  "book.addTag": "+ Hinzufügen",
  "book.removeTag": "{tag} entfernen",

  // ── Zusätzliche Angaben ─────────────────────────────────────────────────
  "enrich.button": "Weitere Angaben suchen",
  "enrich.working": "Wird gesucht...",
  "enrich.updated": "Ergänzt: {fields}.",
  "enrich.nothingNew":
    "Nichts Neues gefunden. Die Angaben hier sind bereits vollständig.",
  "enrich.notFound": "Google Books hat keinen Eintrag zu diesem Buch.",
  "enrich.disabled":
    "Die Google Books Suche ist ausgeschaltet. Ein Administrator kann sie in den Einstellungen aktivieren.",
  "enrich.field.subtitle": "Untertitel",
  "enrich.field.author": "Autor",
  "enrich.field.publisher": "Verlag",
  "enrich.field.year": "Jahr",
  "enrich.field.description": "Beschreibung",
  "enrich.field.page_count": "Seitenzahl",
  "enrich.field.language": "Sprache",
  "enrich.field.categories": "Kategorien",
  "enrich.field.cover_url": "Cover",
  "enrich.field.google_books_id": "Referenz",

  // ── Goodreads ───────────────────────────────────────────────────────────
  "goodreads.lookup": "Bei Goodreads nachschlagen",
  "goodreads.import": "Aus Goodreads importieren",
  "goodreads.importExplain":
    "Goodreads hat seine Schnittstelle 2020 abgeschaltet, ein Konto lässt sich daher nicht verbinden. Exportiere deine Bibliothek bei Goodreads (My Books, dann Import/Export) und lade die Datei hier hoch.",
  "goodreads.chooseFile": "Exportdatei auswählen",
  "goodreads.importing": "Wird importiert...",
  "goodreads.createMissing":
    "Auch Bücher anlegen, die noch nicht in der Bibliothek sind",
  "goodreads.createMissingHint":
    "Neue Bücher werden als nicht bestätigt markiert, denn ein Export sagt nur, was du gelesen hast, nicht was in deinem Regal steht.",
  "goodreads.result":
    "{rowsRead} Einträge gelesen. {matched} zugeordnet, {created} angelegt, {statusesUpdated} Status geändert.",
  "goodreads.skipped":
    "{count} Einträge standen auf einem Regal, das keinem Status entspricht.",
  "goodreads.unmatched": "In deiner Bibliothek nicht gefunden:",
  "goodreads.confirmPrompt":
    "Bei den gerade angelegten Büchern ist nicht bestätigt, ob sie in deinem Regal stehen. Jetzt prüfen?",

  // ── Scannen ─────────────────────────────────────────────────────────────
  "scan.title": "Barcode scannen",
  "scan.pointAtBarcode": "Auf den Barcode richten",
  "scan.cameraUnavailable": "Kamera nicht verfügbar",
  "scan.orEnterManually": "Oder ISBN von Hand eingeben:",
  "scan.isbnLabel": "ISBN",
  "scan.lookUp": "Nachschlagen",
  "scan.lookingUp": "Buch wird gesucht...",
  "scan.invalidIsbn":
    "Das sieht nicht nach einer gültigen ISBN aus. Prüfe die Ziffern und versuche es erneut.",
  "scan.notFoundManual":
    "Keine Angaben zur ISBN {isbn} gefunden. Du kannst das Buch trotzdem von Hand anlegen.",
  "scan.titleRequired": "Titel *",
  "scan.titlePlaceholder": "Buchtitel",
  "scan.authorPlaceholder": "Name des Autors",
  "scan.couldNotAdd": "Das Buch konnte nicht hinzugefügt werden.",
  "scan.authorField": "Autor",
  "scan.addCover": "Coverfoto hinzufügen (optional)",
  "scan.replaceCover": "Coverfoto ersetzen (optional)",
  "scan.privateBook": "Privat (nur für mich sichtbar)",
  "scan.addToLibrary": "Zur Bibliothek hinzufügen",
  "scan.adding": "Wird hinzugefügt...",
  "scan.tagsSelected": "({count} ausgewählt)",

  // ── Suche (Google Books, bevor ein Buch existiert) ──────────────────────
  "search.orSearchByTitle": "Oder nach Titel suchen:",
  "search.placeholder": "Titel, Autor oder beides",
  "search.label": "Google Books durchsuchen",
  "search.button": "Suchen",
  "search.searching": "Suche läuft...",
  "search.noResults":
    "Keine Treffer. Versuche weniger Wörter, oder trage das Buch von Hand ein.",
  "search.pickHint":
    "Wähle einen Treffer aus, um die Angaben zu übernehmen. Gespeichert wird erst, wenn du bestätigst.",
  "search.disabled":
    "Die Suche ist ausgeschaltet. Ein Admin kann sie in den Einstellungen aktivieren.",

  // ── Ausleihen ───────────────────────────────────────────────────────────
  "loans.title": "Ausleihen",
  "loans.showAll": "Alle anzeigen",
  "loans.activeOnly": "Nur laufende",
  "loans.none": "Keine Ausleihen",
  "loans.noneActive": "Keine laufenden Ausleihen",
  "loans.allAccountedFor": "Alle Bücher sind da",
  "loans.loanedToBy": "Verliehen an {to} von {by}",
  "loans.returnedOn": "Zurück am {date}",
  "loans.markReturned": "Als zurück markieren",
  "loans.updating": "Wird aktualisiert...",
  "loans.management": "Ausleihe verwalten",
  "loans.loanTo": "Verleihen an...",
  "loans.loanToLabel": "Ausleihen an",
  "loans.loanButton": "Verleihen",
  "loans.markAsReturned": "Als zurückgegeben markieren",
  "loans.badge": "Verliehen an {name}",
  "loans.couldNotLoad": "Die Ausleihen konnten nicht geladen werden.",

  // ── Notizen ─────────────────────────────────────────────────────────────
  "notes.title": "Notizen",
  "notes.none": "Noch keine Notizen",
  "notes.placeholder": "Notiz hinzufügen...",
  "notes.addLabel": "Notiz hinzufügen",
  "notes.editLabel": "Notiz bearbeiten",

  // ── Statistik ───────────────────────────────────────────────────────────
  "stats.title": "Sammlung in Zahlen",
  "stats.booksInLibrary": "Bücher in deiner Bibliothek",
  "stats.byMember": "Hinzugefügt nach Person",
  "stats.byType": "Nach Art",
  "stats.byGenre": "Nach Genre",
  "stats.byAge": "Nach Alter",
  "stats.overTime": "Hinzugefügt im Zeitverlauf",
  "stats.couldNotLoad": "Die Statistik konnte nicht geladen werden.",
  "stats.loading": "Statistik wird geladen",

  // ── Schlagwörter ────────────────────────────────────────────────────────
  "tags.type": "Art",
  "tags.genre": "Genre",
  "tags.age": "Alter",

  // ── Anmeldung ───────────────────────────────────────────────────────────
  // The product name, left in English on purpose: a brand is not translated.
  "login.appName": "Endpaper",
  "login.tagline": "Euer eigener Bücherkatalog",
  "login.signIn": "Anmelden",
  "login.createAccount": "Konto erstellen",
  "login.switchToSignIn": "Zum Anmelden wechseln",
  "login.switchToRegister": "Zur Registrierung wechseln",
  "login.username": "Benutzername",
  "login.password": "Passwort",
  "login.usernamePlaceholder": "Benutzername eingeben",
  "login.passwordPlaceholder": "Passwort eingeben",
  "login.pleaseWait": "Bitte warten...",
  "login.firstAccountAdmin":
    "Das zuerst erstellte Konto wird zum Administrator.",
  "login.directoryHint":
    "Melde dich mit deinem Verzeichniskonto an. Konten werden dort verwaltet, nicht hier.",
  "login.failed": "Anmeldung fehlgeschlagen.",
  "login.setBackground": "Hintergrundbild festlegen",
  "login.changeBackground": "Hintergrundbild ändern",
  "login.uploading": "Wird hochgeladen...",
  "login.signingYouIn": "Du wirst angemeldet",

  // ── Einstellungen ───────────────────────────────────────────────────────
  "settings.title": "Einstellungen",
  "settings.saved": "Einstellungen gespeichert.",
  "settings.couldNotLoad": "Die Einstellungen konnten nicht geladen werden.",
  "settings.adminOnly": "Nur Administratoren können das ändern.",

  "theme.label": "Darstellung",
  "theme.hint": "Gilt für dich auf diesem Gerät.",
  "theme.light": "Hell",
  "theme.dark": "Dunkel",
  "theme.system": "Systemeinstellung",
  "theme.systemHint":
    "Übernimmt, was auf deinem Handy oder Rechner eingestellt ist.",
  "settings.language": "Sprache",
  "settings.languageHint": "Gilt für dich auf diesem Gerät.",
  "settings.defaultLanguage": "Standardsprache für neue Besucher",
  "settings.language.en": "Englisch",
  "settings.language.de": "Deutsch",

  "settings.googleBooks": "Google Books",
  "settings.googleBooksEnable": "Zusätzliche Buchangaben aktivieren",
  "settings.googleBooksHint":
    "Fügt bei jedem Buch eine Schaltfläche hinzu, die Seitenzahl, Sprache und Kategorien ergänzt.",
  "settings.apiKey": "API-Schlüssel",
  "settings.apiKeyPlaceholder":
    "Neuen Schlüssel einfügen, um den gespeicherten zu ersetzen",
  "settings.apiKeySet": "Ein Schlüssel ist gespeichert ({preview}).",
  "settings.apiKeyMissing": "Noch kein Schlüssel gespeichert.",
  "settings.apiKeyClear": "Gespeicherten Schlüssel entfernen",
  "settings.apiKeyFromEnv":
    "Dieser Schlüssel kommt aus der Serverkonfiguration und lässt sich hier weder ändern noch anzeigen. Ändere GOOGLE_BOOKS_API_KEY dort, wo die App bereitgestellt wird.",
  "settings.apiKeyHelp": "Wie bekomme ich einen Schlüssel?",
  "settings.apiKeyHint":
    "Lege einen in der Google Cloud Console an und aktiviere dafür die Books API. Der Schlüssel wird nach dem Speichern nicht mehr angezeigt.",

  "settings.goodreads": "Goodreads",
  "settings.goodreadsEnable": "Goodreads Links anzeigen",
  "settings.goodreadsHint":
    "Fügt neben jedem Titel einen Link hinzu, der bei Goodreads sucht.",

  // ── Bewertung und Lesedaten ─────────────────────────────────────────────
  "rating.label": "Deine Bewertung",
  "rating.clear": "Bewertung entfernen",
  "rating.setTo": "Mit {stars} von 5 bewerten",
  "rating.unrated": "Nicht bewertet",
  "rating.averageLabel": "Durchschnittliche Bewertung",

  "reading.started": "Begonnen am {date}",
  "reading.finished": "Beendet am {date}",
  "reading.finishedThisYear": "Dieses Jahr beendet",

  // ── Reihe ───────────────────────────────────────────────────────────────
  "series.label": "Reihe",
  "series.title": "Reihen",
  "series.placeholder": "Name der Reihe",
  "series.numberPlaceholder": "Nr.",
  "series.partOf": "{name}, Band {index}",
  "series.partOfUnnumbered": "Teil von {name}",
  "series.bookCount": "{count} Bücher",
  "series.missing": "Fehlt: {numbers}",
  "series.complete": "Keine Lücken",
  "series.none": "Noch keine Reihen",
  "series.noneHint":
    "Trage bei einem Buch eine Reihe ein, dann erscheint sie hier",
  "series.viewAll": "Ganze Reihe ansehen",
  "series.couldNotLoad": "Die Reihen konnten nicht geladen werden.",

  // ── Standort ────────────────────────────────────────────────────────────
  "location.label": "Wo es steht",
  "location.placeholder": "Wohnzimmer Regal 3",
  "location.unset": "Nicht erfasst",
  "location.filterAll": "Überall",
  "location.hint": "Freier Text. So, wie du es auch sagen würdest.",

  // ── Doppelte Einträge ───────────────────────────────────────────────────
  "duplicates.title": "Mögliche Doppelte",
  "duplicates.none": "Keine Doppelten gefunden",
  "duplicates.noneHint":
    "Nichts in der Bibliothek sieht nach demselben Buch aus",
  "duplicates.explain":
    "Diese Einträge sehen nach demselben Buch aus. Wähle den, der bleiben soll, die anderen gehen darin auf.",
  "duplicates.keepThis": "Diesen behalten",
  "duplicates.merging": "Wird zusammengeführt...",
  "duplicates.merged": "Zu einem Eintrag zusammengeführt.",
  "duplicates.confirm":
    '{count} Einträge in "{title}" zusammenführen? Das lässt sich nicht rückgängig machen.',
  "duplicates.couldNotLoad": "Die Prüfung auf Doppelte ist fehlgeschlagen.",

  // ── Sammelaktionen ──────────────────────────────────────────────────────
  "bulk.more": "Weitere Aktionen",
  "bulk.addTag": "Schlagwort hinzufügen",
  "bulk.removeTag": "Schlagwort entfernen",
  "bulk.setStatus": "Lesestatus setzen",
  "bulk.setLocation": "Standort setzen",
  "bulk.delete": "Löschen",
  "bulk.deleteConfirm":
    "{count} Bücher löschen? Das lässt sich nicht rückgängig machen.",
  "bulk.chooseTag": "Schlagwort auswählen",
  "bulk.locationPrompt": "Wo stehen diese Bücher?",
  "bulk.apply": "Anwenden",

  // ── Schnellerfassung ────────────────────────────────────────────────────
  "rapid.title": "Schnellmodus",
  "rapid.start": "Mehrere scannen",
  "rapid.stop": "Scannen beenden",
  "rapid.explain":
    "Scanne einfach weiter. Jedes Buch wird nachgeschlagen und gesammelt, bestätigt wird am Ende alles zusammen.",
  "rapid.queued": "{count} gescannt",
  "rapid.lookingUp": "Wird nachgeschlagen...",
  "rapid.notFound": "Nicht gefunden: {isbn}",
  "rapid.duplicate": "Schon gescannt",
  "rapid.alreadyInLibrary": "Schon in der Bibliothek",
  "rapid.reviewTitle": "{count} Bücher prüfen",
  "rapid.addAll": "Alle hinzufügen",
  "rapid.adding": "Wird hinzugefügt...",
  "rapid.discard": "Verwerfen",
  "rapid.added":
    "{count} hinzugefügt, {failed} konnten nicht hinzugefügt werden.",
  "rapid.nothingScanned": "Noch nichts gescannt",

  // ── Rückgabefristen ─────────────────────────────────────────────────────
  "loans.dueDate": "Zurück bis",
  "loans.dueOn": "Fällig am {date}",
  "loans.noDueDate": "Kein Datum",
  "loans.overdue": "Überfällig",
  "loans.overdueSince": "Überfällig seit {date}",
  "loans.overdueOnly": "Nur überfällige",
  "loans.overdueBanner": "{count} Ausleihen sind überfällig.",
  "loans.chaseThem": "Anzeigen",

  // ── Wunschliste ─────────────────────────────────────────────────────────
  "nav.wishlist": "Wunschliste",
  "wishlist.title": "Wunschliste",
  "wishlist.empty": "Nichts auf der Wunschliste",
  "wishlist.emptyHint":
    "Ein Buch, das du willst, aber noch nicht hast: markiere es als Wunsch und als nicht vorhanden.",
  "wishlist.explain":
    "Bücher, die du lesen willst und die nicht im Regal stehen.",

  // ── Hilfe ───────────────────────────────────────────────────────────────
  "help.title": "Was ist das?",
  "help.aboutSearch": "Über die Suche bei Google Books",
  "help.aboutEnrich": "Über zusätzliche Buchdetails",

  "help.googleBooks.title": "Google-Books-Abfrage",
  "help.googleBooks.what":
    "Google Books ergänzt Angaben, die ein Barcode nicht enthält: Seitenzahl, Sprache, Kategorien, Reihe und eine Beschreibung. Dafür braucht es einen kostenlosen API-Schlüssel, den ein Admin einmal für den ganzen Haushalt einrichtet.",
  "help.googleBooks.notConfigured":
    "Es ist noch kein Schlüssel hinterlegt, deshalb ist die Funktion aus. So bekommst du einen.",
  "help.googleBooks.step1": "Lege in der Google-Cloud-Konsole ein Projekt an.",
  "help.googleBooks.step2": "Aktiviere die Books API für dieses Projekt.",
  "help.googleBooks.step3": "Erstelle unter Anmeldedaten einen API-Schlüssel.",
  "help.googleBooks.step4":
    "Trage ihn hier in den Einstellungen ein und schalte die Funktion an.",
  "help.googleBooks.cost":
    "Die Books API ist kostenlos. Eine Kreditkarte ist nicht nötig, und das Tageskontingent reicht für eine private Bibliothek um ein Vielfaches.",
  "help.googleBooks.restrict":
    "Der Schlüssel liegt hier und wird nur von diesem Server aus verwendet, deshalb genügt es, ihn auf die Books API zu beschränken. Nach dem Speichern wird er nie wieder angezeigt.",
  "help.googleBooks.toSettings": "Einstellungen öffnen",
  "help.googleBooks.adminOnly":
    "Nur ein Admin kann den Schlüssel speichern. Falls du das nicht bist, schick ihm diese Seite.",

  "help.disabledSearch":
    "Die Suche ist aus, bis ein Admin einen Google-Books-Schlüssel hinterlegt.",
  "help.disabledEnrich":
    "Zusätzliche Details sind aus, bis ein Admin einen Google-Books-Schlüssel hinterlegt.",

  // ── Maskierte Felder ────────────────────────────────────────────────────
  "field.show": "Anzeigen",
  "field.hide": "Verbergen",

  // ── Fehler ──────────────────────────────────────────────────────────────
  "error.404.code": "Fehler 404",
  "error.404.title": "Hier ist nichts",
  "error.404.message":
    "Diese Seite oder dieses Buch konnte nicht gefunden werden. Vielleicht wurde es aus dem Katalog entfernt.",
  "error.403.code": "Fehler 403",
  "error.403.title": "Nicht erlaubt",
  "error.403.message":
    "Dein Konto hat darauf keinen Zugriff. Falls es das haben sollte, frage die Person, die die Bibliothek eingerichtet hat.",
  "error.500.code": "Fehler 500",
  "error.500.title": "Da ist etwas kaputt",
  "error.500.message":
    "Das liegt an uns, nicht an dir. Ein Neuladen behebt es meistens.",
  "error.backToLibrary": "Zurück zur Bibliothek",
  "error.reload": "Seite neu laden",
};
