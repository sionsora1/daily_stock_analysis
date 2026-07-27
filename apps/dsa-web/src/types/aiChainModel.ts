export type AIChainGroup = 'hardware' | 'edge' | 'application';
export type AIChainTier = 'core' | 'observation';
export type AIChainAction = 'buy' | 'hold' | 'reduce' | 'avoid' | 'data_insufficient';
export type AIChainMarketGate = 'normal' | 'caution' | 'risk_off';
export type AIChainTaskKind = 'daily_run' | 'backtest';
export type AIChainTaskStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface AIChainModelScore {
  code: string;
  name: string;
  group: AIChainGroup;
  hardwareSubgroup?: string | null;
  tier: AIChainTier;
  score?: number | null;
  factorSnapshot: Record<string, unknown>;
  qualitySnapshot: Record<string, unknown>;
  probabilityUp?: number | null;
  probabilityOutperform?: number | null;
  expectedReturn?: number | null;
  returnLow?: number | null;
  returnHigh?: number | null;
  drawdownRisk?: number | null;
  action: AIChainAction;
  rank: number;
  suggestedWeight: number;
}

export interface AIChainModelSnapshot {
  id: number;
  asOfDate: string;
  modelVersion: string;
  status: string;
  marketGate?: AIChainMarketGate | null;
  dataCoverage?: number | null;
  warnings: string[];
  modelProfile: Record<string, unknown>;
  dataQuality: Record<string, Record<string, unknown>>;
  scores: AIChainModelScore[];
  isStale: boolean;
}

export interface AIChainModelTask {
  taskId: string;
  kind: AIChainTaskKind;
  status: AIChainTaskStatus;
  progress: number;
  message: string;
  result?: Record<string, unknown> | null;
  error?: string | null;
  createdAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
}

export interface AIChainBacktestResult {
  id: number;
  status: string;
  metrics: Record<string, number | string | null>;
  failureReason?: string | null;
  pointTotal: number;
}
