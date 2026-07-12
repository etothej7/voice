import { cn } from '@/lib/utils';
import type { PassFraction } from '@/lib/scorecards';

export function PassRateBar({
  fraction,
  className,
}: {
  fraction: PassFraction;
  className?: string;
}) {
  const pct = fraction.total ? Math.round((100 * fraction.passed) / fraction.total) : 0;
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span className="w-10 text-right font-medium tabular-nums">
        {fraction.total ? `${pct}%` : '–'}
      </span>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-muted dark:bg-secondary dark:border dark:border-border">
        <span
          className={cn('block h-full rounded-full', pct >= 60 ? 'bg-success' : 'bg-warning')}
          style={{ width: `${pct}%` }}
        />
      </span>
    </span>
  );
}

export function PassFractionText({ fraction }: { fraction: PassFraction }) {
  if (!fraction.total) return <span className="text-muted-foreground">–</span>;
  const rate = fraction.passed / fraction.total;
  return (
    <span
      className={cn(
        'font-medium tabular-nums',
        rate === 1 && 'text-success',
        rate < 0.5 && 'text-warning'
      )}
    >
      {fraction.passed}/{fraction.total}
    </span>
  );
}
