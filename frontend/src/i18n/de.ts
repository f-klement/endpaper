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
  "nav.menu": "Menü",
  "nav.menuFor": "Menü für {name}",
  "nav.switchAccount": "Konto wechseln",
  "nav.exportLibrary": "Bibliothek exportieren",
  "nav.logout": "Abmelden",
  "nav.returnToMyAccount": "Zurück zu meinem Konto",

  // ── Allgemein ───────────────────────────────────────────────────────────
  "common.cancel": "Abbrechen",
  "common.save": "Speichern",
  "common.saving": "Wird gespeichert...",
  "common.edit": "Bearbeiten",
  "common.delete": "Löschen",
  "common.done": "Fertig",
  "common.add": "Hinzufügen",
  "common.close": "Schließen",
  "common.undo": "Rückgängig",
  "common.back": "Zurück",
  "common.tryAgain": "Erneut versuchen",
  "common.loading": "Wird geladen...",
  "common.somethingWentWrong": "Etwas ist schiefgelaufen.",
  "common.cannotReachServer":
    "Der Server ist nicht erreichbar. Prüfe deine Verbindung und versuche es erneut.",
  "common.selectAll": "Alle auswählen",
  "common.clearSelection": "Auswahl aufheben",
  "common.selectedCount": "{count} ausgewählt",

  // ── Lesestatus ──────────────────────────────────────────────────────────
  "status.unread": "Ungelesen",
  "status.want_to_read": "Möchte ich lesen",
  "status.reading": "Lese ich gerade",
  "status.read": "Gelesen",
  // Not a literal translation of "Did not finish". "Abgebrochen" is what a
  // German reader says about a book they gave up on, and it fits a pill.
  "status.did_not_finish": "Abgebrochen",
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
  "library.viewLabel": "Darstellung der Bibliothek",
  "library.viewGrid": "Cover",
  "library.viewTable": "Tabelle",
  "library.viewList": "Liste",
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
  "book.remove": "In den Papierkorb",
  "book.movedToTrash": "In den Papierkorb verschoben.",
  "book.noTags": "Noch keine Schlagwörter",
  "book.addTag": "+ Hinzufügen",
  "book.removeTag": "{tag} entfernen",

  // ── Abschnitte der Buchdetails ──────────────────────────────────────────
  "section.reading": "Deine Lektüre",
  "section.filing": "Dieses Exemplar einordnen",
  "section.copies": "Deine Exemplare",
  "section.lending": "Dieses Exemplar verleihen",
  "section.writing": "Notizen und Zitate",
  "section.about": "Über dieses Buch",

  // ── Feldnamen ───────────────────────────────────────────────────────────
  "field.title": "Titel",
  "field.author": "Autor",
  "field.publisher": "Verlag",
  "field.year": "Erscheinungsjahr",
  "field.language": "Sprache",
  "field.pageCount": "Seitenzahl",
  "field.readingStatus": "Lesestatus",
  "field.rating": "Bewertung",
  "field.ownership": "Besitz",
  "field.addedBy": "Hinzugefügt von",
  "field.addedAt": "Hinzugefügt am",

  // ── Ausklappbereich der Karte ───────────────────────────────────────────
  "card.details": "Details",
  "card.detailsFor": "Details zu {title}",

  // ── Zusätzliche Angaben ─────────────────────────────────────────────────
  "enrich.button": "Weitere Angaben suchen",
  "enrich.working": "Wird gesucht...",
  "enrich.updated": "Ergänzt: {fields}.",
  "enrich.nothingNew":
    "Nichts Neues gefunden. Die Angaben hier sind bereits vollständig.",
  "enrich.pickTitle": "Welche Ausgabe ist das?",
  "enrich.pickHint":
    "Wähle die Ausgabe, die du in der Hand hast. Es werden nur leere Felder ergänzt, deine eigenen Angaben bleiben stehen.",
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

  // ── Scannen ─────────────────────────────────────────────────────────────
  "scan.title": "Barcode scannen",
  "scan.pointAtBarcode": "Auf den Barcode richten",
  "scan.torch": "Kameralicht",
  "scan.startScanning": "Scannen starten",
  "scan.stopScanning": "Scannen beenden",
  "scan.cameraIdle": "Die Kamera ist aus",
  "scan.cameraIdleHint": "Es wird nichts aufgezeichnet, die Kamera bleibt geschlossen, bis du sie startest.",
  "scan.notABook": "{code} gelesen, das ist kein Buch-Barcode. Suche den Code ueber der ISBN.",
  "scan.tryAgain": "Erneut versuchen",
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
  "scan.openTheOneWeHave": "Vorhandenes Exemplar öffnen",
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
  "search.label": "Nach Titel oder Autor suchen",
  "search.button": "Suchen",
  "search.searching": "Suche läuft...",
  "search.noResults":
    "Keine Treffer. Versuche weniger Wörter, oder trage das Buch von Hand ein.",
  "search.pickHint":
    "Wähle einen Treffer aus, um die Angaben zu übernehmen. Gespeichert wird erst, wenn du bestätigst.",
  "search.withoutKey":
    "Es wird Open Library durchsucht. Ein Google-Books-Schlüssel ergänzt Beschreibungen und Genres.",

  // ── Ausleihen ───────────────────────────────────────────────────────────
  "loans.title": "Ausleihen",
  "loans.showAll": "Alle anzeigen",
  "loans.activeOnly": "Nur laufende",
  "loans.none": "Keine Ausleihen",
  "loans.noneActive": "Keine laufenden Ausleihen",
  "loans.allAccountedFor": "Alle Bücher sind da",
  "loans.loanedToBy": "Verliehen an {to} von {by}",
  "loans.loanedToExternalBy": "Verliehen an {name} (ohne Konto) von {by}",
  "loans.returnedOn": "Zurück am {date}",
  "loans.markReturned": "Als zurück markieren",
  "loans.updating": "Wird aktualisiert...",
  "loans.management": "Ausleihe verwalten",
  "loans.loanTo": "Verleihen an...",
  "loans.loanToLabel": "Ausleihen an",
  "loans.loanButton": "Verleihen",
  "loans.markAsReturned": "Als zurückgegeben markieren",
  "loans.badge": "Verliehen an {name}",
  "loans.badgeExternal": "Verliehen an {name}, ohne Konto hier",
  "loans.borrowerMember": "Ein Mitglied",
  "loans.borrowerExternal": "Jemand anderes",
  "loans.borrowerKind": "Wer leiht es aus",
  "loans.externalNameLabel": "Name der Person",
  "loans.externalNamePlaceholder": "Wer hat es",
  "loans.couldNotLoad": "Die Ausleihen konnten nicht geladen werden.",

  // ── Notizen ─────────────────────────────────────────────────────────────
  "notes.title": "Notizen",
  "notes.none": "Noch keine Notizen",
  "notes.placeholder": "Notiz hinzufügen...",
  "notes.addLabel": "Notiz hinzufügen",
  "notes.editLabel": "Notiz bearbeiten",

  // ── Zitate ──────────────────────────────────────────────────────────────
  "quotes.title": "Zitate",
  "quotes.none": "Noch keine Zitate",
  "quotes.placeholder": "Eine Stelle abschreiben...",
  "quotes.addLabel": "Die Stelle",
  "quotes.editLabel": "Zitat bearbeiten",
  "quotes.addButton": "Zitat hinzufügen",
  "quotes.pageLabel": "Seite, auf der das Zitat steht",
  "quotes.editPageLabel": "Seite des Zitats bearbeiten",
  "quotes.pagePlaceholder": "Seite",
  "quotes.noteLabel": "Was du dazu sagen möchtest",
  "quotes.editNoteLabel": "Deine Anmerkung bearbeiten",
  "quotes.notePlaceholder": "Warum gerade dieses (optional)",
  "quotes.onPage": "S. {page}",
  "quotes.empty": "Noch keine Zitate gespeichert",
  "quotes.emptyHint": "Öffne ein Buch und schreibe eine Stelle ab, die bleiben soll.",
  "quotes.couldNotLoad": "Die Zitate konnten nicht geladen werden.",
  "quotes.pagination": "Zitatseiten",
  "quotes.pageOf": "Seite {page} von {of}",
  "quotes.previous": "Zurück",
  "quotes.next": "Weiter",

  // ── Statistik ───────────────────────────────────────────────────────────
  "stats.title": "Sammlung in Zahlen",
  "stats.booksInLibrary": "Bücher in deiner Bibliothek",
  "stats.byMember": "Hinzugefügt nach Person",
  "stats.byType": "Nach Art",
  "stats.byGenre": "Nach Genre",
  "stats.byAge": "Nach Alter",
  "stats.byCustomTag": "Nach euren Schlagwörtern",
  "stats.byCollection": "Nach Sammlung",
  "stats.finishedByMonth": "Gelesen, nach Monat",
  "stats.finishedTotal": "Bücher gelesen",
  "stats.pagesByMonth":
    "Gelesene Seiten, nach Monat (nach Seiten erfasste Bücher)",

  "stats.averageRating": "Durchschnitt aus {count} Bewertungen",
  "stats.overTime": "Hinzugefügt im Zeitverlauf",
  "stats.couldNotLoad": "Die Statistik konnte nicht geladen werden.",
  "stats.loading": "Statistik wird geladen",

  // ── Schlagwörter ────────────────────────────────────────────────────────
  "tags.type": "Art",
  "tags.genre": "Genre",
  "tags.age": "Alter",
  "tags.custom": "Eure Schlagwörter",
  "tags.count": "{count}",
  "tags.countWithChosen": "{chosen} von {count}",
  "tags.newLabel": "Neues Schlagwort",
  "tags.newPlaceholder": "Urlaubslektüre",
  "tags.add": "Schlagwort hinzufügen",
  "tags.create": "Anlegen",
  "tags.delete": "{name} löschen",
  "tags.deleteConfirm":
    'Das Schlagwort "{name}" löschen? Es verschwindet bei {count} Büchern, für alle, und lässt sich nicht rückgängig machen.',
  "tags.builtInHint": "Eingebaute Schlagwörter lassen sich nicht löschen.",

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
  "theme.hint": "Wird in deinem Konto gespeichert und gilt auf allen Geräten.",
  "theme.light": "Hell",
  "theme.dark": "Dunkel",
  "theme.system": "Systemeinstellung",
  "theme.systemHint":
    "Übernimmt, was auf deinem Handy oder Rechner eingestellt ist.",
  "theme.wallpaperOff":
    "Das Hintergrundmuster ist aus, weil dein System mehr Kontrast verlangt.",
  "theme.summary": "{palette}, {mode}, {wallpaper}",
  "theme.change": "Farbwelt, hell oder dunkel und ein Hintergrundmuster wählen",

  "appearance.title": "Darstellung",
  "appearance.intro":
    "Alles hier gilt sofort und wird in deinem Konto gespeichert.",
  "appearance.preview": "Deine Bibliothek in dieser Darstellung",
  "appearance.previewEmpty":
    "Auf diesem Gerät sind gerade keine Bücher geladen, also gibt es nichts Echtes zum Ansehen. Geh kurz in deine Bibliothek und komm zurück.",
  "appearance.mode": "Hell und dunkel",
  "appearance.palette": "Farbwelt",
  "appearance.attribution": "Farben von {source}.",
  "appearance.attributionOwn": "Eigene Farben dieses Projekts.",
  "appearance.constructedLight":
    "{palette} veröffentlicht keine helle Variante. Diese ist hier aus veröffentlichten Farben gebaut.",
  "appearance.constructedDark":
    "{palette} veröffentlicht keine dunkle Variante. Diese ist hier aus veröffentlichten Farben gebaut.",
  "appearance.wallpaper": "Hintergrundmuster",
  "appearance.wallpaperNone": "Keins",
  "appearance.wallpaperNoneHint": "Eine schlichte Seite.",
  "appearance.wallpaperSurprise": "Überrasch mich",
  "appearance.wallpaperSurpriseHint": "Bei jedem Besuch ein anderes.",
  "appearance.family.morris": "William Morris",
  "appearance.family.papers": "Buntpapiere",
  "appearance.licences": "Woher das alles stammt",
  "appearance.licencesPalettes":
    "Die Farbwelten unten stehen unter der MIT-Lizenz, ihre Werte stammen aus dem jeweils eigenen Repository. Keines dieser Projekte unterstützt dieses hier.",
  "appearance.licencesMorris":
    "Die Morris-Musternamen bezeichnen die historischen Entwürfe, denen die Zeichnungen folgen. Dieses Projekt steht in keiner Verbindung zu Morris & Co und wird von dort nicht unterstützt.",
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

  "settings.testAccounts": "Testkonten",
  "settings.testAccountsHint":
    "Konten mit einem Passwort, das du festlegst, um die Bibliothek so zu sehen, wie ein gewöhnliches Mitglied sie sieht. Sie sind nie Administratoren und werden auf der Anmeldeseite nicht angeboten.",
  "settings.testAccountsReturnProxy":
    "Zum Zurückkehren im Menü den Eintrag Zurück zu meinem Konto wählen.",
  "settings.testAccountsReturnToken":
    "Zum Zurückkehren melde dich wieder mit deinem eigenen Konto an.",
  "settings.testAccountsEmpty": "Noch keine Testkonten.",
  "settings.testAccountsCreate": "Testkonto anlegen",
  "settings.testAccountsCreateFailed": "Das Konto konnte nicht angelegt werden.",
  "settings.testAccountsPasswordPlaceholder": "Passwort, mindestens 8 Zeichen",
  "settings.testAccountsSwitch": "Wechseln",
  "settings.testAccountsSwitchTo": "Zu {name} wechseln",
  "settings.testAccountsSwitchFailed":
    "Zu diesem Konto konnte nicht gewechselt werden.",
  "settings.testAccountsPasswordFor": "Passwort für {name}",

  // ── Erinnerungen an überfällige Bücher ──────────────────────────────────
  "settings.overdue": "Erinnerungen an überfällige Bücher",
  "settings.overdueEnable": "Erinnerung senden, wenn ein Buch überfällig ist",
  "settings.overdueHint":
    "Endpaper schaut stündlich nach und sendet eine Nachricht mit den Ausleihen, die angemahnt werden. Gibt es nichts anzumahnen, wird nichts gesendet.",
  "settings.overduePrivacyNote":
    "Private Bücher werden nie mitgesendet. Ein Webhook landet in einem Kanal ohne Konto dahinter, dort wäre ein privater Titel für alle lesbar. Überfällige private Bücher erscheinen weiterhin in der Ausleihliste ihrer Besitzerin oder ihres Besitzers.",
  "settings.overdueUrl": "Webhook Adresse",
  "settings.overdueUrlPlaceholder": "https://example.org/hooks/books",
  "settings.overdueSecret": "Signaturgeheimnis",
  "settings.overdueSecretPlaceholder":
    "Neues Geheimnis einfügen, um das gespeicherte zu ersetzen",
  "settings.overdueSecretShow": "Signaturgeheimnis anzeigen",
  "settings.overdueSecretHide": "Signaturgeheimnis verbergen",
  "settings.overdueSecretSet": "Ein Geheimnis ist gespeichert ({preview}).",
  "settings.overdueSecretMissing":
    "Kein Geheimnis gespeichert. Mit einem kann die Gegenstelle prüfen, ob die Nachricht wirklich von hier kommt.",
  "settings.overdueSecretClear": "Gespeichertes Geheimnis entfernen",
  "settings.overdueDays": "Tage zwischen zwei Erinnerungen zur selben Ausleihe",
  "settings.overdueDaysHint":
    "Eine Ausleihe wird erst wieder angemahnt, wenn so viele Tage seit der letzten Erinnerung vergangen sind.",
  "settings.overdueUrlSave": "Adresse speichern",
  "settings.overdueSecretSave": "Geheimnis speichern",
  "settings.overdueDaysSave": "Abstand speichern",
  "settings.overdueSendNow": "Jetzt senden",
  "settings.overdueSending": "Wird gesendet...",
  "settings.overdueSent": "Gesendet, mit {count} Ausleihen.",
  "settings.overdueNothingSent": "Es wurde nichts gesendet.",
  "settings.overdueNotSentDisabled":
    "Es wurde nichts gesendet: Die Erinnerungen sind ausgeschaltet.",
  "settings.overdueNotSentNoUrl":
    "Es wurde nichts gesendet: Es ist keine Webhook Adresse gespeichert.",
  "settings.overdueNotSentNothingDue":
    "Es wurde nichts gesendet: Es ist nichts überfällig.",
  "settings.overdueNotSentUnreachable":
    "Der Webhook war nicht erreichbar, es wurde nichts gesendet. Die Ausleihen werden beim nächsten Versuch erneut angemahnt.",
  "settings.overdueSkippedPrivate":
    "{count} private Bücher wurden ausgelassen.",

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

  // ── Lesefortschritt ─────────────────────────────────────────────────────
  "progress.label": "Lesefortschritt",
  "progress.none": "Noch nichts erfasst.",
  "progress.onPage": "Seite {page}",
  "progress.onPageOf": "Seite {page} von {total}",
  "progress.atPercent": "{percent}% gelesen",
  "progress.unit": "Seite oder Prozent erfassen",
  "progress.unitPage": "Seite",
  "progress.unitPercent": "Prozent",
  "progress.pagePlaceholder": "Erreichte Seite",
  "progress.percentPlaceholder": "Gelesene Prozent",
  "progress.minutes": "Gelesene Minuten",
  "progress.minutesPlaceholder": "Minuten",
  "progress.minutesRead": "{minutes} Min.",
  "progress.record": "Fortschritt erfassen",
  "progress.removeEntry": "Diesen Eintrag entfernen",

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
  "location.carriedOver":
    "Bleibt für das nächste Buch stehen, damit ein ganzes Regal nur einmal getippt wird.",
  "location.batchLabel": "Regal für alles aus diesem Durchgang",

  // ── Sammlungen ──────────────────────────────────────────────────────────
  "collections.title": "Sammlungen",
  "collections.label": "Sammlung",
  "collections.none": "In keiner Sammlung",
  "collections.filterAll": "Alle Sammlungen",
  "collections.filterUnfiled": "In keiner Sammlung",
  "collections.bookCount": "{count} Bücher",
  "collections.empty": "Noch keine Sammlungen",
  "collections.emptyHint":
    "Eine Sammlung teilt das Regal auf: gedruckt und digital, behalten und verkauft, deins und meins. Ein Buch liegt in genau einer Sammlung, also nimm die wichtigste Aufteilung und für alles andere Schlagwörter.",
  "collections.explain":
    "Eine Sammlung gruppiert Bücher. Sie versteckt keines: wer ein Buch sehen kann, hängt weiterhin davon ab, ob es privat ist.",
  "collections.newName": "Name",
  "collections.newPlaceholder": "E-Books",
  "collections.create": "Sammlung anlegen",
  "collections.creating": "Wird angelegt...",
  "collections.rename": "Umbenennen",
  "collections.renamePrompt": "Wie soll diese Sammlung heißen?",
  "collections.delete": "Löschen",
  "collections.deleteConfirm":
    '"{name}" löschen? Die {count} Bücher darin bleiben in der Bibliothek, dann ohne Sammlung.',
  "collections.browse": "Diese Bücher anzeigen",
  "collections.couldNotLoad": "Die Sammlungen konnten nicht geladen werden.",
  "collections.saving": "Wird einsortiert...",

  // ── Autorinnen und Autoren ──────────────────────────────────────────────
  "authors.title": "Autorinnen und Autoren",
  "authors.label": "Autor",
  "authors.explain":
    "Alle, die auf dem Regal genannt sind. Die Namen stammen aus den Büchern selbst, deshalb kann eine Person doppelt auftauchen: führe die Schreibweisen zusammen, die Bücher bleiben unverändert.",
  "authors.search": "Namen durchsuchen",
  "authors.searchPlaceholder": "Name",
  "authors.bookCount": "{count} Bücher",
  "authors.none": "Noch niemand erfasst",
  "authors.noneHint": "Leg ein Buch mit Autorenangabe an, dann steht es hier",
  "authors.noMatches": "Kein Name passt dazu",
  "authors.couldNotLoad": "Die Namen konnten nicht geladen werden.",
  "authors.alsoSpelled": "Auch geschrieben: {spellings}",
  "authors.mergedFrom": "Zusammengeführt aus: {spelling}",
  "authors.undo": "Zusammenführung rückgängig machen",
  "authors.browse": "Diese Bücher anzeigen",
  "authors.select": "{name} auswählen",
  "authors.selectedCount": "{count} ausgewählt",
  "authors.keepNamed": "{name} behalten",
  "authors.suggestionsTitle": "Vermutlich dieselbe Person",
  "authors.suggestionsExplain":
    "Nimm heraus, wer nicht dazugehört, und wähle dann den Namen, der bleiben soll. An den Büchern ändert sich nichts, und über die Karte lässt es sich wieder rückgängig machen.",
  "authors.keepThis": "Diesen Namen behalten",
  "authors.merging": "Wird zusammengeführt...",
  "authors.otherName": "Oder ein Name, den keiner von ihnen trägt",
  "authors.renameName": "Stattdessen dieser Name",
  "authors.rename": "Umbenennen",
  "authors.renameConfirm": '"{from}" in "{name}" umbenennen?',
  "authors.otherNamePlaceholder": "Ursula K. Le Guin",
  "authors.mergeIntoOther": "Unter diesem Namen zusammenführen",
  "authors.confirm": '{count} Schreibweisen zu "{name}" zusammenführen?',
  "authors.foldedInto": 'Dieser Name heißt bereits "{name}", dorthin ging es.',
  "authors.reasonSpelling": "derselbe Name, anders getrennt",
  "authors.reasonInitials": "eine Abkürzung gegen einen ausgeschriebenen Namen",
  "authors.reasonFragment": "Teil eines längeren Namens",
  "authors.include": "{name} einbeziehen",

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
  "bulk.setCollection": "In eine Sammlung legen",
  "bulk.clearCollection": "Aus jeder Sammlung nehmen",
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
    "{count} hinzugefügt. {failed} stehen unten, mit dem Grund.",
  "rapid.removeFromQueue": "{isbn} aus der Liste entfernen",
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

  // ── Das Exemplar ────────────────────────────────────────────────────────
  "copy.title": "Dieses Exemplar",
  "copy.hint": "Was du besitzt, nicht was das Buch ist.",
  "copy.format": "Ausgabe",
  "copy.format.unset": "Nicht erfasst",
  "copy.format.hardcover": "Gebunden",
  "copy.format.paperback": "Taschenbuch",
  "copy.format.ebook": "E-Book",
  "copy.format.audiobook": "Hörbuch",
  "copy.format.other": "Sonstiges",
  "copy.condition": "Zustand",
  "copy.condition.unset": "Nicht erfasst",
  "copy.condition.new": "Wie neu",
  "copy.condition.good": "Gut",
  "copy.condition.fair": "Gebraucht",
  "copy.condition.poor": "Stark gebraucht",
  "copy.condition.ex_library": "Aus einer Bibliothek",
  "copy.price": "Bezahlter Preis",
  "copy.priceInvalid": "Schreibe einen Preis wie 12,99, oder lass das Feld leer.",
  "copy.currency": "Währung",
  "copy.purchasedAt": "Gekauft am",
  "copy.purchaseSource": "Gekauft bei",
  "copy.save": "Angaben zum Exemplar speichern",
  "copy.purchaseSourcePlaceholder": "Der Buchladen um die Ecke",

  // ── Mehrere Exemplare desselben Buchs ───────────────────────────────────
  "copies.title": "Exemplare",
  "copies.count": "{count} Exemplare dieses Buchs",
  "copies.hint": "Ein zweites Exemplar ist ein zweiter Gegenstand: eigenes Regal, eigener Zustand, eigene Ausleihe.",
  "copies.thisOne": "Dieses hier",
  "copies.open": "Öffnen",
  "copies.noShelf": "Kein Regal erfasst",
  "copies.onLoan": "Verliehen",
  "copies.add": "Weiteres Exemplar hinzufügen",
  "copies.adding": "Wird hinzugefügt...",
  "copies.fromScanHint":
    "Ein Exemplar übernimmt Schlagwörter und Titelbild von dem Buch, das schon da ist.",
  "copies.addFailed": "Dieses Exemplar konnte nicht hinzugefügt werden.",
  "copies.loadFailed": "Die anderen Exemplare dieses Buchs konnten nicht geladen werden.",
  "copies.badge": "{count} Exemplare",
  "format.filterAll": "Jede Ausgabe",

  // ── Herborgen und drüber reden ──────────────────────────────────────────
  "lending.label": "Verleihen",
  "lending.unset": "Nicht erfasst",
  "lending.filterAll": "Verleihen: beliebig",
  "lending.happy": "Borge ich gern her",
  "lending.in_use": "Brauche ich gerade selbst",
  "lending.never": "Wird nicht hergeborgt",
  "lending.neverWarning": "Dieses Buch ist als \"wird nicht hergeborgt\" markiert.",
  "lending.lendAnyway": "Trotzdem herborgen",
  "discuss.toggle": "Über dieses Buch rede ich gern, frag mich einfach danach",
  "discuss.label": "Ansprechpartner",
  "discuss.badge": "Gesprächsstoff",
  "discuss.others": "Sprich {names} darauf an.",

  // ── Bibliothek übernehmen ───────────────────────────────────────────────
  "import.title": "Bibliothek übernehmen",
  "import.explain":
    "Ein CSV- oder TSV-Export aus Goodreads, LibraryThing, StoryGraph, Libib oder allem anderen mit einer Titelspalte. Die Spalten werden erkannt und angezeigt, bevor etwas gespeichert wird.",
  "import.chooseFile": "Datei auswählen",
  "import.reading": "Datei wird gelesen...",
  "import.importing": "Import läuft...",
  "import.confirm": "{count} Bücher importieren",
  "import.previewTitle": "{count} Zeilen gelesen. Gefundene Spalten:",
  "import.notFound": "In dieser Datei nicht gefunden: {fields}",
  "import.fieldTitle": "Titel",
  "import.fieldAuthor": "Autor",
  "import.fieldIsbn": "ISBN",
  "import.fieldStatus": "Lesestatus",
  "import.fieldRating": "Bewertung",
  "import.fieldDateRead": "Gelesen am",
  "import.fieldPublisher": "Verlag",
  "import.fieldYear": "Jahr",
  "import.fieldPages": "Seiten",
  "import.fieldFormat": "Format",
  "import.fieldTags": "Schlagwörter",
  "import.createMissing": "Bücher anlegen, die noch nicht im Katalog sind",
  "import.createMissingHint":
    "Sie kommen als nicht bestätigt an: ein Export sagt, was jemand gelesen hat, nicht, was im Regal steht.",
  "import.applyTags": "Schlagwörter mit übernehmen",
  "import.applyTagsHint":
    "Diese Datei enthält {count} verschiedene Schlagwörter. Sie werden hier für alle angelegt, unter Eure Schlagwörter, und lassen sich nur einzeln wieder entfernen.",
  "import.result":
    "{rowsRead} Zeilen gelesen, {matched} zugeordnet, {created} angelegt, {statusesUpdated} Lesestände aktualisiert.",
  "import.skipped": "{count} Zeilen hatten keinen Titel und wurden übersprungen.",
  "import.unmatched": "Nicht im Katalog gefunden:",

  // ── Sicherung ───────────────────────────────────────────────────────────
  "backup.title": "Sicherung",
  "backup.explain":
    "Eine vollständige Kopie der Bibliothek: alle Bücher, Konten, Notizen, Ausleihen, Lesestände und Cover. Der CSV-Export ist das nicht. Er enthält eine Zeile pro Buch und lässt den Rest weg.",
  "backup.download": "Sicherung herunterladen",
  "backup.downloadFailed": "Die Sicherung konnte nicht erstellt werden.",
  "backup.restoreTitle": "Aus einer Sicherung wiederherstellen",
  "backup.restoreWarning":
    "Beim Wiederherstellen wird alles in dieser Bibliothek ersetzt. Bücher, die nach der Sicherung dazugekommen sind, sind weg.",
  "backup.chooseFile": "Sicherungsdatei",
  "backup.restoreAction": "Aus {name} wiederherstellen",
  "backup.restoreConfirm":
    "Alle Bücher, Konten und Cover dieser Bibliothek durch die Sicherung ersetzen? Das lässt sich nicht rückgängig machen.",
  "backup.restoreFailed": "Diese Sicherung konnte nicht wiederhergestellt werden.",
  "backup.restored": "{books} Bücher und {covers} Cover wiederhergestellt.",

  // ── Cover ───────────────────────────────────────────────────────────────
  "covers.title": "Cover",
  "covers.explain":
    "Cover werden einmal geholt und aus dieser Bibliothek ausgeliefert. Ein Buch behält sein Cover also auch dann, wenn der Bilddienst verschwindet, von dem es stammt. Bücher aus einem Import haben noch keines.",
  "covers.backfill": "Fehlende Cover holen",
  "covers.backfillFailed": "Die Cover konnten nicht geholt werden.",
  "covers.result":
    "{examined} Bücher geprüft und {stored} Cover gespeichert. Für {missing} hat kein Bilddienst eines.",
  "covers.unreachable":
    "Für {count} davon gibt es irgendwo ein Cover, das von hier aus nicht geladen werden konnte. Sie behalten ihren Link und werden beim nächsten Durchlauf durch die Bibliothek erneut versucht.",
  "covers.remaining": "Noch {remaining} Bücher offen. Noch einmal ausführen, um weiterzumachen.",
  "covers.allDone": "Jedes Buch, das ein Cover haben kann, hat eines.",

  // ── Über ──────────────────────────────────────────────────────────────────
  "about.title": "Über Endpaper",
  "about.versionLabel": "Version",
  "about.licenceLabel": "Lizenz",
  "about.sourceLabel": "Quelltext",
  "about.support":
    "Wenn dir Endpaper gefällt und du meine Arbeit unterstützen möchtest, spendier mir einen Kaffee. Er hilft, den öffentlichen Server zu finanzieren, der zwischen Haushalten vermitteln kann.",
  "about.kofiAlt": "Endpaper auf Ko-fi unterstützen",

  // ── Gespeicherte Ansichten ──────────────────────────────────────────────
  "saved.saveThisView": "Ansicht speichern",
  "saved.nameLabel": "Name für diese Ansicht",
  "saved.namePlaceholder": "Ungelesen auf dem Dachboden",
  "saved.forget": "{name} vergessen",

  // ── Papierkorb ──────────────────────────────────────────────────────────
  "nav.trash": "Papierkorb",
  "trash.title": "Papierkorb",
  "trash.explain":
    "Gelöschte Bücher warten hier, bis du den Papierkorb leerst. Von allein wird nichts entfernt.",
  "trash.empty": "Der Papierkorb ist leer",
  "trash.emptyHint":
    "Was du löschst, landet hier, mit allem, was daran hängt.",
  "trash.deletedOn": "Gelöscht am {date}",
  "trash.restore": "Zurücklegen",
  "trash.restored": "Wieder im Regal.",
  "trash.deleteForever": "Endgültig löschen",
  "trash.deleteForeverConfirm":
    '"{title}" endgültig löschen? Das lässt sich nicht rückgängig machen.',
  "trash.emptyAll": "Papierkorb leeren",
  "trash.emptyAllConfirm":
    "Alle {count} Bücher im Papierkorb endgültig löschen? Das lässt sich nicht rückgängig machen.",
  "trash.emptied": "{count} Bücher endgültig gelöscht.",
  "trash.movedCount": "{count} Bücher in den Papierkorb verschoben.",
  "trash.open": "Papierkorb öffnen",

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
  "help.aboutSearch": "Über die Buchsuche",
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
    "Die Suche funktioniert ohne Schlüssel. Ein Schlüssel ergänzt Beschreibungen und Genres in den Treffern.",
  "help.disabledEnrich":
    "Zusätzliche Details funktionieren ohne Schlüssel. Ein Schlüssel ergänzt Beschreibungen und Genres.",

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
  "error.sessionEnded.code": "Fehler 401",
  "error.sessionEnded.title": "Deine Sitzung ist beendet",
  "error.sessionEnded.message":
    "Das Anmeldeportal hat diese Sitzung beendet, und ein Neuladen hat sie nicht zurückgebracht. Melde dich bitte erneut an.",
  "error.sessionEnded.action": "Erneut anmelden",
  "error.backToLibrary": "Zurück zur Bibliothek",
  "error.reload": "Seite neu laden",
};
