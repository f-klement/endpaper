interface SkeletonProps {
  className?: string;
}

/**
 * A grey placeholder block. Composed into per-page loading shapes.
 *
 * The dark variant is not decoration. Without it the eight loading cards in
 * the library grid are near-white blocks on a near-black page, which is the
 * brightest thing in the app and appears on every cold load.
 */
export default function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div className={`bg-paper-200 rounded dark:bg-paper-800 ${className}`} />
  );
}
