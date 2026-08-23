# ── Stage 1: Build the React PWA with Bun ──────────────────────────────────
FROM oven/bun:1.3.14-alpine@sha256:5acc90a93e91ff07bf72aa90a7c9f0fa189765aec90b47bdbf2152d2196383c0 AS frontend
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

# ── Stage 2: FastAPI server with uv ────────────────────────────────────────
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
FROM python:3.14.7-alpine@sha256:05b2b8b732ecd268fee8727a369f936f022d1321b59befd13c30ede22769dcdc

# Alpine ships no package manager userland worth keeping current beyond this, but the
# principle that bit webpage applies here too: pinning a base image by digest pins its
# PATCH LEVEL, and the digest stops moving while the distro keeps publishing fixes.
RUN apk upgrade --no-cache

WORKDIR /app

# NOTE THE SOURCE PATH. The Debian uv image ships the binary at /uv; the -alpine
# variant ships it at /usr/local/bin/uv. Copying /uv from the alpine image fails with
# "failed to get fileinfo for /kaniko/deps/.../uv: no such file or directory", which
# reads like a kaniko cross-stage bug and is really just a missing file.
COPY --from=ghcr.io/astral-sh/uv:0.12.5-alpine@sha256:f1150606ed108e062419bf087fb9aacf0688659af3944b00a2e591e81a8c980f /usr/local/bin/uv /bin/uv

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
