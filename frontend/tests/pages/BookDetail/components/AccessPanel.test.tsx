/**
 * Tests for src/pages/BookDetail/components/AccessPanel.tsx.
 *
 * A digital copy is requested and granted rather than lent: the requester sees
 * where their request stands, the holder answers it.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AccessStatus,
  type AccessRequestOut,
  BookFormat,
} from "../../../../src/api/generated/model";
import AccessPanel from "../../../../src/pages/BookDetail/components/AccessPanel";
import { makeBook, makeUser, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

const holder = makeUser({ id: 1, username: "ana" });
const asker = makeUser({ id: 2, username: "ben" });
const merger = makeUser({ id: 3, username: "cy" });

function asked(status: AccessStatus, id = 10): AccessRequestOut {
  return {
    id,
    book_id: 5,
    status,
    requested_by: asker,
    holder,
    requested_at: "2026-10-15T09:00:00Z",
    decided_by: status === AccessStatus.pending ? null : holder,
    decided_at: status === AccessStatus.pending ? null : "2026-10-15T10:00:00Z",
  };
}

function renderPanel(
  viewer: number,
  requests: AccessRequestOut[],
  addedBy = holder,
) {
  const onRequest = vi.fn<() => void>();
  const onDecide = vi.fn<(requestId: number, granted: boolean) => void>();
  renderLocalised(
    <AccessPanel
      book={makeBook({ id: 5, format: BookFormat.ebook, added_by: addedBy })}
      currentUserId={viewer}
      requests={requests}
      isBusy={false}
      onRequest={onRequest}
      onDecide={onDecide}
    />,
  );
  return { onRequest, onDecide };
}

describe("a member who does not hold the copy", () => {
  it("asks for access", async () => {
    const { onRequest } = renderPanel(asker.id, []);
    await userEvent.setup().click(screen.getByText("Request access"));
    expect(onRequest).toHaveBeenCalledOnce();
  });

  it("is told who granted access and where the file comes from", () => {
    renderPanel(asker.id, [asked(AccessStatus.granted)]);
    expect(
      screen.getByText("ana granted you access. Ask them for the file."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Request access")).not.toBeInTheDocument();
  });

  it("may ask again after a refusal", () => {
    renderPanel(asker.id, [asked(AccessStatus.declined)]);
    expect(screen.getByText("Request access")).toBeInTheDocument();
  });
});

describe("the holder", () => {
  it("grants a waiting request", async () => {
    const { onDecide } = renderPanel(holder.id, [asked(AccessStatus.pending)]);
    await userEvent.setup().click(screen.getByText("Grant"));
    expect(onDecide).toHaveBeenCalledWith(10, true);
  });

  it("is the one a request names, not whoever added the entry it moved to", () => {
    // After a merge the entry's adder is somebody the request was never
    // addressed to; the server does not list it to them, and nor does this.
    renderPanel(merger.id, [asked(AccessStatus.pending)], merger);
    expect(screen.queryByText("Grant")).not.toBeInTheDocument();
  });

  it("is offered no request of their own", () => {
    renderPanel(holder.id, []);
    expect(screen.queryByText("Request access")).not.toBeInTheDocument();
  });
});
