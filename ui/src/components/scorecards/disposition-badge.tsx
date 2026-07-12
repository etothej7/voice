import { cn } from '@/lib/utils';
import { DISPOSITION_LABEL } from '@/lib/scorecards';
import type { Disposition } from '@/types/scorecards';

const levelClasses: Record<string, string> = {
  high_energy: 'bg-success/15 text-success',
  steady: 'bg-muted text-muted-foreground border border-border',
  flat: 'bg-destructive/15 text-destructive',
  insufficient_data: 'bg-muted text-muted-foreground border border-border',
};

export function DispositionBadge({
  disposition,
  className,
}: {
  disposition: Disposition | null;
  className?: string;
}) {
  if (!disposition) return <span className="text-muted-foreground">–</span>;
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
        levelClasses[disposition.level],
        className
      )}
    >
      {DISPOSITION_LABEL[disposition.level]}
    </span>
  );
}
