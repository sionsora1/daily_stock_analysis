import apiClient from './index';
import type {
  IntradayMonitorHistoryItem,
  IntradayMonitorPlan,
  IntradayMonitorPlanPayload,
  IntradaySimulationResult,
} from '../types/intradayMonitor';

type PlanListResponse = { items: IntradayMonitorPlan[]; total: number };
type HistoryResponse = { items: IntradayMonitorHistoryItem[]; total: number };

function toSnakePayload(payload: Partial<IntradayMonitorPlanPayload>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  const fields: Array<[keyof IntradayMonitorPlanPayload, string]> = [
    ['name', 'name'],
    ['event_symbol', 'event_symbol'],
    ['sector_symbol', 'sector_symbol'],
    ['monitored_symbols', 'monitored_symbols'],
    ['majority_ratio', 'majority_ratio'],
    ['initial_time', 'initial_time'],
    ['confirm_time', 'confirm_time'],
    ['poll_interval_seconds', 'poll_interval_seconds'],
    ['listing_day_mode', 'listing_day_mode'],
    ['start_date', 'start_date'],
    ['end_date', 'end_date'],
    ['enabled', 'enabled'],
    ['paused', 'paused'],
  ];
  for (const [source, target] of fields) {
    if (payload[source] !== undefined) {
      result[target] = payload[source] ?? null;
    }
  }
  return result;
}

export const intradayMonitorApi = {
  async listPlans(): Promise<PlanListResponse> {
    const response = await apiClient.get<PlanListResponse>('/api/v1/intraday-monitor/plans');
    return response.data;
  },

  async createPlan(payload: IntradayMonitorPlanPayload): Promise<IntradayMonitorPlan> {
    const response = await apiClient.post<IntradayMonitorPlan>(
      '/api/v1/intraday-monitor/plans',
      toSnakePayload(payload),
    );
    return response.data;
  },

  async updatePlan(planId: number, payload: Partial<IntradayMonitorPlanPayload>): Promise<IntradayMonitorPlan> {
    const response = await apiClient.patch<IntradayMonitorPlan>(
      `/api/v1/intraday-monitor/plans/${planId}`,
      toSnakePayload(payload),
    );
    return response.data;
  },

  async setEnabled(planId: number, enabled: boolean): Promise<IntradayMonitorPlan> {
    const response = await apiClient.post<IntradayMonitorPlan>(
      `/api/v1/intraday-monitor/plans/${planId}/${enabled ? 'enable' : 'disable'}`,
    );
    return response.data;
  },

  async setPaused(planId: number, paused: boolean): Promise<IntradayMonitorPlan> {
    const response = await apiClient.post<IntradayMonitorPlan>(
      `/api/v1/intraday-monitor/plans/${planId}/${paused ? 'pause' : 'resume'}`,
    );
    return response.data;
  },

  async evaluateNow(): Promise<PlanListResponse> {
    const response = await apiClient.post<PlanListResponse>('/api/v1/intraday-monitor/evaluate');
    return response.data;
  },

  async simulatePlan(planId: number): Promise<IntradaySimulationResult> {
    const response = await apiClient.post<IntradaySimulationResult>(
      `/api/v1/intraday-monitor/plans/${planId}/simulate`,
    );
    return response.data;
  },

  async listHistory(planId: number, days = 30): Promise<HistoryResponse> {
    const response = await apiClient.get<HistoryResponse>(
      `/api/v1/intraday-monitor/plans/${planId}/history`,
      { params: { days } },
    );
    return response.data;
  },
};
