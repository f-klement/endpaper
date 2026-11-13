# Documentation

Every document here, by what you came to do. What Endpaper is and how to start it is the
top level [README](../README.md).

## Use it

| Document | What it covers |
|---|---|
| [handbook.md](handbook.md) | How to use Endpaper, task by task: first for members, then for admins |
| [featurelist.md](featurelist.md) | What the app does today, and what it deliberately does not |
| [../GLOSSARY.md](../GLOSSARY.md) | The words the app and these documents use: member, book, copy, loan, private book and the rest |
| [legend.md](legend.md) | The library science vocabulary this codebase borrows: the catalogues, MARC, the classification and authority schemes, and the codes inside a record |

## Run it

| Document | What it covers |
|---|---|
| [configuration.md](configuration.md) | Installing and running it: every environment variable, the database, sign in, backups, upgrading and recovery |
| [security.md](security.md) | The authorization model, rate limiting, uploads, headers, and the known limits |

## Change it

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | How the pieces fit, from the request path down to every backend module, with diagrams. Start here |
| [data-model.md](data-model.md) | The tables, the relationships, and the privacy rule that every query must honour |
| [api.md](api.md) | Every endpoint, its auth requirement, and the status codes it returns |
| [frontend.md](frontend.md) | Component and page layout, state handling, the typed API client |
| [theming.md](theming.md) | The ten palettes and the rule that generated them, the sixteen wallpapers and the rule that admits them, the picker, and where an appearance is stored |
| [testing.md](testing.md) | Running the suites, how the mirrored test tree works, and the conventions to follow when adding tests |
| [device-libraries.md](device-libraries.md) | Reading a catalogue off a device the member owns: what the SQLite engine costs, and the rule that an unreadable store is one skipped source |
| [cloud-exports.md](cloud-exports.md) | Reading a library out of a service's own export: which seam an export belongs to, and why a name inside a member's file is not evidence |
| [../conformance/README.md](../conformance/README.md) | The shared fixture set: rules that must give the same answer in Python and in TypeScript, and how to add a case |
| [decisions.md](decisions.md) | Choices that look odd until you know why. Read before "fixing" one |
| [decisions-index.md](decisions-index.md) | Every entry of the register, with the section it sits under and how long it is. Generated from its headings, and a grep target rather than a page to read |
