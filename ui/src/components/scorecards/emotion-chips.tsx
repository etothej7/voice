import { cn } from '@/lib/utils';
import type { EmotionBand } from '@/lib/scorecards';

function chipClass(band: EmotionBand): string {
  // Presence (dominance) is descriptive, not good/bad — keep it neutral.
  if (band.metric === 'dominance' || band.level === 'mid') {
    return 'bg-muted text-muted-foreground border border-border';
  }
  return band.level === 'high' ? 'bg-success/15 text-success' : 'bg-warning/15 text-warning';
}

export function EmotionChips({ bands, className }: { bands: EmotionBand[]; className?: string }) {
  if (!bands.length) return null;
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1.5', className)}>
      {bands.map((band) => (
        <span
          key={band.metric}
          title={`${band.name}: ${Math.round(band.percentile * 100)}th percentile (${band.raw})`}
          className={cn(
            'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium',
            chipClass(band)
          )}
        >
          {band.name} {band.word}
        </span>
      ))}
    </span>
  );
}
