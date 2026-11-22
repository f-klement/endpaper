# Accession number conformance cases

`cases/accession.json`, against `schema/accession.schema.json`, run by
`backend/tests/conformance/test_accession.py` and
`frontend/tests/conformance/accession.test.ts`.

[`README.md`](README.md) holds the directory's argument and the rules every domain
obeys. This file holds what is the accession number's alone. Why the code has the
shape it has is in `backend/accession.py`.

## What a case is

The ISBN shape: one operation, one input, one literal answer, and a `why`. `mint`
takes a row id, the two others a string.

| field | what |
|---|---|
| `id` | Lowercase and hyphens, unique in the file. It is what a failure is named after. |
| `op` | `mint`, `is-accession` or `classify`. Each runner maps it onto its own naming in an explicit table. |
| `input` | A row id for `mint`, a string otherwise. |
| `expect` | What every implementation must answer. |
| `why` | Why the case is here. A measurement or a rule, never an opinion. |

## The symbologies, and the guard between printing and reading

**The file also names every symbology a label may carry**, `symbologies` at its top.
The server will print a label and the browser's camera will read it, and the two are
decided in different places. A label in a symbology the camera does not read never
decodes, which looks like a lighting problem rather than an error (ticket 26). So each
side declares its half, held to this list:

| side | constant | runner |
|---|---|---|
| what a label printer must print from | `accession.LABEL_SYMBOLOGIES` | `test_accession.py` |
| what a label reader must read | `ACCESSION_FORMATS` in `BarcodeScanner.tsx` | `accession.test.ts` |

**Neither constant is read yet**: no printer prints from the first and no camera hint
takes the second. Until the printer and the label reader both do, this guard holds two
declarations to one list, not a printer to a camera.

A label may print either, by label stock (owner, 2026-11-22), so the camera reads both.

## What each case pins

Dropping each guard in turn, derived from the two implementations as written:

| guard dropped | cases that catch it |
|---|---|
| the check digit test | `is-accession-refuses-a-single-digit-error`, `is-accession-refuses-an-adjacent-transposition`, `classify-refuses-a-mistyped-code` |
| the lead digit | `is-accession-refuses-another-lead-digit` |
| the exact length | `is-accession-refuses-eight-digits`, `is-accession-refuses-ten-digits` |
| server ASCII digits | `is-accession-refuses-arabic-indic-digits` |
| the strip before classifying | `classify-strips-a-wedges-newline`, `classify-strips-a-group-separator` |
| the pinned strip set, for either language's default | `classify-keeps-a-no-break-space`, and for `trim()` also `classify-strips-a-group-separator` and `classify-keeps-a-byte-order-mark` |
| the zero padding of the serial | `mint-the-first-row`, `mint-pads-the-row-id`, `mint-a-six-digit-id` |
