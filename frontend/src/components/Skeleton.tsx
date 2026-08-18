interface SkeletonProps {
  className?: string;
}

/** A grey placeholder block. Composed into per-page loading shapes. */
export default function Skeleton({ className = "" }: SkeletonProps) {
  return <div className={`bg-gray-200 rounded ${className}`} />;
}
