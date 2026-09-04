/**
 * Tests for src/i18n/de.ts, and specifically for the one property the type
 * cannot see.
 *
 * `de.ts` is typed as `Messages`, so a missing translation is a compile error.
 * **Nothing in the type system can see how German addresses the reader**, and
 * German makes you choose: `du` for a household, `Sie` for an institution.
 *
 * The answer here is to choose neither. Decided by the owner on 2026-09-03,
 * "rephrase the german version, so we dont need to keep two versions for the
 * same language", after a formal overlay had been built and measured. So this
 * file is **one catalogue that addresses the reader in no register at all**,
 * and these are the rules that keep it that way.
 *
 * ## What that costs, and why it is affordable
 *
 * German has more address free machinery than English does, which is why 82
 * strings could be rephrased without inventing a stilted sentence:
 *
 * | device | example |
 * |---|---|
 * | the infinitive, for every instruction | "Prüfe die Ziffern" became "Bitte die Ziffern prüfen" |
 * | `eigen-`, for a possessive that carries weight | "Deine Lektüre" became "Eigene Lektüre" |
 * | a plain article, for one that does not | "Deine Bibliothek konnte nicht geladen werden" became "Die Bibliothek …" |
 * | the passive and `lässt sich` | "Du kannst das Buch trotzdem von Hand anlegen" became "Das Buch lässt sich trotzdem von Hand anlegen" |
 * | `wer …`, for a conditional about the reader | "Wenn dir Endpaper gefällt und du …" became "Wer Endpaper mag und …" |
 *
 * **One string lost voice rather than meaning**, and it is named here rather
 * than in a register a reader of this file would have to go and find:
 * `quotes.noteLabel` went from the invitation "Was du dazu sagen möchtest" to
 * the plain label "Anmerkung dazu".
 *
 * The criterion, because a count with no criterion is not a measurement: a
 * rewrite loses voice when it replaces a person bearing stance with a nominal
 * or impersonal declarative, so the German reads cooler than the English, **and
 * only where the English is an invitation or an aside rather than a statement**.
 * Without that second half it admits three: "Could not load your library" and
 * its neighbours also lost a possessive, but a statement reads at the same
 * temperature in both languages and nothing was given up. The
 * design seat counted seven against that criterion on the first draft. Six
 * were then repaired rather than accepted: `appearance.wallpaperSurprise` is
 * the reader addressing the app and no register applies to it, so "Überrasch
 * mich" is restored; `appearance.previewEmpty`, `trash.emptyHint`,
 * `login.tagline` and `error.500.message` were reworded to keep the stance
 * without the address; and `collections.emptyHint` carries the owner's own
 * phrase.
 *
 * ## The blind spot, which the overlay had too
 *
 * **An informal imperative is invisible to any rule here.** A German imperative
 * is a bare verb stem and is homographic with a noun and with the third person:
 * "Suche den Code" is an instruction and "Suche läuft" is a noun. Nothing short
 * of parsing German separates them, so a new string added in the imperative
 * still has to be caught by a reader.
 *
 * @vitest-environment node
 */

import { describe, expect, it } from "vitest";

import { de } from "../../src/i18n";

/**
 * Second person informal.
 *
 * **Not "every spelling", which is what this comment used to claim.** Two
 * seats found that false independently, and the two exceptions differ in kind:
 *
 * * **`ihr`, bare and with no suffix.** It is the nominative of the same
 *   plural paradigm as `euch` and `eure`, so it is the likeliest way a `du`
 *   comes back: this file said "Eure Schlagwörter" until 2026-09-03. Measured
 *   over 888 values, standalone `ihr` occurs **0 times**, while the suffixed
 *   forms occur **8 times across 7 strings**, every one the third person
 *   possessive ("behalten **ihren** Link", "in **ihrer** Umgebung"). So the
 *   bare form is free to add and `ihr\w*` would fail the build on seven
 *   strings. That is why this one alternative carries no `\w*` and its
 *   neighbours do.
 *
 *   **Seven and eight are both right and are different units**, strings and
 *   occurrences: `settings.overduePrivacyNote` carries two in one value. That
 *   gap is the whole of it, and a reader reconciling one number to the other
 *   would make it wrong, so the test below recomputes both rather than leaving
 *   a comment asking to be trusted.
 * * **`dein\w*` matched `Deinstallation`**, which is `de` plus `install` and
 *   nothing to do with the possessive. `(?!st)` is narrower than listing the
 *   paradigm: a list drops `deins`, `deinetwegen` and `deinerseits`, and the
 *   only German words beginning `deinst` are that one and its verb.
 *
 * The remaining inexactness is `SET_PHRASES`, where a word matched here is a
 * noun rather than an address.
 */
const INFORMAL = /\b(?:du|dich|dir|dein(?!st)\w*|ihr|euch|eu(?:er|re)\w*)\b/i;

/** Second person formal, in the spellings that carry a capital of their own. */
const FORMAL_ALL = /\b(?:Sie|Ihnen|Ihre?[mnrs]?)\b/g;

/**
 * Idioms in which one of those words is a noun rather than an address.
 *
 * **Matched as a phrase, deliberately, and not keyed on the string it appears
 * in.** Exempting `collections.emptyHint` would switch the rule off for a two
 * hundred character sentence, and the next edit to it could reintroduce a real
 * `du` with nothing to say so. Removing the phrase and testing what is left
 * keeps every other word in that string under the rule.
 *
 * "Mein und Dein" is the fixed German phrase for the boundary between what is
 * one person's and what is another's, as in "Mein und Dein verwechseln". Both
 * halves are capitalised nouns there; `Dein` is not the possessive pronoun and
 * carries no address. Chosen by the owner over two candidates that needed no
 * exemption, because they flattened the sentence.
 */
const SET_PHRASES = ["Mein und Dein"];

/**
 * **Word bounded, and a plain `split` here was wrong.** Removing the phrase as
 * a raw substring turns "Mein und Deine Bücher" into "e Bücher", which no
 * longer matches `dein\w*`, so a real possessive one letter longer than the
 * idiom would have been stripped into silence. Caught by the last test in this
 * file rather than by reading, which is why that test exists.
 */
const escapeRegExp = (literal: string) =>
  literal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const SET_PHRASE_PATTERNS = SET_PHRASES.map(
  // Escaped, because a future phrase carrying a metacharacter would either
  // throw at module load or, with a leading non word character, make the `\b`
  // never match and switch the strip off in silence.
  (phrase) => new RegExp(`\\b${escapeRegExp(phrase)}\\b`, "gu"),
);

const withoutSetPhrases = (value: string) =>
  SET_PHRASE_PATTERNS.reduce(
    (rest, pattern) => rest.replace(pattern, " "),
    value,
  );

/**
 * Whether a capital here is explained by a sentence starting.
 *
 * **One predicate, used by both rules below, and that is load bearing.** They
 * are complements: `formalAddressIn` reports every match that is not a
 * sentence start and `openings` pins every match that is, so between them no
 * match goes unaccounted for. Written out twice they could drift apart, and a
 * match falling into the gap would be reported by neither. Demonstrated by the
 * design seat: widening one to also count an opening quote lets
 * `Fertig. „Sie haben Post", steht dort.` pass both.
 */
const isSentenceStart = (before: string) =>
  before === "" || /[.!?:]\s+$/.test(before) || /["'(„»]$/.test(before);

/** Formal address, ignoring a capital that a sentence start explains. */
function formalAddressIn(value: string): string[] {
  const found: string[] = [];
  for (const match of value.matchAll(FORMAL_ALL)) {
    if (isSentenceStart(value.slice(0, match.index))) continue;
    found.push(match[0]);
  }
  return found;
}

const SIE_IS_THE_THING: Record<string, string[]> = {
  // "Sie wird dort geändert", about the address.
  "account.email.fromDirectory": ["Sie wird"],
  // "Sie versteckt keines", about the collection.
  "collections.explain": ["Sie versteckt"],
};

function openings(value: string): string[] {
  const found: string[] = [];
  for (const match of value.matchAll(FORMAL_ALL)) {
    if (!isSentenceStart(value.slice(0, match.index))) continue;
    const after = value.slice(match.index! + match[0].length);
    const next = /^\s+(\p{L}+)/u.exec(after);
    found.push(next ? `${match[0]} ${next[1]}` : match[0]);
  }
  return found;
}

describe("the German catalogue", () => {
  it("addresses the reader in no register", () => {
    const offenders = Object.entries(de)
      .filter(([, value]) => INFORMAL.test(withoutSetPhrases(value)))
      .map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it("does not address the reader formally either", () => {
    // The published catalogue used to be the exception, addressing a visitor
    // as Sie while the rest of the app said du. One address free file needs no
    // exception, so it lost one: `public.noResultsHint` was the last string
    // carrying any, and it is now an infinitive like every other instruction.
    const offenders = Object.entries(de)
      .filter(([, value]) => formalAddressIn(value).length > 0)
      .map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it("opens a sentence with Sie only where it names a thing", () => {
    const found = Object.fromEntries(
      Object.entries(de)
        .map(([key, value]) => [key, openings(value)] as const)
        .filter(([, hits]) => hits.length > 0),
    );
    expect(found).toEqual(SIE_IS_THE_THING);
  });
});

describe("the set phrase exemption", () => {
  it("is guarding something, rather than describing a string that has gone", () => {
    // An exemption whose subject has been edited away is not a rule, it is a
    // line nobody will delete. If this fails, the phrase left the catalogue and
    // `SET_PHRASES` should go with it.
    const carriers = Object.entries(de)
      .filter(([, value]) => SET_PHRASES.some((p) => value.includes(p)))
      .map(([key]) => key);
    expect(carriers).toEqual(["collections.emptyHint"]);
  });

  it("is what makes that string pass, and nothing else about it", () => {
    // Both sides, which is the point. Without the strip the phrase itself
    // trips the rule, so the exemption is doing real work.
    const value = de["collections.emptyHint"];
    expect(INFORMAL.test(value)).toBe(true);
    expect(INFORMAL.test(withoutSetPhrases(value))).toBe(false);
  });

  it("still catches a real informal address in that same string", () => {
    // **The reason the exemption is on the phrase and not on the key.** Keyed
    // on `collections.emptyHint` the rule would go blind to every other word
    // in a two hundred character sentence.
    const tampered = `${de["collections.emptyHint"]} Nimm dir Zeit.`;
    expect(INFORMAL.test(withoutSetPhrases(tampered))).toBe(true);
  });

  it("catches the plural paradigm's nominative, which is how du comes back", () => {
    // `euch` and `eure` were already covered and `ihr` was not, so the exact
    // form this file used until 2026-09-03 ("Eure Schlagwörter") could have
    // returned through its own subject pronoun with nothing failing.
    expect(INFORMAL.test("Hier findet ihr alle Bücher")).toBe(true);
    // Bare only. The suffixed forms are the third person possessive, so a
    // `\w*` here would fail the build on every one of them.
    expect(INFORMAL.test("Diese Bücher behalten ihren Link")).toBe(false);
    expect(
      INFORMAL.test("Diese Installation setzt das in ihrer Umgebung"),
    ).toBe(false);
  });

  it("keeps the two figures behind that decision honest, in their own units", () => {
    // **Recomputed rather than asserted in prose.** Seven and eight are both
    // correct and count different things, so each is the sort of number a
    // later reader "corrects" into being wrong. `settings.overduePrivacyNote`
    // carries two suffixed forms in one value, and that is the entire gap.
    // **Two constants, for the reason this trio already learned once.** A `/g`
    // regex carries `lastIndex` and `test` advances it, so counting strings
    // with the same object that counted occurrences is right only by luck: it
    // survives here because the seven matching values are scattered among 888
    // and the index resets between them. Adjacent matches would drop one.
    // `gu` and not `g`: the two share a source, and the flag sets disagree
    // about what a source means. `\p{L}+` matches nothing under `g` and
    // matches letters under `u`, so a later edit adding a Unicode class here
    // would have the two lines counting different populations in silence.
    // `g` is now the only difference between them.
    const suffixedAll = /\bihr[a-zäöüß]+\b/gu;
    const suffixed = new RegExp(suffixedAll.source, "u");
    const values = Object.values(de);

    expect(values.filter((value) => /\bihr\b/i.test(value))).toEqual([]);

    const occurrences = values.reduce(
      (total, value) => total + (value.match(suffixedAll)?.length ?? 0),
      0,
    );
    const strings = values.filter((value) => suffixed.test(value)).length;

    expect(occurrences).toBe(8);
    expect(strings).toBe(7);
  });

  it("does not fail the build on a legitimate German word", () => {
    // `dein\w*` matched `Deinstallation`, which is `de` plus `install`.
    expect(INFORMAL.test("Deinstallation")).toBe(false);
    expect(INFORMAL.test("Die App deinstallieren")).toBe(false);
    // And the narrowing keeps every possessive, including the three a listed
    // paradigm would have dropped.
    for (const form of ["Dein Regal", "deins", "deinetwegen", "deinerseits"]) {
      expect(INFORMAL.test(form)).toBe(true);
    }
  });

  it("strips only the phrase, leaving the words it is made of under the rule", () => {
    // "Dein" on its own is the pronoun and must still fail. Only the whole
    // idiom is exempt.
    expect(INFORMAL.test(withoutSetPhrases("Dein Regal"))).toBe(true);
    expect(INFORMAL.test(withoutSetPhrases("Mein und Deine Bücher"))).toBe(
      true,
    );
  });
});
