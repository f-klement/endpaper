import { useTranslation } from "../../../i18n";

/**
 * The README's badge row, drawn in the app.
 *
 * **Markup and CSS, never an image, and that is the whole design.** shields.io
 * and every other badge service hands back a remote PNG or SVG, and the CSP's
 * `img-src` is derived from `covers.COVER_HOSTS` on the server: a badge from
 * there means widening the image policy for decoration, which this card already
 * refused once over the Ko-fi button. Drawn instead, the row themes with
 * whichever of the seven palettes is in force, renders offline in the installed
 * PWA, and tells nobody that a private server exists. Do not
 * "improve" it back into an `<img>`.
 *
 * **Only what is knowable without a network call.** Version, licence, source.
 * Not Docker pulls and not a latest release: both need a request to a host the
 * CSP does not carry, and a number hardcoded to avoid the request is wrong the
 * first week and silent about it.
 *
 * **Three badges, not the README's five, and languages is the one that was
 * cut.** The Language card is the first card on this same page and arrives
 * open, offering those two languages as buttons. This card's own reason for
 * cutting the sentence describing the app applies unchanged: the reader is
 * already inside it. A languages badge answers a stranger evaluating the README.
 * It was also a fourth hardcoded copy of the locale list, after `CATALOGUES` in
 * `i18n/index.tsx` (the exhaustive one) and `LANGUAGES` in `SettingsPage.tsx`,
 * so a third locale would have left it reading "DE, EN" with nothing failing.
 *
 * **This replaced the card's "Version 0.6.0 · Source code" line rather than
 * joining it.** Both of that line's facts are badges now, and a row plus a
 * sentence saying the same two things is the redundancy this change existed to
 * remove.
 *
 * **The chrome is neutral in both modes.** Two solid accent rungs were measured
 * as a value cell first and both fail in the dark: `accent-900` against the dark
 * card `paper-900` is 1.01:1 on gruvbox and `accent-950` is 1.13:1 on rosepine,
 * so half of each link badge would disappear into the card. That rejection is
 * about **solid rungs only**: the app's own dark tint idiom, `bg-accent-500/20`
 * (`app/components/NavBar.tsx`), composites to 8.21 to 13.85 CIE L* off the dark
 * card with `paper-200` ink at 4.92:1 to 10.58:1, and would work. Neutral chrome
 * is a choice about loudness on a card whose whole design is that it is quiet,
 * not a finding that an accent cell cannot be built here.
 *
 * **The two cells are separated by a hairline, not by their own difference.**
 * `paper-100` against `paper-200` is 1.32 CIE L* apart on Rose Pine light, where
 * the other six run 3.14 to 8.89, so on that one palette the badge read as a
 * single flat chip. Rejecting a 1.13:1 accent cell in the dark and then shipping
 * a 1.035:1 split in the light would have been the same defect twice.
 * `border-paper-300` is 6.75 CIE L* off the value cell at worst and 5.43 off the
 * label cell at worst, both on Rose Pine; `dark:border-paper-600` is 12.30 and
 * 24.11 at worst, on Endpaper and gruvbox. `palettes.test.ts` holds all four.
 *
 * **Contrast: 4.57:1 at worst**, on the label cell (`paper-800` on `paper-200`,
 * catppuccin light), against the 4.5 WCAG 1.4.3 asks of text below 18.66px; the
 * badge is `text-xs`, 12px. The link ink is the other tight one, 4.58:1 on
 * solarized dark. All eight pairings are tabulated in `docs/decisions.md` and
 * the `paper` half of them is asserted against this file's own computation by
 * `palettes.test.ts::the contrast table in docs/decisions.md`. They are not
 * repeated here: an unasserted second copy of eight figures is a second copy
 * that drifts.
 *
 * **The status pill's ramp is deliberately not reused.** `paper-600` on
 * `paper-200` is what the `unread` pill draws and it measures 3.55:1 on
 * solarized, 3.56 on nord and 3.87 on catppuccin: under the floor on three of
 * seven, recorded in `docs/decisions.md` as known debt. The badge takes the
 * `paper-800` ink the did-not-finish pill takes instead, which is the one rung
 * of that pairing that clears 4.5 on every palette.
 *
 * **It lives in this page folder rather than in `src/components/`** because the
 * bar there is domain free *and* used by more than one page, and this is used
 * by one. The pill itself is domain free and is the half that moves up if a
 * second page ever wants one.
 */

const PILL = "inline-flex items-center overflow-hidden rounded-full text-xs";
const CELL = "px-2 py-0.5";
const LABEL =
  `${CELL} bg-paper-200 text-paper-800 ` +
  "dark:bg-paper-800 dark:text-paper-200";
// The hairline is what makes the two cells read as two on Rose Pine light,
// where they are 1.32 CIE L* apart. Removing it puts that palette back to one
// flat chip; `palettes.test.ts` holds the separation the border buys.
const VALUE =
  `${CELL} border-l bg-paper-100 border-paper-300 ` +
  "dark:bg-paper-700 dark:border-paper-600";
const STATIC_INK = "text-paper-800 dark:text-paper-200";
// Underlined rather than coloured only, so the two links are not told apart by
// hue alone (WCAG 1.4.1). The dark hover is stated because every ramp runs the
// other way in the dark; `houseRules.test.ts` joins the two halves of this
// concatenation before checking, which is what lets it be written over two
// lines at all.
const LINK_INK =
  "text-accent-800 underline hover:text-accent-900 " +
  "dark:text-accent-200 dark:hover:text-accent-100";

interface BadgeProps {
  label: string;
  value: string;
  href?: string;
}

/**
 * One badge: a label cell and a value cell, split by a hairline.
 *
 * **The space between the cells is load bearing and is not a gap.** Measured
 * with `dom-accessibility-api`, the package testing-library computes names
 * with: two adjacent spans with no whitespace between them name a link
 * "SourceGitHub", and with `{" "}` they name it "Source GitHub". It costs
 * nothing visually, because CSS Flexbox Level 1 section 4 says an anonymous
 * flex item containing only white space is not rendered, as if `display: none`.
 * So the name comes from the badge's own content and no `aria-label` assembles
 * a phrase out of two translated fragments.
 *
 * No focus classes: there is one ring, in `index.css`.
 */
function Badge({ label, value, href }: BadgeProps) {
  const body = (
    <>
      <span className={LABEL}>{label}</span>{" "}
      <span className={`${VALUE} ${href ? LINK_INK : STATIC_INK}`}>
        {value}
      </span>
    </>
  );

  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className={PILL}>
      {body}
    </a>
  ) : (
    <span className={PILL}>{body}</span>
  );
}

const REPOSITORY = "https://github.com/f-klement/endpaper";
// Names, not phrases, so they are not catalogue entries: a translator has
// nothing to do with either and both would be byte identical in every language.
const LICENCE = "Apache 2.0";
const FORGE = "GitHub";

export default function AboutBadges() {
  const { t } = useTranslation();

  return (
    // Wrapping, not scrolling: on a phone the row becomes two, and a badge cut
    // in half at the card's edge is worse than a second line.
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge label={t("about.versionLabel")} value={__APP_VERSION__} />
      <Badge
        label={t("about.licenceLabel")}
        value={LICENCE}
        href={`${REPOSITORY}/blob/main/LICENSE`}
      />
      <Badge label={t("about.sourceLabel")} value={FORGE} href={REPOSITORY} />
    </div>
  );
}
