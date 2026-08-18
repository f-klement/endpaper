/** Tests for src/pages/SettingsPage/components/GoodreadsImport.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { GoodreadsImportOut } from "../../../../src/api/generated/model";
import GoodreadsImport from "../../../../src/pages/SettingsPage/components/GoodreadsImport";
import { renderLocalised } from "../../../utils";

function outcome(
  overrides: Partial<GoodreadsImportOut> = {},
): GoodreadsImportOut {
  return {
    rows_read: 10,
    matched: 6,
    created: 2,
    statuses_updated: 4,
    skipped: 0,
    unmatched_titles: [],
    ...overrides,
  };
}

function renderImport(
  overrides: Partial<Parameters<typeof GoodreadsImport>[0]> = {},
) {
  const props = {
    isUploading: false,
    result: null,
    error: null,
    onUpload: vi.fn(),
    onReviewUnconfirmed: vi.fn(),
    ...overrides,
  };
  renderLocalised(<GoodreadsImport {...props} />);
  return props;
}

/** A CSV the browser would hand over from the file picker. */
function csv(name = "goodreads_library_export.csv"): File {
  return new File(["Title,Author\n"], name, { type: "text/csv" });
}

describe("GoodreadsImport", () => {
  it("explains why there is no account to connect", () => {
    renderImport();
    expect(screen.getByText(/retired its API in 2020/)).toBeInTheDocument();
  });

  describe("choosing a file", () => {
    it("hands the file upwards", async () => {
      const props = renderImport();
      const file = csv();

      await userEvent
        .setup()
        .upload(screen.getByLabelText("Choose export file"), file);

      expect(props.onUpload).toHaveBeenCalledWith(file, true);
    });

    it("passes on the create-missing choice", async () => {
      const props = renderImport();
      const user = userEvent.setup();

      await user.click(
        screen.getByLabelText("Also add books that are not in the library yet"),
      );
      await user.upload(screen.getByLabelText("Choose export file"), csv());

      expect(props.onUpload).toHaveBeenCalledWith(expect.any(File), false);
    });

    it("warns that new books arrive unconfirmed, while that is what will happen", () => {
      // An export says what somebody read, not what is on their shelf, so
      // adding from it cannot assert ownership.
      renderImport();
      expect(
        screen.getByText(
          /an export says what you read, not what is on your shelf/,
        ),
      ).toBeInTheDocument();
    });

    it("drops the warning when nothing new will be added", async () => {
      renderImport();

      await userEvent
        .setup()
        .click(
          screen.getByLabelText(
            "Also add books that are not in the library yet",
          ),
        );

      expect(
        screen.queryByText(/an export says what you read/),
      ).not.toBeInTheDocument();
    });

    it("disables the button while uploading", () => {
      renderImport({ isUploading: true });
      expect(
        screen.getByRole("button", { name: "Importing..." }),
      ).toBeDisabled();
    });
  });

  describe("reporting the result", () => {
    it("breaks the outcome down rather than giving one number", () => {
      renderImport({ result: outcome() });
      expect(
        screen.getByText(
          "10 entries read. 6 matched, 2 added, 4 statuses updated.",
        ),
      ).toBeInTheDocument();
    });

    it("accounts for rows on a shelf it does not map", () => {
      renderImport({ result: outcome({ skipped: 3 }) });
      expect(screen.getByText(/3 entries were on a shelf/)).toBeInTheDocument();
    });

    it("stays quiet about skipped rows when there were none", () => {
      renderImport({ result: outcome({ skipped: 0 }) });
      expect(
        screen.queryByText(/entries were on a shelf/),
      ).not.toBeInTheDocument();
    });

    it("names the books it could not match", () => {
      // "Why did it not pick up X?" is the question after every import.
      renderImport({
        result: outcome({ unmatched_titles: ["Dune", "Neuromancer"] }),
      });
      expect(screen.getByText("Dune")).toBeInTheDocument();
      expect(screen.getByText("Neuromancer")).toBeInTheDocument();
    });

    it("offers to review the newly added books", async () => {
      const props = renderImport({ result: outcome({ created: 2 }) });

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Review them" }));

      expect(props.onReviewUnconfirmed).toHaveBeenCalledOnce();
    });

    it("does not offer a review when nothing was added", () => {
      // Nothing arrived unconfirmed, so there is nothing to confirm.
      renderImport({ result: outcome({ created: 0 }) });
      expect(
        screen.queryByRole("button", { name: "Review them" }),
      ).not.toBeInTheDocument();
    });
  });

  it("shows a rejected file", () => {
    renderImport({
      error: new Error("That does not look like a Goodreads export."),
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Goodreads export");
  });
});
