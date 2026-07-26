export type IntradayMonitorStatus =
  | 'observe'
  | 'preliminary'
  | 'confirmed'
  | 'continue_observing'
  | 'invalidated'
  | 'data_insufficient'
  | 'inactive'
  | string;

export interface IntradayMonitorInstrument {
  code: string;
  name?: string;
  price?: number | null;
  change_pct?: number | null;
  open_price?: number | null;
  amount?: number | null;
  volume?: number | null;
  turnover_rate?: number | null;
  pattern?: string;
  recent_flow?: number | null;
  previous_flow?: number | null;
  above_open?: boolean;
  valid?: boolean;
  fields_missing?: string[];
  data_issues?: string[];
  data_source?: string | null;
  fetched_at?: string | null;
  provider_timestamp?: string | null;
  is_stale?: boolean | null;
  source_is_stale?: boolean | null;
  freshness?: 'fresh' | 'stale' | 'unknown' | string;
  is_fresh?: boolean;
  quote_age_seconds?: number | null;
  freshness_reason?: string | null;
  freshness_timestamp_source?: string | null;
  representative_roles?: string[];
}

export interface IntradayRepresentativeGroup {
  key: string;
  label: string;
  core_symbols: string[];
  backup_symbols: string[];
}

export interface IntradayRepresentativeCoverageGroup extends IntradayRepresentativeGroup {
  core_valid_codes?: string[];
  backup_valid_codes?: string[];
  core_available?: number;
  valid?: boolean;
  used_role?: 'core' | 'backup' | string | null;
  fallback_used?: boolean;
  reason?: string;
}

export interface IntradayMonitorSnapshot {
  status?: IntradayMonitorStatus;
  phase?: string;
  as_of?: string;
  data_quality?: string;
  data_sources?: string[];
  event?: IntradayMonitorInstrument;
  sector?: IntradayMonitorInstrument;
  breadth?: {
    total?: number;
    available?: number;
    strong?: number;
    required?: number;
    ratio?: number;
    valid?: boolean;
  };
  representative_coverage?: {
    enabled?: boolean;
    groups?: IntradayRepresentativeCoverageGroup[];
    strong?: number;
    required?: number;
    valid?: boolean;
  };
  markers?: IntradayMonitorInstrument[];
  trigger_values?: Record<string, unknown>;
  streak?: number;
  confirm_streak?: number;
  reason?: string;
}

export interface IntradayMonitorPlan {
  id: number;
  name: string;
  event_symbol: string;
  sector_symbol: string;
  monitored_symbols: string[];
  representative_groups: IntradayRepresentativeGroup[];
  representative_groups_source?: 'configured' | 'default' | 'legacy' | 'none' | string;
  majority_ratio: number;
  required_count: number;
  initial_time: string;
  confirm_time: string;
  poll_interval_seconds: number;
  listing_day_mode: boolean;
  start_date?: string | null;
  end_date?: string | null;
  enabled: boolean;
  paused: boolean;
  current_status: IntradayMonitorStatus;
  last_evaluated_at?: string | null;
  snapshot: IntradayMonitorSnapshot;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface IntradayMonitorHistoryItem {
  id: number;
  plan_id: number;
  status: IntradayMonitorStatus;
  reason?: string | null;
  values: IntradayMonitorSnapshot;
  created_at?: string | null;
}

export interface IntradayMonitorPlanPayload {
  name: string;
  event_symbol: string;
  sector_symbol: string;
  monitored_symbols: string[];
  representative_groups: IntradayRepresentativeGroup[];
  majority_ratio: number;
  initial_time: string;
  confirm_time: string;
  poll_interval_seconds: number;
  listing_day_mode: boolean;
  start_date?: string | null;
  end_date?: string | null;
  enabled?: boolean;
  paused?: boolean;
}

export interface IntradaySimulationStep {
  as_of: string;
  status: IntradayMonitorStatus;
  reason?: string;
  breadth?: IntradayMonitorSnapshot['breadth'];
  representative_coverage?: IntradayMonitorSnapshot['representative_coverage'];
  trigger_values?: Record<string, unknown>;
  event?: IntradayMonitorInstrument;
  sector?: IntradayMonitorInstrument;
}

export interface IntradaySimulationResult {
  plan_id: number;
  mode: string;
  as_of: string;
  passed: boolean;
  expected_statuses: IntradayMonitorStatus[];
  transition_statuses: IntradayMonitorStatus[];
  transitions: IntradaySimulationStep[];
  steps: IntradaySimulationStep[];
  message: string;
}
