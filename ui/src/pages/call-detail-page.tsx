import { useMemo } from 'react';
import { ChevronRight, Target } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { EmotionChips } from '@/components/scorecards/emotion-chips';
import { EvidenceQuote } from '@/components/scorecards/evidence-quote';
import { InterestBadge } from '@/components/scorecards/interest-badge';
import { VerdictBadge } from '@/components/scorecards/verdict-badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useScorecards } from '@/hooks/use-scorecards';
import {
  buildEmotionStats,
  buildReps,
  callMeta,
  CRITERIA,
  emotionBands,
  findCall,
  repSlug,
} from '@/lib/scorecards';
import { getErrorMessage } from '@/lib/utils';

export function CallDetailPage() {
  const { callSlug } = useParams<{ callSlug: string }>();
  const [searchParams] = useSearchParams();
  const focusRepSlug = searchParams.get('rep');
  const { data, isLoading, error } = useScorecards();

  const call = useMemo(
    () => (data && callSlug ? findCall(data, callSlug) : undefined),
    [data, callSlug]
  );
  const focusRep = useMemo(
    () =>
      data && focusRepSlug
        ? buildReps(data).find((r) => r.slug === focusRepSlug)
        : undefined,
    [data, focusRepSlug]
  );
  const emotionStats = useMemo(() => (data ? buildEmotionStats(data) : null), [data]);

  if (error) {
    return (
      <p className="text-sm text-destructive">
        {getErrorMessage(error, 'Failed to load scorecards.')}
      </p>
    );
  }
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!call) return <p className="text-sm text-muted-foreground">Meeting not found.</p>;

  const meta = callMeta(call.call);
  const sellerNames = Object.keys(call.sellers ?? {}).sort((a, b) => {
    if (focusRep?.name === a) return -1;
    if (focusRep?.name === b) return 1;
    return a.localeCompare(b);
  });

  return (
    <div className="space-y-4">
      <nav className="flex items-center gap-1 text-sm text-muted-foreground">
        <Link to="/" className="text-primary hover:underline">
          Team
        </Link>
        {focusRep && (
          <>
            <ChevronRight className="size-3.5" />
            <Link to={`/reps/${focusRep.slug}`} className="text-primary hover:underline">
              {focusRep.name}
            </Link>
          </>
        )}
        <ChevronRight className="size-3.5" />
        <span>{meta.title}</span>
      </nav>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{meta.title}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
          <span className="font-mono text-xs">{meta.date}</span>
          {Object.entries(call.buyers ?? {}).map(([name, buyer]) => (
            <span key={name} className="inline-flex items-center gap-1.5">
              {name} <InterestBadge level={buyer.interest} />
            </span>
          ))}
        </p>
      </div>

      <p className="max-w-3xl text-sm text-muted-foreground">{call.call_summary}</p>

      {sellerNames.map((name) => {
        const seller = call.sellers[name];
        const acoustics = call.acoustics?.[name];
        return (
          <Card key={name}>
            <CardHeader density="compact" divided>
              <CardTitle className="flex flex-wrap items-baseline gap-x-3 text-base">
                {name}
                {acoustics && (
                  <>
                    <span className="font-mono text-xs font-normal text-muted-foreground">
                      {acoustics.talk_share_pct}% talk share · {acoustics.questions} questions
                    </span>
                    {emotionStats && (
                      <EmotionChips bands={emotionBands(emotionStats, 'seller', acoustics)} />
                    )}
                  </>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent density="compact" className="space-y-4 pt-4">
              <div className="grid gap-3 md:grid-cols-2">
                {CRITERIA.map((criterion) => {
                  const result = seller.criteria?.[criterion.key];
                  if (!result) return null;
                  return (
                    <div
                      key={criterion.key}
                      className="rounded-md border border-border/70 p-3.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold" title={criterion.description}>
                          {criterion.label}
                        </span>
                        <VerdictBadge verdict={result.verdict} />
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {result.explanation}
                      </p>
                      <div className="mt-2 space-y-2">
                        {result.evidence?.slice(0, 2).map((evidence) => (
                          <EvidenceQuote
                            key={`${evidence.timestamp}-${evidence.quote.slice(0, 24)}`}
                            evidence={evidence}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {seller.coaching_action && (
                <div className="flex items-start gap-3 rounded-md border border-border/70 border-l-2 border-l-primary bg-muted/40 p-3.5 dark:bg-transparent">
                  <Target className="mt-0.5 size-4 shrink-0 text-primary" />
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-primary">
                      Coaching action
                    </div>
                    <p className="mt-1 text-sm">{seller.coaching_action}</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}

      {Object.entries(call.buyers ?? {}).map(([name, buyer]) => (
        <Card key={name}>
          <CardHeader density="compact" divided>
            <CardTitle className="flex items-center gap-2 text-base">
              {name} — buyer signals <InterestBadge level={buyer.interest} />
            </CardTitle>
          </CardHeader>
          <CardContent density="compact" className="grid gap-4 pt-4 md:grid-cols-2">
            {buyer.signals?.map((signal) => (
              <div key={`${signal.timestamp}-${signal.signal.slice(0, 24)}`}>
                <p className="text-sm font-medium">{signal.signal}</p>
                <div className="mt-1.5">
                  <EvidenceQuote
                    evidence={{ timestamp: signal.timestamp, quote: signal.quote }}
                  />
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}

      {focusRepSlug && !focusRep && (
        <p className="text-xs text-muted-foreground">Rep “{repSlug(focusRepSlug)}” not found.</p>
      )}
    </div>
  );
}
