interface BarProps {
  value: number;
  max: number;
  colorClass: string;
}

/** A single proportional bar. Used only by StatsPage. */
export default function Bar({ value, max, colorClass }: BarProps) {
  // The caller passes a floored max, so this cannot divide by zero. See
  // StatsPage's use of Math.max(1, …).
  const percent = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden dark:bg-gray-800">
      <div
        className={`h-full rounded-full ${colorClass}`}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
