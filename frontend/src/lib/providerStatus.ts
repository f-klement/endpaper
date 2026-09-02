/**
 * The one line under a catalogue in the provider list.
 *
 * **Its own module rather than a helper inside `ProviderSection`**, because the
 * invariant below is worth testing over every combination of the fields rather
 * than through however many renders it takes to reach one. `classificationLabels`
 * is the same shape: a pure map from a wire row to a `MessageKey`, with no React
 * in it.
 *
 * ## The invariant, which cost two rounds
 *
 * **A line that names registration groups may only be shown for a row those
 * groups actually narrow.** `serves_groups` is the remit a catalogue declares,
 * not the filter applied to it: the leading tier is asked about every ISBN
 * whatever a source's remit, so a promoted catalogue carries a populated
 * `serves_groups` **and** is asked about everything. `asked_first` is the field
 * that answers "is this filtered", and it has to be read before any line that
 * makes a claim about which ISBNs.
 *
 * That rule was written down and then broken one branch along, in the same
 * commit: `lookupOnlyRegional` returned from the `!answers_search` arm, above
 * the `asked_first` test, so a promoted lookup only catalogue with a remit was
 * told it answers "only for ISBNs beginning 978-80" while sitting in a tier
 * nothing filters. Reachable and measured: a plan of `nkp, k10plus, dnb` gives
 * the NKP `asked_first: true, answers_search: false`.
 *
 * **`lookupOnly` was safe in that position and `lookupOnlyRegional` is not**,
 * and that is the whole difference: the first makes no claim about which ISBNs
 * and the second does. So the fix is not a fourth condition on one branch.
 * `isFiltered` is asked by **every** arm that names groups, which takes the
 * guarantee off the ordering of the `if` chain, and
 * `tests/lib/providerStatus.test.ts` sweeps the whole field space to check no
 * arm was missed.
 *
 * **The sweep cannot see its own oracle, which is worth knowing before trusting
 * it.** `isFiltered` is both the condition the arms ask and the assertion the
 * sweep checks them against, so a change *inside* it moves both sides together:
 * drop `!row.asked_first` from it and the sweep and its anti vacuity arm both
 * still pass, and only the named example,
 * `says a promoted lookup only catalogue is asked on every scan`, fails.
 * Nothing is unguarded, but the example is carrying work the sweep gets the
 * credit for. The sweep's real subject is which **arms** consult the predicate,
 * not whether the predicate is right.
 *
 * ## One thing no test here can catch, said rather than left to be found
 *
 * Replacing `isFiltered` in the **regional** arm with the two conditions spelled
 * out again changes no behaviour, because that arm sits below the `asked_first`
 * test and so is already unreachable for a promoted row. A mutation harness
 * scored it a survivor and it is an honest one: the two programs are identical.
 *
 * **That mutant is the code that shipped in `1d89801`**, byte for byte, so it
 * was not caught before this module existed either. The survivor is the state
 * this arm was always in rather than coverage lost in the move, which is worth
 * knowing because a survivor that used to be caught would be a finding.
 *
 * What `isFiltered` buys there is that the arm stops depending on its position,
 * and that was measured rather than argued. Moving the `asked_first` test below
 * it: with `isFiltered` the sweep still passes, and with the two conditions
 * written out it fails on two tests. So the ordering is what protected that arm
 * before, and it is exactly the protection the `!answers_search` arm did not
 * have.
 */

import type { CatalogueSourceOut } from "../api/generated/model";
import type { MessageKey } from "../i18n/en";

/**
 * Whether this row's remit actually narrows the ISBNs it is asked about.
 *
 * Three conditions and none is redundant. **Off** is asked nothing at all.
 * **Promoted** into the leading tier is asked about every ISBN, because that
 * tier is gathered and `metadata.lookup` filters only the sources asked one at
 * a time. **No remit** is the ordinary case.
 */
export function isFiltered(row: CatalogueSourceOut): boolean {
  return row.enabled && !row.asked_first && row.serves_groups.length > 0;
}

/**
 * Why this catalogue is not answering, or what it answers.
 *
 * **Ordered by what a reader can act on.** A missing key is the most likely
 * cause of "why is this not working", so it comes first even for a source that
 * is switched on and looks fine. Then the two "this question, not that one"
 * cases, which explain why moving the row changes nothing about half the app.
 * Then position.
 *
 * Every arm naming groups asks `isFiltered` rather than relying on having been
 * placed below the `asked_first` test. See this module's own docstring.
 */
export function statusOf(row: CatalogueSourceOut): MessageKey {
  // **Two causes, not one.** A source that needs a key and has none wants a
  // key; one that has the key and still is not ready is switched off in its own
  // card below, and telling that library to add a key it already has is the
  // exact symptom this section exists to remove. `ready` alone conflated them.
  if (row.needs_a_key && !row.ready) {
    return row.has_key
      ? "providers.status.switchedOffBelow"
      : "providers.status.needsKey";
  }
  if (!row.answers_lookup) return "providers.status.searchOnly";
  // **The mirror of the line above, and it was missing until the Czech
  // catalogue became the first source to need it.** `answers_search` has been
  // on the wire since the roster gained a search path and was read by nothing,
  // so a lookup-only source rendered as "asked only when the ones above it find
  // nothing" with no hint that its position never affects a title search. That
  // is exactly the promise `searchOnly` exists to stop the screen making.
  //
  // A catalogue can be lookup only and regional at once: the Czech National
  // Library is that shape today. The alternative was forbidding the combination
  // in `sources.SERVES_GROUPS`, which passes today and is the wrong rule, since
  // a remit is meaningful on any source that answers a lookup.
  if (!row.answers_search) {
    return isFiltered(row)
      ? "providers.status.lookupOnlyRegional"
      : "providers.status.lookupOnly";
  }
  // **Before the regional line and not after it**, because the leading tier is
  // asked about every ISBN whatever a source's remit: `metadata.lookup` filters
  // only the sources asked one at a time. A source a household has promoted into
  // that tier really is asked on every scan, and saying otherwise would be the
  // screen promising something the server does not do.
  if (row.enabled && row.asked_first) return "providers.status.askedFirst";
  // A national catalogue below the tier is asked for the registration groups it
  // collects and skipped for the rest, so "asked when the ones above it find
  // nothing" is true of a tenth of scans and reads as true of all of them.
  //
  // `isFiltered` rather than the two conditions spelled out again: `asked_first`
  // is already false here by position, and depending on that is what made the
  // branch above wrong.
  if (isFiltered(row)) return "providers.status.regional";
  if (row.enabled) return "providers.status.askedAfter";
  return "providers.status.off";
}
