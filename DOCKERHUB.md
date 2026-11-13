# Endpaper

[![license](https://img.shields.io/github/license/f-klement/endpaper)](https://github.com/f-klement/endpaper/blob/main/LICENSE)
[![release](https://img.shields.io/github/v/tag/f-klement/endpaper?label=release)](https://github.com/f-klement/endpaper/tags)
[![docker hub](https://img.shields.io/docker/v/fklement/endpaper?label=docker%20hub&logo=docker)](https://hub.docker.com/r/fklement/endpaper)
[![docker pulls](https://img.shields.io/docker/pulls/fklement/endpaper)](https://hub.docker.com/r/fklement/endpaper)
![languages](https://img.shields.io/badge/languages-DE%20%7C%20EN-blue)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-buy%20me%20a%20coffee-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/fklement)

Like Endpaper or find it useful? Offer me a coffee. It helps pay for the public
server that lets two copies of Endpaper reach each other. All features are free
either way.

Catalogue, lend and track a collection of books, on the shelf and in files, shared by
the people who use it. Scan a barcode and the book appears with its cover and metadata,
or point it at a folder of ebooks and it drafts the rows out of the files themselves.
Built for a household's shelves and for the library or archive that has outgrown a
spreadsheet. Self-hosted, no account anywhere else, no telemetry.

One container. It serves the API and the compiled web client together, so there is no
second web server and no CORS to configure. Storage is a SQLite file by default, or
Postgres, plus a directory of cover images.

**Source, issues and the full feature list:**
[github.com/f-klement/endpaper](https://github.com/f-klement/endpaper). This page
covers running it; what it actually does, and what it deliberately does not do, is
in [`docs/featurelist.md`](https://github.com/f-klement/endpaper/blob/main/docs/featurelist.md),
and how to use it is in [the handbook](https://github.com/f-klement/endpaper/blob/main/docs/handbook.md).

## Run it

```bash
docker run -d --name endpaper \
  -p 8000:8000 \
  -v endpaper-data:/app/data \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  fklement/endpaper:latest
```

Open `http://localhost:8000`. **The first account created becomes the admin**, so create it
before anybody else can reach the port.

## Compose

```yaml
services:
  endpaper:
    image: fklement/endpaper:latest
    ports: ["8000:8000"]
    volumes: ["endpaper-data:/app/data"]
    environment:
      SECRET_KEY: "change-me-to-32-random-bytes"
    restart: unless-stopped
volumes:
  endpaper-data:
```

## Configuration

The five you are most likely to set. Every other variable, and what each one does, is in
[the configuration reference](https://github.com/f-klement/endpaper/blob/main/docs/configuration.md#environment-variables).

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | a development placeholder | **Signs session tokens. Set it** to at least 32 random bytes. Outside `APP_ENV=dev` the container refuses to start with the placeholder or a shorter key, because either makes every session forgeable |
| `DATA_DIR` | `/app/data` | The SQLite file, the cover images and the catalogue key file. The only path worth persisting |
| `ALLOW_REGISTRATION` | `true` | Set `false` once your library has signed up, or anyone reaching the port can create an account |
| `AUTH_MODE` | `local` | `local`, `ldap` or `proxy`: [sign-in modes](https://github.com/f-klement/endpaper/blob/main/docs/configuration.md#sign-in-modes) |
| `DATABASE_URL` | `sqlite:///$DATA_DIR/library.db` | SQLite by default. Postgres is the one other engine, spelled `postgresql+pg8000://`, and the driver is in the image: [the database](https://github.com/f-klement/endpaper/blob/main/docs/configuration.md#the-database) |

**In proxy mode the port must not be reachable except through the proxy.** Anything that
can set the identity header is whoever it says it is.

**Setting `LDAP_EMAIL_ATTRIBUTE` or `PROXY_EMAIL_HEADER` clears the stored address of every
member the directory has none for**, at their next sign in, and nobody can type it back.
Populate the directory first.

Overdue reminders by email or Telegram, catalogue logins, TLS to Postgres and running behind
a reverse proxy each have a section in [the configuration reference](https://github.com/f-klement/endpaper/blob/main/docs/configuration.md).

## Backups

Settings has a one-click backup: the whole library, every account and every cover in one
zip, and a restore that takes it back. A restore signs everybody out, deliberately.

The zip is the supported route. Copying `library.db` out from under a running container
is not consistent unless you stop it first. [Data and backups](https://github.com/f-klement/endpaper/blob/main/docs/configuration.md#data-and-backups) has the
rest.

## Upgrading

Take a backup, then pull and recreate:

```bash
docker compose pull && docker compose up -d
```

Schema migrations run at startup and are logged. Name `:vX.Y.Z` rather than `:latest` if
you would rather choose when that happens. An image named by digest does not move on a
pull at all: [Upgrading](https://github.com/f-klement/endpaper/blob/main/docs/configuration.md#upgrading).

## Health

`GET /api/healthz` answers 200 when the process can reach its storage, and 503 when it
cannot. It performs a real filesystem operation rather than a cached read, so a volume
that has gone away or hung is reported rather than passed over. Unauthenticated, and it
discloses nothing but liveness.

## Tags

| Tag | What it is |
|---|---|
| `:latest` | the newest release, moving with each one |
| `:vX.Y.Z` | one release |

Images are built for `linux/amd64` only.

## Notes

* **Privacy is per book.** A book marked private is visible only to the member who added
  it, in every listing, search, export and statistic.
* **Book files never reach the server.** An ebook is read in the browser to draft its
  record, and only the record is sent: no route accepts a book file.
