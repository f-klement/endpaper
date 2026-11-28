#!/bin/sh
# Build YAZ, the Z39.50 client library, from source into /opt/yaz, and assemble the
# subset the runtime image needs into /opt/yaz-runtime.
#
# Usage, and all three modes are used by the Dockerfile:
#
#   build-yaz.sh build     compile, unless this tree is already the build this would make
#   build-yaz.sh verify    refuse unless the tree present IS that build
#   build-yaz.sh id        print the build id and exit
#
# WHY THIS EXISTS AT ALL. Alpine does not package YAZ. Checked 2026-08-28 on the pinned
# base (Alpine 3.24.1) and earlier across edge, v3.22 and v3.21 in main, community and
# testing: there is no `yaz` and no `yaz-dev`, so there is no `apk add yaz` and the only
# way to have it on musl is to compile it.
#
# WHY IT IS A FILE RATHER THAN A RUN BLOCK. Three callers have to agree on what "the same
# build" means: the build stage, the runtime stage, and the pipeline that decides whether
# a prebuilt builder image is still current. All three derive it from the sha256 of this
# file, so a change to the recipe is visible to all of them without anybody remembering to
# bump a version.
#
# Environment, supplied by the Dockerfile as ARGs so a reader finds the pins where they
# expect them:
#   YAZ_VERSION   the upstream release to fetch
#   YAZ_SHA256    the sha256 of that tarball
set -eu

: "${YAZ_VERSION:?YAZ_VERSION must be set}"
: "${YAZ_SHA256:?YAZ_SHA256 must be set}"

MODE="${1:-build}"

# ── The build id, and what it deliberately does not name ─────────────────────────────
#
# It names every input that decides WHAT gets built:
#
#   the version           what was compiled
#   the tarball hash      WHICH BYTES were compiled. Without this, editing YAZ_SHA256
#                         alone changes nothing anybody checks: the tag stays the same,
#                         the builder image is reused, and this gate finds a matching id
#                         and skips, so the hash is verified once in history and never
#                         again. Measured as an uncaught mutation on 2026-08-28.
#   this file             the flags, the strip list, the runtime subset
#
# **IT DOES NOT NAME THE ENVIRONMENT, AND THAT IS THE SECOND ATTEMPT AT THIS.** The first
# version left the base out with a false justification. The second added the musl version,
# and that was worse, because of WHEN the value could be read:
#
#   * assigned here, before `apk add build-base`, it is the musl the stage STARTED with,
#     not the one YAZ was linked against. `musl-dev` depends on `musl=<exact version>`,
#     verified in the v3.24 index as `D:musl=1.2.6-r2`, so `apk add build-base` upgrades
#     musl whenever the repository is ahead of the pinned base digest.
#   * the stamp then names a musl the pushed builder image no longer has, so that image's
#     own reuse gate rejects it and every later build recompiles in silence. That is 61
#     seconds back on every push, which is the whole thing this file exists to avoid.
#   * the recompiled tree stamps the post-add musl, and a runtime check comparing against
#     the pinned base's older musl then HARD FAILS, with no tag change to trigger a fix.
#
# Reading it later does not solve it either: there are three clocks here, the base image,
# the repository and the runtime stage, and any fixed reading point fails in one direction
# or another. **So the environment is not compared as a string at all. It is checked by
# running the library**, in the runtime stage, after its dependencies are installed. That
# covers musl, libxml2, libxslt, gnutls and the install prefix at once, where a musl term
# covered one of them and covered it wrongly.
BUILD_ID="yaz-${YAZ_VERSION}-$(echo "$YAZ_SHA256" | cut -c1-8)-$(sha256sum "$0" | cut -c1-16)"

# **Test only, and it reaches `verify` alone.** That is now true because the stamp path is
# an argument rather than a global: the build path passes the real path as a literal, so
# no environment variable can point it somewhere else. It used to be a global read by all
# three call sites, and the comment claiming otherwise was false: with a planted stamp and
# no /opt/yaz at all, `build` printed "reusing the prebuilt tree" and exited without
# compiling. `--prefix` is baked into yaz-client as its RUNPATH, so a relocatable install
# prefix would be a silent way to ship a binary that cannot find its own library.
DEFAULT_STAMP=/opt/yaz/.build-id

verify () {
    stamp="$1"
    found=$(cat "$stamp" 2>/dev/null || echo "no ${stamp}")
    [ "$found" = "$BUILD_ID" ] && return 0
    echo "yaz: the tree present is not the build this recipe describes." >&2
    echo "     found:  ${found}" >&2
    echo "     wanted: ${BUILD_ID}" >&2
    return 1
}

case "$MODE" in
    id)     echo "$BUILD_ID"; exit 0 ;;
    verify)
        # THE RUNTIME STAGE CALLS THIS, and what it establishes is narrower than it once
        # claimed: that the tree it received is the build these pins describe. In an
        # ordinary build it cannot fire, because the stage that produced the tree ran from
        # the same pins and the same copy of this file. It catches a `COPY --from` pointed
        # at a tree this Dockerfile did not describe. **Whether the library actually loads
        # is a different question**, and the runtime stage answers it by running
        # yaz-client, not by comparing strings.
        verify "${YAZ_ROOT:-}${DEFAULT_STAMP}"
        echo "yaz: the tree is ${BUILD_ID}"
        exit 0 ;;
    build)  ;;
    *)      echo "yaz: unknown mode '${MODE}', expected build, verify or id" >&2; exit 2 ;;
esac

# ── The reuse gate ───────────────────────────────────────────────────────────────────
#
# When the pipeline hands this stage a prebuilt builder image, /opt/yaz is already there
# and this exits in milliseconds. When it hands over the plain base image, or when any of
# the three inputs above moved since that image was built, the id does not match and the
# compile runs. So a stale builder image costs about a minute; it cannot ship the wrong
# YAZ. That property lives here rather than in the tag, which is what lets the tag be a
# performance optimisation instead of a correctness one.
if verify "$DEFAULT_STAMP" 2>/dev/null; then
    echo "yaz: reusing the prebuilt tree, ${BUILD_ID}"
    exit 0
fi

echo "yaz: building ${BUILD_ID}"

# --virtual so the toolchain can be removed again at the end.
#
# NO openssl-dev. YAZ has exactly one TLS path and it is gnutls: `grep -n openssl` over
# configure.ac and m4/*.m4 in 5.37.3 returns nothing at all. It was in this list because
# the first measured build copied a habit, not because anything reads it.
#
# icu-dev IS needed: configure looks for it, and drops libyaz_icu without it. libyaz
# itself does not link ICU, and libyaz_icu is not shipped.
apk add --no-cache --virtual .yaz-build \
    build-base libxml2-dev libxslt-dev icu-dev gnutls-dev

cd /tmp
wget -q -O yaz.tar.gz "https://ftp.indexdata.com/pub/yaz/yaz-${YAZ_VERSION}.tar.gz"
# The tarball is fetched over the network at build time, so it is pinned by content and
# not by URL. Without this line a compromised or merely re-rolled upstream tarball would
# be compiled and shipped with nothing to notice.
#
# **THIS PIN IS TRUST ON FIRST USE AND CANNOT BE CORROBORATED.** IndexData publish no
# signature and no checksum file: `.sig`, `.asc`, `SHA256SUMS`, `CHECKSUMS`,
# `sha256sums.txt` and `MD5SUMS` all 404 under the release directory, checked 2026-08-28.
# So the hash below records the bytes one fetch saw, and re-fetching only proves upstream
# has not changed since. It is worth having anyway: it pins the artefact against a later
# substitution, which is the threat this can actually address.
echo "${YAZ_SHA256}  yaz.tar.gz" | sha256sum -c -
tar xzf yaz.tar.gz
cd "yaz-${YAZ_VERSION}"

# No patches are needed against musl. That claim is narrower than it sounds and is worth
# stating precisely: configure and make complete clean, which is not the same as the
# sources being musl-correct. 5.36.0 carries an upstream fix, "expose gethostbyaddr with
# _GNU_SOURCE", that a clean build would not have revealed.
./configure --prefix=/opt/yaz --disable-static
make -j"$(nproc)"
make install

cd /
rm -rf "/tmp/yaz.tar.gz" "/tmp/yaz-${YAZ_VERSION}"

# Stripping is worth doing rather than assuming. Measured on 5.37.3, Alpine 3.24.1:
# libyaz.so.5.3.0 goes from 5,168,584 to 1,753,232 bytes, a 66.1% cut, and the whole tree
# from 9,048 to 4,536 KiB.
#
# NOTE THE FILENAMES AND WHY THEY ARE GLOBBED. That is the libtool library revision, not
# the release number: 5.35.1 installed libyaz.so.5.1.1 and 5.37.3 installs
# libyaz.so.5.3.0. A strip aimed at either literal finds nothing on the other, and a
# strip aimed at libyaz.so.${YAZ_VERSION} finds nothing ever. The first version of this
# file named 5.1.1 outright, and the bump to 5.37.3 would have failed on it.
strip /opt/yaz/lib/libyaz.so.5.*.* \
      /opt/yaz/lib/libyaz_icu.so.5.*.* \
      /opt/yaz/lib/libyaz_server.so.5.*.*
strip /opt/yaz/bin/yaz-client /opt/yaz/bin/yaz-marcdump /opt/yaz/bin/yaz-url \
      /opt/yaz/bin/yaz-iconv /opt/yaz/bin/yaz-icu /opt/yaz/bin/yaz-illclient \
      /opt/yaz/bin/yaz-json-parse /opt/yaz/bin/yaz-record-conv /opt/yaz/bin/yaz-ztest \
      /opt/yaz/bin/zoomsh

# libtool archives record absolute build paths and are useless without libtool.
rm -f /opt/yaz/lib/*.la

# ── The runtime subset ────────────────────────────────────────────────────────────────
#
# The final image takes this directory and nothing else, so what is not copied here is
# not shipped. Deliberately absent, with the measured cost of each:
#
#   include/            796 KiB   headers, a build-time need. Kept in /opt/yaz so the
#                                 builder image can still compile a binding against it.
#   share/doc, share/man 1,048 KiB
#   share/yaz/z39.50, ill         .asn sources, consumed by yaz-asncomp at build time
#   share/yaz/etc        124 KiB  CQL to PQF maps and MARC21 XSLTs. Nothing needs them
#                                 while queries are written as PQF. A CQL front end
#                                 would, and would change this file, which is exactly
#                                 the event the build id exists to catch.
#   libyaz_icu, libyaz_server  147 KiB  ICU tokenising and the server side of the
#                                 protocol. This application is a client.
mkdir -p /opt/yaz-runtime/lib /opt/yaz-runtime/bin
cp -a /opt/yaz/lib/libyaz.so.5* /opt/yaz-runtime/lib/
cp -a /opt/yaz/bin/yaz-client /opt/yaz-runtime/bin/

# Prove the assembled subset stands on its own BEFORE the toolchain goes, rather than
# discovering a missing file in the runtime image. LD_LIBRARY_PATH points at the subset
# only, so a library left behind in /opt/yaz cannot satisfy this.
echo "yaz: verifying the runtime subset"
LD_LIBRARY_PATH=/opt/yaz-runtime/lib /opt/yaz-runtime/bin/yaz-client -V \
    | grep -q "^YAZ version: ${YAZ_VERSION} " \
    || { echo "yaz: the runtime subset does not report ${YAZ_VERSION}" >&2; exit 1; }

echo "$BUILD_ID" > /opt/yaz/.build-id
cp /opt/yaz/.build-id /opt/yaz-runtime/.build-id

# The recipe checks its own output with the same code the runtime stage will use. Without
# this, deleting the two lines above is a silent mutation: the compile succeeds, the image
# builds, and the first thing to notice is the runtime stage of some later build.
verify "$DEFAULT_STAMP"

apk del .yaz-build
