# Confirm Classifications after Catalogue record review

**Decision:** the planned typed Catalogue record remains external evidence under ADR 0004
until a Member reviews and selects it for a Book. The planned picker will display its
Classifications, and a row selection will confirm the whole record. Automatic enrichment and
Refresh Metadata will change scalar Book facts only; they will not add or complete any
Classification, and individual Classifications will have no separate acceptance action. No
Catalogue record table, source provenance, visibility, cover, wire, backup or migration change
is needed, which keeps external evidence distinct from Household authored knowledge.

This decision is not implemented. Current enrichment and Refresh Metadata behaviour remains
unchanged until the planned work lands.
