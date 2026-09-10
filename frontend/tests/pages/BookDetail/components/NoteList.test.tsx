/**
 * Tests for src/pages/BookDetail/components/NoteList.tsx.
 *
 * The privacy arms are the point of this file. A note's `is_private` is the
 * server's answer and the component may not re-derive it from authorship, so
 * the two states are asserted on a diagonal: the reader's own shared note
 * stays unmarked and another member's private note stays marked. Either arm
 * alone passes on the wrong implementation.
 */

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Locale } from "../../../../src/api/generated/model";
import { Icon } from "../../../../src/components";
import NoteList from "../../../../src/pages/BookDetail/components/NoteList";
import { makeNote, makeUser, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

const READER = makeUser({ id: 1, username: "ada" });

const MARKER = "Only visible to me";

/**
 * The note card a given note's text sits in.
 *
 * Every privacy arm below scopes to a row through this rather than counting
 * markers across the list. A count says how many markers were drawn and not
 * which note carries one, so it passes on an implementation that puts the
 * marker on the wrong row: measured, a mutation drawing it on `notes[0]`
 * whenever any note in the list is private survived all twelve arms with
 * `SUITE EXIT: 0`. That shape is reachable in production on the ordinary
 * post import book, one shared note beside one imported private one.
 */
function cardFor(content: string): HTMLElement {
  const card = screen.getByText(content).closest("div");
  if (card === null) throw new Error(`no note card around "${content}"`);
  return card;
}

function markerIn(content: string): HTMLElement | null {
  return within(cardFor(content)).queryByText(MARKER);
}

function render(
  notes: ReturnType<typeof makeNote>[],
  locale: Locale = Locale.en,
) {
  return renderLocalised(
    <NoteList
      notes={notes}
      currentUser={READER}
      isAdding={false}
      onAdd={vi.fn()}
      onEdit={vi.fn()}
      onRemove={vi.fn()}
    />,
    { locale },
  );
}

describe("a note the rest of the library cannot see", () => {
  it("says so on that note", () => {
    render([makeNote({ is_private: true, content: "An imported review" })]);

    expect(markerIn("An imported review")).toBeInTheDocument();
  });

  it("leaves a shared note unmarked", () => {
    render([makeNote({ is_private: false, content: "Loved the ending" })]);

    expect(markerIn("Loved the ending")).toBeNull();
  });

  it("marks the reader's own note only when the server called it private", () => {
    render([
      makeNote({ user_id: READER.id, is_private: false, content: "Mine" }),
    ]);

    expect(markerIn("Mine")).toBeNull();
  });

  it("marks a private note the reader did not write", () => {
    render([
      makeNote({ user_id: READER.id + 1, is_private: true, content: "Theirs" }),
    ]);

    expect(markerIn("Theirs")).toBeInTheDocument();
  });

  it("marks the private row and not the shared one beside it", () => {
    render([
      makeNote({ id: 1, is_private: false, content: "Shared thought" }),
      makeNote({ id: 2, is_private: true, content: "Private thought" }),
    ]);

    expect(markerIn("Private thought")).toBeInTheDocument();
    expect(markerIn("Shared thought")).toBeNull();
    // Kept beside the two row assertions rather than replaced by them: those
    // two say the right rows are right, and this says no third marker was
    // drawn anywhere else on the list.
    expect(screen.getAllByText(MARKER)).toHaveLength(1);
  });

  it("draws a lock beside the words, which carry the meaning between them", () => {
    // The marker ships with no fill behind it, so the lock and the phrase are
    // the whole of it. Compared against what `Icon` renders for `lock` rather
    // than against a copied path string, which would go stale silently.
    render([makeNote({ is_private: true, content: "An imported review" })]);
    const { container } = renderLocalised(<Icon name="lock" />);

    // The right side is asserted before it is compared against. Both sides are
    // optional chained and `getAttribute` returns null for a missing one, so
    // `undefined === undefined` would pass: were `lock` ever drawn as anything
    // but one `<path d>`, this arm would stop asserting rather than go red, on
    // the element carrying half of what the marker means.
    const expected = container.querySelector("path")?.getAttribute("d");
    expect(expected).toBeTruthy();

    const marker = markerIn("An imported review");
    expect(marker?.querySelector("path")?.getAttribute("d")).toBe(expected);
  });

  it("keeps the lock big enough to be a lock", () => {
    // The arm above verifies the glyph's identity and would pass on one drawn
    // at zero size: happy-dom computes no layout, so `w-0 h-0` is invisible to
    // every other arm here. Measured: that mutation survived all thirteen.
    // Read as a shape, both utilities parsed and required positive, rather
    // than as a blocklist of the spellings that happen to be wrong today.
    render([makeNote({ is_private: true, content: "An imported review" })]);

    const icon = markerIn("An imported review")?.querySelector("svg");
    const classes = icon?.getAttribute("class") ?? "";
    const width = /\bw-(\d+(?:\.\d+)?)\b/.exec(classes);
    const height = /\bh-(\d+(?:\.\d+)?)\b/.exec(classes);

    expect(width).not.toBeNull();
    expect(height).not.toBeNull();
    expect(Number(width?.[1])).toBeGreaterThan(0);
    expect(Number(height?.[1])).toBeGreaterThan(0);
  });

  it("keeps a dark tier for the marker's ink", () => {
    // Deleting `dark:text-paper-300` alone is the tidy-up nothing else here
    // would catch, and it takes the marker from 7.00 (everforest) to 11.64
    // (endpaper) in dark down to 1.36 (nord) to 1.93 (kanagawa), while the
    // light half stays at 5.30 to 8.80 so a reviewer in light mode sees
    // nothing wrong. Measured: that mutation survived all thirteen arms.
    //
    // The shape, not the tier: this asserts a dark variant exists, so
    // re-tiering the marker on evidence stays free. The structural version of
    // this rule belongs beside the `hover:text-` pairing in
    // `frontend/tests/houseRules.test.ts` and covers the whole tree; that file
    // is another trio's this wave, so it is raised in the session note.
    render([makeNote({ is_private: true, content: "An imported review" })]);

    expect(markerIn("An imported review")?.getAttribute("class")).toMatch(
      /\bdark:text-/,
    );
  });
});

describe("the default a member writes under", () => {
  it("is stated whether or not they hold a private note to contrast with", () => {
    render([]);

    expect(
      screen.getByText(
        "Notes added here are visible to every member who can see this book.",
      ),
    ).toBeInTheDocument();
  });

  it("reaches the box a note is typed in, for a reader who sees no layout", () => {
    render([]);

    const hint = screen.getByText(
      "Notes added here are visible to every member who can see this book.",
    );
    expect(screen.getByLabelText("Add a note")).toHaveAttribute(
      "aria-describedby",
      hint.id,
    );
    expect(hint.id).not.toBe("");
  });

  it("still reaches it when a second list is on the page", () => {
    // A literal id survives the test above and breaks here: both hints would
    // carry the same one, so both textareas would be described by the first
    // and a screen reader on the second list would be told about a form it is
    // not in. Nothing about that is visible, which is why it is pinned.
    renderLocalised(
      <div>
        <NoteList
          notes={[]}
          currentUser={READER}
          isAdding={false}
          onAdd={vi.fn()}
          onEdit={vi.fn()}
          onRemove={vi.fn()}
        />
        <NoteList
          notes={[]}
          currentUser={READER}
          isAdding={false}
          onAdd={vi.fn()}
          onEdit={vi.fn()}
          onRemove={vi.fn()}
        />
      </div>,
    );

    const described = screen
      .getAllByLabelText("Add a note")
      .map((box) => box.getAttribute("aria-describedby"));
    const hints = screen
      .getAllByText(
        "Notes added here are visible to every member who can see this book.",
      )
      .map((hint) => hint.id);

    expect(described).toHaveLength(2);
    expect(new Set(described).size).toBe(2);
    expect(described).toEqual(hints);
  });
});

describe("a German reader is told the same two things", () => {
  it("marks a private note", () => {
    render([makeNote({ is_private: true })], Locale.de);

    expect(screen.getByText("Nur für mich sichtbar")).toBeInTheDocument();
  });

  it("states the default above the form", () => {
    render([], Locale.de);

    expect(
      screen.getByText(
        "Hier hinzugefügte Notizen sind für alle Mitglieder sichtbar, die dieses Buch sehen können.",
      ),
    ).toBeInTheDocument();
  });
});

describe("nothing offers to change a note's visibility", () => {
  it("draws the marker as text rather than as a control", () => {
    render([makeNote({ is_private: true })]);

    expect(screen.getByText("Only visible to me").closest("button")).toBeNull();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("offers no privacy control beside the box a note is typed in", () => {
    render([]);

    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button").map((button) => button.textContent),
    ).toEqual(["Add"]);
  });
});
