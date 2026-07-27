import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import AiChainModelPage from '../AiChainModelPage';

const { getLatest, submitRun, submitBacktest, getTask, getBacktest } = vi.hoisted(() => ({
  getLatest: vi.fn(),
  submitRun: vi.fn(),
  submitBacktest: vi.fn(),
  getTask: vi.fn(),
  getBacktest: vi.fn(),
}));

vi.mock('../../api/aiChainModel', () => ({
  aiChainModelApi: { getLatest, submitRun, submitBacktest, getTask, getBacktest },
}));

const snapshot = {
  id: 1,
  asOfDate: '2026-07-24',
  modelVersion: 'v1',
  status: 'succeeded',
  marketGate: 'normal' as const,
  dataCoverage: 0.96,
  warnings: [],
  modelProfile: { holdingDays: 20 },
  dataQuality: { '000977': { status: 'ready' } },
  scores: [
    {
      code: '000977',
      name: 'Hardware sample',
      group: 'hardware' as const,
      tier: 'core' as const,
      score: 72.3,
      factorSnapshot: {},
      qualitySnapshot: { status: 'ready' },
      action: 'buy' as const,
      rank: 1,
      suggestedWeight: 0.15,
    },
    {
      code: '300000',
      name: 'Edge sample',
      group: 'edge' as const,
      tier: 'core' as const,
      score: 65.5,
      factorSnapshot: {},
      qualitySnapshot: { status: 'ready' },
      action: 'hold' as const,
      rank: 2,
      suggestedWeight: 0,
    },
    {
      code: '600000',
      name: 'Application sample',
      group: 'application' as const,
      tier: 'observation' as const,
      score: 59.2,
      factorSnapshot: {},
      qualitySnapshot: { status: 'degraded' },
      action: 'avoid' as const,
      rank: 3,
      suggestedWeight: 0,
    },
  ],
  isStale: false,
};

function renderPage() {
  return render(<UiLanguageProvider><AiChainModelPage /></UiLanguageProvider>);
}

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem('dsa.uiLanguage', 'en');
  vi.clearAllMocks();
  getLatest.mockResolvedValue(snapshot);
  submitRun.mockResolvedValue({
    taskId: 'daily-task', kind: 'daily_run', status: 'completed', progress: 100,
    message: 'completed', createdAt: '2026-07-24T15:00:00',
  });
});

describe('AiChainModelPage', () => {
  it('renders the three agreed AI-chain branches from the latest snapshot', async () => {
    renderPage();

    expect(await screen.findByText('Hardware sample')).toBeInTheDocument();
    expect(screen.getByText('Edge sample')).toBeInTheDocument();
    expect(screen.getByText('Application sample')).toBeInTheDocument();
    expect(screen.getByText('Normal')).toBeInTheDocument();
    expect(screen.getByText('15.0%')).toBeInTheDocument();
  });

  it('shows a first-run empty state and submits a manual end-of-day task', async () => {
    const notFound = { response: { status: 404 } };
    getLatest.mockRejectedValue(notFound);
    renderPage();

    expect(await screen.findByText('No successful snapshot to show yet')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Run EOD model' })[0]);

    await waitFor(() => expect(submitRun).toHaveBeenCalledTimes(1));
  });

  it('marks an older successful snapshot as stale', async () => {
    getLatest.mockResolvedValue({ ...snapshot, isStale: true });
    renderPage();

    expect(await screen.findByText('Snapshot is not current')).toBeInTheDocument();
  });
});
