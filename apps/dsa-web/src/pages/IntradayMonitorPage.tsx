import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Pause, Play, Plus, RefreshCw, Save, Settings2, ShieldAlert, X, Zap } from 'lucide-react';
import { intradayMonitorApi } from '../api/intradayMonitor';
import { getParsedApiError } from '../api/error';
import { AppPage, Button, Card, InlineAlert, Loading, PageHeader, StatCard } from '../components/common';
import type {
  IntradayMonitorHistoryItem,
  IntradayMonitorInstrument,
  IntradayMonitorPlan,
  IntradayMonitorPlanPayload,
  IntradayRepresentativeGroup,
  IntradayMonitorStatus,
  IntradaySimulationResult,
} from '../types/intradayMonitor';

const DEFAULT_SYMBOLS = [
  '002371', '603690', '603929', '603163', '603283', '688596',
  '688409', '300260', '603688', '002409', '603650', '600206',
  '688019', '300054', '300666', '688126', '688268', '688106', '605358',
];

const DEFAULT_REPRESENTATIVE_GROUPS: IntradayRepresentativeGroup[] = [
  { key: 'equipment', label: '设备', core_symbols: ['002371', '603690'], backup_symbols: ['603283', '603929', '603163'] },
  { key: 'components', label: '关键零部件', core_symbols: ['688409', '300260'], backup_symbols: ['688596'] },
  { key: 'materials', label: '材料', core_symbols: ['603688', '002409', '600206'], backup_symbols: ['603650', '688019', '300054', '300666', '688126', '688268', '688106', '605358'] },
];

const DEFAULT_FORM: IntradayMonitorPlanPayload = {
  name: '长鑫上市首日综合监控',
  event_symbol: '688825',
  sector_symbol: '159516',
  monitored_symbols: DEFAULT_SYMBOLS,
  representative_groups: DEFAULT_REPRESENTATIVE_GROUPS,
  majority_ratio: 0.6,
  initial_time: '10:00',
  confirm_time: '10:30',
  poll_interval_seconds: 30,
  listing_day_mode: true,
  start_date: '2026-07-27',
  end_date: '2026-07-27',
  enabled: true,
  paused: false,
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  observe: { label: '观察中', className: 'border-border/70 bg-card/70 text-secondary-text' },
  preliminary: { label: '初步信号', className: 'border-warning/40 bg-warning/10 text-warning' },
  confirmed: { label: '确认信号', className: 'border-success/40 bg-success/10 text-success' },
  continue_observing: { label: '继续观察', className: 'border-warning/40 bg-warning/10 text-warning' },
  invalidated: { label: '信号失效', className: 'border-danger/40 bg-danger/10 text-danger' },
  data_insufficient: { label: '数据不足', className: 'border-danger/40 bg-danger/10 text-danger' },
  inactive: { label: '不在有效期', className: 'border-border/70 bg-card/70 text-secondary-text' },
};

function statusMeta(status?: IntradayMonitorStatus) {
  return STATUS_META[status ?? 'observe'] ?? { label: status ?? '未知', className: 'border-border/70 bg-card/70 text-secondary-text' };
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function formatAmount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '--';
  if (value >= 100000000) return `${(value / 100000000).toFixed(2)} 亿`;
  if (value >= 10000) return `${(value / 10000).toFixed(2)} 万`;
  return value.toLocaleString('zh-CN');
}

function formatTime(value?: string | null): string {
  if (!value) return '--';
  return value.replace('T', ' ').slice(0, 19);
}

function formatShanghaiTime(value?: string | null): string | null {
  if (!value) return null;
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return null;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(timestamp);
}

function elapsedSince(value?: string | null): string | null {
  if (!value) return null;
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp.getTime()) / 1000));
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒前`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分前`;
}

function quoteFreshness(item?: IntradayMonitorInstrument): { label: string; className: string } {
  if (!item || item.fields_missing?.length) {
    return { label: '数据缺失', className: 'text-danger' };
  }
  if (item.is_fresh === false || item.freshness === 'stale') {
    const age = item?.quote_age_seconds == null ? '' : ` · ${item.quote_age_seconds} 秒`;
    return { label: `行情陈旧${age}`, className: 'text-danger' };
  }
  if (item.freshness === 'unknown') {
    const localTime = formatShanghaiTime(item.fetched_at);
    const elapsed = elapsedSince(item.fetched_at);
    if (localTime && elapsed) {
      return { label: `本地拉取 ${localTime} · ${elapsed}`, className: 'text-warning' };
    }
    return { label: '本地拉取时间未知', className: 'text-warning' };
  }
  const age = item?.quote_age_seconds == null ? '' : ` · ${item.quote_age_seconds} 秒`;
  return { label: `新鲜${age}`, className: 'text-success' };
}

function instrumentTone(item?: IntradayMonitorInstrument): 'success' | 'warning' | 'danger' | 'default' {
  if (!item || item.fields_missing?.length || item.is_fresh === false) return 'danger';
  if (item.valid) return 'success';
  if (item.above_open) return 'warning';
  return 'danger';
}

const InstrumentCard: React.FC<{ title: string; item?: IntradayMonitorInstrument }> = ({ title, item }) => (
  <StatCard
    label={title}
    value={item?.price == null ? '--' : formatNumber(item.price)}
    hint={(
      <span className="flex flex-wrap gap-x-3 gap-y-1">
        <span>开盘 {formatNumber(item?.open_price)}</span>
        <span className={item?.change_pct != null && item.change_pct >= 0 ? 'text-success' : 'text-danger'}>
          {item?.change_pct == null ? '--' : `${item.change_pct >= 0 ? '+' : ''}${formatNumber(item.change_pct)}%`}
        </span>
        <span>成交额 {formatAmount(item?.amount)}</span>
        <span className={quoteFreshness(item).className}>{quoteFreshness(item).label}</span>
      </span>
    )}
    tone={instrumentTone(item)}
    icon={<Activity className="h-5 w-5" />}
  />
);

const IntradayMonitorPage: React.FC = () => {
  const [plans, setPlans] = useState<IntradayMonitorPlan[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [history, setHistory] = useState<IntradayMonitorHistoryItem[]>([]);
  const [form, setForm] = useState<IntradayMonitorPlanPayload>(DEFAULT_FORM);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [formDirty, setFormDirty] = useState(false);
  const [simulation, setSimulation] = useState<IntradaySimulationResult | null>(null);
  const [simulationBusy, setSimulationBusy] = useState(false);

  const selectedPlan = useMemo(
    () => plans.find((plan) => plan.id === selectedId) ?? plans[0],
    [plans, selectedId],
  );
  const snapshot = selectedPlan?.snapshot;
  const status = statusMeta(snapshot?.status ?? selectedPlan?.current_status);
  const breadth = snapshot?.breadth;
  const representativeCoverage = snapshot?.representative_coverage;
  const warmingUpCount = snapshot?.markers?.filter((item) => item.pattern === 'warming_up').length ?? 0;
  const representativeGroups: Array<IntradayRepresentativeGroup & { valid?: boolean; reason?: string }> = representativeCoverage?.groups
    ?? selectedPlan?.representative_groups
    ?? [];
  const MonitorActionIcon = selectedPlan?.paused ? Play : Pause;

  const loadPlans = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const response = await intradayMonitorApi.listPlans();
      setPlans(response.items);
      if (response.items.length > 0) {
        setSelectedId((current) => current && response.items.some((item) => item.id === current) ? current : response.items[0].id);
      }
      setError(null);
    } catch (requestError) {
      setError(getParsedApiError(requestError).message);
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPlans(true);
    const interval = Math.max(10, selectedPlan?.poll_interval_seconds ?? 30) * 1000;
    const timer = window.setInterval(() => void loadPlans(), interval);
    return () => window.clearInterval(timer);
  }, [loadPlans, selectedPlan?.poll_interval_seconds]);

  useEffect(() => {
    if (!selectedPlan || formDirty) return;
    setForm({
      name: selectedPlan.name,
      event_symbol: selectedPlan.event_symbol,
      sector_symbol: selectedPlan.sector_symbol,
      monitored_symbols: selectedPlan.monitored_symbols,
      representative_groups: selectedPlan.representative_groups,
      majority_ratio: selectedPlan.majority_ratio,
      initial_time: selectedPlan.initial_time,
      confirm_time: selectedPlan.confirm_time,
      poll_interval_seconds: selectedPlan.poll_interval_seconds,
      listing_day_mode: selectedPlan.listing_day_mode,
      start_date: selectedPlan.start_date ?? null,
      end_date: selectedPlan.end_date ?? null,
      enabled: selectedPlan.enabled,
      paused: selectedPlan.paused,
    });
    void intradayMonitorApi.listHistory(selectedPlan.id).then((response) => setHistory(response.items)).catch(() => setHistory([]));
  }, [formDirty, selectedPlan]);

  const refreshNow = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const response = await intradayMonitorApi.evaluateNow();
      setPlans(response.items);
      setMessage('已请求后台立即刷新，页面将在下一轮同步最新状态。');
      setError(null);
    } catch (requestError) {
      setError(getParsedApiError(requestError).message);
    } finally {
      setBusy(false);
    }
  };

  const runSimulation = async () => {
    if (!selectedPlan) return;
    setSimulationBusy(true);
    setMessage(null);
    try {
      const result = await intradayMonitorApi.simulatePlan(selectedPlan.id);
      setSimulation(result);
      setMessage(result.passed ? '模拟测试通过：确认、失效和恢复链路均符合预期。' : '模拟测试未完全通过，请查看状态序列。');
      setError(null);
    } catch (requestError) {
      setError(getParsedApiError(requestError).message);
    } finally {
      setSimulationBusy(false);
    }
  };

  const savePlan = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const payload = {
        ...form,
        monitored_symbols: form.monitored_symbols,
      };
      const saved = selectedPlan
        ? await intradayMonitorApi.updatePlan(selectedPlan.id, payload)
        : await intradayMonitorApi.createPlan(payload);
      setPlans((current) => selectedPlan ? current.map((item) => item.id === saved.id ? saved : item) : [saved, ...current]);
      setSelectedId(saved.id);
      setFormDirty(false);
      setMessage('监控方案已保存。');
      setError(null);
    } catch (requestError) {
      setError(getParsedApiError(requestError).message);
    } finally {
      setBusy(false);
    }
  };

  const togglePlan = async (action: 'enabled' | 'paused') => {
    if (!selectedPlan) return;
    setBusy(true);
    try {
      const updated = action === 'enabled'
        ? await intradayMonitorApi.setEnabled(selectedPlan.id, !selectedPlan.enabled)
        : await intradayMonitorApi.setPaused(selectedPlan.id, !selectedPlan.paused);
      setPlans((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage(action === 'enabled' ? (updated.enabled ? '方案已启用。' : '方案已停用。') : (updated.paused ? '后台监控已暂停。' : '后台监控已恢复。'));
    } catch (requestError) {
      setError(getParsedApiError(requestError).message);
    } finally {
      setBusy(false);
    }
  };

  const updateForm = <K extends keyof IntradayMonitorPlanPayload>(key: K, value: IntradayMonitorPlanPayload[K]) => {
    setFormDirty(true);
    setForm((current) => ({ ...current, [key]: value }));
  };

  const updateRepresentativeGroup = (
    index: number,
    field: 'label' | 'core_symbols' | 'backup_symbols',
    value: string | string[],
  ) => {
    setFormDirty(true);
    setForm((current) => ({
      ...current,
      representative_groups: current.representative_groups.map((group, groupIndex) => (
        groupIndex === index ? { ...group, [field]: value } : group
      )),
    }));
  };

  const addRepresentativeGroup = () => {
    setFormDirty(true);
    setForm((current) => ({
      ...current,
      representative_groups: [
        ...current.representative_groups,
        {
          key: `group_${Date.now()}`,
          label: '新方向',
          core_symbols: [],
          backup_symbols: [],
        },
      ],
    }));
  };

  const removeRepresentativeGroup = (index: number) => {
    setFormDirty(true);
    setForm((current) => ({
      ...current,
      representative_groups: current.representative_groups.filter((_, groupIndex) => groupIndex !== index),
    }));
  };

  if (loading) {
    return <AppPage><Loading /></AppPage>;
  }

  return (
    <AppPage>
      <PageHeader
        eyebrow="INTRADAY COMPOSITE MONITOR"
        title="盘中综合信号"
        description="后台按方案频率采集直连实时行情；确认信号还要求设备、关键零部件、材料至少两个方向有核心代表走强。"
        actions={(
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => void loadPlans(true)}><RefreshCw className="h-4 w-4" />刷新</Button>
            <Button variant="secondary" size="sm" isLoading={simulationBusy} disabled={!selectedPlan} onClick={() => void runSimulation()}><Activity className="h-4 w-4" />模拟测试</Button>
            <Button variant="primary" size="sm" isLoading={busy} onClick={() => void refreshNow()}><Zap className="h-4 w-4" />立即评估</Button>
          </div>
        )}
      />

      {error ? <InlineAlert variant="danger" className="mt-4" message={error} /> : null}
      {message ? <InlineAlert variant="success" className="mt-4" message={message} /> : null}

      {simulation ? (
        <Card className="mt-5 border-cyan/20" title="模拟测试结果" subtitle="不调用真实行情，也不写入真实方案状态" padding="lg">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="text-sm text-secondary-text">{simulation.message} 最后时间：{formatTime(simulation.as_of)}</div>
            <span className={`rounded-full border px-3 py-1 text-xs font-medium ${simulation.passed ? 'border-success/40 bg-success/10 text-success' : 'border-danger/40 bg-danger/10 text-danger'}`}>
              {simulation.passed ? '模拟通过' : '需要检查'}
            </span>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {simulation.transitions.map((step, index) => {
              const itemStatus = statusMeta(step.status);
              return (
                <div key={`${step.as_of}-${index}`} className="flex items-center gap-2">
                  {index > 0 ? <span className="text-muted-text">→</span> : null}
                  <span className={`rounded-full border px-2.5 py-1 text-xs ${itemStatus.className}`}>{itemStatus.label}</span>
                  <span className="text-xs text-secondary-text">{formatTime(step.as_of)}</span>
                </div>
              );
            })}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {simulation.steps.filter((step) => ['preliminary', 'confirmed', 'invalidated'].includes(step.status)).map((step) => (
                <div key={`${step.as_of}-${step.status}`} className="rounded-xl border border-border/60 bg-card/40 px-3 py-3">
                  <div className="flex items-center justify-between gap-2"><span className="text-xs text-secondary-text">{formatTime(step.as_of)}</span><span className={`text-xs ${statusMeta(step.status).className.split(' ').pop()}`}>{statusMeta(step.status).label}</span></div>
                  <div className="mt-2 text-xs text-secondary-text">{step.reason}</div>
                  {step.representative_coverage?.enabled ? <div className="mt-2 text-xs text-secondary-text">核心代表覆盖：{step.representative_coverage.strong ?? 0}/{step.representative_coverage.groups?.length ?? 0} 个方向</div> : null}
                </div>
            ))}
          </div>
        </Card>
      ) : null}

      <div className="mt-5 grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card title="监控方案" subtitle="可复用配置" padding="sm">
          <div className="space-y-2">
            {plans.map((plan) => {
              const planStatus = statusMeta(plan.current_status);
              return (
                <button
                  type="button"
                  key={plan.id}
                  onClick={() => { setFormDirty(false); setSelectedId(plan.id); }}
                  className={`w-full rounded-xl border px-3 py-3 text-left transition-colors ${plan.id === selectedPlan?.id ? 'border-cyan/40 bg-cyan/10' : 'border-border/60 bg-card/40 hover:bg-hover'}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="truncate text-sm font-medium text-foreground">{plan.name}</span>
                    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${planStatus.className}`}>{planStatus.label}</span>
                  </div>
                  <div className="mt-1 text-xs text-secondary-text">{plan.event_symbol} / {plan.sector_symbol}</div>
                </button>
              );
            })}
            {!plans.length ? <div className="rounded-xl border border-dashed border-border/70 p-4 text-sm text-secondary-text">还没有方案，右侧可以直接创建。</div> : null}
          </div>
        </Card>

        <div className="space-y-5">
          <Card className="border-cyan/20" padding="lg">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-xl font-semibold text-foreground">{selectedPlan?.name ?? '新建监控方案'}</h2>
                  <span className={`rounded-full border px-3 py-1 text-xs font-medium ${status.className}`}>{status.label}</span>
                </div>
                <p className="mt-2 text-sm text-secondary-text">{snapshot?.reason ?? '配置三层条件后，后台会在交易时段持续观察。'}</p>
                <p className="mt-2 text-xs text-muted-text">最后评估：{formatTime(selectedPlan?.last_evaluated_at)} · 数据源：{snapshot?.data_sources?.join(', ') || '--'}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {selectedPlan ? <Button variant="secondary" size="sm" onClick={() => void togglePlan('paused')}><MonitorActionIcon className="h-4 w-4" />{selectedPlan.paused ? '恢复后台监控' : '暂停后台监控'}</Button> : null}
                {selectedPlan ? <Button variant="outline" size="sm" onClick={() => void togglePlan('enabled')}>{selectedPlan.enabled ? '停用方案' : '启用方案'}</Button> : null}
              </div>
            </div>
          </Card>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <InstrumentCard title={`长鑫科技 ${selectedPlan?.event_symbol ?? ''}`} item={snapshot?.event} />
            <InstrumentCard title={`半导体 ETF ${selectedPlan?.sector_symbol ?? ''}`} item={snapshot?.sector} />
            <StatCard
              label="监控池强势数量"
              value={breadth ? `${breadth.strong ?? 0}/${breadth.total ?? 0}` : '--'}
              hint={breadth
                ? warmingUpCount > 0
                  ? `${warmingUpCount}/${breadth.total ?? 0} 只等待三分钟量价样本 · 强势要求至少 ${breadth.required ?? selectedPlan?.required_count ?? '--'} 只`
                  : `要求至少 ${breadth.required ?? selectedPlan?.required_count ?? '--'} 只 · ${((breadth.ratio ?? 0) * 100).toFixed(0)}%`
                : '等待行情数据'}
              tone={breadth?.valid ? 'success' : 'warning'}
              icon={<ShieldAlert className="h-5 w-5" />}
            />
            <StatCard
              label="核心代表覆盖"
              value={representativeCoverage?.enabled ? `${representativeCoverage.strong ?? 0}/${representativeCoverage.groups?.length ?? 0}` : '未配置'}
              hint={representativeCoverage?.enabled
                ? warmingUpCount > 0
                  ? `代表股量价样本预热中 · 至少 ${representativeCoverage.required ?? 0} 个产业方向核心走强`
                  : `至少 ${representativeCoverage.required ?? 0} 个产业方向核心走强`
                : '通用方案不限制产业链方向'}
              tone={representativeCoverage?.enabled ? (representativeCoverage.valid ? 'success' : 'warning') : 'default'}
              icon={<ShieldAlert className="h-5 w-5" />}
            />
          </div>

          <Card title="三层触发值" subtitle="不设固定涨幅阈值，观察开盘价与 3 分钟量价结构" padding="lg">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                ['长鑫高于开盘', snapshot?.trigger_values?.event_above_open],
                ['ETF 高于开盘', snapshot?.trigger_values?.sector_above_open],
                ['强势数量', snapshot?.trigger_values?.strong_count],
                ['最低数量', snapshot?.trigger_values?.required_count],
                ['核心代表方向', representativeCoverage?.enabled ? `${String(snapshot?.trigger_values?.representative_strong ?? 0)}/${String(snapshot?.trigger_values?.representative_required ?? 0)}` : '未配置'],
                ['预热连续次数', snapshot?.trigger_values?.streak],
                ['确认窗口进度', `${String(snapshot?.trigger_values?.confirm_streak ?? 0)}/${String(snapshot?.trigger_values?.confirm_required ?? 2)}`],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-xl border border-border/60 bg-card/40 px-3 py-3">
                  <div className="text-xs text-secondary-text">{String(label)}</div>
                  <div className="mt-2 text-lg font-semibold text-foreground">{typeof value === 'boolean' ? (value ? '是' : '否') : String(value ?? '--')}</div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="产业链代表性" subtitle="核心名单预先配置，不会因盘中领涨临时替换；备用仅在核心行情不可用时显示" padding="lg">
            {representativeGroups.length ? (
              <div className="grid gap-3 md:grid-cols-3">
                {representativeGroups.map((group) => (
                  <div key={group.key} className="rounded-xl border border-border/60 bg-card/40 px-3 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-foreground">{group.label}</span>
                      <span className={group.valid === true ? 'text-xs text-success' : group.valid === false ? 'text-xs text-warning' : 'text-xs text-secondary-text'}>
                        {group.valid === true ? '已覆盖' : group.valid === false ? '未覆盖' : '等待行情'}
                      </span>
                    </div>
                    <div className="mt-2 text-xs text-secondary-text">核心：{group.core_symbols.join('、') || '--'}</div>
                    {group.backup_symbols.length ? <div className="mt-1 text-xs text-muted-text">备用：{group.backup_symbols.join('、')}</div> : null}
                    <div className="mt-2 text-xs text-secondary-text">{group.reason ?? '等待实时结构判断'}</div>
                  </div>
                ))}
              </div>
            ) : <div className="text-sm text-secondary-text">未配置产业链代表组；通用方案仍可按三层条件运行。</div>}
          </Card>

          <Card title="监控池实时明细" subtitle="名称会随行情源自动解析，数据缺失时不缩小分母" padding="none">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="border-b border-border/60 text-left text-xs text-secondary-text">
                  <tr><th className="px-4 py-3">代码 / 名称</th><th className="px-4 py-3">产业链角色</th><th className="px-4 py-3">现价</th><th className="px-4 py-3">开盘</th><th className="px-4 py-3">涨跌</th><th className="px-4 py-3">成交额</th><th className="px-4 py-3">3 分钟结构</th><th className="px-4 py-3">行情时效</th><th className="px-4 py-3">状态</th></tr>
                </thead>
                <tbody>
                  {(snapshot?.markers ?? []).map((item) => (
                    <tr key={item.code} className="border-b border-border/40 last:border-0">
                      <td className="px-4 py-3"><div className="font-medium text-foreground">{item.name || item.code}</div><div className="text-xs text-secondary-text">{item.code}</div></td>
                      <td className="px-4 py-3 text-xs text-secondary-text">{item.representative_roles?.join('、') || '--'}</td>
                      <td className="px-4 py-3 text-foreground">{formatNumber(item.price)}</td>
                      <td className="px-4 py-3 text-secondary-text">{formatNumber(item.open_price)}</td>
                      <td className={`px-4 py-3 ${item.change_pct != null && item.change_pct >= 0 ? 'text-success' : 'text-danger'}`}>{item.change_pct == null ? '--' : `${item.change_pct >= 0 ? '+' : ''}${formatNumber(item.change_pct)}%`}</td>
                      <td className="px-4 py-3 text-secondary-text">{formatAmount(item.amount)}</td>
                      <td className="px-4 py-3 text-secondary-text">{item.pattern || (item.fields_missing?.join(', ') ?? '--')}</td>
                      <td className={`px-4 py-3 ${quoteFreshness(item).className}`}>{quoteFreshness(item).label}</td>
                      <td className="px-4 py-3"><span className={item.valid ? 'text-success' : item.data_issues?.length ? 'text-danger' : 'text-warning'}>{item.valid ? '强势' : item.is_fresh === false ? '行情陈旧' : item.fields_missing?.length ? '数据缺失' : '未满足'}</span></td>
                    </tr>
                  ))}
                  {!snapshot?.markers?.length ? <tr><td colSpan={9} className="px-4 py-8 text-center text-secondary-text">尚未有实时快照</td></tr> : null}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="方案设置" subtitle="有效期可在网页直接调整" padding="lg">
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              <label className="text-sm text-secondary-text">方案名称<input className="mt-1 input-surface w-full" value={form.name} onChange={(event) => updateForm('name', event.target.value)} /></label>
              <label className="text-sm text-secondary-text">事件标的<input className="mt-1 input-surface w-full" value={form.event_symbol} onChange={(event) => updateForm('event_symbol', event.target.value)} /></label>
              <label className="text-sm text-secondary-text">板块 ETF / 指数<input className="mt-1 input-surface w-full" value={form.sector_symbol} onChange={(event) => updateForm('sector_symbol', event.target.value)} /></label>
              <label className="text-sm text-secondary-text">强势占比<input className="mt-1 input-surface w-full" type="number" min="0.01" max="1" step="0.01" value={form.majority_ratio} onChange={(event) => updateForm('majority_ratio', Number(event.target.value))} /></label>
              <label className="text-sm text-secondary-text">初步观察时间<input className="mt-1 input-surface w-full" type="time" value={form.initial_time} onChange={(event) => updateForm('initial_time', event.target.value)} /></label>
              <label className="text-sm text-secondary-text">确认时间<input className="mt-1 input-surface w-full" type="time" value={form.confirm_time} onChange={(event) => updateForm('confirm_time', event.target.value)} /></label>
              <label className="text-sm text-secondary-text">有效开始<input className="mt-1 input-surface w-full" type="date" value={form.start_date ?? ''} onChange={(event) => updateForm('start_date', event.target.value || null)} /></label>
              <label className="text-sm text-secondary-text">有效结束<input className="mt-1 input-surface w-full" type="date" value={form.end_date ?? ''} onChange={(event) => updateForm('end_date', event.target.value || null)} /></label>
            </div>
            <label className="mt-4 block text-sm text-secondary-text">监控池代码（逗号分隔）<textarea className="input-surface mt-1 min-h-24 w-full" value={form.monitored_symbols.join(',')} onChange={(event) => updateForm('monitored_symbols', event.target.value.split(',').map((item) => item.trim()).filter(Boolean))} /></label>
            <div className="mt-5 rounded-xl border border-border/60 bg-card/40 p-4">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="text-sm font-medium text-foreground">产业链代表组</div>
                  <div className="mt-1 text-xs text-secondary-text">确认时至少两个方向的核心代表走强。所有代码必须同时在监控池内；备用不会因盘中领涨而替代走弱的核心。</div>
                </div>
                <Button variant="outline" size="sm" onClick={addRepresentativeGroup}><Plus className="h-4 w-4" />添加方向</Button>
              </div>
              <div className="mt-4 space-y-3">
                {form.representative_groups.map((group, index) => (
                  <div key={group.key} className="grid gap-3 rounded-lg border border-border/50 p-3 lg:grid-cols-[minmax(120px,0.7fr)_minmax(180px,1fr)_minmax(180px,1fr)_auto]">
                    <label className="text-xs text-secondary-text">方向<input className="input-surface mt-1 w-full" value={group.label} onChange={(event) => updateRepresentativeGroup(index, 'label', event.target.value)} /></label>
                    <label className="text-xs text-secondary-text">核心代码（逗号分隔）<input className="input-surface mt-1 w-full" value={group.core_symbols.join(',')} onChange={(event) => updateRepresentativeGroup(index, 'core_symbols', event.target.value.split(',').map((item) => item.trim()).filter(Boolean))} /></label>
                    <label className="text-xs text-secondary-text">备用代码（逗号分隔）<input className="input-surface mt-1 w-full" value={group.backup_symbols.join(',')} onChange={(event) => updateRepresentativeGroup(index, 'backup_symbols', event.target.value.split(',').map((item) => item.trim()).filter(Boolean))} /></label>
                    <div className="flex items-end"><Button variant="ghost" size="sm" aria-label={`删除${group.label}`} onClick={() => removeRepresentativeGroup(index)}><X className="h-4 w-4" />删除</Button></div>
                  </div>
                ))}
                {!form.representative_groups.length ? <div className="text-xs text-secondary-text">未配置时会退化为原有三层条件，不启用产业链覆盖确认。</div> : null}
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs text-secondary-text"><Settings2 className="h-4 w-4" />每 {form.poll_interval_seconds} 秒刷新；上市首日模式：{form.listing_day_mode ? '开启' : '关闭'}</div>
              <Button variant="primary" size="sm" isLoading={busy} onClick={() => void savePlan()}><Save className="h-4 w-4" />保存方案</Button>
            </div>
          </Card>

          <Card title="信号历史" subtitle="保留最近 30 天的状态变化" padding="lg">
            <div className="space-y-3">
              {history.map((item) => {
                const itemStatus = statusMeta(item.status);
                return <div key={item.id} className="flex flex-col gap-1 rounded-xl border border-border/60 bg-card/40 px-3 py-3 sm:flex-row sm:items-start sm:justify-between"><div><span className={`mr-2 inline-flex rounded-full border px-2 py-0.5 text-xs ${itemStatus.className}`}>{itemStatus.label}</span><span className="text-sm text-foreground">{item.reason || '--'}</span></div><span className="text-xs text-secondary-text">{formatTime(item.created_at)}</span></div>;
              })}
              {!history.length ? <div className="text-sm text-secondary-text">暂无状态变化。后台只在状态发生变化时写入，避免 30 秒一条重复记录。</div> : null}
            </div>
          </Card>
        </div>
      </div>
    </AppPage>
  );
};

export default IntradayMonitorPage;
