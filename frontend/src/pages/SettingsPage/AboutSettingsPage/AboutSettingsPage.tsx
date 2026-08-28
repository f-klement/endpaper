import { useTranslation } from "../../../i18n";
import SettingsSubPage from "../components/SettingsSubPage";
import AboutBadges from "./components/AboutBadges";

/**
 * Which build is running, where the source is, and one line asking.
 *
 * **Its own route rather than a card at the foot of a settings list**, which
 * is where it lived until the list became an index of six. It is the only
 * section that answers "what is this", and folding it in beside a backup
 * control would make it harder to find for the one reader who wants it.
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
 * **The size argument this docstring used to open with has expired, and it is
 * worth saying why rather than deleting it.** The card was kept to 210px of
 * 712px because it was one of three open cards on a page a non-admin saw, and a
 * settings page whose one expanded card asks for money reads as a donation
 * prompt wearing a settings page. Nothing folds any more and this is a route of
 * its own, so the constraint it was measured against is gone. What survives is
 * the shape, because the shape is what makes the ask quiet: a badge row, one
 * sentence and one button, and no card competing with it.
 *
 * **The badge row is a row rather than a line of text** for the reason that
 * cost nothing when the height did matter. A `text-sm` paragraph is 20px on
 * Tailwind's scale, and a `text-xs` badge at `py-0.5` is 16px of line box plus
 * 4px of padding, also 20px. Three badges are one line at `max-w-2xl` in both
 * languages
 * (roughly 361px of badge in English, 372px in German, against 632px of content
 * inside `p-5`), and a development build's longer version string takes it to
 * roughly 433px, still one line. It wraps below about 375px of card width, so a
 * phone sees two rows: 20px twice plus `gap-1.5`, which is 26px more, so 236px.
 * Wrapping is the deliberate behaviour, because a badge sliced in half at the
 * card's edge is worse than a second line.
 */
export default function AboutSettingsPage() {
  const { t } = useTranslation();

  return (
    <SettingsSubPage icon="library" title={t("about.title")}>
      {/* One card and no heading inside it: the page header already says
          what this is, and a card titled "About Endpaper" under a page
          titled "About Endpaper" is the same sentence twice. */}
      <section className="card p-5 space-y-4">
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
      </section>
    </SettingsSubPage>
  );
}
