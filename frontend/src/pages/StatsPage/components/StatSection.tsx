import Bar from "./Bar";

export interface StatRow {
  /** Row label, unique within the section. Also used as the React key. */
  label: string;
  count: number;
}

interface StatSectionProps {
  title: string;
  rows: StatRow[];
  colorClass: string;
  /** Width of the label column; month labels need less room than tag names. */
  labelWidthClass?: string;
  /**
   * Width of the count column. The default fits three digits, which is every
   * section that counts books. A section counting **pages** needs more: thirty
   * pages a day is nine hundred a month, and four digits at `text-sm` is about
   * 31px against the 24px `w-6` allows, so the number wrapped under its own
   * bar. `tabular-nums` belongs with it, or the months jitter against each
   * other as the digits change width.
   */
  countWidthClass?: string;
}

/** One titled group of labelled bars. Used only by StatsPage. */
export default function StatSection({
  title,
  rows,
  colorClass,
  labelWidthClass = "w-36",
  countWidthClass = "w-6",
}: StatSectionProps) {
  if (rows.length === 0) return null;

  // Bars are scaled against the largest value in their own group; the floor of
  // 1 keeps an all-zero group from dividing by zero.
  const max = Math.max(1, ...rows.map((row) => row.count));

  return (
    <section>
      <h2 className="text-sm font-semibold text-paper-700 mb-3 dark:text-paper-200">
        {title}
      </h2>
      <div className="space-y-2.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-3">
            <span
              className={`text-sm text-paper-600 truncate dark:text-paper-300 ${labelWidthClass}`}
            >
              {row.label}
            </span>
            <Bar value={row.count} max={max} colorClass={colorClass} />
            <span
              className={`text-sm font-medium text-paper-700 text-right shrink-0 dark:text-paper-200 ${countWidthClass}`}
            >
              {row.count}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
