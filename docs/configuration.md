# Configuration

How to install, configure and run Endpaper. This page is for lookup: find the section you
need in the contents and read that one. How to use the app is in the
[handbook](handbook.md); what it does is in the [feature list](featurelist.md).

Endpaper reads its configuration from environment variables at startup. Most of what an
admin changes day to day is a setting in the app instead, under Settings, and takes effect
without a restart. A few of those settings can also be pinned from the environment, which
[Where a credential lives](#where-a-credential-lives) explains.

## Contents

- [Install](#install)
- [Before you expose it](#before-you-expose-it)
- [Environment variables](#environment-variables)
- [The database](#the-database)
- [Sign-in modes](#sign-in-modes)
- [Reminders](#reminders)
- [Where a credential lives](#where-a-credential-lives)
- [Catalogue logins](#catalogue-logins)
- [Google Books and Goodreads](#google-books-and-goodreads)
- [Behind a reverse proxy](#behind-a-reverse-proxy)
- [Data and backups](#data-and-backups)
- [Upgrading](#upgrading)
- [Recovering the only admin](#recovering-the-only-admin)

## Install

Endpaper is one container. It serves the API and the compiled web client from the same
origin, so there is no second web server to run and no CORS to configure. The image is on
Docker Hub as [`fklement/endpaper`](https://hub.docker.com/r/fklement/endpaper) and is
built for `linux/amd64` only.

| Tag | What it is |
|---|---|
| `:latest` | the newest release, moving with each one |
| `:vX.Y.Z` | one release |

The quickest route is the compose file in the repository root, `docker-compose.deploy.yml`.
Set `SECRET_KEY` in it, then `docker compose -f docker-compose.deploy.yml up -d`.

**That file pins one release by its digest**, the `@sha256:` part of its `image:` line.
With a digest present Docker runs exactly that image and ignores the tag, so your copy of
the file stays on the image it named when you downloaded it, `:latest` or not, until you
change the line: [Upgrading](#upgrading).

**The container runs as uid 1000**, so the host directory mounted at `/app/data` has to be
writable by uid 1000. Create it yourself before the first start, `mkdir -p data`, since a
directory Docker creates for the mount belongs to root. That is enough when your account is
uid 1000, as the first account on most Linux desktops is; otherwise follow it with
`sudo chown 1000:1000 data`.

**To build the image from source** instead, clone the repository and run
`docker compose up --build` in its root. That uses `docker-compose.yml`, which builds the
`Dockerfile` beside it. Its `SECRET_KEY` is a placeholder that startup refuses, so set it
first, as above, or add `APP_ENV=dev` on a machine nobody else reaches.

The app listens on port 8000 inside the container; the compose files map it to 8000 on the
host, and the left side of that mapping is yours to change. Open the host's address and
that port in a browser. **The first account in an empty library becomes the admin**:
under `AUTH_MODE=local` the first one registered, and under `ldap` or `proxy` the first
identity to sign in. Under `local` no route grants admin afterwards; under the other two,
the admin group grants it and, once set, takes it from an account outside the group, the
first one included ([Sign-in modes](#sign-in-modes)).

## Before you expose it

Before anybody other than you can reach the port:

1. **Set `SECRET_KEY`** to a random value of at least 32 bytes, for instance the output of
   `openssl rand -hex 32`. It signs every session token. Outside `APP_ENV=dev` the app
   refuses to start with one of the shipped placeholders or with a shorter key, because
   either would make every token forgeable. Changing the key later signs everybody out.
2. **Sign in first yourself.** The first account in an empty library is made the admin
   under every mode. Under `local` that is the first registration, which is open by
   default. Under `ldap` it is the first directory member to sign in, and under `proxy` the
   first identity the proxy names, on its first request. With no admin group set, that
   account stays the admin. With one set, it loses admin unless it is in the group: at its
   next sign in under `ldap`, and on its next request under `proxy`. Whoever reaches a
   fresh install first is made the admin, so sign in first, as a member of the group if you set
   one.
3. **Close or gate registration** once your members have accounts:
   `ALLOW_REGISTRATION=false` refuses every new signup and leaves existing accounts alone.
   To keep signups open to people you do not know, have each new account confirm its
   address instead; the [handbook](handbook.md#the-first-admin-and-accounts) describes that
   setting. Under `AUTH_MODE=ldap` or `proxy` there is no signup at all.
4. **Serve it over HTTPS.** A phone's browser opens the camera, and so the barcode scanner,
   only on a secure origin. Put it behind a reverse proxy that terminates TLS:
   [Behind a reverse proxy](#behind-a-reverse-proxy).
5. **Write down the catalogue key's recovery phrase** if you make one:
   [Catalogue logins](#catalogue-logins).

## Environment variables

Every variable Endpaper reads, by section. A variable you leave unset takes the default
shown. `.env.example` in the repository root is a commented sample file to start from.

### Core

| Variable | Default | What it does |
|---|---|---|
| `SECRET_KEY` | a development placeholder | Signs the session tokens. **Set it**: [Before you expose it](#before-you-expose-it) |
| `APP_ENV` | production | `dev` relaxes the startup check on `SECRET_KEY` and nothing else. Any other value, a misspelling included, means production |
| `DATA_DIR` | `/app/data` in the container, `./data` outside one | Where the SQLite file, the cover images and the catalogue key file live. The one path worth persisting |
| `ALLOW_REGISTRATION` | `true` | `false` refuses new signups. Read on every request, so it takes effect without a restart |
| `SERVE_FRONTEND` | `true` | `false` runs the API without the web client, for a host nobody browses. Every path outside the API then answers a plain 404, because there are no client routes to serve the page for |
| `CORS_ORIGINS` | empty | A comma separated list of browser origins allowed to make signed in calls. Needed only when the web client is served from a different origin than the API, which the image never does |
| `ENABLE_OVERDUE_TICKER` | `true` | `false` stops the hourly overdue digest: [Reminders](#reminders) |
| `ENABLE_READWISE_TICKER` | `true` | `false` stops the daily Readwise pull. Members can still pull from their account page. A pull needs outbound HTTPS to `readwise.io` |

### Database

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `sqlite:///$DATA_DIR/library.db` | The SQLAlchemy URL. SQLite or Postgres: [The database](#the-database) |
| `DATABASE_SSL_MODE` | empty | How strictly to insist on TLS to a Postgres server: [TLS to Postgres](#tls-to-postgres) |
| `DATABASE_SSL_ROOT_CERT` | empty | The CA bundle `verify-ca` and `verify-full` check against: [TLS to Postgres](#tls-to-postgres) |
| `SQLITE_SYNCHRONOUS` | `FULL` | SQLite's `synchronous` setting. Leave it: `FULL` is what makes a commit survive a power cut, and a lower value can lose the last writes. `OFF`, `NORMAL` and `EXTRA` are taken; anything else means `FULL`. Ignored on Postgres |

### Sign in

| Variable | Default | What it does |
|---|---|---|
| `AUTH_MODE` | `local` | `local`, `ldap` or `proxy`: [Sign-in modes](#sign-in-modes). Any other value stops startup |

The `LDAP_*` and `PROXY_*` variables are in [Sign-in modes](#sign-in-modes), the `MAIL_*`
and `TELEGRAM_*` ones in [Reminders](#reminders), and the catalogue key and logins in
[Catalogue logins](#catalogue-logins).

### Catalogue lookups

| Variable | Default | What it does |
|---|---|---|
| `GOOGLE_BOOKS_API_KEY` | empty | Pins the Google Books key from the deployment rather than the settings screen: [Google Books and Goodreads](#google-books-and-goodreads) |

## The database

**SQLite is the primary target.** It is the default, needs no server, and is what the
whole test suite runs on. The file is `library.db` in `DATA_DIR`.

**Postgres is the one other engine.** The release pipeline builds the schema on a real
Postgres server from the same migration chain, checks that a database left half migrated
is finished, and runs the engine aware tests against it before every release; the whole
suite runs against Postgres every night as well, less the tests that check SQLite's own
behaviour on purpose.

Spell the URL with the driver named:

```
DATABASE_URL=postgresql+pg8000://user:password@host/endpaper
```

The `pg8000` driver is in the image, so nothing has to be installed. **A bare
`postgresql://` fails**, because it asks SQLAlchemy for its default Postgres driver, which
the image does not carry. Do not put `?sslmode=` in the URL either: this driver does not
accept it, and the first connection fails. TLS is `DATABASE_SSL_MODE`'s job.

### TLS to Postgres

**The default connection checks no certificate and can fall back to cleartext**, so either
set `DATABASE_SSL_MODE` or keep the server on a network you trust. Left empty, the mode is
`prefer`: it offers TLS and verifies neither the certificate nor the host name, and on a
server that declines TLS it carries on unencrypted and logs a warning saying so. The
default is that loose because a self hosted Postgres is usually a container with no
certificate, and a stricter default would refuse the ordinary deployment.
[`security.md`](security.md#the-database-connection-verifies-nothing-by-default-and-says-so-when-it-downgrades)
states the reasoning in full.

The names are libpq's, less `allow`, which this driver cannot express:

| `DATABASE_SSL_MODE` | Refuses | Breaks |
|---|---|---|
| `disable` | nothing; it never offers TLS | a managed server that accepts only TLS |
| `prefer` | nothing. A downgrade is logged, not refused | nothing |
| `require` | a server that declines TLS | the usual compose Postgres, which ships with TLS off |
| `verify-ca` | that, and a certificate that chains to nothing trusted | a self signed certificate with no `DATABASE_SSL_ROOT_CERT`, and a private CA not mounted into the container |
| `verify-full` | that, and a certificate whose name is not the host in `DATABASE_URL` | reaching the server by container name or IP address, which is most of compose |

`DATABASE_SSL_ROOT_CERT` is a path **inside the container**, so mount the CA file first.
It replaces the image's trust store rather than adding to it, which is what you want for a
certificate you issued yourself.

**Startup refuses a TLS setting the connection cannot honour**, rather than ignoring it:

- either variable set while `DATABASE_URL` is not a `postgresql+pg8000://` URL, SQLite
  included, and including `DATABASE_SSL_MODE=prefer` or `disable`;
- `DATABASE_SSL_ROOT_CERT` set with a mode that checks no certificate;
- `DATABASE_SSL_ROOT_CERT` naming a file the process cannot see;
- a mode name that is not in the table.

## Sign-in modes

`AUTH_MODE` decides who checks a password.

| Mode | Who holds the passwords | Signup |
|---|---|---|
| `local` | this app | the sign in page offers it, unless `ALLOW_REGISTRATION=false` |
| `ldap` | a directory. An account is created here at its first sign in, so books and notes still have an owner | none |
| `proxy` | a forward authentication portal in front of the app, which names the member in a request header. The login form is not shown at all | none |

Under every mode an admin can make local test accounts and switch into one, to see the
library as an ordinary member does: the
[handbook](handbook.md#seeing-the-library-as-a-member) explains how. A forgotten local
password is reset by another admin, and the last admin's own is
[recovered from the container](#recovering-the-only-admin).

### LDAP

| Variable | Default | What it does |
|---|---|---|
| `LDAP_URL` | empty | The directory, for instance `ldaps://directory.example:636`. Required for `ldap` |
| `LDAP_USER_BASE_DN` | empty | Where to search for accounts. Required for `ldap` |
| `LDAP_BIND_DN` | empty | The service account the search binds as. Empty searches anonymously |
| `LDAP_BIND_PASSWORD` | empty | That account's password. **Required when `LDAP_BIND_DN` is set**: most directories treat a bind with a blank password as anonymous and quietly return nothing, so startup refuses it |
| `LDAP_USER_FILTER` | `(&(objectClass=person)(uid={username}))` | The search for one member. `{username}` is escaped and then substituted |
| `LDAP_USERNAME_ATTRIBUTE` | `uid` | The attribute holding the login name |
| `LDAP_ADMIN_GROUP` | empty | Members of this group are admins here, checked again at every sign in, so leaving the group takes admin away. Empty, the directory makes nobody an admin and takes admin from nobody: an existing admin stays one, and the first account in an empty library is made one. Set, that first account is still made an admin, and loses it at its next sign in unless it is a member |
| `LDAP_EMAIL_ATTRIBUTE` | empty | The attribute holding a member's address, usually `mail`. Set, the directory owns the address: it is applied at every sign in and read only in the app. **It also clears the stored address of every member the directory has none for**, at their next sign in, and nobody can type it back. Populate the attribute in the directory first. Empty leaves members to set their own |
| `LDAP_START_TLS` | `false` | Upgrade a plain `ldap://` connection with StartTLS. If the directory will not upgrade, no password is sent |
| `LDAP_CA_FILE` | empty | A CA bundle for a self signed or private directory certificate, as a path inside the container. It **replaces** the image's trust store. Startup refuses it on a connection without TLS, and refuses a file it cannot load |
| `LDAP_ALLOW_CLEARTEXT` | `false` | `true` lets the app start on an `ldap://` URL without StartTLS. Every sign in then sends the member's password in cleartext, so startup refuses that unless this is set |

Over TLS the directory's certificate and host name are always checked, and nothing turns
that off. A certificate listing DNS names in its subjectAltName has to list the `LDAP_URL`
host among them. Python's strict X.509 checks also need a home made CA to carry key usage
and a subject key identifier, and the server certificate an authority key identifier.

### Proxy

| Variable | Default | What it does |
|---|---|---|
| `PROXY_USER_HEADER` | `Remote-User` | The header naming the signed in account |
| `PROXY_GROUPS_HEADER` | `Remote-Groups` | The header carrying the member's groups, comma separated |
| `PROXY_ADMIN_GROUP` | empty | Membership of this group makes an admin, checked again on every request. Empty, the proxy makes nobody an admin and takes admin from nobody: an existing admin stays one, and the first account in an empty library is made one. Set, that first account is still made an admin, and loses it on its next request unless it is a member |
| `PROXY_EMAIL_HEADER` | empty | The header asserting the member's address, `Remote-Email` for Authelia. The same ownership rule, and the same clearing, as `LDAP_EMAIL_ATTRIBUTE` |

> **`AUTH_MODE=proxy` trusts headers.** It is safe only behind a proxy that sets them
> itself *and strips any arriving from the client*, and only when the app's port cannot be
> reached except through that proxy. Reached directly, anyone can send the header and claim
> to be an admin.
>
> The shipped compose files publish the port as `"8000:8000"`, on every interface of the
> host. With the proxy running on the host, publish it as `"127.0.0.1:8000:8000"`. With the
> proxy in a container, remove `ports:` and put both containers on one compose network,
> where the proxy reaches the app by its service name on port 8000.

## Reminders

The overdue digest goes out on each channel an admin switches on in Settings: a webhook,
email, or a Telegram chat. The recipients, the interval and the switches are settings in
the app. The mail and Telegram connection details may come from the environment instead,
under the rule in [Where a credential lives](#where-a-credential-lives).

| Variable | Default | What it does |
|---|---|---|
| `MAIL_SERVER` | empty | The SMTP host |
| `MAIL_PORT` | `587` | The SMTP port |
| `MAIL_USERNAME` | empty | Empty for a relay that needs no login |
| `MAIL_PASSWORD` | empty | Refused unless `MAIL_USE_TLS` or `MAIL_USE_SSL` is on, since it would otherwise cross the network in the clear |
| `MAIL_USE_TLS` | `true` | STARTTLS on a plain connection |
| `MAIL_USE_SSL` | `false` | Implicit TLS. Turning on both is refused: they are two protocols |
| `MAIL_DEFAULT_SENDER` | empty | The `From` address |
| `TELEGRAM_BOT_TOKEN` | empty | The bot's token, from BotFather. It travels in every request's URL, so treat it as a password |
| `TELEGRAM_CHAT_ID` | empty | The chat the bot posts to |

Mail certificates and host names are always verified, and nothing switches that off.
`MAIL_DEBUG`, the eighth of the usual `MAIL_*` names, is deliberately not read: Python's
SMTP client writes the login exchange to the log under it, mail password included.

**The digest runs inside the web process, once an hour**, and assumes there is exactly one
such process, which the image guarantees. If you run more than one, set
`ENABLE_OVERDUE_TICKER=false` and send the digest from a scheduled job instead, through
`POST /api/loans/overdue/notify`. That route is for admins only: under `local` or `ldap`
the job signs in through `POST /auth/login` as an admin and sends the token it gets back
as `Authorization: Bearer`, and under `proxy` it has to come through the proxy as an
admin. A token lasts a week, so sign in on every run.

The daily Readwise pull has the same one process assumption, so set
`ENABLE_READWISE_TICKER=false` as well. There is no route that pulls for everybody, so
with the ticker off nothing pulls on a schedule: each member pulls from their account
page.

## Where a credential lives

By default an admin pastes a credential into Settings and it is stored in the database.
Setting the matching environment variable hands that job to the deployment instead:

- the environment value **wins** over anything stored;
- the field in Settings is greyed out and names the variable;
- the app refuses to overwrite it, rather than accept a change the next restart would undo.

Either way a secret is never shown again once set. This holds for `GOOGLE_BOOKS_API_KEY`,
the seven `MAIL_*` variables in [Reminders](#reminders), both `TELEGRAM_*` ones, and each
`CATALOGUE_CREDENTIAL_<SOURCE>`. An empty `MAIL_*`, `TELEGRAM_*` or Google Books variable
counts as unset; an empty catalogue login does not, as the next section says.

Other admin preferences, such as the default language, the reminder interval, which
catalogues are asked, and the account policy, have no variable: a mistaken click there is
corrected by another click rather than a redeploy.

## Catalogue logins

Some catalogues need a login. [The feature list](featurelist.md#the-catalogue) says which.
**A catalogue login is somebody else's account**, held here on its behalf, so it is stored
apart from this deployment's own secrets. Both are sealed with one key that is never written
to the database: the logins, and the Google Books key, mail password, Telegram bot token and
webhook secret set under Settings. A backup carries them sealed and not the key, so nobody
can read them from the archive alone. A secret saved before the deployment had a key stays
as it was typed until a key exists, and is sealed then.

### The key

The key is a recovery phrase of **24 words**, in the shape a wallet recovery phrase takes.
It is checksummed, so a mistyped or misread word is refused rather than quietly becoming a
different key.

With no key the app starts and simply cannot store a login or one of those four secrets;
one set through the environment is never stored, and needs no key. Settings then offers to make
one and shows the words **once**; nothing can display them again. The app keeps the key in
the machine's keychain where there is one, and otherwise in a file only its own account
can read. The container has no keychain, so there the key is a file in `DATA_DIR`.

| Variable | Default | What it does |
|---|---|---|
| `CREDENTIAL_ENCRYPTION_KEY` | empty | The phrase itself. Pinned this way, Settings cannot replace or discard it |
| `CREDENTIAL_ENCRYPTION_KEY_FILE` | `$DATA_DIR/credential-key` | Read the phrase from this file instead. A Docker secret and a Kubernetes Secret both arrive as a file. On a read only mount, Settings cannot discard it |

**Write the words down.** If the key is lost or replaced, every stored catalogue login and
settings secret has to be entered again. Restoring a backup onto another machine needs the phrase, because the
archive deliberately does not carry the key.

### Which login is used

Each catalogue's login comes from the first of these that has one:

1. the environment, `CATALOGUE_CREDENTIAL_<SOURCE>`;
2. a login an admin entered in Settings;
3. a login Endpaper ships.

**Two catalogues' logins ship with Endpaper**, the Argentine and the Uruguayan national
libraries'. Each library publishes that username and password on its own page for
librarians, so carrying them discloses nothing the library has not, and both catalogues
answer on a fresh install. Removing a login from Settings falls back to the shipped one
rather than to nothing. The Settings screen names which of the three is in use.

| Variable | Default | What it does |
|---|---|---|
| `CATALOGUE_CREDENTIAL_<SOURCE>` | unset | Pins one catalogue's login as `username:password`, `<SOURCE>` being its identifier in capitals, for instance `CATALOGUE_CREDENTIAL_BNA`. Everything after the first colon is the password |

**Setting one to nothing pins that catalogue as unusable rather than clearing it.** A
compose line `- CATALOGUE_CREDENTIAL_BNA=${LOGIN}` with `LOGIN` unset stops that catalogue
answering, and Settings reports the variable as set and not a login. Remove the variable to
fall back.

## Google Books and Goodreads

Both are configured in the app: sign in as an admin and open Settings.

- **Google Books** needs an API key. Without one it is not asked; the other catalogues need
  no API key. A key pasted in Settings is stored in the database and never shown again;
  `GOOGLE_BOOKS_API_KEY` pins one from the deployment instead.
- **Goodreads** has no API here. The setting only shows or hides a link that looks a book
  up on Goodreads.

## Behind a reverse proxy

Run Endpaper behind Caddy, nginx or another proxy that terminates TLS, and point the proxy
at the container's port 8000.

- **HTTPS** is what lets a phone open the camera. The app sends `Strict-Transport-Security`
  only on a request that arrived over HTTPS, directly or as the proxy's
  `X-Forwarded-Proto: https` says, so a LAN install with no certificate is never locked out.
- **The request body limit** has to fit a backup archive, which holds every cover image.
  nginx's default limit refuses all but the smallest restore; raise `client_max_body_size`.
- **Rate limits are keyed per address only where no username is available**, and the app
  does not trust `X-Forwarded-For`, since a client can set it. Behind a proxy those limits
  therefore apply to everybody together. The ones on sign in key on the username as well.
- **Under `AUTH_MODE=proxy`** the proxy has to set the identity headers itself and strip any
  the client sent: [Proxy](#proxy).
- **One origin.** The proxy serves the API and the web client together, so `CORS_ORIGINS`
  stays empty.

## Data and backups

Everything lives in `DATA_DIR`, mounted from the host at `/app/data` in the compose files:

| Path | What it holds |
|---|---|
| `library.db` | the SQLite database, when `DATABASE_URL` is left at its default |
| `covers/` | the cover images, uploaded and downloaded |
| `credential-key` | the catalogue key, when the app made one and `CREDENTIAL_ENCRYPTION_KEY_FILE` names nowhere else |

**Back up from the app.** Settings has a backup that downloads the whole library, every
account and every cover in one zip, and a restore that takes it back. It works the same on
SQLite and Postgres. An archive from an older version restores on a newer one as long as
the archive format has not changed, and a migration adding a column does not change it. A
newer version that cannot read an archive refuses it and says which format it is.

- **A restore replaces everything** in the library. It asks first.
- **A restore signs everybody out**, because the accounts table it brings back may give a
  live session's account number to somebody else.
- **The archive does not carry the key** its logins and settings secrets are sealed with.
  Keep the recovery phrase with it:
  [Catalogue logins](#catalogue-logins).

**Copying `library.db` out from under a running container is not a consistent backup.**
SQLite here keeps recent writes in a separate journal file beside it until they are folded
in, so a copy of the one file can miss them. To copy files instead of using the zip, stop
the container first and copy the whole of `DATA_DIR`. That copy also holds the key file,
so store it as carefully as the phrase.

## Upgrading

Take a backup first: [Data and backups](#data-and-backups).

**Pulling alone upgrades nothing.** `docker-compose.deploy.yml` names its image by digest,
so a pull fetches the image the file already names. Change the `image:` line first, to
either of:

- `fklement/endpaper:vX.Y.Z`, the tag of the release you chose, with no digest.
- the `image:` line of `docker-compose.deploy.yml` on the `main` branch. Each release
  moves `:latest`, and a Renovate update on `main` then moves that line's digest to it,
  some time after the release is published; until it lands, the line still names an
  earlier release. The line names `:latest`, so it does not say which release it is.

**A copy of the file taken from a release tag does not pin that release.** The image is
built from the tag, so the tag's own file can only name an image published before it.

Then pull the image and recreate the container:

```bash
docker compose -f docker-compose.deploy.yml pull
docker compose -f docker-compose.deploy.yml up -d
```

Schema migrations run at startup and are logged. An `image:` line naming `:latest` with no
digest takes whatever release is newest at each pull, so you no longer choose when to
upgrade. What changed in each release is in the [changelog](../CHANGELOG.md).

## Recovering the only admin

**Keep the first admin's password.** A forgotten password is reset with another admin's
approval, so a library with exactly one admin cannot reset that admin's from inside the
app. The way back is a shell in the container:

```bash
docker exec -it endpaper python -m recover <username>
```

`endpaper` is the container's name in the shipped compose file; use yours if it differs.
The command asks for the new password twice on standard input, never on the command line,
and holds it to the same length rules as the sign up form. It signs out every session and
every KOReader device on that account. It refuses an account a directory authenticates,
whose password is held there.

It needs no new capability: whoever can run a command in the container can already read
the database.
