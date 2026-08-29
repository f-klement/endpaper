/** Tests for src/lib/languageName. */

import { describe, expect, it } from "vitest";

import { languageName } from "../../src/lib/languageName";

describe("languageName", () => {
  it("names a language in the reader's own language", () => {
    expect(languageName("fr", "en")).toBe("French");
    expect(languageName("fr", "de")).toBe("Französisch");
  });

  it("falls back to the code for a Wikipedia edition Intl refuses", () => {
    // **These throw rather than falling back**, which is the whole reason this
    // helper exists: `Intl.DisplayNames.of` raises a `RangeError` on a string
    // that is not a well formed language tag, and `fallback: "code"` does not
    // cover that case. All four are real Wikipedia subdomains and all four are
    // reachable, because the article link's last tier takes any edition at all.
    for (const code of ["bat-smg", "zh-yue", "roa-rup", "cbk-zam"]) {
      expect(languageName(code, "en")).toBe(code);
    }
  });

  it("falls back to the code for a well formed tag with no name", () => {
    // The other half, and it is a different mechanism: `simple` and `xx` are
    // well formed, so `Intl` answers for them itself rather than throwing.
    //
    // **This test guards nothing in this file and is kept anyway**, which is
    // worth saying because the first version of this comment implied otherwise.
    // Measured: it survives `fallback: "none"`, the option being removed
    // entirely, and `?? code` being removed, because `"code"` is the ECMA-402
    // default and the coalesce gives the same answer. The option is spelled out
    // for a reader, not for behaviour.
    //
    // **And the diagonal is not this test's either**, which is what the first
    // version of this comment claimed. Measured against a helper that returns
    // the code for everything: the first test fails and both this one and the
    // one above pass, so the first is what shows the helper does more than echo
    // its argument. What this one earns is a smaller thing said plainly: it
    // records that the two fallbacks have different causes, so a later reader
    // does not conclude from the test above that `Intl` throws on everything it
    // has no name for.
    expect(languageName("simple", "en")).toBe("simple");
    expect(languageName("xx", "en")).toBe("xx");
  });
});
