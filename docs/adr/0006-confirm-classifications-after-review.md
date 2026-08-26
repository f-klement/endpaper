# Confirm Classifications after Catalogue record review

**Decision:** a Catalogue record remains external evidence under ADR 0004 until a Member
reviews and selects it for an existing Book. The picker displays its Classifications, including
an explicit empty state, and a row selection confirms the whole record. Automatic enrichment
and Refresh Metadata change scalar Book facts only. They do not add, complete or report a
Classification. Individual Classifications have no separate acceptance action.

`POST /{book_id}/enrich/apply` is the sole existing Book writer for fresh Catalogue record
Classifications. No Catalogue record table, source provenance, visibility, cover, wire, backup
or migration change is needed, which keeps external evidence distinct from Household authored
knowledge.

**Status:** implemented on 2026-08-25.
