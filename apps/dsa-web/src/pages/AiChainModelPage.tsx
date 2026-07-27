import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BrainCircuit, Database, FlaskConical, Play, RefreshCw } from 'lucide-react';
import { aiChainModelApi } from '../api/aiChainModel';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import {
  ApiErrorAlert,
  AppPage,
  Badge,
  Card,
  EmptyState,
  InlineAlert,
  PageHeader,
  StatCard,
} from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiTextKey } from '../i18n/uiText';
import type {
  AIChainAction,
  AIChainBacktestResult,
  AIChainGroup,
  AIChainModelScore,
  AIChainModelSnapshot,
  AIChainModelTask,
} from '../types/aiChainModel';

const POLL_INTERVAL_MS = 2_000;

const GROUP_KEYS: Record<AIChainGroup, UiTextKey> = {
  hardware: 'aiChain.group.hardware',
  edge: 'aiChain.group.edge',
  application: 'aiChain.group.application',
};

const ACTION_KEYS: Record<AIChainAction, UiTextKey> = {
  buy: 'aiChain.action.buy',
  hold: 'aiChain.action.hold',
  reduce: 'aiChain.action.reduce',
  avoid: 'aiChain.action.avoid',
  data_insufficient: 'aiChain.action.dataInsufficient',
};

function asPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(digits)}%`;
}

function asNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return value.toFixed(1);
}

function isNotFound(error: unknown): boolean {
  return typeof error === 'object' && error !== null
    && 'response' in error
    && (error as { response?: { status?: number } }).response?.status === 404;
}

function actionVariant(action: AIChainAction): 'success' | 'warning' | 'danger' | 'default' {
  if (action === 'buy') return 'success';
  if (action === 'hold') return 'warning';
  if (action === 'reduce') return 'danger';
  return 'default';
}

function gateVariant(gate: AIChainModelSnapshot['marketGate']): 'success' | 'warning' | 'danger' | 'default' {
  if (gate === 'normal') return 'success';
  if (gate === 'caution') return 'warning';
  if (gate === 'risk_off') return 'danger';
  return 'default';
}

const AiChainModelPage: React.FC = () => {
  const { t } = useUiLanguage();
  const [snapshot, setSnapshot] = useState<AIChainModelSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [task, setTask] = useState<AIChainModelTask | null>(null);
  const [backtest, setBacktest] = useState<AIChainBacktestResult | null>(null);
  const requestIdRef = useRef(0);

  const loadLatest = useCallback(async () => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    try {
      const next = await aiChainModelApi.getLatest();
      if (requestIdRef.current !== requestId) return;
      setSnapshot(next);
      setError(null);
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      if (isNotFound(err)) {
        setSnapshot(null);
        setError(null);
      } else {
        setError(getParsedApiError(err));
      }
    } finally {
      if (requestIdRef.current === requestId) setLoading(false);
    }
  }, []);

  useEffect(() => {
    document.title = t('aiChain.pageTitleDocument');
  }, [t]);

  useEffect(() => {
    void loadLatest();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadLatest]);

  useEffect(() => {
    if (!task || !['pending', 'processing'].includes(task.status)) return undefined;
    const timer = window.setInterval(() => {
      void aiChainModelApi.getTask(task.taskId)
        .then(async (nextTask) => {
          setTask(nextTask);
          if (nextTask.status !== 'completed') return;
          if (nextTask.kind === 'daily_run') {
            await loadLatest();
            return;
          }
          const backtestRunId = Number(nextTask.result?.backtest_run_id);
          if (Number.isInteger(backtestRunId) && backtestRunId > 0) {
            setBacktest(await aiChainModelApi.getBacktest(backtestRunId));
          }
        })
        .catch((err) => setError(getParsedApiError(err)));
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadLatest, task]);

  const startTask = useCallback(async (kind: 'daily_run' | 'backtest') => {
    try {
      setError(null);
      setTask(kind === 'daily_run'
        ? await aiChainModelApi.submitRun()
        : await aiChainModelApi.submitBacktest());
    } catch (err) {
      setError(getParsedApiError(err));
    }
  }, []);

  const groupedScores = useMemo(() => {
    const groups: Record<AIChainGroup, AIChainModelScore[]> = {
      hardware: [], edge: [], application: [],
    };
    for (const item of snapshot?.scores ?? []) groups[item.group].push(item);
    return groups;
  }, [snapshot]);

  const selectedCount = (snapshot?.scores ?? []).filter((item) => item.suggestedWeight > 0).length;
  const selectedWeight = (snapshot?.scores ?? []).reduce((total, item) => total + item.suggestedWeight, 0);
  const running = task?.status === 'pending' || task?.status === 'processing';

  return (
    <AppPage className="space-y-4">
      <PageHeader
        eyebrow={t('aiChain.eyebrow')}
        title={t('aiChain.pageTitle')}
        description={t('aiChain.description')}
        actions={(
          <>
            <button type="button" className="btn-secondary" onClick={() => void loadLatest()} disabled={loading || running}>
              <RefreshCw className="h-4 w-4" />{t('aiChain.refresh')}
            </button>
            <button type="button" className="btn-secondary" onClick={() => void startTask('backtest')} disabled={running}>
              <FlaskConical className="h-4 w-4" />{running && task?.kind === 'backtest' ? t('aiChain.running') : t('aiChain.backtest')}
            </button>
            <button type="button" className="btn-primary" onClick={() => void startTask('daily_run')} disabled={running}>
              <Play className="h-4 w-4" />{running && task?.kind === 'daily_run' ? t('aiChain.running') : t('aiChain.run')}
            </button>
          </>
        )}
      />

      <InlineAlert
        variant="info"
        title={t('aiChain.decisionSupportTitle')}
        message={t('aiChain.decisionSupportDescription')}
      />

      {error ? <ApiErrorAlert error={error} onAction={() => void loadLatest()} actionLabel={t('common.retry')} /> : null}

      {task ? (
        <Card padding="sm" className={task.status === 'failed' ? 'border-danger/30' : ''}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-foreground">{t('aiChain.taskStatus')}</p>
              <p className="mt-1 text-xs text-secondary-text">{task.message}{task.error ? ` · ${task.error}` : ''}</p>
            </div>
            <Badge variant={task.status === 'failed' ? 'danger' : task.status === 'completed' ? 'success' : 'info'}>
              {task.progress}%
            </Badge>
          </div>
        </Card>
      ) : null}

      {loading ? (
        <Card><div className="py-10 text-center text-sm text-secondary-text">{t('common.loading')}</div></Card>
      ) : snapshot ? (
        <>
          {snapshot.isStale ? (
            <InlineAlert variant="warning" title={t('aiChain.staleTitle')} message={t('aiChain.staleDescription')} />
          ) : null}

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label={t('aiChain.asOf')} value={snapshot.asOfDate} icon={<Database className="h-5 w-5" />} tone="primary" />
            <StatCard
              label={t('aiChain.marketGate')}
              value={<Badge variant={gateVariant(snapshot.marketGate)} size="md">{t(`aiChain.marketGate.${snapshot.marketGate ?? 'unknown'}` as UiTextKey)}</Badge>}
              hint={snapshot.modelVersion}
              tone={snapshot.marketGate === 'risk_off' ? 'danger' : snapshot.marketGate === 'caution' ? 'warning' : 'success'}
            />
            <StatCard label={t('aiChain.selectedNames')} value={selectedCount} hint={t('aiChain.selectedWeight', { value: asPercent(selectedWeight) })} />
            <StatCard label={t('aiChain.dataCoverage')} value={asPercent(snapshot.dataCoverage)} hint={t('aiChain.calibrationHint')} />
          </section>

          {snapshot.warnings.length > 0 ? (
            <InlineAlert variant="warning" title={t('aiChain.dataWarnings')} message={snapshot.warnings.join('；')} />
          ) : null}

          <Card title={t('aiChain.scoreboardTitle')} subtitle={t('aiChain.eyebrow')}>
            <p className="-mt-1 mb-4 text-sm text-secondary-text">{t('aiChain.scoreboardDescription')}</p>
            <div className="space-y-6">
              {(Object.keys(GROUP_KEYS) as AIChainGroup[]).map((group) => (
                <section key={group} aria-label={t(GROUP_KEYS[group])}>
                  <div className="mb-2 flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-foreground">{t(GROUP_KEYS[group])}</h2>
                    <Badge variant="default">{groupedScores[group].length}</Badge>
                  </div>
                  <div className="overflow-x-auto rounded-xl border border-border/60">
                    <table className="min-w-[760px] w-full text-left text-sm">
                      <thead className="bg-elevated/70 text-xs text-secondary-text">
                        <tr>
                          <th className="px-3 py-2 font-medium">{t('aiChain.rank')}</th>
                          <th className="px-3 py-2 font-medium">{t('aiChain.stock')}</th>
                          <th className="px-3 py-2 font-medium">{t('aiChain.score')}</th>
                          <th className="px-3 py-2 font-medium">{t('aiChain.action')}</th>
                          <th className="px-3 py-2 font-medium">{t('aiChain.suggestedWeight')}</th>
                          <th className="px-3 py-2 font-medium">{t('aiChain.dataQuality')}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/50">
                        {groupedScores[group].map((item) => (
                          <tr key={item.code} className="hover:bg-hover/50">
                            <td className="px-3 py-2 text-secondary-text">{item.rank}</td>
                            <td className="px-3 py-2"><div className="font-medium text-foreground">{item.name}</div><div className="text-xs text-secondary-text">{item.code} · {item.tier === 'core' ? t('aiChain.tier.core') : t('aiChain.tier.observation')}</div></td>
                            <td className="px-3 py-2 font-semibold text-foreground">{asNumber(item.score)}</td>
                            <td className="px-3 py-2"><Badge variant={actionVariant(item.action)}>{t(ACTION_KEYS[item.action])}</Badge></td>
                            <td className="px-3 py-2 text-foreground">{asPercent(item.suggestedWeight)}</td>
                            <td className="px-3 py-2 text-secondary-text">{String(item.qualitySnapshot.status ?? '--')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
            </div>
          </Card>

          <Card title={t('aiChain.methodTitle')}>
            <p className="text-sm leading-6 text-secondary-text">{t('aiChain.methodDescription')}</p>
          </Card>

          {backtest ? (
            <Card title={t('aiChain.backtestTitle')}>
              <div className="grid gap-3 sm:grid-cols-3">
                <StatCard label={t('aiChain.backtestStatus')} value={backtest.status} />
                <StatCard label={t('aiChain.backtestFinalValue')} value={asNumber(Number(backtest.metrics['finalPortfolioValue']))} />
                <StatCard label={t('aiChain.backtestPoints')} value={backtest.pointTotal} />
              </div>
              {backtest.failureReason ? <p className="mt-3 text-sm text-danger">{backtest.failureReason}</p> : null}
            </Card>
          ) : null}
        </>
      ) : (
        <EmptyState
          icon={<BrainCircuit className="h-9 w-9" />}
          title={t('aiChain.emptyTitle')}
          description={t('aiChain.emptyDescription')}
          action={<button type="button" className="btn-primary" onClick={() => void startTask('daily_run')} disabled={running}><Play className="h-4 w-4" />{t('aiChain.run')}</button>}
        />
      )}
    </AppPage>
  );
};

export default AiChainModelPage;
