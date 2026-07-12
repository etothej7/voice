import { cn } from '@/lib/utils';
import { INTEREST_LABEL } from '@/lib/scorecards';
import type { InterestLevel } from '@/types/scorecards';

const interestClasses: Record<InterestLevel, string> = {
  strong: 'bg-success/15 text-success',
  moderate: 'bg-warning/15 text-warning',
  weak: 'bg-destructive/10 text-destructive',
};

export function InterestBadge({ level, className }: { level: InterestLevel; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
        interestClasses[level],
        className
      )}
    >
      {INTEREST_LABEL[level]}
    </span>
  );
}
