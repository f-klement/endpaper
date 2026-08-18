import { useGetStats } from "../../api/generated/endpoints/stats/stats";
import type { StatsOut } from "../../api/generated/model";

export interface UseStatsResult {
  stats: StatsOut | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

export function useStats(): UseStatsResult {
  const query = useGetStats();
  return {
    stats: query.data,
    isLoading: query.isPending,
    error: query.error,
    refetch: () => void query.refetch(),
  };
}
