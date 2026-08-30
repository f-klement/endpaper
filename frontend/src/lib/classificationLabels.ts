/**
 * What each published scheme is called on screen.
 *
 * **One table, because there were about to be three.** The book page's panel
 * and the library's filter each carried their own copy, and the table view
 * would have been the third. `Record<ClassificationScheme, MessageKey>` makes
 * a *missing* scheme a compile error in every copy, so the keys could not
 * drift; the values could, and three places pointing at three different
 * spellings of the same scheme is exactly the drift nobody notices.
 */

import { ClassificationScheme } from "../api/generated/model";
import type { MessageKey } from "../i18n/en";

export const SCHEME_LABEL: Record<ClassificationScheme, MessageKey> = {
  [ClassificationScheme.ddc]: "classification.scheme.ddc",
  [ClassificationScheme.lcc]: "classification.scheme.lcc",
  [ClassificationScheme.gnd]: "classification.scheme.gnd",
  [ClassificationScheme.lcsh]: "classification.scheme.lcsh",
};
