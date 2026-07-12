import { cn } from '@/lib/utils';
import { BUCKET_LABEL, type BucketVerdict } from '@/lib/scorecards';

const bucketClasses: Record<string, string> = {
  performer: 'bg-success/15 text-success',
  coachable: 'bg-warning/15 text-warning',
  inconsistent: 'bg-muted text-muted-foreground border border-border',
  underperformer: 'bg-destructive/15 text-destructive',
  insufficient_data: 'bg-muted text-muted-foreground border border-border',
};

export function BucketBadge({
  bucket,
  size = 'sm',
  className,
}: {
  bucket: BucketVerdict;
  size?: 'sm' | 'lg';
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center whitespace-nowrap rounded-full font-semibold',
        size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2.5 py-0.5 text-xs',
        bucketClasses[bucket.key],
        className
      )}
    >
      {BUCKET_LABEL[bucket.key]}
    </span>
  );
}
