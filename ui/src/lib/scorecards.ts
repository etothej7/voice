import type {
  CriterionKey,
  Disposition,
  DispositionLevel,
  InterestLevel,
  Scorecard,
  ScorecardBundle,
  Verdict,
} from '@/types/scorecards';

export const DISPOSITION_LABEL: Record<DispositionLevel, string> = {
  high_energy: 'High energy',
  steady: 'Steady',
  flat: 'Flat — review',
  insufficient_data: 'Insufficient data',
};

export const CRITERIA: {
  key: CriterionKey;
  label: string;
  short: string;
  description: string;
}[] = [
  {
    key: 'delivery_engagement',
    label: 'Delivery & engagement',
    short: 'Delivery',
    description:
      'Did they sound engaged — energy, vocal variety, confidence? Judged against the rep’s own baseline, so quieter styles aren’t penalized.',
  },
  {
    key: 'value_prop_clarity',
    label: 'Value prop clarity',
    short: 'Value prop',
    description:
      'Did they clearly explain what the product does and why it matters, in plain terms the buyer could repeat to their boss?',
  },
  {
    key: 'relevance',
    label: 'Relevance',
    short: 'Relevance',
    description:
      'Did they tailor the pitch to this buyer’s business and situation, or run a generic script?',
  },
  {
    key: 'discovery_progression',
    label: 'Discovery & progression',
    short: 'Discovery',
    description:
      'Did they ask questions that uncover the buyer’s needs and close with a concrete, dated next step?',
  },
];

export const INTEREST_LABEL: Record<InterestLevel, string> = {
  strong: 'Strong interest',
  moderate: 'Moderate interest',
  weak: 'Weak interest',
};

export function repSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

export interface CallMeta {
  title: string;
  date: string;
}

export function callMeta(slug: string): CallMeta {
  const m = slug.match(/(.+?)-(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return { title: slug, date: '' };
  const title = m[1]
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
    .replace(' Io', '.io')
    .replace(/^Mode /, 'MODE ');
  return { title, date: `${m[2]}-${m[3]}-${m[4]}` };
}

export interface PassFraction {
  passed: number;
  total: number;
}

export interface RepCallSummary {
  call: string;
  title: string;
  date: string;
  verdicts: Partial<Record<CriterionKey, Verdict>>;
  talkSharePct: number | null;
  questions: number | null;
  buyers: { name: string; interest: InterestLevel }[];
}

export interface RepSummary {
  name: string;
  slug: string;
  calls: RepCallSummary[];
  criteria: Record<CriterionKey, PassFraction>;
  overall: PassFraction;
  avgTalkShare: number | null;
  avgQuestions: number | null;
  coaching: string | null;
  baselineCalls: number;
  baselineActive: boolean;
  disposition: Disposition | null;
  bucket: BucketVerdict;
}

export type BucketKey =
  | 'performer'
  | 'coachable'
  | 'inconsistent'
  | 'underperformer'
  | 'insufficient_data';

export interface BucketVerdict {
  key: BucketKey;
  reason: string;
}

export const BUCKET_LABEL: Record<BucketKey, string> = {
  performer: 'Performer',
  coachable: 'Coachable',
  inconsistent: 'Inconsistent / constrained',
  underperformer: 'Under-performer',
  insufficient_data: 'Insufficient data',
};

export const BUCKET_RANK: Record<BucketKey, number> = {
  performer: 4,
  coachable: 3,
  inconsistent: 2,
  insufficient_data: 1,
  underperformer: 0,
};

// Quality bars for bucket legs. Activity (dials/connects) isn't wired yet, so
// buckets classify the call-quality axis only.
const DELIVERY_BAR = 0.7;
const VALUE_PROP_BAR = 0.7;
const ADVANCE_BAR = 0.5;

function computeBucket(rep: Omit<RepSummary, 'bucket'>, minCalls: number): BucketVerdict {
  if (rep.calls.length < minCalls) {
    return {
      key: 'insufficient_data',
      reason: `Below the ${minCalls}-call minimum for a performance label.`,
    };
  }

  const rate = (key: CriterionKey) => passRate(rep.criteria[key]) ?? 0;
  const engaged = rate('delivery_engagement') >= DELIVERY_BAR && rep.disposition?.level !== 'flat';
  const gaps: string[] = [];
  if (rate('value_prop_clarity') < VALUE_PROP_BAR) gaps.push('a clear value proposition');
  if (rate('relevance') < VALUE_PROP_BAR) gaps.push('tailoring to the buyer');
  if (rate('discovery_progression') < ADVANCE_BAR) gaps.push('the next-step ask');

  if (engaged && gaps.length === 0) {
    return {
      key: 'performer',
      reason: 'Clear value proposition, engaged delivery, and conversations advance.',
    };
  }
  if (engaged) {
    return {
      key: 'coachable',
      reason: `Brings good energy to calls, but consistently misses ${gaps.join(' and ')} — a trainable behavior.`,
    };
  }
  return {
    key: 'underperformer',
    reason:
      gaps.length > 0
        ? `Delivery is flat or disengaged and calls miss ${gaps.join(' and ')}.`
        : 'Delivery is flat or disengaged across the sample.',
  };
}

function average(values: number[]): number | null {
  if (!values.length) return null;
  return Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10;
}

export function buildReps(bundle: ScorecardBundle): RepSummary[] {
  const reps = new Map<string, Omit<RepSummary, 'bucket'>>();
  const sorted = [...bundle.scorecards].sort((a, b) => a.call.localeCompare(b.call));

  for (const sc of sorted) {
    const meta = callMeta(sc.call);
    const buyers = Object.entries(sc.buyers ?? {}).map(([name, b]) => ({
      name,
      interest: b.interest,
    }));

    for (const [name, seller] of Object.entries(sc.sellers ?? {})) {
      let rep = reps.get(name);
      if (!rep) {
        rep = {
          name,
          slug: repSlug(name),
          calls: [],
          criteria: Object.fromEntries(
            CRITERIA.map((c) => [c.key, { passed: 0, total: 0 }])
          ) as Record<CriterionKey, PassFraction>,
          overall: { passed: 0, total: 0 },
          avgTalkShare: null,
          avgQuestions: null,
          coaching: null,
          baselineCalls: 0,
          baselineActive: false,
          disposition: null,
        };
        reps.set(name, rep);
      }

      const verdicts: Partial<Record<CriterionKey, Verdict>> = {};
      for (const { key } of CRITERIA) {
        const verdict = seller.criteria?.[key]?.verdict;
        if (!verdict) continue;
        verdicts[key] = verdict;
        rep.criteria[key].total += 1;
        rep.overall.total += 1;
        if (verdict === 'pass') {
          rep.criteria[key].passed += 1;
          rep.overall.passed += 1;
        }
      }

      const acoustics = sc.acoustics?.[name];
      rep.calls.push({
        call: sc.call,
        title: meta.title,
        date: meta.date,
        verdicts,
        talkSharePct: acoustics?.talk_share_pct ?? null,
        questions: acoustics?.questions ?? null,
        buyers,
      });
      // sorted ascending by slug (date-prefixed), so the last write wins = latest call
      rep.coaching = seller.coaching_action ?? rep.coaching;
    }
  }

  const minCalls = bundle.config.min_calls_for_baseline ?? 5;
  return [...reps.values()].map((rep) => {
    rep.calls.sort((a, b) => b.date.localeCompare(a.date));
    rep.avgTalkShare = average(rep.calls.map((c) => c.talkSharePct).filter((v): v is number => v != null));
    rep.avgQuestions = average(rep.calls.map((c) => c.questions).filter((v): v is number => v != null));
    const ledger = bundle.ledgers.find((l) => l.rep === rep.name);
    rep.baselineCalls = ledger?.baseline?.n_calls ?? rep.calls.length;
    rep.baselineActive = ledger?.baseline?.active ?? false;
    rep.disposition = ledger?.disposition ?? null;
    return { ...rep, bucket: computeBucket(rep, minCalls) };
  });
}

export function passRate({ passed, total }: PassFraction): number | null {
  return total ? passed / total : null;
}

export interface TeamInsight {
  criterion: string;
  passed: number;
  total: number;
}

export function teamInsight(reps: RepSummary[]): TeamInsight | null {
  let worst: TeamInsight | null = null;
  let worstRate = 1;
  for (const { key, label } of CRITERIA) {
    let passed = 0;
    let total = 0;
    for (const rep of reps) {
      passed += rep.criteria[key].passed;
      total += rep.criteria[key].total;
    }
    if (!total) continue;
    const rate = passed / total;
    if (rate <= 0.5 && rate < worstRate) {
      worstRate = rate;
      worst = { criterion: label, passed, total };
    }
  }
  return worst;
}

export function findCall(bundle: ScorecardBundle, slug: string): Scorecard | undefined {
  return bundle.scorecards.find((sc) => sc.call === slug);
}

// --- Emotion bands ---------------------------------------------------------
// Raw model outputs cluster in a narrow range (e.g. arousal 0.42-0.58 across
// the whole team), so absolute numbers read as "no difference". Bands rank
// each value against everyone else in the same role (seller vs buyer).

export type EmotionMetric = 'arousal' | 'valence' | 'dominance';
export type EmotionBandLevel = 'low' | 'mid' | 'high';

const EMOTION_WORDS: Record<
  EmotionMetric,
  { name: string; low: string; mid: string; high: string }
> = {
  arousal: { name: 'energy', low: 'low', mid: 'typical', high: 'high' },
  valence: { name: 'tone', low: 'downbeat', mid: 'neutral', high: 'upbeat' },
  dominance: { name: 'presence', low: 'tentative', mid: 'steady', high: 'assertive' },
};

export interface EmotionStats {
  seller: Record<EmotionMetric, number[]>;
  buyer: Record<EmotionMetric, number[]>;
}

const EMOTION_METRICS: EmotionMetric[] = ['arousal', 'valence', 'dominance'];

export function buildEmotionStats(bundle: ScorecardBundle): EmotionStats {
  const sellers = new Set(bundle.config.sellers);
  const stats: EmotionStats = {
    seller: { arousal: [], valence: [], dominance: [] },
    buyer: { arousal: [], valence: [], dominance: [] },
  };
  for (const sc of bundle.scorecards) {
    for (const [name, a] of Object.entries(sc.acoustics ?? {})) {
      const role = sellers.has(name) ? 'seller' : 'buyer';
      for (const m of EMOTION_METRICS) {
        const v = a[m];
        if (v != null) stats[role][m].push(v);
      }
    }
  }
  for (const role of ['seller', 'buyer'] as const) {
    for (const m of EMOTION_METRICS) stats[role][m].sort((a, b) => a - b);
  }
  return stats;
}

function percentile(sorted: number[], value: number): number {
  if (!sorted.length) return 0.5;
  let below = 0;
  for (const v of sorted) {
    if (v <= value) below++;
    else break;
  }
  return below / sorted.length;
}

export interface EmotionBand {
  metric: EmotionMetric;
  name: string;
  word: string;
  level: EmotionBandLevel;
  percentile: number;
  raw: number;
}

export function emotionBands(
  stats: EmotionStats,
  role: 'seller' | 'buyer',
  acoustics: { arousal?: number; valence?: number; dominance?: number }
): EmotionBand[] {
  const bands: EmotionBand[] = [];
  for (const m of EMOTION_METRICS) {
    const raw = acoustics[m];
    if (raw == null) continue;
    const pct = percentile(stats[role][m], raw);
    const level: EmotionBandLevel = pct >= 0.75 ? 'high' : pct < 0.25 ? 'low' : 'mid';
    const words = EMOTION_WORDS[m];
    bands.push({ metric: m, name: words.name, word: words[level], level, percentile: pct, raw });
  }
  return bands;
}
