/** Tests for src/pages/BookDetail/components/CustomFieldsPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  CustomFieldOut,
  CustomFieldValueOut,
} from "../../../../src/api/generated/model";
import CustomFieldsPanel from "../../../../src/pages/BookDetail/components/CustomFieldsPanel";
import { renderLocalised } from "../../../utils";

const LINK: CustomFieldOut = { id: 1, name: "Calibre-web", kind: "url" };
const TEXT: CustomFieldOut = { id: 2, name: "Bought from", kind: "text" };

interface Callbacks {
  onSuccess: () => void;
  onError: () => void;
}

function filled(overrides: Partial<CustomFieldValueOut> = {}) {
  return {
    field_id: 1,
    name: "Calibre-web",
    kind: "url",
    value: "https://calibre.example/book/12",
    href: "https://calibre.example/book/12",
    ...overrides,
  } as CustomFieldValueOut;
}

function renderPanel(overrides = {}) {
  const props = {
    definitions: [LINK, TEXT],
    values: [filled()],
    isSaving: false,
    error: null,
    // Answers success unless a test overrides it. A stub that never calls
    // back would leave the editor open in every test and hide the one thing
    // these assertions are about.
    onSave: vi.fn((_id: number, _value: string, callbacks: Callbacks) =>
      callbacks.onSuccess(),
    ),
    ...overrides,
  };
  renderLocalised(<CustomFieldsPanel {...props} />);
  return props;
}

describe("CustomFieldsPanel", () => {
  it("draws nothing at all when the library has defined no fields", () => {
    // A household that never uses this feature never sees it. An empty panel
    // with an Edit button would be the opposite.
    const { container } = renderLocalised(
      <CustomFieldsPanel
        definitions={[]}
        values={[]}
        isSaving={false}
        error={null}
        onSave={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("still reports a failed request when there is nothing to draw", () => {
    // With no definitions the whole panel is absent, so an early return on
    // error would make a failed fetch invisible rather than quiet.
    renderLocalised(
      <CustomFieldsPanel
        definitions={[]}
        values={[]}
        isSaving={false}
        error={new Error("Could not reach the server.")}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByText("Could not reach the server.")).toBeInTheDocument();
  });

  it("shows a field the book has something in", () => {
    renderPanel();

    expect(screen.getByText("Calibre-web")).toBeInTheDocument();
  });

  it("shows nothing for a field with no value", () => {
    // User story 4, and the reason editing is a mode: reading a book's page
    // shows what is there rather than a column of empty boxes.
    renderPanel();

    expect(screen.queryByText("Bought from")).not.toBeInTheDocument();
  });

  it("renders a url field as a link that opens away from the app", () => {
    renderPanel();

    const link = screen.getByRole("link", {
      name: "https://calibre.example/book/12",
    });
    expect(link).toHaveAttribute("href", "https://calibre.example/book/12");
    expect(link).toHaveAttribute("target", "_blank");
    // Without `noopener` the opened page can reach back through
    // `window.opener`, and this one goes to a system the app knows nothing
    // about.
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders a value with no target as text", () => {
    renderPanel({ values: [filled({ href: null, value: "not a link" })] });

    expect(screen.getByText("not a link")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a row whose value and href differ as text", () => {
    // The sharpest phishing case, and the one the server's read end now stops:
    // the link text is `value` and the destination is `href`, so a row where
    // they differ names one registrable domain and goes to another. Repeated
    // here rather than trusted, because this module exists for the row the
    // server never wrote.
    renderPanel({
      values: [
        filled({
          value: "https://calibre.example\u3002evil.example/x",
          href: "https://calibre.example.evil.example/x",
        }),
      ],
    });

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.getByText("https://calibre.example\u3002evil.example/x"),
    ).toBeInTheDocument();
  });

  it.each([
    ["a separator", "https://calibre.example\u3002evil.example/x"],
    ["a percent escape", "https://calibre.example%2eevil.example/x"],
  ])("renders %s in the host as text rather than a link", (_name, value) => {
    // Both read as a host this household trusts and resolve to
    // `evil.example`. The server rewrites the first and refuses the second, so
    // a value this app stored carries neither; this is the row the server
    // never saw.
    //
    // **Text, not a resolved link**, and that is the point: the link text is
    // the stored `value` and the destination is `href`, so resolving here
    // would put two different registrable domains in one anchor, which is a
    // sharper phishing case than leaving it unlinked.
    renderPanel({ values: [filled({ value, href: value })] });

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(value)).toBeInTheDocument();
  });

  it("refuses to link a target the server should never have sent", () => {
    // Defence in depth rather than a hypothetical: React 19 renders
    // `href="javascript:..."` without a warning, so a component that trusts
    // the server here is trusting it for something the framework will not
    // check.
    renderPanel({
      values: [filled({ href: "javascript:alert(1)", value: "click me" })],
    });

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("click me")).toBeInTheDocument();
  });

  it("offers every definition once editing, filled or not", async () => {
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));

    expect(screen.getByLabelText("Calibre-web")).toHaveValue(
      "https://calibre.example/book/12",
    );
    expect(screen.getByLabelText("Bought from")).toHaveValue("");
  });

  it("writes only the fields that changed", async () => {
    // Writing every field would send one request per definition to store what
    // is already stored, and each would invalidate the list again.
    const props = renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));
    await userEvent.type(screen.getByLabelText("Bought from"), "Oxfam");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onSave).toHaveBeenCalledTimes(1);
    expect(props.onSave).toHaveBeenCalledWith(2, "Oxfam", expect.anything());
  });

  it("clears a field by emptying it", async () => {
    const props = renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));
    await userEvent.clear(screen.getByLabelText("Calibre-web"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onSave).toHaveBeenCalledWith(1, "", expect.anything());
  });

  it("writes nothing when the edit is cancelled", async () => {
    const props = renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));
    await userEvent.type(screen.getByLabelText("Bought from"), "Oxfam");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(props.onSave).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Bought from")).not.toBeInTheDocument();
  });

  it("keeps what was typed when the server refuses it", async () => {
    // The 422 on a url field exists so the member can be told; closing the
    // editor first threw away the half that makes the message actionable, and
    // the only way forward was to reopen and retype.
    const props = renderPanel({
      onSave: vi.fn((_id: number, _value: string, callbacks: Callbacks) =>
        callbacks.onError(),
      ),
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));
    await userEvent.clear(screen.getByLabelText("Calibre-web"));
    await userEvent.type(screen.getByLabelText("Calibre-web"), "not a url");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onSave).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Calibre-web")).toHaveValue("not a url");
  });

  it("closes the editor once every write has landed", async () => {
    renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));
    await userEvent.type(screen.getByLabelText("Bought from"), "Oxfam");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.queryByLabelText("Bought from")).not.toBeInTheDocument();
  });

  it("keeps every draft when only one of two writes is refused", async () => {
    // A partial failure is the case a per-field close would get wrong: one
    // field lands, the other 422s, and reopening has to show both drafts.
    const props = renderPanel({
      onSave: vi.fn((id: number, _value: string, callbacks: Callbacks) =>
        id === 1 ? callbacks.onError() : callbacks.onSuccess(),
      ),
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit details" }));
    await userEvent.clear(screen.getByLabelText("Calibre-web"));
    await userEvent.type(screen.getByLabelText("Calibre-web"), "not a url");
    await userEvent.type(screen.getByLabelText("Bought from"), "Oxfam");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onSave).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("Calibre-web")).toHaveValue("not a url");
    expect(screen.getByLabelText("Bought from")).toHaveValue("Oxfam");
  });

  it("says so when the book has nothing filled in", () => {
    renderPanel({ values: [] });

    expect(screen.getByText("Nothing filled in yet")).toBeInTheDocument();
  });

  it("shows what the server refused", () => {
    renderPanel({ error: new Error("That is not a web address.") });

    expect(screen.getByText("That is not a web address.")).toBeInTheDocument();
  });
});
