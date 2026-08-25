# Endpaper context

Endpaper is a household library for cataloguing books and keeping reading information. It
distinguishes a book object from each member's relationship with it.

## Household library

**Household**:
The group that shares one Library and its shared choices.
_Avoid_: Tenant, organisation

**Library**:
The Household's catalogue of Books, Tags, Collections and Loans.
_Avoid_: Personal shelf, global catalogue

**Member**:
A person who belongs to the Household and may have personal reading information.
_Avoid_: Reader, account

**Book**:
One object recorded in the Library. It is not a title or a work.
_Avoid_: Title, work

**Copy**:
Another Book object deliberately recorded as the same edition or printing.
_Avoid_: Duplicate

**Collection**:
A named, Household wide part of the Library that a Book may belong to.
_Avoid_: Private shelf

**Loan**:
A Book from the Household Library that is with a named borrower.
_Avoid_: Borrowed in book

## Reading and privacy

**Reading record**:
A Member's status, rating, dates, progress and discussion offer for one Book.
_Avoid_: Book status, shared reading history

**Ownership**:
Whether a Book object is physically on the shelf, not whether a Member has read it.
_Avoid_: Read status

**Private Book**:
A Book whose content is visible only to the Member who added it.
_Avoid_: Private Collection

## Catalogue language

**Catalogue record**:
Outside evidence about a title or edition that may supply a Book's bibliographic facts, but is
not Household authored knowledge.
_Avoid_: Canonical book

**Tag**:
A word the Household curates to describe or group Books.
_Avoid_: Category, classification

**Category**:
An uncontrolled subject label supplied by a publisher or catalogue.
_Avoid_: Tag

**Classification**:
An assertion from a published scheme about what a Book is about.
_Avoid_: Tag, category
