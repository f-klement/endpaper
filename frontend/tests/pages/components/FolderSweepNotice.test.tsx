/** Tests for src/pages/components/FolderSweepNotice.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FolderSweepNotice from "../../../src/pages/components/FolderSweepNotice";
import type { FolderSweep } from "../../../src/pages/hooks";
import { renderWithProviders } from "../../utils";

const CHECKED: FolderSweep = {
  kind: "checked",
  root: "Books",
  seen: 3,
  moved: 0,
  notFound: [{ referenceId: 2, bookId: 20, path: "Gone.epub" }],
  marked: null,
  bookIds: [10],
};

function notice(
  swept: readonly FolderSweep[] | null,
  onMarkMissing = vi.fn<(root: string) => void>(),
) {
  return renderWithProviders(
    <FolderSweepNotice
      swept={swept}
      failed={false}
      isMarking={false}
      onMarkMissing={onMarkMissing}
    />,
  );
}

describe("FolderSweepNotice", () => {
  it("links each file not found to its book", () => {
    notice([CHECKED]);

    expect(screen.getByRole("link", { name: "Gone.epub" })).toHaveAttribute(
      "href",
      "/book/20",
    );
  });

  it("marks them missing only on the press", async () => {
    const onMarkMissing = vi.fn<(root: string) => void>();
    notice([CHECKED], onMarkMissing);
    expect(onMarkMissing).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", { name: "Mark these as missing" }),
    );

    expect(onMarkMissing).toHaveBeenCalledWith("Books");
  });

  it("says a folder holding none of the saved files was taken for another", () => {
    notice([{ kind: "different", root: "Books", saved: 4 }]);

    expect(screen.getByRole("status")).toHaveTextContent(
      /taken for a different folder/,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says nothing for a pick with nothing saved under it", () => {
    const { container } = notice([]);

    expect(container).toBeEmptyDOMElement();
  });
});
