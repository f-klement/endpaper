interface SpinnerProps {
  /** Announced to assistive tech, so say what is loading. */
  label: string;
  className?: string;
}

/** A general, reusable loading indicator. Props in, nothing else. */
export default function Spinner({ label, className = "" }: SpinnerProps) {
  return (
    <div className="flex items-center justify-center min-h-64">
      <div
        role="status"
        aria-label={label}
        className={`w-8 h-8 rounded-full animate-spin border-[3px] border-accent-500/25 border-t-accent-600 dark:border-accent-400/25 dark:border-t-accent-300 ${className}`}
      />
    </div>
  );
}
