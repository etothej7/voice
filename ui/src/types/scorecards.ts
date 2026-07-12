export type Verdict = 'pass' | 'needs_improvement';
export type InterestLevel = 'strong' | 'moderate' | 'weak';

export type CriterionKey =
  | 'delivery_engagement'
  | 'value_prop_clarity'
  | 'relevance'
  | 'discovery_progression';

export interface Evidence {
  timestamp: string;
  quote: string;
}

export interface CriterionResult {
  verdict: Verdict;
  explanation: string;
  evidence: Evidence[];
}

export interface SellerScore {
  criteria: Partial<Record<CriterionKey, CriterionResult>>;
  coaching_action: string;
}

export interface BuyerSignal {
  signal: string;
  timestamp: string;
  quote: string;
}

export interface BuyerScore {
  interest: InterestLevel;
  signals: BuyerSignal[];
}

export interface SpeakerAcoustics {
  words: number;
  questions: number;
  speech_min: number;
  loudness_mean: number | null;
  loudness_cv: number | null;
  f0_std_semitones: number | null;
  pace_peaks_per_sec: number | null;
  talk_share_pct: number;
  arousal?: number;
  valence?: number;
  dominance?: number;
  arousal_thirds?: (number | null)[];
  seconds_analyzed?: number;
}

export interface Scorecard {
  call: string;
  source: { recording: string; notes: string };
  rubric_version: string;
  acoustics: Record<string, SpeakerAcoustics>;
  call_summary: string;
  sellers: Record<string, SellerScore>;
  buyers: Record<string, BuyerScore>;
}

export interface LedgerCall {
  call: string;
  talk_share_pct: number;
  questions: number;
  speech_min: number;
  loudness_mean: number | null;
  loudness_cv: number | null;
  f0_std_semitones: number | null;
  pace_peaks_per_sec: number | null;
  rubric: Partial<Record<CriterionKey, Verdict>>;
}

export interface LedgerBaseline {
  n_calls: number;
  active: boolean;
}

export type DispositionLevel = 'high_energy' | 'steady' | 'flat' | 'insufficient_data';

export interface Disposition {
  level: DispositionLevel;
  n_calls: number;
  mean_arousal?: number;
  ceiling?: number;
  fade_rate?: number;
  range_mean?: number | null;
  fade_warning?: boolean;
  thresholds_version?: string;
}

export interface Ledger {
  rep: string;
  calls: LedgerCall[];
  baseline?: LedgerBaseline;
  disposition?: Disposition;
}

export interface ScorecardBundle {
  config: { sellers: string[]; min_calls_for_baseline: number };
  scorecards: Scorecard[];
  ledgers: Ledger[];
}
