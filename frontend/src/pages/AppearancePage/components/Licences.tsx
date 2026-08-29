import { useTranslation } from "../../../i18n";
import { PALETTES } from "../../../theme";

/**
 * Where the colours and the pattern names came from.
 *
 * On the screen that offers them rather than only in `docs/theming.md`, which
 * is where a reader can find it and where an attribution belongs. Nine MIT
 * notices, generated from the catalogue so a new palette cannot ship without
 * one, and the Morris & Co sentence, which is a trademark matter rather
 * than a copyright one: the five designs are public domain and the five names
 * are in current commercial use.
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
    </div>
  );
}
