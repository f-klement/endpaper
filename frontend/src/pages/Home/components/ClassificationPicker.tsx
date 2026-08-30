import { useId, useState } from "react";

import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import type { MessageKey } from "../../../i18n/en";
import {
  type ClassificationFacets,
  type DivisionFacetOut,
  type HeadingFacetOut,
} from "../../../api/generated/model";
import { SCHEME_LABEL } from "../../../lib/classificationLabels";

interface ClassificationPickerProps {
  facets: ClassificationFacets | undefined;
  selectedHeadings: string[];
  selectedDivisions: string[];
  onToggleHeading: (heading: string) => void;
  onToggleDivision: (division: string) => void;
}

/**
 * The classification filter, shaped like the tag filter on purpose.
 *
 * Two groups rather than one list, because the two answer different questions
 * and take different operators. A heading narrows and is ANDed, like a tag. A
 * division is a shelf and is ORed, so picking two shows both shelves rather
 * than the empty set: argued in `docs/decisions.md`.
 *
 * **The scheme is on every heading chip** for the same reason it is on the book
 * detail: `004` is computing in Dewey and is not a Library of Congress call
 * number at all, so a number with no scheme cannot be read.
 */

/** The wire spelling of one heading, and the only place it is assembled. */
export function headingKey(facet: HeadingFacetOut): string {
  return `${facet.scheme}:${facet.number}`;
}

const CHIP =
  "inline-flex items-baseline gap-1.5 text-xs px-2 py-1 rounded-full border transition-colors";
const CHOSEN = "bg-accent-fill border-accent-fill text-on-accent";
const UNCHOSEN =
  "border-paper-200 text-paper-600 bg-paper-0 hover:border-accent-300 " +
  "dark:bg-paper-900 dark:border-paper-700 dark:text-paper-300 dark:hover:border-accent-700";

export default function ClassificationPicker({
  facets,
  selectedHeadings,
  selectedDivisions,
  onToggleHeading,
  onToggleDivision,
}: ClassificationPickerProps) {
  const { t } = useTranslation();
  const panelId = useId();
  // Both groups start open. There are two of them, not a dozen categories, so
  // the collapse the tag picker needs would only add a click here.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const headings = facets?.headings ?? [];
  const divisions = facets?.divisions ?? [];

  if (headings.length === 0 && divisions.length === 0) {
    return (
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("classification.noneToFilter")}
      </p>
    );
  }

  function toggleGroup(group: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(group)) next.add(group);
      return next;
    });
  }

  function group(
    key: string,
    label: MessageKey,
    chosen: number,
    count: number,
    body: React.ReactNode,
  ) {
    const expanded = !collapsed.has(key);
    return (
      <div>
        <button
          type="button"
          onClick={() => toggleGroup(key)}
          aria-expanded={expanded}
          aria-controls={`${panelId}-${key}`}
          className="flex w-full items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-paper-600 hover:text-paper-800 dark:text-paper-400 dark:hover:text-paper-300"
        >
          <Icon
            name="chevron"
            className={`h-3 w-3 transition-transform duration-150 ${
              expanded ? "rotate-90" : ""
            }`}
          />
          {t(label)}{" "}
          <span className="font-normal normal-case text-paper-600 dark:text-paper-400">
            {chosen > 0
              ? t("tags.countWithChosen", { count, chosen })
              : t("tags.count", { count })}
          </span>
        </button>
        {expanded && (
          <div
            id={`${panelId}-${key}`}
            role="group"
            aria-label={t(label)}
            className="mt-1 flex flex-wrap gap-1.5"
          >
            {body}
          </div>
        )}
      </div>
    );
  }

  function divisionChip(facet: DivisionFacetOut) {
    const selected = selectedDivisions.includes(facet.division);
    return (
      <button
        key={facet.division}
        type="button"
        aria-pressed={selected}
        onClick={() => onToggleDivision(facet.division)}
        className={`${CHIP} ${selected ? CHOSEN : UNCHOSEN}`}
      >
        <span className="font-medium">{facet.division}</span>
        {/* This library's own word for the division, absent where the division
            maps to no tag. The number alone is a real answer there rather than
            a gap: see `DivisionFacetOut.label` in the backend schema. */}
        {facet.label && <span>{facet.label}</span>}
        <span className="opacity-70">{facet.book_count}</span>
      </button>
    );
  }

  function headingChip(facet: HeadingFacetOut) {
    const key = headingKey(facet);
    const selected = selectedHeadings.includes(key);
    return (
      <button
        key={key}
        type="button"
        aria-pressed={selected}
        onClick={() => onToggleHeading(key)}
        className={`${CHIP} ${selected ? CHOSEN : UNCHOSEN}`}
      >
        <span className={selected ? "opacity-80" : "opacity-70"}>
          {t(SCHEME_LABEL[facet.scheme])}
        </span>
        <span className="font-medium">{facet.number}</span>
        <span className="opacity-70">{facet.book_count}</span>
      </button>
    );
  }

  return (
    <div className="space-y-2.5">
      {divisions.length > 0 &&
        group(
          "divisions",
          "classification.divisions",
          selectedDivisions.length,
          divisions.length,
          divisions.map(divisionChip),
        )}
      {headings.length > 0 &&
        group(
          "headings",
          "classification.headings",
          selectedHeadings.length,
          headings.length,
          headings.map(headingChip),
        )}
    </div>
  );
}
