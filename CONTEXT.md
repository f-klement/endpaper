# Endpaper context

Endpaper is a catalogue for books that more than one person shares. It distinguishes a book
object from each member's relationship with it.

**One deployment holds one Library.** There is no multi tenancy, so the group that runs a
Library rarely needs naming in code: name the **Library** or its **Members** instead. Where the
operator does need naming, there are two kinds and they are not interchangeable in tone or in
obligation.

## Who runs a Library

**Household**:
A Library shared by a family or a home.
_Avoid_: Tenant, organisation

**Institution**:
A Library run by a library or an archive, whose readers are mostly not Members.
_Avoid_: Tenant, organisation, customer, client

**Library mode**:
The default off setting that turns a Library from a Household's into an Institution's: a public
catalogue, a cataloguer's columns, Patrons and a circulation desk.
_Avoid_: Public mode, archive mode

Both are the same product, decided 2026-08-26. See `docs/adr/0007-one-library-two-operators.md`.
**A rule that holds for a Household holds for an Institution unless this glossary says
otherwise**, and the one that never bends is the Private Book.

## The Library

**Library**:
The catalogue of Books, Tags, Collections and Loans that its Members share.
_Avoid_: Personal shelf, global catalogue

**Member**:
A person who belongs to this Library and may have personal reading information.
_Avoid_: Reader, account, user

**Patron**:
A person who borrows from an Institution's Library but is not a Member and has no account.
Their record is the most sensitive data this application stores.
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
A Book whose content is visible only to the Member who added it. **Private Books stay private
in every mode**, and a public catalogue never exposes one.
_Avoid_: Private Collection

## Catalogue language

**Catalogue record**:
Outside evidence about a title or edition that may supply a Book's bibliographic facts, but is
not knowledge this Library authored.
_Avoid_: Canonical book

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
the host keyboard layout decides, and only digits survive every layout.
_Avoid_: Barcode, copy id
