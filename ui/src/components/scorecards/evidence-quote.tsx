import type { Evidence } from '@/types/scorecards';

export function EvidenceQuote({ evidence }: { evidence: Evidence }) {
  return (
    <blockquote className="border-l-2 border-border pl-3 text-sm italic text-muted-foreground">
      <span className="mr-2 font-mono text-xs not-italic text-muted-foreground/70">
        {evidence.timestamp}
      </span>
      &ldquo;{evidence.quote}&rdquo;
    </blockquote>
  );
}
