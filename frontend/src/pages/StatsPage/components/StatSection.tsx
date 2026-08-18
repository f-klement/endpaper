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
}

/** One titled group of labelled bars. Used only by StatsPage. */
export default function StatSection({
  title,
  rows,
  colorClass,
  labelWidthClass = "w-36",
}: StatSectionProps) {
  if (rows.length === 0) return null;

  // Bars are scaled against the largest value in their own group; the floor of
  // 1 keeps an all-zero group from dividing by zero.
  const max = Math.max(1, ...rows.map((row) => row.count));

  return (
    <section>
      <h2 className="text-sm font-semibold text-gray-700 mb-3 dark:text-gray-200">
        {title}
      </h2>
      <div className="space-y-2.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-3">
            <span
              className={`text-sm text-gray-600 truncate ${labelWidthClass}`}
            >
              {row.label}
            </span>
            <Bar value={row.count} max={max} colorClass={colorClass} />
            <span className="text-sm font-medium text-gray-700 w-6 text-right dark:text-gray-200">
              {row.count}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
