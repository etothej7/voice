import { useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Lightbulb } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { BucketBadge } from '@/components/scorecards/bucket-badge';
import { CriteriaInfo } from '@/components/scorecards/criteria-info';
import { DispositionBadge } from '@/components/scorecards/disposition-badge';
import { PassFractionText, PassRateBar } from '@/components/scorecards/pass-rate';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableEmptyRow,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useScorecards } from '@/hooks/use-scorecards';
import {
  BUCKET_RANK,
  buildReps,
  CRITERIA,
  passRate,
  teamInsight,
  type RepSummary,
} from '@/lib/scorecards';
import { cn, getErrorMessage } from '@/lib/utils';

type SortKey =
  | 'name'
  | 'calls'
  | 'bucket'
  | 'score'
  | 'talk'
  | 'questions'
  | 'engagement'
  | (typeof CRITERIA)[number]['key'];

const dispositionRank: Record<string, number> = {
  high_energy: 3,
  steady: 2,
  flat: 0,
  insufficient_data: 1,
};

const sortAccessors: Record<SortKey, (rep: RepSummary) => string | number> = {
  name: (rep) => rep.name,
  calls: (rep) => rep.calls.length,
  bucket: (rep) => BUCKET_RANK[rep.bucket.key],
  score: (rep) => passRate(rep.overall) ?? -1,
  talk: (rep) => rep.avgTalkShare ?? -1,
  questions: (rep) => rep.avgQuestions ?? -1,
  engagement: (rep) => (rep.disposition ? dispositionRank[rep.disposition.level] : -1),
  delivery_engagement: (rep) => passRate(rep.criteria.delivery_engagement) ?? -1,
  value_prop_clarity: (rep) => passRate(rep.criteria.value_prop_clarity) ?? -1,
  relevance: (rep) => passRate(rep.criteria.relevance) ?? -1,
  discovery_progression: (rep) => passRate(rep.criteria.discovery_progression) ?? -1,
};

export function TeamPage() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useScorecards();
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDesc, setSortDesc] = useState(true);

  const reps = useMemo(() => (data ? buildReps(data) : []), [data]);
  const insight = useMemo(() => teamInsight(reps), [reps]);

  const sortedReps = useMemo(() => {
    const accessor = sortAccessors[sortKey];
    return [...reps].sort((a, b) => {
      const va = accessor(a);
      const vb = accessor(b);
      const cmp =
        typeof va === 'string' && typeof vb === 'string'
          ? va.localeCompare(vb)
          : Number(va) - Number(vb);
      return sortDesc ? -cmp : cmp;
    });
  }, [reps, sortKey, sortDesc]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDesc((d) => !d);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  }

  function sortableHead(key: SortKey, label: string, className?: string) {
    const active = key === sortKey;
    const Arrow = sortDesc ? ArrowDown : ArrowUp;
    return (
      <TableHead
        className={cn('cursor-pointer select-none whitespace-nowrap', className)}
        aria-sort={active ? (sortDesc ? 'descending' : 'ascending') : undefined}
        onClick={() => toggleSort(key)}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {active && <Arrow className="size-3" />}
        </span>
      </TableHead>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-destructive">
        {getErrorMessage(error, 'Failed to load scorecards.')}
      </p>
    );
  }

  const callCount = data?.scorecards.length ?? 0;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Team</h1>
        <p className="text-sm text-muted-foreground">
          {reps.length} reps · {callCount} scored calls
        </p>
      </div>

      {insight && (
        <Card className="flex items-start gap-3 border-l-2 border-l-primary p-4">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" />
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Team insight:</span>{' '}
            only {insight.passed} of {insight.total} gradings passed{' '}
            <span className="font-medium text-foreground">{insight.criterion}</span> — the
            team&apos;s biggest open coaching area.
          </p>
        </Card>
      )}

      <Card>
        <div className="flex items-center justify-end border-b border-border/70 px-5 py-2">
          <CriteriaInfo align="right" />
        </div>
        <div className="scroll-affordance overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                {sortableHead('name', 'Rep')}
                {sortableHead('bucket', 'Bucket')}
                {sortableHead('calls', 'Calls', 'text-right')}
                {sortableHead('score', 'Score')}
                {CRITERIA.map((c) => sortableHead(c.key, c.short, 'text-right'))}
                {sortableHead('engagement', 'Engagement')}
                {sortableHead('talk', 'Talk %', 'text-right')}
                {sortableHead('questions', 'Questions', 'text-right')}
                <TableHead>Baseline</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && <TableEmptyRow colSpan={12}>Loading…</TableEmptyRow>}
              {!isLoading && sortedReps.length === 0 && (
                <TableEmptyRow colSpan={12}>No scored calls yet.</TableEmptyRow>
              )}
              {sortedReps.map((rep) => (
                <TableRow
                  key={rep.slug}
                  interactive
                  onClick={() => navigate(`/reps/${rep.slug}`)}
                >
                  <TableCell className="font-medium">{rep.name}</TableCell>
                  <TableCell>
                    <BucketBadge bucket={rep.bucket} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{rep.calls.length}</TableCell>
                  <TableCell>
                    <PassRateBar fraction={rep.overall} />
                  </TableCell>
                  {CRITERIA.map((c) => (
                    <TableCell key={c.key} className="text-right">
                      <PassFractionText fraction={rep.criteria[c.key]} />
                    </TableCell>
                  ))}
                  <TableCell>
                    <DispositionBadge disposition={rep.disposition} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rep.avgTalkShare ?? '–'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {rep.avgQuestions ?? '–'}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="font-normal text-muted-foreground">
                      {rep.baselineActive
                        ? 'active'
                        : `${rep.baselineCalls}/${data?.config.min_calls_for_baseline ?? 5}`}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>

    </div>
  );
}
