# ── The pins every stage shares ────────────────────────────────────────────
#
# BASE IS WRITTEN ONCE AND USED BY TWO STAGES. YAZ is compiled in the first and loaded in
# the last, so they have to be the same image: a library built against one musl and linked
# into another is the failure this whole arrangement exists to prevent. It used to be
# written out twice with a pipeline check comparing them, which is a fact stored twice
# with a guard bolted on. Verified under kaniko v1.28.3 that this shape works and that
# `--build-arg YAZ_BUILDER=...` still overrides only the builder half.
#
# Renovate bumps this line: the dockerfile manager reads an `ARG` default that a `FROM`
# consumes, and the runtime stage consumes it directly.
ARG BASE=python:3.14.7-alpine@sha256:c6ead215bfd31f1e433d968853b7a769989117115b728874824e6c0a27cb96fc

# Bumped by hand, and BOTH LINES TOGETHER. A version moved without its hash fails the
# build at `sha256sum -c`, which is the failure you want. Renovate raises the version half
# from the upstream git tags and cannot know the hash, so its merge request is expected to
# be red until somebody pastes the new one in; that is why it is not automerged.
#
# **The hash is trust on first use.** IndexData publish no signature and no checksum file
# alongside the release, so nothing corroborates it. See docker/build-yaz.sh.
ARG YAZ_VERSION=5.37.3
ARG YAZ_SHA256=975d7878b272cc999e5acbd02dc272a46607f95e6ee4f35ac655e8e4d333bf2b

# ── Stage 1: YAZ, the Z39.50 client library ────────────────────────────────
#
# Alpine packages no YAZ, so it is compiled here. Why it is here at all, and why not
# Debian: docs/architecture.md, "The Z39.50 client library".
#
# THIS STAGE IS FIRST SO IT CAN BE BUILT ALONE. `--target yaz` builds every stage up to
# the target and skips the rest, so with this at the top the pipeline can produce a
# prebuilt image without also running the Bun install.
#
# YAZ_BUILDER IS THE WHOLE MECHANISM, and it takes this shape because of what kaniko
# does and does not substitute. Measured against kaniko v1.28.3 on 2026-08-28:
#
#   COPY --from=${SOME_ARG}   fails outright, "could not parse reference: ${SOME_ARG}"
#   FROM ${SOME_ARG}          works, and --build-arg overrides the default
#
# So the parameter is the BASE OF THIS STAGE rather than the source of a COPY, which is
# the reverse of the obvious shape. Handed the plain base image, this stage compiles YAZ
# in about a minute. Handed a prebuilt image, build-yaz.sh finds its own build id already
# in /opt/yaz and returns in milliseconds.
#
# **Correctness does not depend on which, and it does not depend on the pipeline either.**
# The build id names the YAZ version, the tarball hash, the recipe and the musl it was
# linked against, so a prebuilt image that disagrees on any of them is recompiled here,
# and one that disagrees on musl is refused by the runtime stage below. The pipeline's tag
# is a performance optimisation on top of that, not the guarantee.
ARG YAZ_BUILDER=${BASE}
FROM ${YAZ_BUILDER} AS yaz

ARG YAZ_VERSION
ARG YAZ_SHA256
ENV YAZ_VERSION=$YAZ_VERSION YAZ_SHA256=$YAZ_SHA256

COPY docker/build-yaz.sh /tmp/build-yaz.sh
RUN sh /tmp/build-yaz.sh build && rm -f /tmp/build-yaz.sh

# ── Stage 2: Build the React PWA with Bun ──────────────────────────────────
FROM oven/bun:1.4.1-alpine@sha256:2ef545220f7a886f22fcb3f2309bbd6bcf1c0aa04b7d79c31765c7aa4a13aac1 AS frontend
WORKDIR /app/frontend

# Manifest, lockfile and bunfig first, so the install layer is cached until a
# dependency actually changes. bunfig.toml belongs here: it configures the
# security scanner that screens packages during this very install.
COPY frontend/package.json frontend/bun.lock frontend/bunfig.toml ./
# --frozen-lockfile fails the build if the lockfile and manifest disagree,
# rather than silently resolving something the lockfile never pinned.
RUN bun install --frozen-lockfile

COPY frontend/ .
# `build` runs `tsc --noEmit` first, so a type error fails the image build.
# The version the About card shows. The frontend is built here, in a stage with no
# .git and no CI variables, so the tag cannot be discovered and has to be handed in.
# Empty on a local build, which is correct: vite.config falls back to git describe,
# and to `unknown` when there is no git either.
ARG APP_VERSION=""
ENV CI_COMMIT_TAG=$APP_VERSION

RUN bun run build

# ── Stage 3: FastAPI server with uv ────────────────────────────────────────
#
# Alpine, matching stage 1. Moved off python:3.14.7-slim (Debian 13) on 2026-08-18,
# alongside the same move in the webpage project, where the first gating image scan
# blocked on CVE-2026-53615 in util-linux: nine binary packages from one source, none
# of which a uvicorn process ever invokes, and with no fixed base image to bump to.
# Debian's userland is apt, dpkg and their dependencies: findings waiting to happen
# against software that is never executed. Alpine's is busybox and musl.
#
# HIGHER RISK HERE THAN IN WEBPAGE, AND VERIFIED RATHER THAN ASSUMED. musl breaks
# manylinux wheels, and unlike webpage this backend leans on compiled packages:
# bcrypt, pydantic-core, uvloop, httptools, watchfiles, greenlet, sqlalchemy, pyyaml.
# Before the switch, the whole lockfile was resolved inside python:3.14.7-alpine: all
# 28 runtime packages installed from musllinux wheels in about two seconds, nothing
# fell back to a source build, and the dev group resolved too. Installing is not
# running, so the C extensions were then exercised: bcrypt hashed a password, verified
# it, and correctly rejected a wrong one; uvloop actually supplied the event loop;
# SQLAlchemy opened SQLite and ran a query; pydantic-core validated a model.
#
# Keep that bar for new dependencies. A package with a C extension and no musllinux
# wheel will not fail politely: uv will try to build it from source and die for want
# of a compiler, in CI, at image-build time.
FROM ${BASE}

# ── The YAZ tree ───────────────────────────────────────────────────────────
#
# Two checks, and they answer different questions. This one asks whether the tree is the
# build this Dockerfile describes: the version, the tarball it came from, and the recipe
# that made it. Whether it actually LINKS in this image is a separate question, checked
# further down once its libraries are installed, by running it.
#
# **BE CLEAR ABOUT WHAT THIS ONE CAN AND CANNOT CATCH.** In an ordinary build it cannot
# fire: the stage above runs from the same pins and the same recipe file, so the stamp
# matches by construction. It is a check on the COPY source, and the thing it would catch
# is somebody pointing `--from` at a tree this Dockerfile did not describe. **It does not
# catch a different subset of the SAME build**, because the recipe writes the same id into
# /opt/yaz and /opt/yaz-runtime alike, so copying the full tree would pass here and
# silently ship the headers, the documentation and the two libraries the runtime subset
# exists to leave out. The guarantee that the library works in this image is the load
# check below, not this line.
ARG YAZ_VERSION
ARG YAZ_SHA256
COPY --from=yaz /opt/yaz-runtime /opt/yaz
COPY docker/build-yaz.sh /tmp/build-yaz.sh
RUN sh /tmp/build-yaz.sh verify && rm -f /tmp/build-yaz.sh

# Alpine ships no package manager userland worth keeping current beyond this, but the
# principle that bit webpage applies here too: pinning a base image by digest pins its
# PATCH LEVEL, and the digest stops moving while the distro keeps publishing fixes.
#
# **This line is only true if the layer is not cached**, and on 2026-08-27 it was not
# true: kaniko's default cache TTL is two weeks, so this ran once and every release
# afterwards inherited that day's patch level. v0.10.0 was refused by `verify:image`
# over a fixed openssl HIGH the upgrade should have taken. `release:build` now passes
# `--cache-ttl=6h`; if that flag is ever removed, this line becomes decorative again.
RUN apk upgrade --no-cache

# ── YAZ's runtime dependencies ─────────────────────────────────────────────
#
# libyaz links libxml2, libxslt and gnutls, and the base image carries none of them.
# THE COST IS 2.7 TIMES WHAT THE FIRST ESTIMATE SAID, because the estimate costed three
# packages and apk installs TEN. Measured 2026-08-28 on this exact base by `du -sk /`
# before and after, Alpine 3.24.1, package count 30 to 32 to 40:
#
#   libxml2 + libxslt                                        +1,384 KiB
#   gnutls, which drags in nettle, gmp, p11-kit, libtasn1,
#   libunistring, brotli-libs and libidn2                    +7,704 KiB
#                                                            ───────────
#   packages, against the 3,359 KiB first estimated           9,088 KiB   2.7x
#   /opt/yaz below                                           +1,844 KiB
#                                                            ───────────
#   in the image                                             10,932 KiB
#
# The 2.7 is packages against packages. An earlier version of this said 3.3x, which put
# /opt/yaz in the numerator and not the denominator.
#
# **gnutls and its seven dependants are 85% of the package cost, 70% of the total above,
# and buy Z39.50 over TLS**, which no target measured for #92 uses: every one answers
# plaintext on 210, 2100 or 9991. Dropping it is a capability decision for whoever writes
# the transport, not a build tidy-up, so it is recorded rather than taken.
#
# **AND IT IS TWO EDITS, NOT ONE.** `./configure --without-gnutls` in docker/build-yaz.sh
# stops libyaz linking it; the 7,704 KiB leaves the image only when `gnutls` also comes
# off the line below. The build id makes the recompile automatic. It does not touch this
# line, and an earlier version of this comment claimed there was "nothing else to
# remember", which was wrong about the larger half.
#
# **What gnutls buys is transport encryption and NOT peer authentication.** YAZ performs
# no certificate verification in any released version: `verify_peers`,
# `set_x509_system_trust`, `session_set_verify_cert`, `set_x509_trust_file` and
# `GNUTLS_CERT` appear nowhere in src/ or client/, on 5.35.1 or on 5.37.3.
# src/tcpip.c allocates certificate credentials and calls gnutls_init(GNUTLS_CLIENT)
# without ever loading a trust store. So an `ssl:` target is encrypted against a passive
# listener and not against anyone who can answer for the address.
RUN apk add --no-cache libxml2 libxslt gnutls

# ── And now make it actually link ──────────────────────────────────────────
#
# **THIS REPLACES A STRING COMPARISON WITH THE THING THE STRING WAS A PROXY FOR.** The
# build id used to carry the musl version so this stage could refuse a library built
# against a different libc. That was wrong twice over: it was read before `apk add
# build-base`, which upgrades musl whenever the repository is ahead of the pinned digest
# (`musl-dev` depends on `musl=<exact version>`), and it said nothing at all about
# libxml2, libxslt or gnutls, which libyaz also links.
#
# Loading the library answers all of it at once, and answers the question that actually
# matters rather than a proxy for it: musl, all three shared libraries, and the install
# prefix, since libtool baked /opt/yaz/lib into the binary as its RUNPATH and a tree
# copied anywhere else cannot find itself. A missing library names itself and exits
# non-zero.
#
# The release smoke test runs the same command again on the finished image. That is not
# duplication: this line fails the BUILD, in any build including somebody's own
# `docker build`, while the smoke test proves it in the artefact that is about to be
# published, after the unprivileged user and the file ownership are in place.
# `LD_BIND_NOW=1` resolves every symbol at load instead of on first call, so a missing
# one fails here rather than at some later request. Measured to work: the same binary
# loads clean with it set.
RUN LD_BIND_NOW=1 /opt/yaz/bin/yaz-client -V | grep -q "^YAZ version: ${YAZ_VERSION} " \
    || { echo "the YAZ in /opt/yaz does not load, or is not ${YAZ_VERSION}" >&2; \
         /opt/yaz/bin/yaz-client -V >&2 || true; exit 1; }

WORKDIR /app

# NOTE THE SOURCE PATH. The Debian uv image ships the binary at /uv; the -alpine
# variant ships it at /usr/local/bin/uv. Copying /uv from the alpine image fails with
# "failed to get fileinfo for /kaniko/deps/.../uv: no such file or directory", which
# reads like a kaniko cross-stage bug and is really just a missing file.
COPY --from=ghcr.io/astral-sh/uv:0.12.9-alpine@sha256:ff22262d24de43d6938c324797bc51b405b705d59e0a3d1873b0a66b2c778c5c /usr/local/bin/uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

COPY backend/pyproject.toml backend/uv.lock ./
# --no-dev omits pytest, ruff and mypy: the test tooling has no place in a
# runtime image. --frozen refuses to silently re-resolve the lockfile.
RUN uv sync --frozen --no-cache --no-dev --no-install-project

COPY backend/ .
# Only the compiled assets cross from stage 1: no Bun, no node_modules,
# no TypeScript sources in the shipped image.
COPY --from=frontend /app/frontend/dist ./static

# DATA_DIR holds the SQLite database and uploaded covers, and is the path to
# mount a volume at. Created here so a first run works with no volume.
ENV DATA_DIR=/app/data
RUN mkdir -p "$DATA_DIR/covers"

# ── Run as a non-root user ─────────────────────────────────────────────────
#
# uid/gid 1000 specifically, not an arbitrary or system-allocated id: the
# Kubernetes chart chowns its NFS volume to 1000:1000 from an initContainer,
# because fsGroup does not work on that storage class (an NFS volume has no
# fsType, so the kubelet skips ownership management entirely). Mismatch here
# means the app cannot write its own database.
#
# adduser fails the build if 1000 is already taken, which is the behaviour we
# want. A silently different uid would surface much later as a permissions
# error on a mounted volume.
#
# busybox adduser/addgroup, not shadow's useradd/groupadd: Alpine does not install
# shadow, and the build would fail with "command not found". -D creates the account
# with no password and -H skips the home directory, which a service account wants.
RUN addgroup -g 1000 app \
    && adduser -D -H -h /app -u 1000 -G app app \
    && chown -R 1000:1000 /app

# ── Drop pip and setuptools ────────────────────────────────────────────────
#
# Nothing here uses them. Dependencies arrive as the uv-built virtualenv above, which
# uv creates WITHOUT pip, and PATH puts that venv first. These are the base image's
# copies sitting unused in /usr/local.
#
# Unused is not harmless: a scanner cannot tell a package you ship from one you run.
# The same deletion in the webpage project removed two of its three blocking findings
# outright (CVE-2025-47273 in setuptools, and GHSA-6v7p-g79w-8964 in msgpack, which is
# reachable only because pip VENDORS msgpack). It removes the category as well as the
# instances: pip vendors a dozen libraries, each a future finding against code nothing
# calls.
#
# Before USER, since /usr/local is root-owned.
RUN rm -rf /usr/local/lib/python3.14/site-packages/pip \
           /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.14/site-packages/setuptools \
           /usr/local/lib/python3.14/site-packages/setuptools-*.dist-info \
           /usr/local/lib/python3.14/site-packages/pkg_resources \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.14

USER 1000:1000

# Note for readOnlyRootFilesystem deployments: /tmp must stay writable (mount
# an emptyDir there). FastAPI spools an uploaded cover into a
# SpooledTemporaryFile that rolls over to a real file in TMPDIR once it
# outgrows its buffer, so cover uploads fail without it. Nothing else needs a
# writable path outside DATA_DIR. UV_COMPILE_BYTECODE precompiles the .pyc
# files at build time, so the venv is never written to at runtime.

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
