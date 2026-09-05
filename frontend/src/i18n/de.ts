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
 * * **No address, in either register.** German makes you choose between `du`
 *   and `Sie`, and this file chooses neither.
 *
 *   The file used to be `du` throughout, justified as "a household bookshelf,
 *   not a bank". That was right until library mode existed, at which point it
 *   was wrong for an institution: a German library addresses a Benutzer:in as
 *   `Sie`, and a catalogue written in `du` reads as careless. A formal overlay
 *   was built, measured at **82 of 888 strings**, and reviewed. **The owner
 *   retired it on 2026-09-03**: "rephrase the german version, so we dont need
 *   to keep two versions for the same language."
 *
 *   So **82** strings differ from the file the overlay was measured against.
 *   The same total, and deliberately not the same set: `public.noResultsHint`
 *   joins it, having been written in `Sie` and so needing no formal variant of
 *   its own, and `appearance.wallpaperSurprise` leaves it, being the one place
 *   the reader addresses the app rather than the other way round.
 *
 *   German has the machinery for it: the infinitive for every instruction ("Bitte die
 *   Ziffern prüfen"), `eigen-` for a possessive that carries weight ("Eigene
 *   Lektüre"), a plain article for one that does not ("Die Bibliothek konnte
 *   nicht geladen werden"), the passive and `lässt sich`, and `wer …` for a
 *   conditional about the reader.
 *
 *   **One string on screen does carry a `du` form, and it is not an
 *   exception.** `appearance.wallpaperSurprise` is "Überrasch mich": the
 *   reader addressing the app, not the app addressing the reader, and the
 *   rule here is about the second. Worth knowing because it is the one string
 *   that leans on the blind spot below rather than merely coexisting with it:
 *   no rule can see it, so nothing would stop it being changed to something
 *   the rule should catch.
 *
 *   **A string added here in `du` or `Sie` fails the build**, at
 *   `frontend/tests/i18n/de.test.ts`, which also carries the one exemption
 *   (the idiom "Mein und Dein", where `Dein` is a noun) and the blind spot
 *   nothing can close: an informal imperative is a bare verb stem and is
 *   homographic with a noun, so "Suche den Code" and "Suche läuft" cannot be
 *   told apart by any rule. That one still needs a reader.
 *
 *   The published catalogue is no longer an exception either. It addressed a
 *   visitor as `Sie` while the rest of the app said `du`; with one address
 *   free file it needs no rule of its own.
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
    "Der Server ist nicht erreichbar. Bitte die Verbindung prüfen und es erneut versuchen.",
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
    "Ob ein Exemplar wirklich hier steht. Unabhängig davon, ob es gelesen wurde.",
  "ownership.confirmSelected": "Als im Regal markieren",
  "ownership.markNotOwned": "Als nicht im Besitz markieren",
  "ownership.bulkResult":
    "{updated} geändert, {unchanged} bereits gesetzt, {skipped} übersprungen.",
  "ownership.unconfirmedBanner":
    "Bei {count} Büchern ist nicht bestätigt, ob sie im Regal stehen.",
  "ownership.reviewThem": "Jetzt prüfen",

  "library.overdueBanner": "{count} Ausleihen sollten angemahnt werden.",
  "library.overdueBannerAction": "Ansehen",
  "library.channelBroken":
    "Erinnerungen an überfällige Bücher kommen über {channels} nicht an.",
  "library.channelBrokenAction": "Einstellungen prüfen",

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
  "library.adjustFilters": "Es mit anderen Filtern versuchen",
  "library.scanFirstBook":
    "Einen Barcode scannen, um das erste Buch hinzuzufügen",
  "library.couldNotLoad": "Die Bibliothek konnte nicht geladen werden.",
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
  "sort.ddc": "DDC-Notation",
  "classification.section": "Klassifikation",
  "classification.filter": "Klassifikation",
  "classification.headings": "Schlagworte und Notationen",
  "classification.divisions": "DDC-Sachgruppe",
  "classification.noneOnBook": "Noch keine Klassifikation.",
  "classification.noneToFilter": "Noch kein Buch im Bestand tr\u00e4gt eine.",
  "classification.filterBy": "Nur B\u00fccher mit {heading} zeigen",
  "classification.scheme.ddc": "DDC",
  "classification.scheme.lcc": "Library of Congress",
  "classification.scheme.gnd": "GND",
  "classification.scheme.lcsh": "Schlagwort",

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
  "section.reading": "Eigene Lektüre",
  "section.filing": "Dieses Exemplar einordnen",
  "section.copies": "Eigene Exemplare",
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
  // "Signatur" ist der bibliothekarische Begriff für die Notation, unter der
  // ein Buch im Regal steht. Bewusst nicht "Regal": das ist `location.label`,
  // die freie Beschreibung, wo ein Buch in diesem Haushalt tatsächlich steht.
  "field.callNumber": "Signatur",
  "field.classification": "Schlagwörter",

  // ── Spalten der Tabelle wählen ──────────────────────────────────────────
  "columns.label": "Spalten",
  "columns.summary": "{shown} von {total}",
  "columns.reset": "Zurück zu den üblichen Spalten",
  "columns.alwaysShown": "Der Titel wird immer angezeigt.",

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
    "Die Ausgabe wählen, die vorliegt. Es werden nur leere Felder ergänzt, eigene Angaben bleiben stehen.",
  "enrich.proposedClassifications": "Vorgeschlagene Klassifikationen",
  "enrich.noClassifications": "Keine Klassifikationen vorgeschlagen.",
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
  "scan.cameraIdleHint":
    "Es wird nichts aufgezeichnet, die Kamera bleibt geschlossen, bis sie gestartet wird.",
  "scan.notABook":
    "{code} gelesen, das ist kein Buch-Barcode. Der gesuchte Code steht über der ISBN.",
  "scan.tryAgain": "Erneut versuchen",
  "scan.cameraUnavailable": "Kamera nicht verfügbar",
  "scan.orEnterManually": "Oder ISBN von Hand eingeben:",
  "scan.isbnLabel": "ISBN",
  "scan.lookUp": "Nachschlagen",
  "scan.lookingUp": "Buch wird gesucht...",
  "scan.invalidIsbn":
    "Das sieht nicht nach einer gültigen ISBN aus. Bitte die Ziffern prüfen und es erneut versuchen.",
  "scan.notFoundManual":
    "Keine Angaben zur ISBN {isbn} gefunden. Das Buch lässt sich trotzdem von Hand anlegen.",
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
    "Keine Treffer. Weniger Wörter versuchen, oder das Buch von Hand eintragen.",
  "search.pickHint":
    "Einen Treffer auswählen, um die Angaben zu übernehmen. Gespeichert wird erst nach dem Bestätigen.",
  "search.withoutKey":
    "Es wird Open Library durchsucht. Ein Google-Books-Schlüssel ergänzt Beschreibungen und Genres.",
  "search.slow.offer":
    "{names} sind langsamer, als eine schnelle Suche warten kann.",
  "search.slow.button": "Gründlicher suchen",
  "search.slow.done": "Alle Kataloge wurden gefragt.",
  "search.slow.busy":
    "Es läuft immer nur eine lange Suche gleichzeitig. Bitte gleich noch einmal versuchen.",
  "search.slow.nothingAsked":
    "Es wurde nichts durchsucht. Jeder Katalog, den diese Bibliothek eingeschaltet hat, ist ein langsamer.",

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

  // ── Custom fields ───────────────────────────────────────────────────────
  "customFields.title": "Eigene Felder",
  "customFields.explain":
    "Angaben zu einem Buch, für die Endpaper keinen Platz hat, zum Beispiel ein Link auf dasselbe Buch in einer anderen App.",
  "customFields.none": "Noch keine eigenen Felder",
  "customFields.nameLabel": "Feldname",
  "customFields.namePlaceholder": "Calibre-web",
  "customFields.kindLabel": "Was darin steht",
  "customFields.kindText": "Text",
  "customFields.kindUrl": "Ein Weblink",
  "customFields.addButton": "Feld hinzufügen",
  "customFields.renameLabel": "Neuer Name für {name}",
  "customFields.deleteConfirm":
    "{name} löschen? Der Eintrag wird bei jedem Buch entfernt und lässt sich nicht wiederherstellen.",
  "customFields.bookNone": "Noch nichts eingetragen",
  "customFields.editButton": "Angaben bearbeiten",
  "customFields.valuePlaceholder": "Leer lassen, um zu löschen",
  "customFields.opensElsewhere": "Öffnet in einem neuen Tab",

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
  "quotes.noteLabel": "Anmerkung dazu",
  "quotes.editNoteLabel": "Anmerkung bearbeiten",
  "quotes.notePlaceholder": "Warum gerade dieses (optional)",
  "quotes.onPage": "S. {page}",
  "quotes.empty": "Noch keine Zitate gespeichert",
  "quotes.emptyHint":
    "Ein Buch öffnen und eine Stelle abschreiben, die bleiben soll.",
  "quotes.couldNotLoad": "Die Zitate konnten nicht geladen werden.",
  "quotes.pagination": "Zitatseiten",
  "quotes.pageOf": "Seite {page} von {of}",
  "quotes.previous": "Zurück",
  "quotes.next": "Weiter",

  // ── Statistik ───────────────────────────────────────────────────────────
  "stats.title": "Sammlung in Zahlen",
  "stats.booksInLibrary": "Bücher in der Bibliothek",
  "stats.byMember": "Hinzugefügt nach Person",
  "stats.byType": "Nach Art",
  "stats.byGenre": "Nach Genre",
  "stats.byAge": "Nach Alter",
  "stats.byCustomTag": "Nach freien Schlagwörtern",
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
  "tags.custom": "Freie Schlagwörter",
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
  "login.tagline": "Ein eigener Bücherkatalog",
  "login.signIn": "Anmelden",
  "login.createAccount": "Konto erstellen",
  "login.switchToSignIn": "Zum Anmelden wechseln",
  "login.switchToRegister": "Zur Registrierung wechseln",
  "login.username": "Benutzername",
  "login.password": "Passwort",
  "login.usernamePlaceholder": "Benutzername eingeben",
  "login.passwordPlaceholder": "Passwort eingeben",
  "login.email": "E-Mail-Adresse",
  "login.emailOptional": "optional",
  "login.emailHint":
    "Hierhin ginge eine persönlich adressierte Erinnerung. Verschickt wird noch nichts, und die Adresse lässt sich auch später eintragen.",
  "login.emailPlaceholder": "name@example.org",
  "login.pleaseWait": "Bitte warten...",
  "login.browseCatalogue": "Den öffentlichen Katalog durchsuchen",
  "login.firstAccountAdmin":
    "Das zuerst erstellte Konto wird zum Administrator.",
  "login.directoryHint":
    "Anmeldung mit dem Verzeichniskonto. Konten werden dort verwaltet, nicht hier.",
  "login.failed": "Anmeldung fehlgeschlagen.",
  "login.setBackground": "Hintergrundbild festlegen",
  "login.changeBackground": "Hintergrundbild ändern",
  "login.uploading": "Wird hochgeladen...",
  "login.signingYouIn": "Anmeldung läuft",

  // ── Einstellungen ───────────────────────────────────────────────────────
  "settings.title": "Einstellungen",
  "settings.saved": "Einstellungen gespeichert.",
  "settings.couldNotLoad": "Die Einstellungen konnten nicht geladen werden.",
  "settings.adminOnly": "Nur Administratoren können das ändern.",

  "settings.appearance.title": "Darstellung",
  "settings.appearance.summary":
    "Das Farbschema, hell oder dunkel, das Hintergrundmuster und die Sprache der App.",
  "settings.account.title": "Eigenes Konto",
  "settings.account.summary":
    "Die Adresse, an die eine persönlich adressierte Erinnerung ginge.",
  "settings.catalogue.title": "Katalogquellen",
  "settings.catalogue.summary":
    "Woher die Angaben zu einem Buch stammen, wenn es gescannt oder gesucht wird.",
  "settings.library.title": "Eigene Bibliothek",
  "settings.library.summary":
    "Bücher aus einem anderen Dienst übernehmen, fehlende Cover nachholen und Angaben ergänzen, für die Endpaper keine Spalte hat.",
  "settings.public.title": "Öffentlicher Katalog",
  "settings.public.summary":
    "Der Bibliotheksmodus, und ob Lesende ohne Konto in diesem Katalog suchen dürfen. Beides ist aus, bis es eingeschaltet wird.",
  "settings.public.modeTitle": "Bibliotheksmodus",
  "settings.public.modeLabel": "Diese Bibliothek als Bibliothek katalogisieren",
  "settings.public.modeHint":
    "Zeigt Signatur und Schlagwörter und blendet Besitz und Lesestatus aus. Veröffentlicht wird dadurch nichts.",
  "settings.public.modeRepublishes":
    "Das Veröffentlichen ist bereits eingeschaltet. Wird dies wieder eingeschaltet, ist der Katalog sofort erneut öffentlich.",
  "settings.public.publishTitle": "Veröffentlichen",
  "settings.public.publishLabel": "Alle dürfen in diesem Katalog suchen",
  "settings.public.publishHint":
    "Suche und ein Datensatz je Buch, lesbar ohne Konto. Sonst nichts.",
  "settings.public.publishNeedsMode":
    "Zuerst den Bibliotheksmodus einschalten. Ohne ihn lässt sich kein Katalog veröffentlichen.",
  "settings.public.liveNotice": "Dieser Katalog ist veröffentlicht.",
  "settings.public.liveLink": "Ansehen, was Besuchende sehen",
  "settings.public.indexingLabel": "Suchmaschinen dürfen ihn indexieren",
  "settings.public.indexingHint":
    "Standardmäßig aus. Einen Katalog zu veröffentlichen und eine Suchmaschine einzuladen, ihn zu durchsuchen, sind zwei verschiedene Entscheidungen.",
  "settings.public.confirmTitle": "Diesen Katalog veröffentlichen?",
  "settings.public.confirmBody":
    "Alle, die diesen Server erreichen, können darin suchen und je Buch einen Datensatz lesen, ohne Konto und ohne Passwort.",
  "settings.public.confirmShown":
    "Sichtbar: Titel, Autorin oder Autor, Verlag, Jahr, ISBN, Sprache, Seitenzahl, Ausgabeform, Reihe, Beschreibung, Schlagwörter und Klassifikationen.",
  "settings.public.confirmWithheld":
    "Nicht sichtbar: wem ein Buch gehört, ob es verliehen wird, wer es gelesen hat, wo es steht, was es gekostet hat, und sämtliche Notizen.",
  "settings.public.confirmPrivate":
    "Private Bücher bleiben privat, und alles im Papierkorb ebenso.",
  "settings.public.confirmIndexing":
    "Suchmaschinen wird gesagt, dass sie fernbleiben sollen, bis sie eigens zugelassen werden.",
  "settings.public.confirmAction": "Veröffentlichen",
  "settings.lending.title": "Ausleihe",
  "settings.lending.summary":
    "Erinnerungen an überfällige Bücher, und wohin sie gehen.",
  "settings.data.title": "Daten und Konten",
  "settings.data.summary":
    "Die ganze Bibliothek sichern und zurückspielen, und Konten, um sie wie ein gewöhnliches Mitglied zu sehen.",
  "settings.about.summary":
    "Welche Version läuft, wo der Quelltext liegt und wie sich das Projekt unterstützen lässt.",

  // ── Eigenes Konto ───────────────────────────────────────────────────────
  "account.email.title": "E-Mail-Adresse",
  "account.email.hint":
    "Hierhin ginge eine persönlich adressierte Erinnerung. Verschickt wird noch nichts: Erinnerungen an überfällige Bücher gehen an das Postfach des Haushalts.",
  "account.email.yours": "Eigene Adresse",
  "account.email.placeholder": "name@example.org",
  "account.email.none": "Nicht hinterlegt.",
  "account.email.noneFromDirectory":
    "Nicht hinterlegt. Das Verzeichnis liefert keine Adresse, sie kann hier eingetragen werden.",
  "account.email.fromDirectory":
    "Diese Adresse stammt aus dem Verzeichnis. Sie wird dort geändert.",
  "account.email.directoryRefused":
    "Diese Adresse gehört dem Verzeichnis und wurde hier nicht geändert.",
  "account.email.couldNotSave": "Die Adresse konnte nicht gespeichert werden.",
  "account.members.title": "Adressen der Mitglieder",
  "account.members.hint":
    "Damit sich die fehlende oder falsch getippte Adresse finden lässt, wenn Erinnerungen nirgends ankommen.",

  "theme.hint": "Wird im Konto gespeichert und gilt auf allen Geräten.",
  "theme.light": "Hell",
  "theme.dark": "Dunkel",
  "theme.system": "Systemeinstellung",
  "theme.systemHint":
    "Übernimmt, was auf diesem Handy oder Rechner eingestellt ist.",
  "theme.wallpaperOff":
    "Das Hintergrundmuster ist aus, weil das System mehr Kontrast verlangt.",
  "theme.summary": "{palette}, {mode}, {wallpaper}",
  "theme.change": "Farbwelt, hell oder dunkel und ein Hintergrundmuster wählen",

  "appearance.title": "Farbschema und Hintergrund",
  "appearance.intro": "Alles hier gilt sofort und wird im Konto gespeichert.",
  "appearance.preview": "Die Bibliothek in dieser Darstellung",
  "appearance.previewEmpty":
    "Auf diesem Gerät sind gerade keine Bücher geladen, also gibt es nichts Echtes zum Ansehen. Kurz in die Bibliothek wechseln und zurückkommen.",
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
  "settings.languageHint": "Gilt nur auf diesem Gerät.",
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
    "Dieser Schlüssel kommt aus der Serverkonfiguration und lässt sich hier weder ändern noch anzeigen. GOOGLE_BOOKS_API_KEY wird dort geändert, wo die App bereitgestellt wird.",
  "settings.apiKeyHelp": "Wie bekomme ich einen Schlüssel?",
  "settings.apiKeyHint":
    "Einen in der Google Cloud Console anlegen und dafür die Books API aktivieren. Der Schlüssel wird nach dem Speichern nicht mehr angezeigt.",

  "settings.testAccounts": "Testkonten",
  "settings.testAccountsHint":
    "Konten mit einem selbst gewählten Passwort, um die Bibliothek so zu sehen, wie ein gewöhnliches Mitglied sie sieht. Diese Konten sind nie Administratoren und werden auf der Anmeldeseite nicht angeboten.",
  "settings.testAccountsReturnProxy":
    "Zum Zurückkehren im Menü den Eintrag Zurück zu meinem Konto wählen.",
  "settings.testAccountsReturnToken":
    "Zum Zurückkehren wieder mit dem eigenen Konto anmelden.",
  "settings.testAccountsEmpty": "Noch keine Testkonten.",
  "settings.testAccountsCreate": "Testkonto anlegen",
  "settings.testAccountsCreateFailed":
    "Das Konto konnte nicht angelegt werden.",
  "settings.testAccountsPasswordPlaceholder": "Passwort, mindestens 8 Zeichen",
  "settings.testAccountsAddress": "E-Mail-Adresse für dieses Konto, optional",
  "settings.testAccountsAddressPlaceholder": "E-Mail-Adresse (optional)",
  "settings.testAccountsAddressHint":
    "Verschickt wird noch nichts. Erinnerungen an überfällige Bücher gehen an das Postfach des Haushalts.",
  "settings.testAccountsSwitch": "Wechseln",
  "settings.testAccountsSwitchTo": "Zu {name} wechseln",
  "settings.testAccountsSwitchFailed":
    "Zu diesem Konto konnte nicht gewechselt werden.",
  "settings.testAccountsPasswordFor": "Passwort für {name}",

  // ── Erinnerungen an überfällige Bücher ──────────────────────────────────
  "settings.overdue": "Erinnerungen an überfällige Bücher",
  "settings.overdueEnable": "Erinnerung an einen Webhook senden",
  "settings.overdueHint":
    "Endpaper schaut stündlich nach und sendet über jeden eingeschalteten Kanal eine Nachricht mit den Ausleihen, die angemahnt werden. Gibt es nichts anzumahnen, wird nichts gesendet.",
  "settings.overduePrivacyNote":
    "Private Bücher werden über keinen Kanal mitgesendet. Jeder Kanal hier landet an einem Ort ohne ein einzelnes Konto dahinter, dort wäre ein privater Titel für alle lesbar, die mitlesen. Überfällige private Bücher erscheinen weiterhin in der Ausleihliste ihrer Besitzerin oder ihres Besitzers.",
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
  "settings.overdueNotSentMisconfigured":
    "Es wurde nichts gesendet: Ein Kanal ist eingeschaltet und seine Einstellungen sind unbrauchbar. Welcher, steht unten.",
  "settings.overdueNotSentInAppOnly":
    "Nach außen wurde nichts gesendet: Der Hinweis in der App ist der einzige eingeschaltete Kanal, und alle Mitglieder lesen ihn in der Bibliothek.",
  "settings.overdueSenderInApp": "In der App",
  "settings.overdueSenderWebhook": "Webhook",
  "settings.overdueSenderEmail": "E-Mail",
  "settings.overdueSenderTelegram": "Telegram",
  "settings.overdueSenderSent": "{sender}: gesendet.",
  "settings.overdueSenderFailed": "{sender}: {detail}",
  "settings.overdueRowDisabled": "ausgeschaltet.",
  "settings.overdueRowNoUrl": "keine Adresse gespeichert.",
  "settings.overdueRowNothingDue": "nichts zu senden.",
  "settings.overdueRowUnreachable":
    "nicht erreichbar. Es wird erneut versucht.",
  "settings.overdueRowMisconfigured": "die Einstellungen sind unbrauchbar.",
  "settings.overdueRowInAppOnly": "nach außen nichts zu senden.",
  "settings.overdueRowNothingSent": "nichts gesendet.",

  // ── Erinnerungen in der App, und ob ein Kanal funktioniert ──────────────
  "settings.inApp": "In der App",
  "settings.inAppEnable": "Überfällige Ausleihen in der App anzeigen",
  "settings.inAppHint":
    "Ein Hinweis auf der Bibliotheksseite und die Seite mit den überfälligen Ausleihen, auf die er verweist. Wird er ausgeschaltet, bleibt diese Seite leer, alle anderen Kanäle laufen weiter. Dies ist der einzige Kanal, für den nichts eingerichtet werden muss, deshalb ist er von Anfang an eingeschaltet.",
  "settings.inAppPrivacyNote":
    "Dieser Kanal hat eine Leserin oder einen Leser, deshalb gilt der Hinweis oben für ihn nicht: Jede Person sieht die überfälligen Ausleihen, die sie verliehen oder ausgeliehen hat, einschließlich ihrer eigenen privaten Bücher, und niemals die anderer. Im Bibliotheksmodus sieht jede Person stattdessen alle überfälligen Ausleihen der Bibliothek, und weiterhin nie ein privates Buch, das jemand anderes angelegt hat.",
  "settings.senderHealthNotYet":
    "Noch nicht gelaufen. Erinnerungen gehen stündlich raus, und nur wenn etwas überfällig ist.",
  "settings.senderHealthWorking": "Funktioniert. Zuletzt gelaufen am {when}.",
  "settings.senderHealthFailedOnce":
    "Der letzte Versuch ist fehlgeschlagen: {detail} Es wird erneut versucht.",
  "settings.senderHealthBroken":
    "Funktioniert seit dem {since} nicht mehr. Der letzte Versuch war am {when}: {detail}",

  // ── Erinnerungen per Mail und Chat ──────────────────────────────────────
  "settings.senders": "Erinnerungen per Mail und Chat",
  "settings.sendersHint":
    "Dieselbe Erinnerung über Kanäle, die ein Haushalt ohnehin hat. Jeder wird einzeln eingeschaltet, und jeder eingeschaltete bekommt dieselbe Nachricht.",
  "settings.sendersPrivacyNote":
    "Beide landen in einem Postfach oder einem Chat, den mehrere Menschen lesen. Private Bücher bleiben dort genauso außen vor wie beim Webhook.",

  "settings.mail": "E-Mail",
  "settings.mailEnable": "Erinnerung per E-Mail senden",
  "settings.mailHint":
    "Eine Nachricht an das Postfach des Haushalts, mit denselben Ausleihen.",
  "settings.mailServer": "Mailserver",
  "settings.mailServerPlaceholder": "smtp.example.org",
  "settings.mailPort": "Port",
  "settings.mailUsername": "Mail Benutzername",
  "settings.mailUsernamePlaceholder":
    "Leer lassen, wenn der Server keine Anmeldung braucht",
  "settings.mailPassword": "Mail Passwort",
  "settings.mailPasswordPlaceholder":
    "Neues Passwort einfügen, um das gespeicherte zu ersetzen",
  "settings.mailPasswordShow": "Mailpasswort anzeigen",
  "settings.mailPasswordHide": "Mailpasswort verbergen",
  "settings.mailPasswordSet": "Ein Passwort ist gespeichert ({preview}).",
  "settings.mailPasswordMissing": "Kein Passwort gespeichert.",
  "settings.mailPasswordSave": "Passwort speichern",
  "settings.mailPasswordClear": "Gespeichertes Passwort entfernen",
  "settings.mailSecurity": "Verschlüsselung",
  "settings.mailSecurityStartTls": "STARTTLS",
  "settings.mailSecurityTls": "TLS",
  "settings.mailSecurityNone": "Keine",
  "settings.mailSecurityHint":
    "Zertifikate und Hostnamen werden immer geprüft, und nichts hier kann das abschalten. Ein Passwort ohne Verschlüsselung wird abgelehnt, denn es ginge im Klartext über das Netz.",
  "settings.mailFrom": "Absenderadresse",
  "settings.mailFromPlaceholder": "library@example.org",
  "settings.mailTo": "Erinnerungen senden an",
  "settings.mailToPlaceholder": "house@example.org",
  "settings.mailToHint":
    "Eine Adresse, oder mehrere durch Kommas getrennt. Höchstens zehn.",
  "settings.mailSave": "Mail Einstellungen speichern",
  "settings.mailFromEnv":
    "Diese Installation setzt {fields} in ihrer Umgebung, diese Felder sind hier deshalb fest.",

  "settings.telegram": "Telegram",
  "settings.telegramEnable": "Erinnerung an einen Telegram Chat senden",
  "settings.telegramHint":
    "Eine Nachricht an einen Chat, nicht an jede Person einzeln. Ein Bot kann niemandem schreiben, der ihm nicht zuerst geschrieben hat, deshalb würde ein Versand pro Person für alle stillschweigend fehlschlagen, die diesen Schritt auslassen.",
  "settings.telegramToken": "Bot Token",
  "settings.telegramTokenPlaceholder":
    "Neues Token einfügen, um das gespeicherte zu ersetzen",
  "settings.telegramTokenShow": "Bot Token anzeigen",
  "settings.telegramTokenHide": "Bot Token verbergen",
  "settings.telegramTokenSet": "Ein Token ist gespeichert ({preview}).",
  "settings.telegramTokenMissing":
    "Kein Token gespeichert. Mit @BotFather einen Bot anlegen und das Token einfügen, das er nennt.",
  "settings.telegramTokenSave": "Token speichern",
  "settings.telegramTokenClear": "Gespeichertes Token entfernen",
  "settings.telegramChat": "Chat Id",
  "settings.telegramChatPlaceholder": "-1001234567890",
  "settings.telegramChatHint":
    "Die Nummer der Gruppe, in die der Bot aufgenommen wurde, oder ein @Name für einen öffentlichen Kanal.",
  "settings.telegramChatSave": "Chat Id speichern",
  "settings.telegramFromEnv":
    "Diese Installation setzt das in ihrer Umgebung, hier ist es deshalb fest.",

  "settings.goodreads": "Goodreads",
  "settings.goodreadsEnable": "Goodreads Links anzeigen",
  "settings.goodreadsHint":
    "Fügt neben jedem Titel einen Link hinzu, der bei Goodreads sucht.",

  // ── Bewertung und Lesedaten ─────────────────────────────────────────────
  "rating.label": "Eigene Bewertung",
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
    "Bei einem Buch eine Reihe eintragen, dann erscheint sie hier",
  "series.viewAll": "Ganze Reihe ansehen",
  "series.couldNotLoad": "Die Reihen konnten nicht geladen werden.",

  // ── Standort ────────────────────────────────────────────────────────────
  "location.label": "Wo es steht",
  "location.placeholder": "Wohnzimmer Regal 3",
  "location.unset": "Nicht erfasst",
  "location.filterAll": "Überall",
  "location.hint": "Freier Text. So, wie man es auch sagen würde.",
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
    "Eine Sammlung teilt das Regal auf: gedruckt und digital, behalten und verkauft, Mein und Dein. Ein Buch liegt in genau einer Sammlung, also die wichtigste Aufteilung wählen; für alles andere gibt es Schlagwörter.",
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
    "Alle, die auf dem Regal genannt sind. Die Namen stammen aus den Büchern selbst, deshalb kann eine Person doppelt auftauchen: die Schreibweisen lassen sich zusammenführen, die Bücher bleiben unverändert.",
  "authors.search": "Namen durchsuchen",
  "authors.searchPlaceholder": "Name",
  "authors.bookCount": "{count} Bücher",
  "authors.none": "Noch niemand erfasst",
  "authors.noneHint": "Ein Buch mit Autorenangabe anlegen, dann steht es hier",
  "authors.noMatches": "Kein Name passt dazu",
  "authors.couldNotLoad": "Die Namen konnten nicht geladen werden.",
  "authors.alsoSpelled": "Auch geschrieben: {spellings}",
  "authors.mergedFrom": "Zusammengeführt aus: {spelling}",
  "authors.undo": "Zusammenführung rückgängig machen",
  "authors.browse": "Diese Bücher anzeigen",
  "authors.wikipediaOn": "Über {name} auf Wikipedia lesen",
  "authors.wikipediaInOther": "Über {name} auf Wikipedia lesen, auf {language}",
  "authors.wikidataItem": "{name} auf Wikidata nachschlagen",
  "authors.select": "{name} auswählen",
  "authors.selectedCount": "{count} ausgewählt",
  "authors.keepNamed": "{name} behalten",
  "authors.suggestionsTitle": "Vermutlich dieselbe Person",
  "authors.suggestionsExplain":
    "Alle herausnehmen, die nicht dazugehören, und dann den Namen wählen, der bleiben soll. An den Büchern ändert sich nichts, und über die Karte lässt es sich wieder rückgängig machen.",
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
  "authors.reasonIdentity": "derselbe Normdatensatz",
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
    "Diese Einträge sehen nach demselben Buch aus. Den auswählen, der bleiben soll, die anderen gehen darin auf.",
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
    "Einfach weiterscannen. Jedes Buch wird nachgeschlagen und gesammelt, bestätigt wird am Ende alles zusammen.",
  "rapid.queued": "{count} gescannt",
  "rapid.lookingUp": "Wird nachgeschlagen...",
  "rapid.notFound": "Nicht gefunden: {isbn}",
  "rapid.duplicate": "Schon gescannt",
  "rapid.alreadyInLibrary": "Schon in der Bibliothek",
  "rapid.reviewTitle": "{count} Bücher prüfen",
  "rapid.addAll": "Alle hinzufügen",
  "rapid.adding": "Wird hinzugefügt...",
  "rapid.discard": "Verwerfen",
  "rapid.added": "{count} hinzugefügt. {failed} stehen unten, mit dem Grund.",
  "rapid.removeFromQueue": "{isbn} aus der Liste entfernen",
  "rapid.nothingScanned": "Noch nichts gescannt",

  // ── Rückgabefristen ─────────────────────────────────────────────────────
  "loans.dueDate": "Zurück bis",
  "loans.dueOn": "Fällig am {date}",
  "loans.noDueDate": "Kein Datum",
  "loans.overdue": "Überfällig",
  "loans.overdueSince": "Überfällig seit {date}",
  "loans.overdueByDaysSince": "{days} Tage überfällig, seit {date}",
  "loans.overdueByOneDaySince": "1 Tag überfällig, seit {date}",
  // "Seit ... ausgeliehen" rather than a word-for-word "Out for": German puts
  // the participle last, so the English order does not survive translation.
  "loans.outFor": "Seit {days} Tagen ausgeliehen",
  "loans.outForOne": "Seit 1 Tag ausgeliehen",
  "loans.overdueOnly": "Nur überfällige",
  "loans.overdueBanner": "{count} Ausleihen sollten angemahnt werden.",
  "loans.chaseThem": "Anzeigen",

  // ── Die Seite mit den überfälligen Ausleihen ────────────────────────────
  "overdue.title": "Überfällig",
  "overdue.couldNotLoad":
    "Die überfälligen Ausleihen konnten nicht geladen werden.",
  "overdue.none": "Nichts ist überfällig",
  "overdue.noneHint":
    "Jedes ausgeliehene Buch ist noch innerhalb seiner Frist.",
  "overdue.switchedOff": "Die Erinnerung in der App ist ausgeschaltet",
  "overdue.switchedOffHint":
    "Ein Administrator kann sie unter Ausleihe wieder einschalten. Betroffen ist nur diese Seite: Kanäle, die nach außen verschicken, laufen weiter, und die Ausleihen selbst stehen weiterhin auf der Ausleihseite.",
  "overdue.capped":
    "Es werden die {shown} am längsten überfälligen von {total} angezeigt.",
  "overdue.deliveryTitle": "Erinnerungskanäle",
  "overdue.deliveryNote":
    "Endpaper hält fest, was jeder Kanal bei seinem letzten Lauf getan hat. Es hält nicht fest, welche Erinnerung wen erreicht hat: diese Zeilen beschreiben also den Kanal und keine einzelne Ausleihe darunter.",
  "overdue.deliveryNone":
    "Kein Kanal verschickt diese Erinnerungen irgendwohin.",
  "overdue.deliveryUnreadable":
    "Der Kanalbericht konnte nicht gelesen werden. Diese Seite sagt daher nichts darüber aus, ob Erinnerungen verschickt werden.",

  // ── Das Exemplar ────────────────────────────────────────────────────────
  "copy.title": "Dieses Exemplar",
  "copy.hint": "Was an diesem Exemplar hängt, nicht was das Buch ist.",
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
  "copy.priceInvalid":
    "Einen Preis wie 12,99 eintragen, oder das Feld leer lassen.",
  "copy.currency": "Währung",
  "copy.purchasedAt": "Gekauft am",
  "copy.purchaseSource": "Gekauft bei",
  "copy.save": "Angaben zum Exemplar speichern",
  "copy.purchaseSourcePlaceholder": "Der Buchladen um die Ecke",

  // ── Mehrere Exemplare desselben Buchs ───────────────────────────────────
  "copies.title": "Exemplare",
  "copies.count": "{count} Exemplare dieses Buchs",
  "copies.hint":
    "Ein zweites Exemplar ist ein zweiter Gegenstand: eigenes Regal, eigener Zustand, eigene Ausleihe.",
  "copies.thisOne": "Dieses hier",
  "copies.open": "Öffnen",
  "copies.noShelf": "Kein Regal erfasst",
  "copies.onLoan": "Verliehen",
  "copies.add": "Weiteres Exemplar hinzufügen",
  "copies.adding": "Wird hinzugefügt...",
  "copies.fromScanHint":
    "Ein Exemplar übernimmt Schlagwörter, Titelbild und die Sichtbarkeit von dem Buch, das schon da ist.",
  "copies.addFailed": "Dieses Exemplar konnte nicht hinzugefügt werden.",
  "copies.loadFailed":
    "Die anderen Exemplare dieses Buchs konnten nicht geladen werden.",
  "copies.badge": "{count} Exemplare",
  "format.filterAll": "Jede Ausgabe",

  // ── Herborgen und drüber reden ──────────────────────────────────────────
  "lending.label": "Verleihen",
  "lending.unset": "Nicht erfasst",
  "lending.filterAll": "Verleihen: beliebig",
  "lending.happy": "Borge ich gern her",
  "lending.in_use": "Brauche ich gerade selbst",
  "lending.never": "Wird nicht hergeborgt",
  "lending.neverWarning":
    'Dieses Buch ist als "wird nicht hergeborgt" markiert.',
  "lending.lendAnyway": "Trotzdem herborgen",
  "discuss.toggle": "Über dieses Buch rede ich gern, einfach danach fragen",
  "discuss.label": "Ansprechpartner",
  "discuss.badge": "Gesprächsstoff",
  "discuss.others": "{names} darauf ansprechen.",

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
    "Diese Bücher kommen als nicht bestätigt an: ein Export sagt, was jemand gelesen hat, nicht, was im Regal steht.",
  "import.applyTags": "Schlagwörter mit übernehmen",
  "import.applyTagsHint":
    "Diese Datei enthält {count} verschiedene Schlagwörter. Angelegt werden sie hier für alle, unter Freie Schlagwörter, und lassen sich nur einzeln wieder entfernen.",
  "import.result":
    "{rowsRead} Zeilen gelesen, {matched} zugeordnet, {created} angelegt, {statusesUpdated} Lesestände aktualisiert.",
  "import.skipped":
    "{count} Zeilen hatten keinen Titel und wurden übersprungen.",
  "import.unmatched": "Nicht im Katalog gefunden:",

  // ── MARC (Bibliotheksmodus) ─────────────────────────────────────────────
  "marc.title": "Einen Katalog übernehmen",
  "marc.explain":
    "Eine MARCXML-Datei, die eine andere Bibliothek exportiert hat. Datensätze werden über die ISBN zugeordnet, sonst über Verfasser und Titel zusammen, damit ein zweiter Import derselben Datei den Katalog nicht verdoppelt.",
  "marc.chooseFile": "MARC-Datei auswählen",
  "marc.reading": "Datei wird gelesen...",
  "marc.importing": "Wird importiert...",
  "marc.previewTitle":
    "{total} Datensätze in der Datei, {readable} davon kann diese App speichern.",
  "marc.alreadyHeld":
    "{count} davon stehen bereits in diesem Regal und werden ergänzt statt neu angelegt.",
  "marc.blocked":
    "{count} tragen eine ISBN, die zu einem für dieses Konto nicht sichtbaren Buch gehört, und bleiben unangetastet.",
  "marc.skipped":
    "{count} Datensätze haben keinen Titel und bleiben unberücksichtigt.",
  "marc.createMissing":
    "Die {count} Datensätze anlegen, die dieser Katalog nicht hat",
  "marc.createMissingHint":
    "Diese Datensätze werden als nicht bestätigt angelegt: der Datensatz einer anderen Bibliothek sagt, dass jene Bibliothek das Buch besitzt, nicht diese.",
  "marc.confirm": "{count} Datensätze importieren",
  "marc.confirmMatchedOnly": "{count} bereits vorhandene Datensätze ergänzen",
  "marc.result":
    "{rowsRead} Datensätze gelesen, {matched} zugeordnet, {created} angelegt.",
  "marc.resultSkipped":
    "{count} Datensätze blieben unberücksichtigt: kein Titel, oder eine ISBN, die zu einem für dieses Konto nicht sichtbaren Buch gehört.",

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
  "backup.restoreFailed":
    "Diese Sicherung konnte nicht wiederhergestellt werden.",
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
    "Für {count} davon gibt es irgendwo ein Cover, das von hier aus nicht geladen werden konnte. Diese Bücher behalten ihren Link und werden beim nächsten Durchlauf durch die Bibliothek erneut abgerufen.",
  "covers.remaining":
    "Noch {remaining} Bücher offen. Noch einmal ausführen, um weiterzumachen.",
  "covers.allDone": "Jedes Buch, das ein Cover haben kann, hat eines.",

  // ── Über ────────────────────────────────────────────────────────────────
  "about.title": "Über Endpaper",
  "about.versionLabel": "Version",
  "about.licenceLabel": "Lizenz",
  "about.sourceLabel": "Quelltext",
  "about.support":
    "Wer Endpaper mag und meine Arbeit unterstützen möchte, kann mir einen Kaffee spendieren. Er hilft, den öffentlichen Server zu finanzieren, der zwei Endpaper-Installationen miteinander verbindet. Alle Funktionen sind so oder so kostenlos.",
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
    "Gelöschte Bücher warten hier, bis der Papierkorb geleert wird. Von allein wird nichts entfernt.",
  "trash.empty": "Der Papierkorb ist leer",
  "trash.emptyHint":
    "Bücher, die gelöscht werden, landen hier, mit allem, was daran hängt.",
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
    "Ein Buch, das noch fehlt: als Wunsch und als nicht vorhanden markieren.",
  "wishlist.explain": "Gewünschte Bücher, die nicht im Regal stehen.",

  // ── Hilfe ───────────────────────────────────────────────────────────────
  "help.title": "Was ist das?",
  "help.aboutSearch": "Über die Buchsuche",
  "help.aboutEnrich": "Über zusätzliche Buchdetails",

  "help.googleBooks.title": "Google-Books-Abfrage",
  "help.googleBooks.what":
    "Google Books ergänzt Angaben, die ein Barcode nicht enthält: Seitenzahl, Sprache, Kategorien, Reihe und eine Beschreibung. Dafür braucht es einen kostenlosen API-Schlüssel, den ein Admin einmal für alle hier einrichtet.",
  "help.googleBooks.notConfigured":
    "Es ist noch kein Schlüssel hinterlegt, deshalb ist die Funktion aus. So kommt man an einen.",
  "help.googleBooks.step1": "In der Google-Cloud-Konsole ein Projekt anlegen.",
  "help.googleBooks.step2": "Die Books API für dieses Projekt aktivieren.",
  "help.googleBooks.step3": "Unter Anmeldedaten einen API-Schlüssel erstellen.",
  "help.googleBooks.step4":
    "Den Schlüssel hier in den Einstellungen eintragen und die Funktion einschalten.",
  "help.googleBooks.cost":
    "Die Books API ist kostenlos. Eine Kreditkarte ist nicht nötig, und das Tageskontingent reicht für eine private Bibliothek um ein Vielfaches.",
  "help.googleBooks.restrict":
    "Der Schlüssel liegt hier und wird nur von diesem Server aus verwendet, deshalb genügt es, ihn auf die Books API zu beschränken. Nach dem Speichern wird er nie wieder angezeigt.",
  "help.googleBooks.toSettings": "Einstellungen öffnen",
  "help.googleBooks.adminOnly":
    "Nur ein Admin kann den Schlüssel speichern. Wer keiner ist, kann einem Admin diese Seite schicken.",

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
    "Dieses Konto hat darauf keinen Zugriff. Falls es das haben sollte, hilft die Person weiter, die die Bibliothek eingerichtet hat.",
  "error.500.code": "Fehler 500",
  "error.500.title": "Da ist etwas kaputt",
  "error.500.message":
    "Hier wurde nichts falsch gemacht, der Fehler liegt bei uns. Meistens hilft ein Neuladen.",
  "error.sessionEnded.code": "Fehler 401",
  "error.sessionEnded.title": "Die Sitzung ist beendet",
  "error.sessionEnded.message":
    "Das Anmeldeportal hat diese Sitzung beendet, und ein Neuladen hat sie nicht zurückgebracht. Bitte erneut anmelden.",
  "error.sessionEnded.action": "Erneut anmelden",
  "error.backToLibrary": "Zurück zur Bibliothek",
  "error.reload": "Seite neu laden",

  // ── Der veröffentlichte Katalog ─────────────────────────────────────────
  //
  // Wer diese Seiten liest, gehört nicht zum Haushalt. Früher wurde hier
  // gesiezt, während der Rest der Anwendung duzte; seit die ganze Datei ohne
  // Anrede auskommt, braucht dieser Abschnitt keine eigene Regel mehr.
  "public.title": "Katalog",
  "public.skipToContent": "Zum Katalog springen",
  "public.signIn": "Anmelden",
  "public.search": "In diesem Katalog suchen...",
  "public.searchLabel": "In diesem Katalog suchen",
  "public.resultCount": "{count} Bücher",
  "public.resultCountOne": "1 Buch",
  "public.noResults": "Nichts gefunden",
  "public.noResultsHint":
    "Weniger Wörter oder eine andere Schreibweise versuchen.",
  "public.emptyHint": "In diesem Katalog steht noch nichts.",
  "public.loadMore": "Mehr anzeigen",
  "public.backToCatalogue": "Zurück zum Katalog",
  "public.closedTitle": "Hier ist nichts",
  "public.closedHint": "Diese Bibliothek veröffentlicht ihren Katalog nicht.",
  "public.classifications": "Klassifikation",
  "public.fact.isbn": "ISBN",
  "public.fact.publisher": "Verlag",
  "public.fact.year": "Jahr",
  "public.fact.language": "Sprache",
  "public.fact.pages": "Seiten",
  "public.fact.format": "Ausgabeform",
  "public.fact.series": "Reihe",

  // Die Anbieterliste. Katalognamen sind Eigennamen und bleiben unübersetzt.
  "providers.title": "Woher die Buchdaten kommen",
  "providers.hint":
    "Diese Kataloge fragt diese Bibliothek zu einem Buch. Wer ausgeschaltet ist, wird gar nicht gefragt. Die Reihenfolge ist die Reihenfolge der Anfragen; sie entscheidet nicht, welchem Katalog geglaubt wird, wenn zwei sich beim selben Feld widersprechen.",
  "providers.costHint":
    "Die Titelsuche fragt alle eingeschalteten Kataloge gleichzeitig, ein weiterer kostet also nichts, außer er ist der langsamste. Beim Scannen einer ISBN werden die oberen beiden zusammen gefragt und der Rest einzeln, bis einer antwortet.",
  "providers.moveUp": "{name} nach oben schieben",
  "providers.moveDown": "{name} nach unten schieben",
  "providers.moved": "{name} steht jetzt an Position {position} von {total}.",
  "providers.name.open_library": "Open Library",
  "providers.name.google_books": "Google Books",
  "providers.name.dnb": "Deutsche Nationalbibliothek",
  "providers.name.k10plus": "K10plus",
  "providers.name.oenb": "Österreichische Nationalbibliothek",
  "providers.name.nlg": "Griechische Nationalbibliothek",
  "providers.name.nkp": "Tschechische Nationalbibliothek",
  "providers.name.bnf": "Französische Nationalbibliothek",
  "providers.name.loc": "Library of Congress",
  "providers.status.needsKey":
    "Braucht einen API-Schlüssel. Unten einen hinterlegen, sonst kann dieser Katalog nichts beantworten.",
  "providers.status.switchedOffBelow":
    "Ein Schlüssel ist hinterlegt, dieser Katalog ist aber in seiner eigenen Karte weiter unten ausgeschaltet.",
  "providers.status.searchOnly":
    "Beantwortet nur Titelsuchen, die Position wirkt sich also nicht auf das Scannen aus.",
  "providers.status.lookupOnly":
    "Beantwortet nur Scans, die Position wirkt sich also nicht auf die Titelsuche aus.",
  "providers.status.askedFirst":
    "Wird bei jedem Scan gefragt, zusammen mit den anderen oben in dieser Liste.",
  "providers.status.askedAfter":
    "Wird nur gefragt, wenn die darüber nichts finden.",
  "providers.status.regional":
    "Wird nur gefragt, wenn die darüber nichts finden, und nur bei ISBNs, die mit {groups} beginnen.",
  "providers.status.lookupOnlyRegional":
    "Beantwortet nur Scans, und nur bei ISBNs, die mit {groups} beginnen, die Position wirkt sich also nicht auf die Titelsuche aus.",
  "providers.status.off": "Aus. Dieser Katalog wird nie gefragt.",
  "providers.slow":
    "Zu langsam für eine schnelle Suche. Wird nur gefragt, wenn jemand gründlicher sucht.",
  "providers.slowLegend":
    "Ein als langsam markierter Katalog kann eine Titelsuche nicht innerhalb der Frist beantworten, die die schnelle Suche zulässt. Er bleibt deshalb bei dieser außen vor und wird nur gefragt, wenn jemand danach verlangt. Einen Scan beantwortet er genauso wie die anderen.",
};
