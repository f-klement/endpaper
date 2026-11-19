import { useTranslation } from "../../../i18n";
import { PALETTES } from "../../../theme";

/**
 * Where the image serves each notices file. `tests/licence.test.ts` reads both
 * against the files that put them there: the Dockerfile's last stage for the
 * collected notices, `public/` for the engine's.
 */
const NOTICES = [
  {
    href: "/licences/third-party.txt",
    label: "appearance.licencesThirdParty",
  },
  {
    href: "/licences/tesseract.txt",
    label: "appearance.licencesEngine",
  },
] as const;

/**
 * Where the colours and the pattern names came from.
 *
 * On the screen that offers them rather than only in `docs/theming.md`, which
 * is where a reader can find it and where an attribution belongs. Nine MIT
 * notices, generated from the catalogue so a new palette cannot ship without
 * one, and the Morris & Co sentence, which is a trademark matter rather
 * than a copyright one: the five designs are public domain and the five names
 * are in current commercial use.
 *
 * Then the third party software the image ships, as links to two files the
 * server serves beside the bundle: the notices the image build collects for
 * every JavaScript, Python and YAZ package, and the OCR engine's own. The
 * first exists only in a built image, so it is a 404 under `bun run dev`.
 */
export default function Licences() {
  const { t } = useTranslation();
  const attributions: string[] = PALETTES.map(
    (palette) => palette.attribution,
  ).filter((attribution) => attribution !== null);

  return (
    <div className="space-y-2 text-xs text-paper-600 dark:text-paper-400">
      <p>{t("appearance.licencesPalettes")}</p>
      <ul className="list-disc ps-5 space-y-0.5">
        {attributions.map((attribution) => (
          <li key={attribution}>{attribution}</li>
        ))}
      </ul>
      <p>{t("appearance.licencesMorris")}</p>
      <p>{t("appearance.licencesSoftware")}</p>
      <ul className="list-disc ps-5 space-y-0.5">
        {NOTICES.map(({ href, label }) => (
          <li key={href}>
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-700 hover:text-accent-800 underline dark:text-accent-400 dark:hover:text-accent-300"
            >
              {t(label)}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
