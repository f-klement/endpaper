"""What the `Dockerfile` keeps out of the image's layers, and what the app's user may touch.

Every regression here is silent: the image builds, starts and passes its smoke test, and
then only gets larger and slower to push, lets the process rewrite its own code, or
fails to start for whoever builds it from a checkout made under a restrictive umask.
Each is also what an ordinary edit produces, which is why they are pinned rather than
left to the comments beside them.

Read from the file's instructions the way Docker reads them: continuation lines are
joined, and comment and blank lines are dropped wherever they sit, so prose naming a
command is not an instruction. What it does not see: a `RUN` calling a script that does
any of this, a command named through a variable, and the JSON form of `COPY` and `RUN`.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _ROOT / "Dockerfile"
_DOCKERIGNORE = _ROOT / ".dockerignore"


def _stages(text: str) -> list[list[str]]:
    """The instructions of each stage, in order, one string per instruction.

    A comment or blank line inside a continued instruction is dropped and the
    instruction goes on, as Docker does. Ending it there instead splits one `RUN`
    into two halves, and each half is then judged alone and wrongly.
    """
    stages: list[list[str]] = []
    pending = ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        instruction = " ".join((pending + line).split())
        pending = ""
        if instruction.upper().startswith("FROM "):
            stages.append([])
        if stages:
            stages[-1].append(instruction)
    return stages


def _name(stage: list[str]) -> str:
    found = re.search(r"\sAS\s+(\S+)$", stage[0], re.IGNORECASE)
    return found.group(1).lower() if found else ""


def _stage_named(stages: list[list[str]], name: str) -> list[str]:
    for stage in stages:
        if _name(stage) == name:
            return stage
    raise AssertionError(f"no stage named {name} in the Dockerfile")


def _keyword(instruction: str) -> str:
    return instruction.split(maxsplit=1)[0].upper()


def _copy(instruction: str) -> tuple[dict[str, str], list[str], str]:
    """The flags, the sources and the destination of a `COPY` or `ADD`."""
    words = instruction.split()[1:]
    flags: dict[str, str] = {}
    while words and words[0].startswith("--"):
        key, _, value = words.pop(0)[2:].partition("=")
        flags[key.lower()] = value
    return flags, words[:-1], words[-1]


def _calls(instruction: str, program: str) -> list[list[str]]:
    """The arguments of each call of `program` in a `RUN`, with the quotes removed.

    The program is found wherever a shell could run it, not only at the head of a
    segment: after `then` or `do`, an assignment, `xargs`, `find -exec`, `sh -c` or `$(`.
    Read only at the head, `then chown -R 1000:1000 /app` would pass. The cost is that an
    argument spelled like the program, as in `echo chown`, is read as a call too.
    """
    calls = []
    for segment in re.split(r"&&|\|\||[;|]", re.sub(r"^RUN\s+", "", instruction, flags=re.IGNORECASE)):
        words = [word.replace('"', "").replace("'", "") for word in segment.split()]
        calls += [words[i + 1 :] for i, word in enumerate(words) if word.lstrip("$({`") == program]
    return calls


def _operands(arguments: list[str]) -> list[str]:
    return [argument for argument in arguments if not argument.startswith("-")]


def _recursive(arguments: list[str]) -> bool:
    return any(
        argument == "--recursive"
        or (re.fullmatch(r"-[A-Za-z]+", argument) is not None and "r" in argument.lower())
        for argument in arguments
    )


def _resolve(workdir: str, path: str) -> str:
    return posixpath.normpath(posixpath.join(workdir, path))


def _within(outer: str, inner: str) -> bool:
    return inner == outer or inner.startswith(outer.rstrip("/") + "/")


def _clauses(mode: str) -> list[tuple[str, str, str]]:
    """A symbolic mode as (who, operator, permissions), one per operator."""
    clauses = []
    for clause in mode.split(","):
        who = re.sub(r"[^ugoa].*", "", clause)
        for operator, permissions in re.findall(r"([-+=])([rwxXst]*)", clause[len(who) :]):
            clauses.append((who, operator, permissions))
    return clauses


def _grants_write(mode: str) -> bool:
    """Whether a chmod mode gives write to anybody but the owner, who is root here."""
    if re.fullmatch(r"[0-7]{3,4}", mode):
        return bool(int(mode, 8) & 0o022)
    return any(
        operator != "-" and "w" in permissions and (not who or set(who) & set("goa"))
        for who, operator, permissions in _clauses(mode)
    )


def _opens_to_reading(mode: str) -> bool:
    """Whether a chmod mode lets everybody read a file and traverse a directory."""
    if re.fullmatch(r"[0-7]{3,4}", mode):
        return int(mode, 8) & 0o005 == 0o005
    return any(
        operator != "-"
        and "r" in permissions
        and set(permissions) & set("xX")
        and (not who or set(who) & set("oa"))
        for who, operator, permissions in _clauses(mode)
    )


def _reaching_the_runtime(stages: list[list[str]]) -> list[list[str]]:
    """The runtime stage and every stage whose files cross into it, however indirectly.

    A builder stage's modes cross a `COPY --from` with its files, and so can its
    owners, so what it grants there is granted in the image.
    """
    named = {_name(stage): stage for stage in stages if _name(stage)}
    reached = [stages[-1]]
    for stage in reached:
        for instruction in stage:
            if _keyword(instruction) in ("COPY", "ADD"):
                source = _copy(instruction)[0].get("from", "").lower()
                if source in named and named[source] not in reached:
                    reached.append(named[source])
    return reached


def _data_dir(runtime: list[str]) -> str:
    declared = [i for i in runtime if re.match(r"ENV\s+DATA_DIR=", i, re.IGNORECASE)]
    assert declared, "the runtime stage declares no DATA_DIR, so nothing here can be judged"
    return declared[0].split("=", 1)[1].strip().strip("\"'")


def _target(path: str, workdir: str, data_dir: str) -> str:
    """A path as the shell resolves it: `DATA_DIR` substituted, then joined to `WORKDIR`.

    Compared raw, `data` after `WORKDIR /app` would read as outside `DATA_DIR`, and
    `"$DATA_DIR"/..`, which is `/app`, as inside it.
    """
    return _resolve(workdir, path.replace("${DATA_DIR}", data_dir).replace("$DATA_DIR", data_dir))


def _in_stage(stage: list[str], data_dir: str) -> Iterator[tuple[str, str]]:
    """Each instruction of a stage beside the working directory it runs in.

    A stage's working directory is taken to start at `/`, whatever its base image sets.
    """
    workdir = "/"
    for instruction in stage:
        if _keyword(instruction) == "WORKDIR":
            workdir = _target(instruction.split(maxsplit=1)[1], workdir, data_dir)
        yield workdir, instruction


def _to_root(owner: str) -> bool:
    """Whether a chown owner gives the files to root, which grants the app's user nothing."""
    return all(part in ("", "0", "root") for part in re.split(r"[:.]", owner))


class TestTheFrontendStageCachesNoDependencies:
    """The frontend stage installs, builds and deletes what it installed in one `RUN`.

    kaniko caches every `RUN` layer in a registry, so whatever a `RUN` leaves behind is
    pushed and pulled though only `dist` leaves the stage. `node_modules` holds every
    dependency, and bun's install cache holds a copy of every package it fetched.
    """

    def _install(self) -> tuple[list[str], str, str, list[str]]:
        """The stage, the one `RUN` installing, its working directory, what it deletes."""
        stage = _stage_named(_stages(_DOCKERFILE.read_text()), "frontend")
        workdir = "/"
        installs: list[tuple[str, str]] = []
        for instruction in stage:
            if _keyword(instruction) == "WORKDIR":
                workdir = _resolve(workdir, instruction.split(maxsplit=1)[1])
            if _keyword(instruction) == "RUN" and "bun install" in instruction:
                installs.append((instruction, workdir))
        assert len(installs) == 1, f"expected one RUN installing, found {installs}"
        install, workdir = installs[0]
        deleted = [
            _resolve(workdir, target)
            for arguments in _calls(install, "rm")
            if _recursive(arguments)
            for target in _operands(arguments)
        ]
        return stage, install, workdir, deleted

    def test_the_install_the_build_and_the_deletion_of_node_modules_share_one_run(self) -> None:
        _, install, workdir, deleted = self._install()

        assert "bun run build" in install, (
            f"the install and the build are separate RUNs, so a layer holding node_modules "
            f"is cached: {install}"
        )
        assert _resolve(workdir, "node_modules") in deleted, (
            f"the RUN that installs does not delete node_modules: {install}"
        )

    def test_bun_install_cache_is_pointed_at_a_path_the_same_run_deletes(self) -> None:
        stage, install, workdir, deleted = self._install()
        assignments = re.findall(r"\bBUN_INSTALL_CACHE_DIR=(\S+)", install) + [
            i.split("=", 1)[1] for i in stage if re.match(r"ENV\s+BUN_INSTALL_CACHE_DIR=", i)
        ]

        assert assignments, (
            "nothing sets BUN_INSTALL_CACHE_DIR, so bun caches every package it fetches "
            f"under root's home, inside the install's layer: {install}"
        )
        cache = _resolve(workdir, assignments[0].replace('"', "").replace("'", ""))
        assert cache in deleted, (
            f"the RUN that installs leaves bun's install cache at {cache} in its layer: {install}"
        )


class TestNoInstructionGivesTheAppUserWritePastTheDataDirectory:
    """No chown, chmod or COPY flag gives the app's user write past `DATA_DIR`.

    Read over the runtime stage and every stage it copies from, with each target
    resolved against its stage's `WORKDIR`. A chown or a chmod of `/app` in the runtime
    stage also copies every file it touches into one more layer, on every build. Opening
    a mode to reading, and giving a file to root, are let through: neither grants write.

    What it does not read: a mode a tool sets itself, as uv does in making `.venv/.lock`
    writable by everybody; `mkdir -m`; `install` with `-m` or `-o`; a `chgrp`
    followed by `chmod g=u`, whose `g=u` is read as granting nothing; and a stage reached
    through `FROM <stage>` rather than `COPY --from`. A target that `find -exec` or
    `xargs` supplies is unnamed here, so it is refused even inside `DATA_DIR`.
    """

    def test_no_copy_gives_its_files_to_the_app_user_or_opens_them_to_writing(self) -> None:
        stages = _stages(_DOCKERFILE.read_text())
        data_dir = _data_dir(stages[-1])

        offenders = []
        for stage in _reaching_the_runtime(stages):
            for workdir, instruction in _in_stage(stage, data_dir):
                if _keyword(instruction) not in ("COPY", "ADD"):
                    continue
                flags, _, destination = _copy(instruction)
                gives = "chown" in flags and not _to_root(flags["chown"])
                if (gives or _grants_write(flags.get("chmod", ""))) and not _within(
                    data_dir, _target(destination, workdir, data_dir)
                ):
                    offenders.append(instruction)
        assert not offenders, f"a COPY hands the app's user files it may then rewrite: {offenders}"

    def test_no_chown_or_chmod_opens_anything_past_the_data_directory(self) -> None:
        stages = _stages(_DOCKERFILE.read_text())
        data_dir = _data_dir(stages[-1])

        def past(targets: list[str], workdir: str, arguments: list[str]) -> list[str]:
            if not targets:
                return [f"{' '.join(arguments)}, on targets it does not name"]
            return [t for t in targets if not _within(data_dir, _target(t, workdir, data_dir))]

        offenders = []
        for stage in _reaching_the_runtime(stages):
            for workdir, instruction in _in_stage(stage, data_dir):
                if _keyword(instruction) != "RUN":
                    continue
                for arguments in _calls(instruction, "chown"):
                    owner, *targets = _operands(arguments) or [""]
                    if not _to_root(owner):
                        offenders += past(targets, workdir, arguments)
                for arguments in _calls(instruction, "chmod"):
                    mode, *targets = _operands(arguments) or [""]
                    if _grants_write(mode):
                        offenders += past(targets, workdir, arguments)
        assert not offenders, (
            f"a chown or a chmod gives the app's user write access past DATA_DIR: {offenders}"
        )

    def test_the_runtime_stage_gives_the_data_directory_to_the_app_user(self) -> None:
        """Without it a first run with no volume cannot write its database, and the arm
        above passes on a Dockerfile that chowns nothing at all."""
        runtime = _stages(_DOCKERFILE.read_text())[-1]
        data_dir = _data_dir(runtime)

        chowned = [
            target
            for workdir, instruction in _in_stage(runtime, data_dir)
            if _keyword(instruction) == "RUN"
            for arguments in _calls(instruction, "chown")
            for owner, *targets in [_operands(arguments) or [""]]
            if not _to_root(owner)
            for target in targets
            if _within(data_dir, _target(target, workdir, data_dir))
        ]
        assert chowned, "the runtime stage chowns nothing, so DATA_DIR is not the app's"


class TestTheAppUserCanReadWhatItRuns:
    """A directory from the build context reaches the runtime only with its modes opened.

    A `COPY` keeps the modes the checkout gave each file. Under umask 077 that is 0600
    and 0700, so uid 1000 cannot read the root owned `/app`, and the pipeline's
    permissive checkout never shows it. A single file from the context is let through:
    the one the runtime copies, `LICENSE`, is never opened by the process. A directory
    is recognised by looking at the build context, so a glob source is read as files.
    """

    def test_the_runtime_stage_copies_no_directory_from_the_build_context(self) -> None:
        runtime = _stages(_DOCKERFILE.read_text())[-1]
        offenders = []
        for instruction in runtime:
            if _keyword(instruction) in ("COPY", "ADD"):
                flags, sources, _ = _copy(instruction)
                if "from" not in flags and any((_ROOT / s).is_dir() for s in sources):
                    offenders.append(instruction)
        assert not offenders, (
            "the runtime stage copies a directory from the build context, with whatever "
            f"modes the checkout gave it; copy it through a stage that opens them: {offenders}"
        )

    def test_a_stage_the_runtime_copies_from_opens_the_modes_of_what_it_copies(self) -> None:
        stages = _stages(_DOCKERFILE.read_text())
        named = {_name(stage): stage for stage in stages if _name(stage)}
        taken: list[tuple[str, str]] = []
        for instruction in stages[-1]:
            if _keyword(instruction) in ("COPY", "ADD"):
                flags, sources, _ = _copy(instruction)
                if flags.get("from", "").lower() in named:
                    taken += [(flags["from"].lower(), _resolve("/", s)) for s in sources]

        checked, offenders = 0, []
        for name, path in taken:
            workdir, copied, opened = "/", False, False
            for instruction in named[name]:
                keyword = _keyword(instruction)
                if keyword == "WORKDIR":
                    workdir = _resolve(workdir, instruction.split(maxsplit=1)[1])
                elif keyword in ("COPY", "ADD") and "from" not in _copy(instruction)[0]:
                    _, sources, destination = _copy(instruction)
                    landing = _resolve(workdir, destination)
                    if any((_ROOT / s).is_dir() for s in sources) and (
                        _within(landing, path) or _within(path, landing)
                    ):
                        copied, opened = True, False
                elif keyword == "RUN" and copied:
                    for arguments in _calls(instruction, "chmod"):
                        mode, *targets = _operands(arguments) or [""]
                        if (
                            _recursive(arguments)
                            and _opens_to_reading(mode)
                            and any(_within(_resolve(workdir, t), path) for t in targets)
                        ):
                            opened = True
            if copied:
                checked += 1
                if not opened:
                    offenders.append(f"{path} from the {name} stage")
        assert checked, "no stage the runtime copies from takes a directory from the context"
        assert not offenders, (
            "the runtime copies a directory from the build context whose modes nothing "
            f"opened with a chmod -R a+rX after the COPY: {offenders}"
        )


def _ignored(path: str, text: str) -> bool:
    """Whether a `.dockerignore` leaves a context path out, read the way Docker reads it.

    Each pattern is cleaned and anchored at the context root, `**` spans any number of
    directories including none, `*` and `?` stop at a slash, a pattern matching a parent
    directory takes its contents too, and the last pattern to match wins, so a `!` line
    puts a path back. A character class or an escaped character is read literally.
    """
    parents = [path] + [path.rsplit("/", n)[0] for n in range(1, path.count("/") + 1)]
    ignored = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern = posixpath.normpath(line.removeprefix("!").strip()).lstrip("/")
        regex, i = "", 0
        while i < len(pattern):
            if pattern.startswith("**", i):
                i += 3 if pattern.startswith("**/", i) else 2
                regex += ".*" if i >= len(pattern) else "(.*/)?"
                continue
            regex += {"*": "[^/]*", "?": "[^/]"}.get(pattern[i], re.escape(pattern[i]))
            i += 1
        if any(re.fullmatch(regex, parent) for parent in parents):
            ignored = not line.startswith("!")
    return ignored


class TestTheBuildContextCarriesNoSecret:
    """A secret on the developer's disk stays out of the build context at any depth.

    A pattern without a directory matches only at the context root, so `.env` alone
    lets `backend/.env` through, `COPY backend/ .` puts it in the image, and the app
    stage's `a+rX` makes it readable by the app's user. Checked at the root, in each
    directory the Dockerfile copies from the context, and one level below each.
    """

    def test_a_secret_file_is_ignored_wherever_it_sits(self) -> None:
        directories = {""} | {
            source.rstrip("/") + "/" + below
            for stage in _stages(_DOCKERFILE.read_text())
            for instruction in stage
            if _keyword(instruction) in ("COPY", "ADD") and "from" not in _copy(instruction)[0]
            for source in _copy(instruction)[1]
            if (_ROOT / source).is_dir()
            for below in ("", "nested/")
        }
        assert len(directories) > 1, "the Dockerfile copies no directory from the context"
        text = _DOCKERIGNORE.read_text()

        reached = sorted(
            path
            for directory in directories
            for name in (".env", "server.pem", "server.key")
            if not _ignored(path := directory + name, text)
        )
        assert not reached, f"the build context carries a secret the image then ships: {reached}"


class TestTheDockerfileIsReadTheWayDockerReadsIt:
    def test_a_comment_line_inside_a_continued_run_does_not_end_it(self) -> None:
        text = "FROM base AS one\nRUN first \\\n    # an aside\n    && second\n"

        assert _stages(text) == [["FROM base AS one", "RUN first && second"]]
