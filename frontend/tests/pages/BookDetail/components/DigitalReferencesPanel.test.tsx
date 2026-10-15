/** Tests for src/pages/BookDetail/components/DigitalReferencesPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  type DigitalReferenceOut,
} from "../../../../src/api/generated/model";
import DigitalReferencesPanel from "../../../../src/pages/BookDetail/components/DigitalReferencesPanel";
import { renderLocalised } from "../../../utils";

/** One stored reference, as the list route returns it. */
function reference(
  overrides: Partial<DigitalReferenceOut> = {},
): DigitalReferenceOut {
  return {
    id: 1,
    book_id: 7,
    root_label: "Books",
    relative_path: "Frank Herbert/Dune.epub",
    root_confirmed: true,
    size_bytes: 1024,
    file_modified_at: null,
    created_at: "2026-10-01T12:00:00Z",
    confirmed_at: "2026-10-12T12:00:00Z",
    missing_since: null,
    ...overrides,
  };
}

function renderPanel(
  references: DigitalReferenceOut[],
  {
    listError = null,
    forgetting = new Set<number>(),
    locale = Locale.en,
  }: {
    listError?: unknown;
    forgetting?: ReadonlySet<number>;
    locale?: Locale;
  } = {},
) {
  const onForget =
    vi.fn<(reference: DigitalReferenceOut, shownAs: string) => void>();
  const { container } = renderLocalised(
    <DigitalReferencesPanel
      references={references}
      forgetting={forgetting}
      listError={listError}
      error={null}
      onForget={onForget}
    />,
    { locale },
  );
  return { onForget, container };
}

describe("DigitalReferencesPanel", () => {
  it("draws nothing for a book no folder pick has located", () => {
    const { container } = renderPanel([]);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the picked folder and the path beneath it", () => {
    renderPanel([reference()]);

    expect(screen.getByText("Books")).toBeInTheDocument();
    expect(
      screen.getByText((_text, node) =>
        node?.tagName === "P"
          ? node.textContent === "Books/Frank Herbert/Dune.epub"
          : false,
      ),
    ).toBeInTheDocument();
  });

  it("draws a folder name without the control characters it carried", () => {
    // **The raw text is what is stored, and it is not what is drawn.** A right
    // to left override in a folder name reverses everything printed after it.
    renderPanel([reference({ root_label: "Bo\u202Eoks" })]);

    expect(screen.getByText("Books")).toBeInTheDocument();
  });

  it("draws the path beneath it without the control characters it carried", () => {
    // The same rule for the second half: the path is a member's own folder
    // and file names, and an override there reorders the file name after it.
    renderPanel([
      reference({ relative_path: "Frank\u202E Herbert/Dune.epub" }),
    ]);

    expect(
      screen.getByRole("button", {
        name: "Forget Books/Frank Herbert/Dune.epub",
      }),
    ).toBeInTheDocument();
  });

  it("says when the location was last reported", () => {
    renderPanel([reference()]);

    expect(screen.getByText("Last reported Oct 12, 2026")).toBeInTheDocument();
  });

  it("says since when a browser could not find the file", () => {
    renderPanel([reference({ missing_since: "2026-10-14T12:00:00Z" })]);

    expect(
      screen.getByText("Not found since Oct 14, 2026"),
    ).toBeInTheDocument();
  });

  it("flags nothing on a location nobody has reported missing", () => {
    renderPanel([reference()]);

    expect(screen.queryByText(/Not found since/)).not.toBeInTheDocument();
  });

  it("forgets one location by the path a member can read", async () => {
    const stored = reference({ root_label: "Bo\u202Eoks" });
    const { onForget } = renderPanel([stored]);

    await userEvent.click(
      screen.getByRole("button", {
        name: "Forget Books/Frank Herbert/Dune.epub",
      }),
    );

    expect(onForget).toHaveBeenCalledWith(
      stored,
      "Books/Frank Herbert/Dune.epub",
    );
  });

  it("holds the Forget of a location already being forgotten", () => {
    renderPanel([reference({ id: 4 })], { forgetting: new Set([4]) });

    expect(screen.getByRole("button", { name: /^Forget/ })).toBeDisabled();
  });

  it("says the list could not be read rather than drawing no files", () => {
    renderPanel([], { listError: new Error("boom") });

    expect(screen.getByText(/could not be loaded|boom/)).toBeInTheDocument();
  });

  it("speaks German", () => {
    renderPanel([reference({ missing_since: "2026-10-14T12:00:00Z" })], {
      locale: Locale.de,
    });

    expect(screen.getByText("Buchdateien")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /vergessen$/ }),
    ).toBeInTheDocument();
  });
});
