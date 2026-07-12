import { useQuery } from '@tanstack/react-query';

import type { ScorecardBundle } from '@/types/scorecards';

async function fetchScorecards(): Promise<ScorecardBundle> {
  const res = await fetch('/data/scorecards.json');
  if (!res.ok) {
    throw new Error(`Failed to load scorecards (${res.status})`);
  }
  return res.json();
}

export function useScorecards() {
  return useQuery({
    queryKey: ['scorecards'],
    queryFn: fetchScorecards,
  });
}
