# Endpaper

Catalogue, lend and track a household's collection of **physical** books. Scan a barcode,
the book appears with its cover and metadata. Self-hosted, no account anywhere else, no
telemetry.

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
| `ALLOW_REGISTRATION` | `true` | Set `false` once your household has signed up, or anyone reaching the port can create an account |
| `AUTH_MODE` | `local` | `local`, `ldap`, or `proxy`. See below |
| `GOOGLE_BOOKS_API_KEY` | none | Optional. Metadata works without it: the German National Library, K10plus and Open Library are queried first and need no key |
| `APP_ENV` | `prod` | `dev` relaxes the startup secret check and nothing else |
| `CORS_ORIGINS` | none | Only needed if you serve the client from a different origin, which this image does not |
| `SERVE_FRONTEND` | `true` | Set `false` to run the API alone. The image still contains the compiled frontend; it is simply not mounted, and every path outside the API answers 404 |

### Overdue reminders

| Variable | Default | Notes |
|---|---|---|
| `ENABLE_OVERDUE_TICKER` | `true` | The hourly digest runs in-process. **Set it `false` if you run more than one web process**, and drive `POST /api/loans/overdue/notify` from cron instead: the ticker assumes exactly one process, which the shipped image guarantees and a scaled deployment does not. |

Where the digest is posted, how often a loan is chased, and whether the feature is
on at all are settings in the app rather than environment variables.

### Authentication

`AUTH_MODE=local` is the default: accounts and passwords in this database.

`AUTH_MODE=ldap` checks credentials against a directory and creates no local passwords.
Needs `LDAP_URL`, `LDAP_USER_BASE_DN`, and usually `LDAP_BIND_DN` with
`LDAP_BIND_PASSWORD`. `LDAP_ADMIN_GROUP` grants admin; `LDAP_USER_FILTER`,
`LDAP_USERNAME_ATTRIBUTE` and `LDAP_START_TLS` tune the rest.

`AUTH_MODE=proxy` trusts an identity header set by a forward-auth portal (Authelia,
oauth2-proxy). Needs `PROXY_USER_HEADER` (default `Remote-User`);
`PROXY_GROUPS_HEADER` and `PROXY_ADMIN_GROUP` grant admin.

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

## Supporting it

* **Ko-fi**, for a one off: `https://ko-fi.com/REPLACE_ME`
* **Patreon**, for something monthly: `https://patreon.com/REPLACE_ME`

The money pays for one thing: running the shared relay that lets two households reach each
other when neither is reachable from the internet. It is not a paid tier and no feature
sits behind it. This image is the complete app, a relay is optional, and nothing in it
asks a reader for money.

## Licence

Apache-2.0. Source at
[github.com/f-klement/endpaper](https://github.com/f-klement/endpaper).
