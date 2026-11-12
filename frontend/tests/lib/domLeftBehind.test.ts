/** Tests for tests/lib/domLeftBehind.ts. */

import { afterEach, describe, expect, it } from "vitest";

import { domLeftBehind } from "./domLeftBehind";

afterEach(() => {
  document.body.replaceChildren();
});

describe("domLeftBehind", () => {
  it("answers nothing for an empty body", () => {
    expect(domLeftBehind("after")).toBeNull();
  });

  it("names a node appended to the body and empties it", () => {
    const stray = document.createElement("div");
    stray.id = "stray-portal";
    document.body.append(stray);

    const message = domLeftBehind("after");

    expect(message).toContain("left 1 node(s)");
    expect(message).toContain('id="stray-portal"');
    expect(document.body.childNodes).toHaveLength(0);
  });

  it("names a bare text node by its text", () => {
    document.body.append("orphaned words");

    expect(domLeftBehind("after")).toContain('"orphaned words"');
  });

  it("blames the previous test by name when asked before a test", () => {
    document.body.append(document.createElement("section"));

    expect(domLeftBehind("before", "tests/a.test.ts > writes late")).toContain(
      "the test before this one in the worker, tests/a.test.ts > writes late:",
    );
  });

  it("says no test was recorded when asked before the first", () => {
    document.body.append(document.createElement("section"));

    expect(domLeftBehind("before")).toContain("which no test recorded");
  });
});
