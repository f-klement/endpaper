# Glossary

One meaning per word, used the same way in the code, the documentation and the interface. Each
entry names the word, says what it means here, and lists the words to avoid for it, because each
of those already means something else or means nothing precise.

A word defined here is capitalised in this file only. Everywhere else, in prose and in the
interface, it is written in lowercase: a book, a member, a loan.

## Who runs a Library

**One deployment holds one Library.** There is no multi tenancy, so the group that runs a
Library rarely needs naming: name the **Library** or its **Members** instead. Where the operator
does need naming, there are two kinds, and they differ in tone and in obligation. Both run the
same product. **A rule that holds for a Household holds for an Institution unless this glossary
says otherwise**, and the one that never bends is the Private Book.

**Household**:
A Library shared by a family or a home.
_Avoid_: Tenant, organisation

**Institution**:
A Library run by a library or an archive, whose readers are mostly not Members.
_Avoid_: Tenant, organisation, customer, client

**Library mode**:
The setting, off by default, that turns a Library from a Household's into an Institution's: a
cataloguer's columns, MARC exchange, and the choice to publish a public catalogue. It is not a
circulation desk.
_Avoid_: Public mode, archive mode

## The Library

**Library**:
The catalogue of Books, Tags, Collections and Loans that its Members share.
_Avoid_: Personal shelf, global catalogue

**Member**:
A person who belongs to this Library and may have personal reading information.
_Avoid_: Reader, account, user

**Patron**:
A person who borrows from an Institution's Library but is not a Member and has no account.
Their record is the most sensitive data this application stores. Endpaper keeps no Patron record:
a Loan to one names them as typed text.
_Avoid_: Customer, borrower as a noun for the record, Kunde

**Book**:
One object recorded in the Library. It is not a title or a work.
_Avoid_: Title, work

**Copy**:
Another Book object deliberately recorded as the same edition or printing.
_Avoid_: Duplicate

**Collection**:
A named, Library wide part of the Library that a Book may belong to.
_Avoid_: Private shelf

**Loan**:
A Book from the Library that is with a named borrower, who may be a Member, a Patron, or a
typed name.
_Avoid_: Borrowed in book

## Reading and privacy

**Reading record**:
A Member's status, rating, dates, progress and discussion offer for one Book.
_Avoid_: Book status, shared reading history

**Ownership**:
Whether a Book object is physically on the shelf, not whether a Member has read it.
_Avoid_: Read status

**Private Book**:
A Book visible in the app only to the Member who added it. **Private Books stay private in
every mode**, and a public catalogue never exposes one. Private in the app only: an admin's backup
carries every Private Book and the rest of every Member's private data
([what a backup holds](docs/handbook.md#backup-and-restore-in-the-app)).
_Avoid_: Private Collection

## Catalogue language

**Catalogue record**:
Outside evidence about a title or edition that may supply a Book's bibliographic facts, but is
not knowledge this Library authored. Typed as `catalogue.Record`, which is where every source
adapter normalises to and the only shape that crosses that seam.
_Avoid_: Canonical book

**Recognition**:
Answering which Book already in the Library a record, row or file describes, as one Member
sees it: one Book, none, several the tie rule will not choose between, only Books in their
trash, or a Book they cannot see. `backend/recognition.py` answers it for every import and
for an add.
_Avoid_: Matching, deduplication

**Tag**:
A word this Library curates to describe or group Books. Shared by every Member, which is what
distinguishes it from the two below: a Tag is chosen here, they are supplied from outside.
_Avoid_: Category, classification

**Category**:
An uncontrolled subject label supplied by a publisher or catalogue.
_Avoid_: Tag

**Classification**:
An assertion from a published scheme about what a Book is about.
_Avoid_: Tag, category

**Call number**:
Where a Book sits on a shelf, derived from a Classification so it can be sorted and matched.
Not the same as a location, which is prose about a shelf.
_Avoid_: Location, shelfmark as a synonym for location

**Accession number**:
An Institution's own identifier for one Copy, distinct from an ISBN, which names a title.
Digits only and fixed length, because a barcode scanner in keyboard mode emits characters that
the host keyboard layout decides, and only digits survive every layout. Endpaper does not assign
one.
_Avoid_: Barcode, copy id

## A Member's files

**File reference**:
One client's account of where one of a Book's files is: a Root, a path beneath it, and a
fingerprint of size, modification time and KOReader's partial MD5. Never the file, and
nothing in it was verified by the server. A location belongs to one Book among those a Member
can see: a new location another Book the Member can see already holds is refused, and one held
only by a Book they cannot see is accepted, so the refusal discloses nothing.
_Avoid_: Digital copy, attachment, file

**Root**:
The name of the folder a path is written under, as the browser gave it. Only a name, so two
Members' Roots can share it and a path beneath it while naming different files.
_Avoid_: Library folder, mount point

**Sighting**:
One look at a known location that found the file, whether reported alone, by a re-picked
folder's sweep, or carried by a merge. It fills in what the File reference is missing, never
replaces a different fingerprint, and never lowers whether the Root was corroborated.
_Avoid_: Scan, refresh, re-import
