import { useState, useMemo, useRef } from 'react';
import { useClaims, useRecommendation } from '@/api/claims/hooks';
import { ScoredClaim, RuleTrace, NextStep } from '@/api/claims/api-requests';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type SortField =
  | 'claim_id'
  | 'insured_id'
  | 'loss_date'
  | 'fraud_score'
  | 'anomaly_score'
  | 'routing_decision'
  | 'rule_fired'
  | 'gap_count';
type SortDir = 'asc' | 'desc';

const ROUTING_COLORS: Record<string, string> = {
  'Recommend Decline Review': 'bg-red-600 text-white border-red-700',
  Complex: 'bg-orange-500 text-white border-orange-600',
  'More Info Needed': 'bg-yellow-500 text-black border-yellow-600',
  Standard: 'bg-blue-600 text-white border-blue-700',
  'Fast Track': 'bg-emerald-600 text-white border-emerald-700',
};

const ROUTING_DOT: Record<string, string> = {
  'Recommend Decline Review': 'bg-red-500',
  Complex: 'bg-orange-400',
  'More Info Needed': 'bg-yellow-400',
  Standard: 'bg-blue-500',
  'Fast Track': 'bg-emerald-500',
};

function RoutingBadge({ decision }: { decision: string }) {
  const cls = ROUTING_COLORS[decision] ?? 'bg-gray-600 text-white border-gray-700';
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${cls} whitespace-nowrap`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${ROUTING_DOT[decision] ?? 'bg-gray-400'}`} />
      {decision}
    </span>
  );
}

function ScoreBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-300 w-12 text-right font-mono">{value.toFixed(1)}</span>
    </div>
  );
}

function SortIcon({ field, current, dir }: { field: SortField; current: SortField; dir: SortDir }) {
  if (field !== current) return <span className="text-gray-600 ml-1">⇅</span>;
  return <span className="text-blue-400 ml-1">{dir === 'asc' ? '↑' : '↓'}</span>;
}

const GOOD_RULES = new Set(['R5', 'R6']);

function RuleTracePanel({ trace }: { trace: RuleTrace[] }) {
  return (
    <div className="space-y-1.5">
      {trace.map(r => {
        const isGood = r.passed && GOOD_RULES.has(r.rule);
        const rowCls = r.passed
          ? isGood
            ? 'bg-emerald-950 border-emerald-800 text-emerald-200'
            : 'bg-red-950 border-red-800 text-red-200'
          : 'bg-gray-800 border-gray-700 text-gray-400';
        const ruleCls = r.passed ? (isGood ? 'text-emerald-400' : 'text-red-400') : 'text-gray-500';
        const labelCls = r.passed
          ? isGood
            ? 'text-emerald-300'
            : 'text-red-300'
          : 'text-gray-500';
        return (
          <div
            key={r.rule}
            className={`flex items-start gap-2 px-3 py-2 rounded text-xs border ${rowCls}`}
          >
            <span className={`font-bold font-mono w-6 shrink-0 ${ruleCls}`}>{r.rule}</span>
            <span className={`w-14 shrink-0 font-semibold ${labelCls}`}>
              {r.passed ? '▶ FIRED' : '○ skip'}
            </span>
            <span className="break-words whitespace-normal">{r.description}</span>
          </div>
        );
      })}
    </div>
  );
}

const EnvelopeIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 20 20"
    fill="currentColor"
    className="w-3.5 h-3.5 shrink-0"
    aria-hidden="true"
  >
    <path d="M3 4a2 2 0 0 0-2 2v.217l9 4.5 9-4.5V6a2 2 0 0 0-2-2H3Z" />
    <path d="m19 8.434-8.717 4.358a1 1 0 0 1-.566 0L1 8.434V14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8.434Z" />
  </svg>
);

function EmailComposer({
  initialSubject,
  initialBody,
  onDiscard,
}: {
  initialSubject: string;
  initialBody: string;
  onDiscard: () => void;
}) {
  const [to, setTo] = useState('');
  const [subject, setSubject] = useState(initialSubject);
  const [body, setBody] = useState(initialBody);
  const [sent, setSent] = useState(false);
  const toRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    // Mark as sent — a real integration would POST to a backend mailer here
    setSent(true);
  };

  if (sent) {
    return (
      <div className="mt-3 rounded-lg border border-emerald-700 bg-emerald-950/60 px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm text-emerald-300">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="w-4 h-4 shrink-0"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
              clipRule="evenodd"
            />
          </svg>
          Email marked as sent{to ? ` to ${to}` : ''}.
        </div>
        <button
          onClick={onDiscard}
          className="text-xs text-emerald-500 hover:text-emerald-300 transition-colors"
        >
          Dismiss
        </button>
      </div>
    );
  }

  return (
    <div
      className="mt-3 rounded-lg border border-blue-700 bg-gray-900 overflow-hidden"
      role="region"
      aria-label="Email composer"
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-blue-900 bg-blue-950/40">
        <div className="flex items-center gap-1.5 text-xs text-blue-300 font-semibold">
          <EnvelopeIcon />
          New Email
        </div>
        <button
          onClick={onDiscard}
          aria-label="Discard email"
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-1.5 py-0.5 rounded hover:bg-gray-800"
        >
          Discard ✕
        </button>
      </div>

      {/* Fields */}
      <div className="divide-y divide-gray-800">
        {/* To */}
        <div className="flex items-center gap-2 px-3 py-2">
          <label htmlFor="email-to" className="text-xs text-gray-500 w-14 shrink-0 font-medium">
            To
          </label>
          <input
            id="email-to"
            ref={toRef}
            type="email"
            value={to}
            onChange={e => setTo(e.target.value)}
            placeholder="recipient@example.com"
            className="flex-1 bg-transparent text-sm text-gray-100 placeholder:text-gray-600 outline-none min-w-0"
          />
        </div>

        {/* Subject */}
        <div className="flex items-center gap-2 px-3 py-2">
          <label
            htmlFor="email-subject"
            className="text-xs text-gray-500 w-14 shrink-0 font-medium"
          >
            Subject
          </label>
          <input
            id="email-subject"
            type="text"
            value={subject}
            onChange={e => setSubject(e.target.value)}
            className="flex-1 bg-transparent text-sm text-gray-100 outline-none min-w-0"
          />
        </div>

        {/* Body */}
        <div className="px-3 py-2">
          <label htmlFor="email-body" className="sr-only">
            Email body
          </label>
          <textarea
            id="email-body"
            value={body}
            onChange={e => setBody(e.target.value)}
            rows={7}
            className="w-full bg-transparent text-sm text-gray-200 leading-relaxed resize-y outline-none placeholder:text-gray-600"
            placeholder="Email body…"
          />
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-gray-800 bg-gray-950/40">
        <button
          onClick={handleSend}
          disabled={!to.trim()}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors"
          aria-disabled={!to.trim()}
        >
          <EnvelopeIcon />
          Send
        </button>
        <button
          onClick={onDiscard}
          className="px-3 py-1.5 rounded text-xs font-semibold text-gray-400 hover:text-gray-200 hover:bg-gray-800 transition-colors"
        >
          Discard
        </button>
      </div>
    </div>
  );
}

function NextStepItem({ step, index }: { step: NextStep; index: number }) {
  const canEmail = step.requires_outreach && step.email_template !== null;
  const [composing, setComposing] = useState(false);

  return (
    <li>
      <div className="flex items-start gap-3">
        <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-700 text-blue-100 text-xs font-bold shrink-0 mt-0.5">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <span className="text-sm text-blue-100 leading-snug break-words">{step.text}</span>
          {canEmail && !composing && (
            <div className="mt-1.5">
              <button
                onClick={() => setComposing(true)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-semibold bg-blue-800 hover:bg-blue-700 text-blue-100 border border-blue-600 hover:border-blue-500 transition-colors"
              >
                <EnvelopeIcon />
                Compose Email
              </button>
            </div>
          )}
          {canEmail && composing && step.email_template && (
            <EmailComposer
              initialSubject={step.email_template.subject}
              initialBody={step.email_template.body}
              onDiscard={() => setComposing(false)}
            />
          )}
        </div>
      </div>
    </li>
  );
}

function AuditTrail({ claim }: { claim: ScoredClaim }) {
  const {
    data: rec,
    isLoading: recLoading,
    isError: recError,
  } = useRecommendation(claim.claim_id, true);

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 space-y-5">
      {/* ── Agent Recommendation — hero block ── */}
      <div className="rounded-xl border-2 border-blue-600 bg-blue-950/60 p-5 shadow-lg shadow-blue-950/40">
        <div className="flex items-center gap-2 mb-3">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold shrink-0">
            AI
          </span>
          <span className="text-sm font-bold text-blue-200 uppercase tracking-wider">
            Agent Recommendation
          </span>
        </div>
        {recLoading && (
          <div className="text-sm text-blue-400 italic animate-pulse">
            Asking agent for recommendation…
          </div>
        )}
        {recError && (
          <div className="text-sm text-gray-400 italic">
            Agent unavailable — {claim.recommended_action}
          </div>
        )}
        {rec && (
          <div className="space-y-4">
            <p className="text-base text-blue-100 leading-relaxed break-words whitespace-normal">
              {rec.recommendation}
            </p>
            {rec.next_steps && rec.next_steps.length > 0 && (
              <div>
                <div className="text-xs text-blue-400 uppercase tracking-wider font-semibold mb-2">
                  Next Steps
                </div>
                <ol className="space-y-3">
                  {rec.next_steps.map((step, i) => (
                    <NextStepItem key={i} step={step} index={i} />
                  ))}
                </ol>
              </div>
            )}
          </div>
        )}
        {!recLoading && !recError && !rec && (
          <div className="text-sm text-blue-400 italic animate-pulse">
            Asking agent for recommendation…
          </div>
        )}
      </div>

      {/* ── Supporting detail ── */}
      <div className="space-y-5">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-px bg-gray-700" />
          <span className="text-xs text-gray-500 uppercase tracking-widest font-semibold px-2">
            Supporting Detail
          </span>
          <div className="flex-1 h-px bg-gray-700" />
        </div>

        {/* Score cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Fraud Score</div>
            <div className="text-2xl font-bold text-white">{claim.fraud_score.toFixed(1)}%</div>
            <div
              className={`text-xs mt-1 ${claim.fraud_score >= 70 ? 'text-red-400' : claim.fraud_score >= 50 ? 'text-orange-400' : 'text-emerald-400'}`}
            >
              {claim.fraud_score >= 70
                ? 'HIGH RISK'
                : claim.fraud_score >= 50
                  ? 'MODERATE'
                  : 'LOW RISK'}
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Anomaly Score</div>
            <div className="text-2xl font-bold text-white">{claim.anomaly_score.toFixed(3)}</div>
            <div
              className={`text-xs mt-1 ${claim.anomaly_score >= 0.5 ? 'text-red-400' : 'text-emerald-400'}`}
            >
              {claim.anomaly_score >= 0.5 ? 'FLAGGED' : 'NORMAL'}
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Evidence Gaps</div>
            <div className="text-2xl font-bold text-white">{claim.gap_count}</div>
            <div
              className={`text-xs mt-1 ${claim.gap_count >= 3 ? 'text-red-400' : claim.gap_count > 0 ? 'text-yellow-400' : 'text-emerald-400'}`}
            >
              {claim.gap_count === 0
                ? 'COMPLETE'
                : claim.gap_count >= 3
                  ? 'CRITICAL'
                  : 'INCOMPLETE'}
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Red Flags</div>
            <div className="text-2xl font-bold text-white">{claim.red_flag_count}</div>
            <div
              className={`text-xs mt-1 ${claim.red_flag_count >= 3 ? 'text-red-400' : claim.red_flag_count > 0 ? 'text-orange-400' : 'text-emerald-400'}`}
            >
              {claim.red_flag_count === 0
                ? 'NONE'
                : `${claim.red_flag_count} FLAG${claim.red_flag_count > 1 ? 'S' : ''}`}
            </div>
          </div>
        </div>

        {/* Decision Rationale */}
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-2 font-semibold flex items-center gap-2">
            Decision Rationale
            <span className="text-gray-600 font-normal normal-case tracking-normal">
              — AI-generated
            </span>
          </div>
          {recLoading && (
            <div className="bg-gray-800 border border-gray-700 rounded px-4 py-3 text-sm text-gray-500 italic animate-pulse">
              Agent analyzing claim…
            </div>
          )}
          {(recError || (rec && !rec.rationale)) && (
            <div className="bg-gray-800 border border-gray-700 rounded px-4 py-3 text-sm text-gray-200 break-words whitespace-normal leading-relaxed">
              {claim.rationale}
            </div>
          )}
          {rec && rec.rationale && (
            <div className="bg-gray-800 border border-gray-700 rounded px-4 py-3 text-sm text-gray-200 break-words whitespace-normal leading-relaxed">
              {rec.rationale}
            </div>
          )}
        </div>

        {/* Rule Trace */}
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-2 font-semibold">
            Rule Trace (R0–R6)
          </div>
          <RuleTracePanel trace={claim.rule_trace} />
        </div>

        {/* Evidence Gaps */}
        {claim.gaps.length > 0 && (
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-2 font-semibold">
              Evidence Gaps
            </div>
            <div className="space-y-1">
              {claim.gaps.map((gap, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 text-xs text-yellow-300 bg-yellow-950 border border-yellow-800 rounded px-3 py-1.5"
                >
                  <span className="text-yellow-500 shrink-0">⚠</span>
                  <span className="break-words whitespace-normal">{gap}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-3xl font-bold ${color ?? 'text-white'}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}

export function ClaimsDashboard() {
  const { data: claims, isLoading, isError, error, refetch, isFetching } = useClaims();
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>('claim_id');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const handleSort = (field: SortField) => {
    if (field === sortField) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('desc');
    }
  };

  const filtered = useMemo(() => {
    if (!claims) return [];
    const q = search.toLowerCase();
    return claims.filter(
      c =>
        !q ||
        c.claim_id.toLowerCase().includes(q) ||
        (c.insured_id ?? '').toLowerCase().includes(q) ||
        (c.loss_type ?? '').toLowerCase().includes(q)
    );
  }, [claims, search]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let av: string | number = a[sortField] ?? '';
      let bv: string | number = b[sortField] ?? '';
      if (typeof av === 'string') av = av.toLowerCase();
      if (typeof bv === 'string') bv = bv.toLowerCase();
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filtered, sortField, sortDir]);

  const stats = useMemo(() => {
    if (!claims) return null;
    const routingCounts: Record<string, number> = {};
    let highFraud = 0;
    for (const c of claims) {
      routingCounts[c.routing_decision] = (routingCounts[c.routing_decision] ?? 0) + 1;
      if (c.fraud_score >= 70) highFraud++;
    }
    return { total: claims.length, highFraud, routingCounts };
  }, [claims]);

  const thClass =
    'text-xs font-semibold text-gray-400 uppercase tracking-wide cursor-pointer hover:text-white select-none whitespace-nowrap';

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      <header className="border-b border-gray-800 bg-gray-900 px-6 py-4 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
            P
          </div>
          <div>
            <h1 className="text-lg font-bold text-white leading-none">P&C Claims Intelligence</h1>
            <p className="text-xs text-gray-500 mt-0.5">Motor Claims | FNOL Processing Dashboard</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {stats && <span className="text-xs text-gray-500">{stats.total} claims loaded</span>}
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetch()}
            disabled={isFetching}
            className="border-gray-700 text-gray-300 hover:bg-gray-800 hover:text-white text-xs"
          >
            {isFetching ? 'Refreshing...' : 'Refresh'}
          </Button>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-6 space-y-6">
        {isLoading && (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-24 bg-gray-800" />
              ))}
            </div>
            <Skeleton className="h-96 bg-gray-800" />
          </div>
        )}

        {isError && (
          <div className="bg-red-950 border border-red-800 rounded-lg p-6 text-center">
            <div className="text-red-400 text-lg font-semibold mb-2">Failed to load claims</div>
            <div className="text-red-300 text-sm mb-4">{String(error)}</div>
            <Button
              onClick={() => refetch()}
              variant="outline"
              className="border-red-700 text-red-300 hover:bg-red-900"
            >
              Retry
            </Button>
          </div>
        )}

        {!isLoading && !isError && claims && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard label="Total Claims" value={stats?.total ?? 0} sub="All FNOL records" />
              <StatCard
                label="High Fraud Risk"
                value={stats?.highFraud ?? 0}
                sub="Score ≥ 70%"
                color="text-red-400"
              />
              <StatCard
                label="Decline Review"
                value={stats?.routingCounts['Recommend Decline Review'] ?? 0}
                sub="Rule R0 triggered"
                color="text-red-400"
              />
              <StatCard
                label="Fast Track"
                value={stats?.routingCounts['Fast Track'] ?? 0}
                sub="Rule R5 — auto-eligible"
                color="text-emerald-400"
              />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              {Object.entries(stats?.routingCounts ?? {}).map(([k, v]) => (
                <div
                  key={k}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 flex items-center gap-2"
                >
                  <span
                    className={`w-2 h-2 rounded-full shrink-0 ${ROUTING_DOT[k] ?? 'bg-gray-500'}`}
                  />
                  <div>
                    <div className="text-xs text-gray-400 leading-tight">{k}</div>
                    <div className="text-sm font-bold text-white">{v}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-800 flex items-center gap-3">
                <Input
                  placeholder="Search by Claim ID, Insured ID, or Loss Type..."
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="max-w-sm bg-gray-800 border-gray-700 text-gray-100 placeholder:text-gray-500 text-sm"
                />
                {search && (
                  <span className="text-xs text-gray-500">
                    {sorted.length} result{sorted.length !== 1 ? 's' : ''}
                  </span>
                )}
              </div>

              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="border-gray-800 hover:bg-transparent">
                      <TableHead className={thClass} onClick={() => handleSort('claim_id')}>
                        Claim ID <SortIcon field="claim_id" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className={thClass} onClick={() => handleSort('insured_id')}>
                        Insured ID <SortIcon field="insured_id" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className={thClass} onClick={() => handleSort('loss_date')}>
                        Date <SortIcon field="loss_date" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className={thClass} onClick={() => handleSort('fraud_score')}>
                        Fraud Score{' '}
                        <SortIcon field="fraud_score" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className={thClass} onClick={() => handleSort('anomaly_score')}>
                        Anomaly <SortIcon field="anomaly_score" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className={thClass} onClick={() => handleSort('routing_decision')}>
                        Decision{' '}
                        <SortIcon field="routing_decision" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className={thClass} onClick={() => handleSort('rule_fired')}>
                        Rule <SortIcon field="rule_fired" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className={thClass} onClick={() => handleSort('gap_count')}>
                        Gaps <SortIcon field="gap_count" current={sortField} dir={sortDir} />
                      </TableHead>
                      <TableHead className="text-xs font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap">
                        Audit
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sorted.map(claim => {
                      const isExpanded = expanded === claim.claim_id;
                      return (
                        <>
                          <TableRow
                            key={claim.claim_id}
                            className={`border-gray-800 cursor-pointer transition-colors ${isExpanded ? 'bg-gray-800' : 'hover:bg-gray-800/60'}`}
                            onClick={() => setExpanded(isExpanded ? null : claim.claim_id)}
                          >
                            <TableCell className="font-mono text-sm text-blue-300 font-semibold">
                              {claim.claim_id}
                            </TableCell>
                            <TableCell className="text-sm text-gray-300">
                              {claim.insured_id ?? '—'}
                            </TableCell>
                            <TableCell className="text-sm text-gray-400 whitespace-nowrap">
                              {claim.loss_date ? claim.loss_date.split('T')[0] : '—'}
                            </TableCell>
                            <TableCell className="min-w-32">
                              <ScoreBar
                                value={claim.fraud_score}
                                max={100}
                                color={
                                  claim.fraud_score >= 70
                                    ? 'bg-red-500'
                                    : claim.fraud_score >= 50
                                      ? 'bg-orange-400'
                                      : 'bg-emerald-500'
                                }
                              />
                            </TableCell>
                            <TableCell className="min-w-28">
                              <ScoreBar
                                value={claim.anomaly_score}
                                max={1}
                                color={claim.anomaly_score >= 0.5 ? 'bg-red-500' : 'bg-blue-400'}
                              />
                            </TableCell>
                            <TableCell>
                              <RoutingBadge decision={claim.routing_decision} />
                            </TableCell>
                            <TableCell className="font-mono text-xs text-gray-400 font-bold">
                              {claim.rule_fired}
                            </TableCell>
                            <TableCell>
                              {claim.gap_count > 0 ? (
                                <span
                                  className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${claim.gap_count >= 3 ? 'bg-red-900 text-red-300' : 'bg-yellow-900 text-yellow-300'}`}
                                >
                                  {claim.gap_count}
                                </span>
                              ) : (
                                <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs bg-gray-800 text-gray-500">
                                  0
                                </span>
                              )}
                            </TableCell>
                            <TableCell>
                              <button
                                className="text-xs text-gray-400 hover:text-blue-300 transition-colors"
                                onClick={e => {
                                  e.stopPropagation();
                                  setExpanded(isExpanded ? null : claim.claim_id);
                                }}
                              >
                                {isExpanded ? '▲ Hide' : '▼ Show'}
                              </button>
                            </TableCell>
                          </TableRow>
                          {isExpanded && (
                            <TableRow
                              key={`${claim.claim_id}-detail`}
                              className="border-gray-800 bg-gray-900/50"
                            >
                              <TableCell colSpan={9} className="p-4">
                                <AuditTrail claim={claim} />
                              </TableCell>
                            </TableRow>
                          )}
                        </>
                      );
                    })}
                    {sorted.length === 0 && !isLoading && (
                      <TableRow>
                        <TableCell colSpan={9} className="text-center text-gray-500 py-12">
                          {search ? 'No claims match your search.' : 'No claims available.'}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
