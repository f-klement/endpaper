# One Library, two kinds of operator

Decided 2026-08-26. Refines ADR 0001, which says a Household shares one catalogue and stays
true structurally: one deployment still holds one Library, and Members still share its public
Book content, Tags, Collections and Loans.

What 0001 left implicit is that the operator is always a family. It is not. A library or an
archive runs the same Library, with the same data model, and turns on Library mode to get a
public catalogue, a cataloguer's columns, Patrons and a circulation desk. **They are one
product covering two use cases, not one product with a second audience tolerated at the
edges.** The rejected alternative was to serve Households and let Institutions use it if they
happened to fit, which sounds cautious and leaves every institutional feature permanently half
specified behind a mode nobody commits to finishing.

Three consequences bind on the model rather than on the marketing. A **Patron** is a third kind
of borrower beside a Member and a typed name, so the loan constraint becomes exactly one of
three, and that record carries obligations no other table here does. **Private Books stay
private in every mode**, and this decision does not license a public catalogue to relax it.
Naming follows the Library and its Members rather than the operator wherever it can, because
the operator kind is a fact about who deployed it and almost never a fact the code needs.
