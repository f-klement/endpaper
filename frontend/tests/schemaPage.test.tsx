/**
 * Tests for tests/schemaPage.tsx: what the oracle refuses, each over a page
 * that asks for nothing, so the one thing on screen is the thing judged.
 */

import { useQuery } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { forget, overSchema, scripted } from "./schemaPage";

afterEach(forget);

/** What the oracle says of `ui`. */
async function judged(ui: ReactElement): Promise<readonly string[]> {
  return (await overSchema(ui, scripted([]))).problems;
}

/** A page whose query fails with a throw of its own, shown as an alert. */
function Failing() {
  const query = useQuery({
    queryKey: ["failing"],
    queryFn: (): never => {
      throw new TypeError("it broke");
    },
  });
  return query.error ? <div role="alert">{query.error.message}</div> : null;
}

describe("the schema page oracle", () => {
  it("refuses an alert holding nothing but an invisible character", async () => {
    // A zero width space survives `trim()`, so an alert of one read as words.
    expect(
      await judged(
        <div role="alert">
          {"\u200b"}
          <button>Try again</button>
        </div>,
      ),
    ).toEqual(["raised an alert saying nothing"]);
  });

  it("refuses NaN in a value a screen reader announces", async () => {
    const spoken: Record<string, string> = { "aria-valuenow": "NaN" };
    expect(await judged(<div role="progressbar" {...spoken} />)).toEqual([
      'showed NaN in "NaN"',
    ]);
  });

  it("refuses the infinity sign a number format prints", async () => {
    expect(await judged(<p>{(1 / 0).toLocaleString("en")}</p>)).toEqual([
      'showed \u221e in "\u221e"',
    ]);
  });

  it("refuses a query failing with a throw rather than an answer", async () => {
    // The alert says something, so only the failure's kind gives it away.
    expect(await judged(<Failing />)).toEqual([
      "failed with TypeError: it broke, which no answer is",
    ]);
  });
});
