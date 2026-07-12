import { Check, TriangleAlert } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { Verdict } from '@/types/scorecards';

export function VerdictBadge({ verdict, className }: { verdict?: Verdict; className?: string }) {
  if (!verdict) return null;
  const pass = verdict === 'pass';
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold',
        pass ? 'bg-success/15 text-success' : 'bg-warning/15 text-warning',
        className
      )}
    >
      {pass ? <Check className="size-3" /> : <TriangleAlert className="size-3" />}
      {pass ? 'Pass' : 'Needs improvement'}
    </span>
  );
}

export function VerdictDot({ verdict, label }: { verdict?: Verdict; label: string }) {
  return (
    <span
      title={`${label}: ${verdict === 'pass' ? 'pass' : 'needs improvement'}`}
      className={cn(
        'inline-block size-2 rounded-[3px]',
        verdict === 'pass' ? 'bg-success' : 'bg-warning'
      )}
    />
  );
}
