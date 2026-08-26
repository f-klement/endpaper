# A household shares one catalogue

Endpaper models a Household as the owner of one Library. Members share its public Book
content, Tags, Collections and Loans, while private Book content and personal reading
information follow one Member. Separate catalogues per Member would prevent the shared shelf,
and a global catalogue would lose Household autonomy.

Refined by [ADR 0007](0007-one-library-two-operators.md), which records that the operator may be a Household or an Institution. The structure here is unchanged: one deployment, one Library, Members sharing it.
