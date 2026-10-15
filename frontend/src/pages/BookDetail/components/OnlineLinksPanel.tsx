import { LinkRelationship } from "../../../api/generated/model";
import type { OnlineLinkOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import type { MessageKey } from "../../../i18n/en";
import { safeHref } from "../../../lib/safeHref";

/** Total over the enum, so a relation added to the API is a compile error here. */
const RELATION_LABEL: Record<LinkRelationship, MessageKey> = {
  [LinkRelationship.resource]: "onlineLinks.relation.resource",
  [LinkRelationship.version]: "onlineLinks.relation.version",
  [LinkRelationship.related]: "onlineLinks.relation.related",
};

interface OnlineLinksPanelProps {
  links: OnlineLinkOut[];
  /** Take one link off the book. The caller asks first. */
  onRemove: (link: OnlineLinkOut) => void;
}

/**
 * What a catalogue record says is online about this book: MARC 856.
 *
 * **Separate from the file references**, which say where a member's own file
 * is; these are a catalogue's links and were never fetched by this app. Draws
 * nothing when the book has none, which is most books.
 *
 * The href comes from `safeHref` and never from the stored string, so a row
 * the server did not write (a restore) cannot become a `javascript:` link; a
 * URL it refuses is shown as text.
 */
export default function OnlineLinksPanel({
  links,
  onRemove,
}: OnlineLinksPanelProps) {
  const { t } = useTranslation();
  if (links.length === 0) return null;

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-paper-800 dark:text-paper-200">
        {t("onlineLinks.section")}
      </h3>
      <ul className="mt-2 space-y-1 text-sm">
        {links.map((link) => {
          const target = safeHref(link.url);
          const text = link.label ?? link.url;
          return (
            <li key={link.id} className="break-all">
              {target ? (
                <a
                  href={target}
                  target="_blank"
                  // `noopener` stops the opened page reaching back through
                  // `window.opener`; the host is whatever the catalogue named.
                  rel="noopener noreferrer"
                  title={t("customFields.opensElsewhere")}
                  className="text-accent-600 hover:text-accent-800 underline dark:text-accent-400 dark:hover:text-accent-300"
                >
                  {text}
                </a>
              ) : (
                <span className="text-paper-700 dark:text-paper-200">
                  {text}
                </span>
              )}
              {link.relation ? (
                <span className="ml-2 text-xs text-paper-600 dark:text-paper-400">
                  {t(RELATION_LABEL[link.relation])}
                </span>
              ) : null}
              <button
                type="button"
                onClick={() => onRemove(link)}
                // The link's own text, so two remove buttons are told apart.
                aria-label={t("onlineLinks.remove", { link: text })}
                className="ml-2 opacity-60 hover:opacity-100 leading-none"
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
