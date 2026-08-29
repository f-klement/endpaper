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

Catalogue, lend and track a collection of **physical** books, shared by the people who use
it. Scan a barcode, the book appears with its cover and metadata. Built for a household's
shelves and for the library or archive that has outgrown a spreadsheet. Self-hosted, no
account anywhere else, no telemetry.

One container. It serves the API and the compiled web client together, so there is no
second web server and no CORS to configure. Storage is a single SQLite file plus a
directory of cover images.

**Source, issues and the full feature list:**
[github.com/f-klement/endpaper](https://github.com/f-klement/endpaper). This page
covers running it; what it actually does, and what it deliberately does not do, is
in [`docs/featurelist.md`](https://github.com/f-klement/endpaper/blob/main/docs/featurelist.md).

## Run it

```bash
docker run -d --name endpaper \
  -p 8000:8000 \
  -v endpaper-data:/app/data \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  fklement/endpaper:latest
```

Open `http://localhost:8000`. **The first account created becomes the admin.**

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

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | none | **Signs session tokens. Set it.** The container refuses to start in production without one, because the example value makes every session forgeable |
| `DATA_DIR` | `/app/data` | The SQLite file and the cover images. This is the only path worth persisting |
| `DATABASE_URL` | `sqlite:///$DATA_DIR/library.db` | Point elsewhere if you must; SQLite is what it is tested against |
| `ALLOW_REGISTRATION` | `true` | Set `false` once your library has signed up, or anyone reaching the port can create an account |
| `AUTH_MODE` | `local` | `local`, `ldap`, or `proxy`. See below |
| `GOOGLE_BOOKS_API_KEY` | none | Optional. Metadata works without it: the German National Library, K10plus and Open Library are queried first and need no key |
| `APP_ENV` | `prod` | `dev` relaxes the startup secret check and nothing else |
| `CORS_ORIGINS` | none | Only needed if you serve the client from a different origin, which this image does not |
| `SERVE_FRONTEND` | `true` | Set `false` to run the API alone. The image still contains the compiled frontend; it is simply not mounted, and every path outside the API answers 404 |

### Overdue reminders

| Variable | Default | Notes |
|---|---|---|
| `ENABLE_OVERDUE_TICKER` | `true` | The hourly digest runs in-process. **Set it `false` if you run more than one web process**, and drive `POST /api/loans/overdue/notify` from cron instead: the ticker assumes exactly one process, which the shipped image guarantees and a scaled deployment does not. |

Where the digest is posted, how often a loan is chased, and whether each channel is on at
all are settings in the app rather than environment variables. The digest goes out on every
channel switched on: a webhook, email over SMTP, and a Telegram chat.

The mail and Telegram **credentials** may come from the environment instead, which is what
a secret manager or a compose file is for. Where one is set it wins over anything stored,
the field in Settings is greyed out, and the app refuses to overwrite it.

| Variable | Default | Notes |
|---|---|---|
| `MAIL_SERVER` | none | SMTP host |
| `MAIL_PORT` | `587` | |
| `MAIL_USERNAME` | none | Leave empty for a relay that needs no login |
| `MAIL_PASSWORD` | none | Refused unless STARTTLS or TLS is on: it would otherwise cross the network in the clear |
| `MAIL_USE_TLS` | `true` | STARTTLS on a plain connection |
| `MAIL_USE_SSL` | `false` | Implicit TLS. Setting both is refused: they are two protocols |
| `MAIL_DEFAULT_SENDER` | none | The `From` address |
| `TELEGRAM_BOT_TOKEN` | none | From @BotFather |
| `TELEGRAM_CHAT_ID` | none | The group the bot was added to, or an `@name` |

`MAIL_DEBUG` is **not** honoured, though it is the eighth of the standard `MAIL_*` names.
Python's smtplib writes the AUTH exchange to stderr under it, so supporting it would be a
supported way of printing your mail password into the container log.

Certificates and host names are always verified, and nothing here can switch that off. The
recipient list lives in Settings rather than the environment, because it is the household's
to change.

### Authentication

`AUTH_MODE=local` is the default: accounts and passwords in this database.

`AUTH_MODE=ldap` checks credentials against a directory and creates no local passwords.
Needs `LDAP_URL`, `LDAP_USER_BASE_DN`, and usually `LDAP_BIND_DN` with
`LDAP_BIND_PASSWORD`. `LDAP_ADMIN_GROUP` grants admin; `LDAP_USER_FILTER`,
`LDAP_USERNAME_ATTRIBUTE` and `LDAP_START_TLS` tune the rest.
`LDAP_EMAIL_ATTRIBUTE` (usually `mail`) hands the directory ownership of each
member's address; leave it empty and members set their own in the app. Turning it
on **clears the address of every member the directory has none for**, at their
next sign in, and the field is read only from then on: populate the attribute
before setting this.

`AUTH_MODE=proxy` trusts an identity header set by a forward-auth portal (Authelia,
oauth2-proxy). Needs `PROXY_USER_HEADER` (default `Remote-User`);
`PROXY_GROUPS_HEADER` and `PROXY_ADMIN_GROUP` grant admin, and
`PROXY_EMAIL_HEADER` (`Remote-Email` for Authelia) asserts the address, with the
same clearing as `LDAP_EMAIL_ATTRIBUTE`.

**In proxy mode the port must not be reachable except through the portal.** Anything
that can set that header is whoever it says it is.

## Backups

Settings has a one-click backup: the whole library and every cover in one zip, and a
restore that takes it back. A restore ends every session issued before it, deliberately.

The zip is the supported route. Copying `library.db` out from under a running container
is not consistent unless you stop it first.

## Upgrading

Pull and recreate. Schema migrations run at startup and are logged; an archive taken
before an upgrade still restores afterwards.

```bash
docker pull fklement/endpaper:latest && docker compose up -d
```

Pin a version rather than tracking `latest` if you would rather choose when that happens.

## Health

`GET /api/healthz` answers 200 when the process can reach its storage, and 503 when it
cannot. It performs a real filesystem operation rather than a cached read, so a volume
that has gone away or hung is reported rather than passed over. Unauthenticated, and it
discloses nothing but liveness.

## Notes

* **Physical books.** There is no reader and no ebook library; it catalogues objects on
  shelves.
* **Privacy is per book.** A book marked private is visible only to the member who added
  it, in every listing, search, export and statistic.
* Images are published for `linux/amd64` and `linux/arm64`.
