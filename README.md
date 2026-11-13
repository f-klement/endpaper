# Endpaper

[![license](https://img.shields.io/github/license/f-klement/endpaper)](LICENSE)
[![release](https://img.shields.io/github/v/tag/f-klement/endpaper?label=release)](https://github.com/f-klement/endpaper/tags)
[![docker hub](https://img.shields.io/docker/v/fklement/endpaper?label=docker%20hub&logo=docker)](https://hub.docker.com/r/fklement/endpaper)
[![docker pulls](https://img.shields.io/docker/pulls/fklement/endpaper)](https://hub.docker.com/r/fklement/endpaper)
![languages](https://img.shields.io/badge/languages-DE%20%7C%20EN-blue)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-buy%20me%20a%20coffee-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/fklement)

A self-hosted catalogue for the books you share.

Built for a household's shelves and for the library or archive that has outgrown a
spreadsheet. Scan a barcode and get a real bibliographic record, or point it at a folder
of ebooks and let it draft the rows out of them, and know who has what across the people
and places that share it.

Like Endpaper or find it useful? Offer me a coffee. It helps pay for the public
server that lets two copies of Endpaper reach each other. All features are free
either way.

## Motivation

**A book that has been read once goes back on a shelf and stops being a book anybody reads.**
Most of a household's library is like that: finished, kept because it was good, and invisible
to everybody who might want it next. The people who would most enjoy a particular book are
usually the ones already in the same building, the same street or the same group of friends,
and none of them knows it is there.

Endpaper exists to make a shelf legible to the people around it. Catalogue what you own once,
and then the question "does anybody have a copy of this" has an answer, as does the more
interesting question of what is sitting on somebody else's shelf that you would never have
gone looking for. Lending is tracked because the practical obstacle to lending a book is not
generosity, it is forgetting who has it.

It is self hosted for the same reason. A record of what you read is not something to hand to
a company, a shelf is a private thing until its owner decides otherwise, and nothing here
needs an account with anybody. Books that are private stay private, and what you share is a
decision you make per book rather than a setting you forget.

## Quick Start

Run the published image. No build step, nothing to clone:

```bash
curl -O https://raw.githubusercontent.com/f-klement/endpaper/main/docker-compose.deploy.yml
# set SECRET_KEY to 32 or more random characters (openssl rand -hex 32): it signs the login tokens
mkdir -p data
docker compose -f docker-compose.deploy.yml up -d
```

Create `data` yourself before the first start: the container runs as uid 1000 and writes its
database there, and a directory Docker creates for the mount belongs to root.
[Install](docs/configuration.md#install) says what to do when your account is not uid 1000.

Then open port 8000 on that host in a browser. The first account you register becomes the
admin, so register it before anybody else can reach the port. The same address works on your
phone, but its camera, and so the barcode scanner, needs HTTPS:
[Before you expose it](docs/configuration.md#before-you-expose-it).

The file names the image [`fklement/endpaper`](https://hub.docker.com/r/fklement/endpaper)
by digest, so it stays on the release it names until you change its `image:` line, whatever
`:latest` does in the meantime. [Upgrading](docs/configuration.md#upgrading) says how to
move it. The image is built for `linux/amd64` only. What changed in each release is in
[CHANGELOG.md](CHANGELOG.md).

Building from source, the image tags, every environment variable and what to do before
other people can reach it are in [the configuration reference](docs/configuration.md).

## Features

- **Barcode scanning** with a phone camera, or type the ISBN.
- **Records from ten catalogues**, asked in an order you choose, with the cover stored here
  rather than linked from somebody else's server.
- **Bringing a library in** from Goodreads, LibraryThing, StoryGraph, Libib, Openreads,
  Calibre or MARC records, or from a folder of ebook files that are read in your browser and
  never uploaded.
- **Private or shared, decided per book.** A private book is invisible to everybody else, in
  listings, in search, in statistics and by guessing its address.
- **Reading status, ratings, notes, quotes and highlights**, each member's own.
- **Lending**: who has which copy and until when, with overdue reminders by email, Telegram
  or a signed webhook. A borrower needs no account.
- **More than one copy** of a title, each with its own shelf, condition and loan.
- **Finding things**: search and filters, a cover grid, a dense list or a table, author
  pages, series, collections, tags and custom fields.
- **Library mode and a public catalogue**, both off by default, with SRU for other
  libraries' software.
- **Sign in** with local accounts, against an LDAP directory, or behind an authenticating
  reverse proxy.
- **Backup and restore** of the whole library, covers included, from Settings.
- **Installable on a phone** as a progressive web app, with no app store involved.
- **German and English** throughout the interface.

**The complete list, including what Endpaper deliberately does not do, is
[`docs/featurelist.md`](docs/featurelist.md)**: no offline mode, no Apple build, no
circulation desk. Worth knowing before you install it rather than after.

## Documentation

| Document | For |
|---|---|
| [The handbook](docs/handbook.md) | Using it, task by task: first for members, then for admins |
| [The configuration reference](docs/configuration.md) | Installing and running it: every environment variable, the database, sign in, backups, upgrading, recovery |
| [The feature list](docs/featurelist.md) | Whether it does something, and what it deliberately does not do |
| [The glossary](GLOSSARY.md) | The words the app and these documents use |
| [The developer docs](docs/README.md) | Changing it: architecture, data model, API, security, testing |
| [The changelog](CHANGELOG.md) | What changed in each release |

## Local Development

Two processes: the API on `:8000` and the Vite dev server on `:5173`, which proxies
`/api`, `/auth` and `/covers` across to the API. Run them in separate terminals.

**Backend**, with [uv](https://docs.astral.sh/uv/) 0.9.17 or later (an older uv cannot read
`backend/uv.toml` and stops on every command) and Python 3.14:
```bash
cd backend
uv sync                       # creates .venv and installs from uv.lock
DATA_DIR=./data uv run uvicorn main:app --reload
```
`DATA_DIR` decides where the SQLite file and uploaded covers live. It defaults to
`/app/data` (the path inside the container), so set it when running outside one.
Interactive API docs are then at `http://localhost:8000/docs`.

**Frontend**, with [Bun](https://bun.com) 1.3:
```bash
cd frontend
bun install
bun run dev
```

`bun install` screens every incoming package through Bun's security scanner
(`frontend/bunfig.toml`) before any package code runs, and a critical finding stops the
install.

**Testing.** Both suites refuse to start unless `ENDPAPER_SUITE_SANCTIONED` is `1`, and
neither touches the network. [`docs/testing.md`](docs/testing.md#running) says why, how to
run them and their variants, and how the mirrored test tree is laid out.

## Architecture

One Docker container: FastAPI (Python 3.14) serves the REST API and the compiled React 19
PWA as static files. Storage is SQLite by default, or Postgres. The multi-stage build
compiles the frontend with Bun, then copies only the built assets into the Python image, so
Bun and `node_modules` are not in the shipped image. [`docs/architecture.md`](docs/architecture.md)
describes the pieces, the catalogue lookup and the build, with diagrams.

## Contributing

Bug reports, questions and patches are all welcome. **For anything larger than a small fix,
open an issue first**, because the reasoning behind a surprising decision is usually written
down somewhere and it is cheaper to read it than to rediscover it.

Set up a local checkout with *Local Development* above, and run the suites and the linters
[`docs/testing.md`](docs/testing.md) lists before proposing a change. Both suites run
offline, so neither needs credentials or a network.

A few conventions are load bearing, and a change that ignores them will be sent back:

- **Tests mirror the source tree and are never beside the file they test.** `backend/tests/`
  mirrors `backend/`, and `frontend/tests/` mirrors `frontend/src/`.
- **Every query that returns or counts books goes through `backend/shelf.py`.** Visibility is
  applied by construction there. Omitting it is how private books leak with a 200 and no
  error, which is the one defect class this codebase guards hardest.
- **Write tersely, and explain why rather than what.** A comment that guards a trap says what
  breaks if it is removed. Prose that merely restates the code is deleted.
- **No dashes as punctuation.** Use a colon, a comma or a full stop. This is enforced by a
  test, so a dash will fail the suite rather than a review.

**Read [`docs/decisions.md`](docs/decisions.md) before changing something that looks wrong.**
It records what was already tried and why the current shape was chosen, and a good proportion
of the odd looking things in this repository are odd on purpose.

## License

MIT. The full text is in [`LICENSE`](LICENSE).
