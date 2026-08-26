
import { CollapsibleSection } from "../../../components";
import { useTranslation } from "../../../i18n";
import AboutBadges from "./AboutBadges";

interface AboutSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

/**
 * Which build is running, where the source is, and one line asking.
 *
 * **A badge row, one line and a button, and the shortness is the design.** A
 * sentence describing the app was written and cut: somebody reading this is
 * already inside it and does not need to be told what it is. What is left is
 * what an About card is for. A version number is what gets quoted in a bug
 * report, and the source link is what an Apache-2.0 reader goes looking for.
 * Both are now badges, in `AboutBadges`, which is why the paragraph that used
 * to carry them is gone rather than sitting above them: two statements of the
 * same two facts is what the badge row was added to remove.
 *
 * **The ask is one sentence and does not explain itself.** `README.md` and the
 * Docker Hub page ask in the same sentence and add two facts, that it pays for
 * the shared relay and that nothing sits behind it; here even those are left
 * out, because this reader is already inside the app. Nowhere is it a pitch:
 * earlier drafts of all three argued the case at length and read as one.
 *
 * **The version is derived from the git tag, not declared anywhere.**
 * `__APP_VERSION__` is substituted by `vite.config.ts`: the tag on a release
 * build, `git describe` otherwise, so a development build reads
 * `0.6.0-14-gbbdf755` and cannot be mistaken for a release, and a build with
 * neither reads `unknown`. It used to be
 * `package.json`, which meant editing that file, and `pyproject.toml`, and one
 * day a mobile manifest, before every tag. Both were still at 0.5.0 while
 * v0.6.0 was being cut. A number maintained by memory is wrong the first time
 * somebody forgets it, and the guard that would have failed the release on a
 * mismatch only converted a forgotten edit into a re-tag.
 *
 * **The Ko-fi button is served from this deployment**, not from
 * `storage.ko-fi.com`. Two reasons, and neither is bandwidth: the CSP's
 * `img-src` is derived from `covers.COVER_HOSTS` on the server, so a remote
 * button would mean widening the policy for a decoration; and a remote button
 * would tell Ko-fi the address of a private server every time
 * somebody opened Settings. `rel="noopener noreferrer"` keeps that true of the
 * link as well: following it tells them nothing about where it was followed
 * from.
 *
 * Size matters more here than anywhere else on the page, because a member who
 * is not an admin sees five cards rather than eleven, and this is one of the
 * three that are open. Computed from the class list at `max-w-2xl`: 210px, of
 * 712px of painted card, against 170px for the language card. Tightening the
 * panel's own `space-y-4` would buy 24px and was refused: it would give this
 * one card a rhythm no other card has.
 *
 * **The badge row cost that figure nothing**, which is why it could be a row
 * rather than a line of text. A `text-sm` paragraph is 20px on Tailwind's
 * scale, and a `text-xs` badge at `py-0.5` is 16px of line box plus 4px of
 * padding, also 20px. Three badges are one line at this width in both languages
 * (roughly 361px of badge in English, 372px in German, against 632px of content
 * inside `p-5`), and a development build's longer version string takes it to
 * roughly 433px, still one line. It wraps below about 375px of card width, so a
 * phone sees two rows: 20px twice plus `gap-1.5`, which is 26px more, so 236px.
 * Wrapping is the deliberate behaviour, because a badge sliced in half at the
 * card's edge is worse than a second line.
 */
export default function AboutSection({ isOpen, onToggle }: AboutSectionProps) {
  const { t } = useTranslation();

  return (
    <CollapsibleSection
      variant="card"
      icon="library"
      id="about"
      title={t("about.title")}
      isOpen={isOpen}
      onToggle={onToggle}
    >
      <AboutBadges />

      <p className="text-sm text-paper-600 dark:text-paper-400">
        {t("about.support")}
      </p>

      <a
        href="https://ko-fi.com/fklement"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block"
      >
        <img
          src="/kofi-button.png"
          alt={t("about.kofiAlt")}
          // The artwork's own ratio, 580x146, so the card does not jump when
          // the image lands. The class is what sizes it on the page.
          width={580}
          height={146}
          className="h-9 w-auto"
        />
      </a>
    </CollapsibleSection>
  );
}
