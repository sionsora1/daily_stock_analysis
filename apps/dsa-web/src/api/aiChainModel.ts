import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  AIChainBacktestResult,
  AIChainModelSnapshot,
  AIChainModelTask,
} from '../types/aiChainModel';

function toSnapshot(data: Record<string, unknown>): AIChainModelSnapshot {
  return toCamelCase<AIChainModelSnapshot>(data);
}

function toTask(data: Record<string, unknown>): AIChainModelTask {
  return toCamelCase<AIChainModelTask>(data);
}

export const aiChainModelApi = {
  async getLatest(): Promise<AIChainModelSnapshot> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/ai-chain-model/latest');
    return toSnapshot(response.data);
  },

  async submitRun(asOfDate?: string): Promise<AIChainModelTask> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/ai-chain-model/runs', {
      as_of_date: asOfDate,
    });
    return toTask(response.data);
  },

  async getTask(taskId: string): Promise<AIChainModelTask> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/ai-chain-model/runs/${taskId}`);
    return toTask(response.data);
  },

  async submitBacktest(): Promise<AIChainModelTask> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/ai-chain-model/backtests', {
      holding_days: 20,
      rebalance_every_days: 5,
    });
    return toTask(response.data);
  },

  async getBacktest(backtestRunId: number): Promise<AIChainBacktestResult> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/ai-chain-model/backtests/${backtestRunId}`);
    return toCamelCase<AIChainBacktestResult>(response.data);
  },
};
