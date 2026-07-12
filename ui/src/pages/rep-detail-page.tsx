import { useMemo } from 'react';
import { ChevronRight, Target } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { BucketBadge } from '@/components/scorecards/bucket-badge';
import { CriteriaInfo } from '@/components/scorecards/criteria-info';
import { DispositionBadge } from '@/components/scorecards/disposition-badge';
import { InterestBadge } from '@/components/scorecards/interest-badge';
import { VerdictDot } from '@/components/scorecards/verdict-badge';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useScorecards } from '@/hooks/use-scorecards';
import { buildReps, CRITERIA, passRate } from '@/lib/scorecards';
import { cn, getErrorMessage } from '@/lib/utils';

function MetricTile({ value, label }: { value: string; label: string }) {
  return (
    <Card>
      <CardContent density="compact" className="pt-4">
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  );
}

export function RepDetailPage() {
  const { repSlug } = useParams<{ repSlug: string }>();
  const navigate = useNavigate();
  const { data, isLoading, error } = useScorecards();

  const rep = useMemo(
    () => (data ? buildReps(data).find((r) => r.slug === repSlug) : undefined),
    [data, repSlug]
  );

  if (error) {
    return (
      <p className="text-sm text-destructive">
        {getErrorMessage(error, 'Failed to load scorecards.')}
      </p>
    );
  }
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!rep) return <p className="text-sm text-muted-foreground">Rep not found.</p>;

  const overallRate = passRate(rep.overall);

  return (
    <div className="space-y-4">
      <nav className="flex items-center gap-1 text-sm text-muted-foreground">
        <Link to="/" className="text-primary hover:underline">
          Team
        </Link>
        <ChevronRight className="size-3.5" />
        <span>{rep.name}</span>
      </nav>

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{rep.name}</h1>
          <p className="text-sm text-muted-foreground">
            {rep.calls.length} scored call{rep.calls.length !== 1 ? 's' : ''}
          </p>
        </div>
        <Badge variant="outline" className="font-normal text-muted-foreground">
          {rep.baselineActive
            ? 'baseline active'
            : `baseline ${rep.baselineCalls}/${data?.config.min_calls_for_baseline ?? 5}`}
        </Badge>
      </div>

      <Card>
        <CardContent density="compact" className="space-y-1.5 pt-4">
          <div className="flex flex-wrap items-center gap-2.5">
            <BucketBadge bucket={rep.bucket} size="lg" />
            {rep.disposition && rep.disposition.level !== 'insufficient_data' && (
              <DispositionBadge disposition={rep.disposition} />
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {rep.bucket.reason}
            {rep.disposition?.fade_warning &&
              ' Energy frequently fades in the back half of calls — worth reviewing call length or fatigue.'}
          </p>
          <p className="text-xs text-muted-foreground/70">
            Based on call quality only — activity (dials, connects) isn’t connected yet.
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-3 gap-3">
        <MetricTile
          value={overallRate == null ? '–' : `${Math.round(overallRate * 100)}%`}
          label="criteria passed"
        />
        <MetricTile value={rep.avgTalkShare == null ? '–' : `${rep.avgTalkShare}%`} label="avg talk share" />
        <MetricTile value={rep.avgQuestions == null ? '–' : String(rep.avgQuestions)} label="questions / call" />
      </div>

      <Card>
        <CardHeader density="compact">
          <CardTitle className="flex items-center justify-between text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Criteria
            <CriteriaInfo align="right" className="normal-case tracking-normal" />
          </CardTitle>
        </CardHeader>
        <CardContent density="compact" className="space-y-2.5">
          {CRITERIA.map((c) => {
            const fraction = rep.criteria[c.key];
            const pct = fraction.total
              ? Math.round((100 * fraction.passed) / fraction.total)
              : 0;
            return (
              <div key={c.key} className="flex items-center gap-3 text-sm">
                <span className="w-52 shrink-0">{c.label}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted dark:bg-secondary dark:border dark:border-border">
                  <span
                    className={cn(
                      'block h-full rounded-full',
                      pct >= 60 ? 'bg-success' : 'bg-warning'
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </span>
                <span className="w-10 text-right font-mono text-xs tabular-nums text-muted-foreground">
                  {fraction.total ? `${fraction.passed}/${fraction.total}` : '–'}
                </span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {rep.coaching && (
        <Card className="border-l-2 border-l-primary">
          <CardContent density="compact" className="flex items-start gap-3 pt-4">
            <Target className="mt-0.5 size-4 shrink-0 text-primary" />
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-primary">
                Current coaching focus
              </div>
              <p className="mt-1 text-sm">{rep.coaching}</p>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader density="compact" divided>
          <CardTitle className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Meetings
          </CardTitle>
        </CardHeader>
        <CardContent density="none">
          {rep.calls.map((call) => (
            <button
              key={call.call}
              type="button"
              onClick={() => navigate(`/calls/${call.call}?rep=${rep.slug}`)}
              className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 border-b border-border/70 px-5 py-3 text-left transition-colors last:border-b-0 hover:bg-muted/50"
            >
              <span className="font-mono text-xs text-muted-foreground">{call.date}</span>
              <span className="text-sm font-medium">{call.title}</span>
              <span className="flex items-center gap-2 text-sm text-muted-foreground">
                {call.buyers.map((buyer) => (
                  <span key={buyer.name} className="inline-flex items-center gap-1.5">
                    {buyer.name} <InterestBadge level={buyer.interest} />
                  </span>
                ))}
              </span>
              <span className="ml-auto flex items-center gap-1.5">
                {CRITERIA.map((c) => (
                  <VerdictDot key={c.key} verdict={call.verdicts[c.key]} label={c.label} />
                ))}
              </span>
            </button>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
