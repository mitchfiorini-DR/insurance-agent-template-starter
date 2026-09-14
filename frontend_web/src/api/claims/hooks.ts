import { useQuery } from '@tanstack/react-query';
import { fetchClaims, fetchRecommendation } from './api-requests';

export function useClaims() {
  return useQuery({
    queryKey: ['claims'],
    queryFn: fetchClaims,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  });
}

export function useRecommendation(claimId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['recommendation', claimId],
    queryFn: () => fetchRecommendation(claimId),
    enabled,
    staleTime: Infinity,
    retry: 1,
  });
}
