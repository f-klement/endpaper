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
        className={`w-8 h-8 border-4 border-sky-200 border-t-sky-500 rounded-full animate-spin ${className}`}
      />
    </div>
  );
}
