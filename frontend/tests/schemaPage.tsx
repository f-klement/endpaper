/**
 * A page rendered over answers the committed schema permits, and what such a
 * page may not show.
 *
 * **The seam is `fetch`, under the generated client**, as everywhere in this
 * suite: a page's `hooks.ts` runs for real, through the real mutator, and
 * every request any hook makes is answered by drawing from what
 * `openapi.json` declares for that operation (`tests/lib/schemaArbitrary.ts`).
 * Drawn on demand through `fc.gen`, so a hook reached through a shared
 * module, the feature flags or the appearance, is answered from the schema
 * too, rather than being a request somebody forgot to stub.
 *
 * **What a page may not do over such an answer**, the property's oracle:
 *
 * - throw, during a render, an effect or a handler React reports;
 * - end a query or a mutation in an error that is not an `ApiError`, which
 *   is a throw the page then shows as an alert: every drawn answer is a
 *   declared status, so every failure should be one the mutator named;
 * - show a token no drawn string spelled: `undefined`, `null`, `NaN`,
 *   `Infinity` or the infinity sign a number format prints for it,
 *   `[object Object]` or `Invalid Date`, in text or in an attribute read
 *   aloud to a reader or followed;
 * - raise an alert that says nothing a reader can see but its buttons;
 * - make a request the document has no operation for;
 * - show a session token an answer carried, under `SESSION_KEY`, or any
 *   `PIECE` characters of one: in a text node, in any attribute as written or
 *   with its escapes read, or in the path, its query or its hash;
 * - where it renders to a visitor with no account (`anonymous`), ask for an
 *   operation the document requires an account for.
 *
 * Every answer comes with an empty status text, as a browser talking HTTP/2
 * is handed one, so a message that falls back to it is seen as production
 * shows it.
 *
 * **What it does not see, stated**: a value shown that is wrong but
 * nameable, such as a count disagreeing with the rows beside it; a hostile
 * value shown as written, such as a `javascript:` link, since no drawn
 * string is hostile and no link is judged by its scheme; a control or a link
 * with an empty accessible name, which a drawn empty title makes; a warning
 * React only logs, such as two rows sharing a key; anything a page does
 * after a click, except the steps a caller hands `overSchema` as `uses`;
 * anything it does later of its own accord, such as a request a timer asks
 * after the page has settled; a toast, since no `ToastProvider` is mounted
 * and `useToast` answers a no-op without one; and anything outside the
 * rendered container, such as `document.body` or `document.title`.
 *
 * **A reach that a drawn value got to the page counts `DISTINCT` markers
 * only** (`echoed`), so a page's own words spelling a short drawn string do
 * not pass it.
 */

import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup } from "@testing-library/react";
import type fc from "fast-check";
import { Component, type ReactElement, type ReactNode } from "react";

import type { Locale } from "../src/api/generated/model";
import { ApiError } from "../src/api/mutator";
import {
  anonymousOperations,
  answersOf,
  DISTINCT,
  operationAt,
  SESSION_KEY,
  spelledOut,
  type Answer,
} from "./lib/schemaArbitrary";
import { createTestQueryClient, mockApi, renderWithProviders } from "./utils";

/** Catches what a page throws while rendering, and records it. */
class Boundary extends Component<
  { readonly onError: (error: unknown) => void; readonly children: ReactNode },
  { readonly failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    this.props.onError(error);
  }

  render(): ReactNode {
    return this.state.failed ? null : this.props.children;
  }
}

/** The tokens a value that never arrived prints as. */
const UNNAMED =
  /\bundefined\b|\bnull\b|\bNaN\b|\bInfinity\b|\u221e|\[object Object\]|\bInvalid Date\b/gu;

/** Attributes a reader hears or follows, where such a token is as visible. */
const SPOKEN = [
  "alt",
  "aria-description",
  "aria-label",
  "aria-valuemax",
  "aria-valuemin",
  "aria-valuenow",
  "aria-valuetext",
  "href",
  "placeholder",
  "src",
  "title",
  "value",
];

/** Every string in `value`, however deep. */
function stringsIn(value: unknown, into: string[] = []): string[] {
  if (typeof value === "string") into.push(value);
  else if (typeof value === "object" && value !== null) {
    for (const each of Object.values(value)) stringsIn(each, into);
  }
  return into;
}

/** Each text node under `root`. */
function textsIn(root: HTMLElement): string[] {
  const found: string[] = [];
  const texts = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = texts.nextNode(); node !== null; node = texts.nextNode()) {
    found.push(node.textContent ?? "");
  }
  return found;
}

/** What `root` shows a reader: each text node, and each spoken attribute. */
function shownIn(root: HTMLElement): string[] {
  const shown = textsIn(root);
  for (const element of root.querySelectorAll("*")) {
    for (const name of SPOKEN) {
      const value = element.getAttribute(name);
      if (value !== null) shown.push(value);
    }
  }
  return shown;
}

/**
 * Everything under `root` a script or a copy can read: each text node, and
 * every attribute, `data-*` among them, as written and with its escapes read.
 * A secret in any of them has left its home.
 */
function exposedIn(root: HTMLElement): string[] {
  const exposed = textsIn(root);
  for (const element of root.querySelectorAll("*")) {
    for (const { value } of element.attributes) {
      exposed.push(value, decoded(value));
    }
  }
  return exposed;
}

/**
 * A character somebody can see. Whitespace and the invisible format
 * characters, a zero width space or a soft hyphen, are not; `trim()` sees
 * only the first.
 */
const SEEN = /[\p{L}\p{N}\p{P}\p{S}]/u;

/** An alert's text without its buttons' text: what it says. */
function saying(alert: Element): string {
  const parts: string[] = [];
  const texts = document.createTreeWalker(alert, NodeFilter.SHOW_TEXT);
  for (let node = texts.nextNode(); node !== null; node = texts.nextNode()) {
    if (node.parentElement?.closest("button") === null) {
      parts.push(node.textContent ?? "");
    }
  }
  return parts.join("").trim();
}

/**
 * Every string under a `SESSION_KEY` key in `value`, however deep.
 *
 * Deep is what reaches a registration's session, which `RegistrationOut`
 * nests as `token.access_token` rather than carrying as a string.
 */
function sessionsIn(value: unknown, into: string[] = []): string[] {
  if (typeof value === "object" && value !== null) {
    for (const [key, each] of Object.entries(value)) {
      if (key === SESSION_KEY && typeof each === "string") into.push(each);
      else sessionsIn(each, into);
    }
  }
  return into;
}

/**
 * How many characters of a session token in a row count as showing it: a
 * page that cuts one short, `token.slice(0, 10)`, still shows a secret. Safe
 * because the deriver draws every token as a `SESSION_TOKEN`, whose pieces
 * this long no page's words spell. A piece shorter than this goes unseen.
 */
const PIECE = 10;

/** Every `PIECE` characters in a row of `token`. */
function piecesOf(token: string): string[] {
  return Array.from({ length: token.length - PIECE + 1 }, (_, at) =>
    token.slice(at, at + PIECE),
  );
}

/** `text` with its escapes read, or as it is where one is malformed. */
function decoded(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

/** Flush one turn of the event loop inside `act`. */
async function turn(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** How many turns a page may take to stop asking. */
const PATIENCE = 50;

/**
 * Whether `client` has nothing in flight for two turns running, within
 * `PATIENCE` turns. Two, because a query one answer enables starts on the
 * turn after that answer lands. A turn at a time, in order, by recursion.
 */
async function settles(
  client: QueryClient,
  turns = 0,
  quiet = 0,
): Promise<boolean> {
  if (quiet === 2) return true;
  if (turns === PATIENCE) return false;
  await turn();
  const idle = client.isFetching() + client.isMutating() === 0;
  return settles(client, turns + 1, idle ? quiet + 1 : 0);
}

/**
 * Each of `steps` over `page`, in order, each in an `act` of its own and the
 * page settling after it, so a step acts on what the one before it asked
 * for. Settled once, after the last, Show more is pressed before the search
 * has answered, and the public catalogue's reach that it was pressed misses
 * at some seeds. By recursion, as `settles` is.
 */
async function stepThrough(
  page: HTMLElement,
  steps: readonly ((page: HTMLElement) => void)[],
  client: QueryClient,
  problems: string[],
  at = 1,
): Promise<void> {
  const [step, ...rest] = steps;
  if (step === undefined) return;
  await act(async () => {
    step(page);
  });
  if (!(await settles(client))) {
    problems.push(`still asking ${PATIENCE} turns after step ${at}`);
  }
  return stepThrough(page, rest, client, problems, at + 1);
}

/** What a page did over one draw of answers. */
export interface OverSchema {
  /** What the page did that the oracle refuses, in words. Empty is a pass. */
  readonly problems: readonly string[];
  /** The rendered page, for a reach to be asked of before `forget`. */
  readonly container: HTMLElement;
  /**
   * What the page showed a reader when it was judged: each text node, and
   * each spoken attribute. Read here rather than off `container`, which
   * `forget` empties before a reach is asked.
   */
  readonly shown: readonly string[];
  /** What each alert on the page says, its buttons left out. */
  readonly alerts: readonly string[];
  /**
   * How many `DISTINCT` markers the answers carried reached the page
   * verbatim: the reach saying a draw got as far as the screen, rather than a
   * page that drew nothing whatever it was sent. Markers only, because a
   * short drawn string is spelled by the page's own words by chance.
   */
  readonly echoed: number;
  /**
   * Each request's operation and the answer it was handed, in the order
   * asked: what a reach reads to ask that one answer reached the page.
   */
  readonly answered: readonly (readonly [string, Answer])[];
  /**
   * The operation each request named, in the order asked. Three uses read
   * it: Scan's reach, that its use looked the book up; Login's, that its use
   * signed in or registered; and the public catalogue's, that a search and
   * Show more each asked for the catalogue again.
   */
  readonly asked: readonly string[];
}

/**
 * Render `ui` with every request answered from `g`, wait until no query or
 * mutation is in flight, and judge what is on screen. The page stays
 * mounted until `forget`, so a reach can be asked of it.
 *
 * `uses`, where given, are the steps of one use of the settled page, such as
 * a form filled and submitted, for a page whose main request is asked for on a
 * reader's act rather than on arrival. The page settles after each step, and
 * is judged once, at the end.
 *
 * `anonymous` is for a page that renders to a visitor with no account: it
 * may ask only for what `anonymousOperations` lists.
 */
export async function overSchema(
  ui: ReactElement,
  g: fc.GeneratorValue,
  {
    route,
    locale,
    uses,
    anonymous = false,
  }: {
    route?: string;
    locale?: Locale;
    uses?: readonly ((page: HTMLElement) => void)[];
    anonymous?: boolean;
  } = {},
): Promise<OverSchema> {
  const drawn: unknown[] = [];
  const problems: string[] = [];
  const answered: [string, Answer][] = [];
  const open = anonymous ? anonymousOperations() : undefined;
  const api = mockApi();
  api.on(/./, (url, init) => {
    const method = (init.method ?? "GET").toUpperCase();
    const operationId = operationAt(method, url);
    if (operationId === undefined) {
      problems.push(
        `asked ${method} ${url}, which the document does not declare`,
      );
      return { status: 404 };
    }
    if (open !== undefined && !open.has(operationId)) {
      problems.push(`asked ${operationId}, which needs an account`);
    }
    const answer = g(answersOf, operationId);
    if (answer.body === undefined) {
      answered.push([operationId, answer]);
      return { status: answer.status, statusText: "" };
    }
    // What a page is handed is what survives JSON: no `-0`, no `undefined`.
    const body: unknown = JSON.parse(JSON.stringify(spelledOut(answer.body)));
    drawn.push(body);
    answered.push([operationId, { status: answer.status, body }]);
    return { status: answer.status, statusText: "", body };
  });

  const reported = (event: ErrorEvent | PromiseRejectionEvent) => {
    problems.push(
      `reported ${String("error" in event ? event.error : event.reason)}`,
    );
  };
  window.addEventListener("error", reported);
  window.addEventListener("unhandledrejection", reported);
  const client = createTestQueryClient();
  try {
    const { container, path } = renderWithProviders(
      <Boundary onError={(error) => problems.push(`threw ${String(error)}`)}>
        {ui}
      </Boundary>,
      { queryClient: client, route, locale },
    );
    if (!(await settles(client))) {
      problems.push(`still asking after ${PATIENCE} turns`);
    }
    if (uses !== undefined) {
      await stepThrough(container, uses, client, problems);
    }
    const failed = [
      ...client.getQueryCache().getAll(),
      ...client.getMutationCache().getAll(),
    ].map((each) => each.state.error);
    for (const error of failed) {
      if (error != null && !(error instanceof ApiError)) {
        problems.push(`failed with ${String(error)}, which no answer is`);
      }
    }

    const spelled = stringsIn(drawn);
    const shown = shownIn(container);
    for (const text of shown) {
      for (const token of text.match(UNNAMED) ?? []) {
        if (!spelled.some((each) => each.includes(token))) {
          problems.push(`showed ${token} in ${JSON.stringify(text)}`);
        }
      }
    }
    const alerts = [...container.querySelectorAll('[role="alert"]')].map(
      saying,
    );
    if (alerts.some((alert) => !SEEN.test(alert))) {
      problems.push("raised an alert saying nothing");
    }
    const page = shown.join("\n");
    const where = [...exposedIn(container), path(), decoded(path())];
    for (const session of sessionsIn(drawn)) {
      const pieces = piecesOf(session);
      if (where.some((text) => pieces.some((piece) => text.includes(piece)))) {
        problems.push(`showed the session token ${JSON.stringify(session)}`);
      }
    }
    const echoed = spelled.filter(
      (text) => DISTINCT.test(text) && page.includes(text),
    ).length;
    const asked = answered.map(([operationId]) => operationId);
    return { problems, container, shown, alerts, echoed, answered, asked };
  } finally {
    window.removeEventListener("error", reported);
    window.removeEventListener("unhandledrejection", reported);
  }
}

/**
 * A generator handing back `answers` in the order given, each to the
 * operation it names: a counterexample's printed answers, replayed request by
 * request, as the property's own `fc.gen` handed them out. **A request for
 * any other operation is refused**, so a page that reorders its requests reds
 * by name rather than feeding one hook the body another was drawn for.
 */
export function scripted(
  answers: readonly (readonly [string, Answer])[],
): fc.GeneratorValue {
  const queue = [...answers];
  const next = (_: unknown, asked: unknown) => {
    const entry = queue.shift();
    if (entry === undefined) {
      throw new Error(`the literal ran out of answers at ${String(asked)}`);
    }
    const [operationId, answer] = entry;
    if (operationId !== asked) {
      throw new Error(
        `the literal answers ${operationId} where the page asked ${String(asked)}`,
      );
    }
    return answer;
  };
  return Object.assign(next, {
    values: () => answers.map(([, answer]) => answer),
  }) as never;
}

/**
 * Unmount what `overSchema` rendered and forget what it stored, so the next
 * draw starts from nothing. `tests/setup.ts` does this between tests; a
 * property's examples share one test.
 */
export function forget(): void {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
}
