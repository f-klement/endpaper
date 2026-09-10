/**
 * @vitest-environment node
 *
 * Every place that declares this project's licence declares the same one.
 *
 * Four files name it and none of them can see the others: `LICENSE` is the
 * licence, `frontend/package.json` and `backend/pyproject.toml` each carry an
 * SPDX id, and `AboutBadges.tsx` puts a name on a badge a member reads. A
 * licence change that reaches three of the four is silent, and the badge is the
 * one that is silent to everybody except the person it misinforms.
 *
 * **No licence is named here.** `package.json` is read as the source and the
 * other three are compared against it, so this asserts agreement rather than
 * policy: a project that changes licence in all four places passes, which is
 * correct, and one that changes it in three fails. What the licence *is* lives
 * in `LICENSE` and nowhere else. What a member sees on the badge is asserted as
 * text by `AboutBadges.test.tsx`; this file is the four declarations.
 *
 * **Two bounds, and each is the same shape: a licence spelled one way.**
 *
 * - The badge's name and the SPDX id have to be the same string. True of `MIT`,
 *   and under `Apache-2.0` the badge read `Apache 2.0`, a hyphen apart from the
 *   id with nothing comparing them. A licence whose display name differs from
 *   its id fails the badge arm, and that failure is where both names get
 *   recorded.
 * - `LICENSE`'s first line has to read `<id> License`. **Stricter than the
 *   first, and the licence this project just left fails it twice**: the SPDX
 *   Apache title is `Apache License`, not `Apache-2.0 License`, and that file
 *   opened with a blank line. `The MIT License (MIT)`, a common titling of this
 *   same licence, fails it too. A licence whose file titles itself differently
 *   fails that arm, and the remedy is to read the title out of the file's own
 *   first line here rather than to delete the comparison: what it is for is a
 *   `LICENSE` swapped for a different licence entirely.
 *
 * **What this does not cover**: prose. A sentence in a document naming the
 * licence is not a declaration and is not read here, which is why the register
 * carries the switch rather than this file carrying a grep.
 *
 * **`node:fs` rather than `import.meta.glob`**, which `houseRules.test.ts`
 * prefers and which cannot reach `LICENSE` or `backend/`: the glob is rooted at
 * `frontend/`. `conformance/isbn.test.ts` reads across the trees the same way
 * and for the same reason.
 *
 * **The node environment is load bearing here, not tidiness.** Under happy-dom
 * `import.meta.url` is not a `file:` URL and `fileURLToPath` throws before a
 * single assertion runs. The pragma belongs in this docblock rather than in a
 * `//` comment above it, because `vite.config.ts` counts the opt outs with a
 * grep anchored on ` * @vitest-environment node`.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const ROOT = new URL("../../", import.meta.url);

const sha256 = (text: string): string =>
  createHash("sha256").update(text, "utf8").digest("hex");

/**
 * A licence's text less the two things detection does not read.
 *
 * The copyright line is dropped and whitespace is collapsed, because that is
 * what a licence detector does before matching and therefore what decides
 * whether the badges resolve. Pinning the file whole would fire on a copyright
 * year bump, which is the one edit to this file certain to happen and the one
 * that cannot blank a badge.
 *
 * **The bound**: a copyright line is recognised as a line beginning `copyright`,
 * and every such line is dropped from both sides, so **the digest says nothing
 * about who holds the copyright**. Deleting the notice outright or changing the
 * holder passes it. That is what the arm below is for; a licence stating its
 * holder some other way is pinned with the body instead and fails there.
 */
const licenceBody = (text: string): string =>
  text
    .split("\n")
    .filter((line) => !/^copyright\b/i.test(line.trim()))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();

function read(relative: string): string {
  const path = fileURLToPath(new URL(relative, ROOT));
  try {
    return readFileSync(path, "utf8");
  } catch (cause) {
    throw new Error(
      `${relative} is missing or unreadable at ${path}, so the licence ` +
        `declarations cannot be compared. This test refuses to pass by ` +
        `reading nothing.`,
      { cause },
    );
  }
}

/**
 * The SPDX id every other declaration is measured against.
 *
 * Throws at module scope rather than returning an empty string, which would
 * make every assertion below vacuously true: that is the one way this file
 * stops testing anything without going red.
 */
function declaredLicence(): string {
  const parsed = JSON.parse(read("frontend/package.json")) as {
    license?: unknown;
  };
  if (typeof parsed.license !== "string" || parsed.license === "") {
    throw new Error(
      "frontend/package.json declares no licence, so the comparisons in " +
        "licence.test.ts have nothing to measure against.",
    );
  }
  return parsed.license;
}

const DECLARED = declaredLicence();

describe("the project's licence", () => {
  it("is declared as an SPDX id and not as a sentence", () => {
    expect(DECLARED).toMatch(/^[A-Za-z0-9][A-Za-z0-9.+-]*$/);
  });

  it("is the licence the LICENSE file itself carries", () => {
    // The whole line is compared rather than searched: a substring match would
    // pass on a file replaced by a different licence that merely mentions this
    // one, which several licences do.
    expect(read("LICENSE").split("\n")[0]?.trim()).toBe(`${DECLARED} License`);
  });

  it("is what the backend declares", () => {
    const declaration = /^license = "(.+)"$/m.exec(
      read("backend/pyproject.toml"),
    );

    expect(declaration?.[1]).toBe(DECLARED);
  });

  it("is the name the About badge puts in front of a member", () => {
    const badge = /^const LICENCE = "(.+)";$/m.exec(
      read(
        "frontend/src/pages/SettingsPage/AboutSettingsPage/components/AboutBadges.tsx",
      ),
    );

    expect(badge?.[1]).toBe(DECLARED);
  });

  it("has a body nobody has quietly reworded", () => {
    // **A change detector, not a licence validator**, and the difference is
    // worth stating: nothing here can tell a valid licence from an invalid one.
    // What it stops is the failure mode the register calls load bearing. Both
    // badges, the README's and the Docker Hub page's, are shields.io reading
    // the licence GitHub detects from this file, and detection wants the
    // verbatim SPDX text: reword one clause and both badges go blank with every
    // other arm in this file still green. Measured by the design seat, which
    // changed "free of charge" to "without charge" and got 4 passed, exit 0.
    //
    // **The body, not the file**, for the same reason the arm exists: a
    // detector strips the copyright line and collapses whitespace before
    // matching, so a whole file pin fires on a year bump and a trailing space,
    // neither of which can blank a badge. Both were measured against the whole
    // file pin this replaces, and both went red.
    //
    // **When this fails, the digest is the last thing to update.** Read the
    // file against the SPDX text for the id above first, and update the digest
    // in the same commit that changed the licence, never on its own.
    expect(
      sha256(licenceBody(read("LICENSE"))),
      "LICENSE's body has changed. Read it against the SPDX text for the id " +
        "declared in package.json before touching this digest: GitHub detects " +
        "a reworded licence as NOASSERTION, and the README and Docker Hub " +
        "badges go blank without failing anything. A copyright line or a " +
        "whitespace edit does not reach this arm. Update the digest in the " +
        "commit that changed the licence, never on its own.",
    ).toBe("7c9b48b52decb9837c70f608678129e1ac79e056829c8d1e82e8cdd8aed562f8");
  });

  it("still says who holds the copyright, which the digest cannot", () => {
    // The digest arm above drops every copyright line before hashing, so on its
    // own it accepts a `LICENSE` with the notice deleted or the holder changed:
    // measured, both pass all the other arms. The whole file pin this replaced
    // refused them, and that is what it refused that the narrower one accepts.
    //
    // A shape rather than a second digest, so the year keeps its own arm's
    // freedom to move: MIT requires the notice to travel with every copy, and a
    // copy carrying somebody else's name or no name is the failure.
    //
    // **A holder added beside this one is the case neither arm sees**, measured:
    // the digest drops every copyright line and this arm is satisfied by finding
    // the original. A second contributor is a real event and it changes who has
    // to agree to the next relicence, so it is named here rather than left to be
    // discovered.
    expect(read("LICENSE")).toMatch(
      /^Copyright \(c\) [\d-]+ Florian Klement$/m,
    );
  });

  it("travels inside the image, which is a copy like any other", () => {
    // MIT conditions the grant on the notice being included in every copy, and
    // an image is a copy. Apache-2.0 clause 4(a) wanted the same and the line
    // was missing for as long as that licence stood, which is why this arm
    // exists rather than being left to a reviewer of the Dockerfile.
    //
    // **Only the last stage counts, and this reads only the last stage.** A
    // `COPY LICENSE` in a builder stage ships nothing: that stage is discarded.
    // Measured against the first version of this arm, which matched the whole
    // file: the instruction moved into the frontend build stage and six arms
    // passed green, which is the state the arm exists to forbid.
    //
    // The filename ends on whitespace rather than a word boundary, because
    // `\b` matches before a dot and `COPY LICENSE.md` would have satisfied it.
    //
    // **The bound: it reads the instruction, not a built image.** A build
    // targeting an earlier stage, or an image assembled some other way, is
    // outside it, and closing that means inspecting a built image, which a
    // frontend unit suite is the wrong place for.
    const dockerfile = read("Dockerfile");
    const lastStage = dockerfile.slice(dockerfile.lastIndexOf("\nFROM "));

    expect(lastStage).toMatch(/^COPY LICENSE\s/m);
  });
});
