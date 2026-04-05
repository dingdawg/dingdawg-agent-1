"use client";

/**
 * Admin Workflows page — Workflow Test Runner.
 *
 * - 4 built-in test cards: Health Check, Auth Flow, Agent Creation, Stripe Webhook
 * - Each card: name, description, last result (pass/fail), last run time, Run button
 * - Run All button at top
 * - Expandable results panel with step-by-step execution
 * - Test History table
 * - Manual trigger only — no auto-polling
 * - Mobile responsive with 48px touch targets
 * - No HTML entities in JSX
 */

import { useEffect, useState, useCallback } from "react";
import {
  Play,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Activity,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getWorkflowTests,
  runWorkflowTest,
  runAllWorkflowTests,
  getTestHistory,
  type WorkflowTest,
  type RunTestResponse,
  type TestHistoryEntry,
  type TestResult,
  type TestStep,
} from "@/services/api/adminService";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ─── Built-in test definitions (static fallback if backend returns empty) ─────

const BUILTIN_TESTS: WorkflowTest[] = [
  {
    id: "health-check",
    name: "Health Check",
    description:
      "Verifies all backend services are reachable and returning 200 OK.",
    last_result: "pending",
  },
  {
    id: "auth-flow",
    name: "Auth Flow",
    description:
      "Registers a test user, logs in, refreshes token, and logs out.",
    last_result: "pending",
  },
  {
    id: "agent-creation",
    name: "Agent Creation",
    description:
      "Creates a test agent with a unique handle, verifies it persists, then cleans up.",
    last_result: "pending",
  },
  {
    id: "stripe-webhook",
    name: "Stripe Webhook",
    description:
      "Sends a simulated Stripe payment_intent.succeeded event and verifies processing.",
    last_result: "pending",
  },
];

// ─── Result badge ─────────────────────────────────────────────────────────────

function ResultBadge({ result }: { result: TestResult }) {
  const config: Record<TestResult, { icon: React.ComponentType<{ className?: string }>; label: string; className: string }> = {
    pass: {
      icon: CheckCircle2,
      label: "Pass",
      className: "text-green-400 bg-green-500/10 border-green-500/20",
    },
    fail: {
      icon: XCircle,
      label: "Fail",
      className: "text-red-400 bg-red-500/10 border-red-500/20",
    },
    pending: {
      icon: Clock,
      label: "Not run",
      className: "text-gray-400 bg-gray-500/10 border-gray-500/20",
    },
    running: {
      icon: Activity,
      label: "Running",
      className: "text-blue-400 bg-blue-500/10 border-blue-500/20",
    },
  };
  const cfg = config[result] ?? config.pending;
  const Icon = cfg.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border",
        cfg.className
      )}
    >
      <Icon className={cn("h-3 w-3", result === "running" && "animate-spin")} />
      {cfg.label}
    </span>
  );
}

// ─── Step row ─────────────────────────────────────────────────────────────────

function StepRow({ step }: { step: TestStep }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-[#1a2a3d] last:border-0">
      {step.result === "pass" ? (
        <CheckCircle2 className="h-4 w-4 text-green-400 flex-shrink-0 mt-0.5" />
      ) : (
        <XCircle className="h-4 w-4 text-red-400 flex-shrink-0 mt-0.5" />
      )}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-white">{step.name}</p>
        {step.error && (
          <p className="text-xs text-red-400 mt-0.5 font-mono break-all">
            {step.error}
          </p>
        )}
      </div>
      <span className="text-xs text-gray-500 flex-shrink-0">
        {formatMs(step.duration_ms)}
      </span>
    </div>
  );
}

// ─── Test Card ────────────────────────────────────────────────────────────────

function TestCard({
  test,
  runResult,
  running,
  onRun,
}: {
  test: WorkflowTest;
  runResult: RunTestResponse | null;
  running: boolean;
  onRun: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const currentResult: TestResult = running
    ? "running"
    : runResult?.result ?? test.last_result;
  const steps = runResult?.steps ?? test.steps ?? [];
  const hasSteps = steps.length > 0;
  const lastRan = runResult?.ran_at ?? test.last_run_at;

  return (
    <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl overflow-hidden">
      {/* Card header */}
      <div className="p-4">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white">{test.name}</p>
            <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">
              {test.description}
            </p>
          </div>
          <ResultBadge result={currentResult} />
        </div>

        {lastRan && (
          <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-3">
            <Clock className="h-3 w-3" />
            Last run {formatTimestamp(lastRan)}
            {runResult && (
              <span className="ml-1">
                ({formatMs(runResult.duration_ms)})
              </span>
            )}
          </div>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={() => onRun(test.id)}
            disabled={running}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-all min-h-[44px]",
              running
                ? "bg-blue-500/10 border border-blue-500/20 text-blue-400"
                : "bg-[var(--gold-400)] text-[#07111c] hover:opacity-90"
            )}
          >
            <Play className={cn("h-3.5 w-3.5", running && "animate-pulse")} />
            {running ? "Running..." : "Run"}
          </button>

          {hasSteps && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-colors min-h-[44px]"
            >
              {expanded ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
              {expanded ? "Hide" : "Details"}
            </button>
          )}
        </div>
      </div>

      {/* Expandable steps */}
      {expanded && hasSteps && (
        <div className="border-t border-[#1a2a3d] px-4 py-3 bg-black/10">
          <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wide">
            Steps
          </p>
          <div>
            {steps.map((step, idx) => (
              <StepRow key={idx} step={step} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Test History ─────────────────────────────────────────────────────────────

function TestHistory({
  entries,
  loading,
}: {
  entries: TestHistoryEntry[];
  loading: boolean;
}) {
  if (loading && entries.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-10 rounded-lg bg-white/3 animate-pulse border border-[#1a2a3d]"
          />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="text-sm text-gray-500 text-center py-6">
        No test history yet
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-0 divide-y divide-[#1a2a3d]">
      {entries.slice(0, 20).map((entry, idx) => (
        <div key={idx} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
          {entry.result === "pass" ? (
            <CheckCircle2 className="h-4 w-4 text-green-400 flex-shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 text-red-400 flex-shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-white truncate">
              {entry.test_name}
            </p>
            <p className="text-xs text-gray-500">
              {formatTimestamp(entry.ran_at)}
            </p>
          </div>
          <span className="text-xs text-gray-500 flex-shrink-0">
            {formatMs(entry.duration_ms)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function WorkflowsPage() {
  return <WorkflowsContent />;
}

function WorkflowsContent() {
  const [tests, setTests] = useState<WorkflowTest[]>(BUILTIN_TESTS);
  const [history, setHistory] = useState<TestHistoryEntry[]>([]);
  const [runResults, setRunResults] = useState<Record<string, RunTestResponse>>({});
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runningAll, setRunningAll] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTests = useCallback(async () => {
    try {
      const data = await getWorkflowTests();
      if (data.length > 0) {
        setTests(data);
      }
      // If backend returns empty, keep the BUILTIN_TESTS fallback
    } catch {
      // Non-critical — keep built-in definitions
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await getTestHistory();
      setHistory(data);
    } catch {
      // History is non-critical
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTests();
    loadHistory();
  }, [loadTests, loadHistory]);

  const handleRunTest = useCallback(
    async (testId: string) => {
      setRunningId(testId);
      setError(null);
      try {
        const result = await runWorkflowTest(testId);
        setRunResults((prev) => ({ ...prev, [testId]: result }));
        // Update the test's last_result in the list
        setTests((prev) =>
          prev.map((t) =>
            t.id === testId
              ? { ...t, last_result: result.result, last_run_at: result.ran_at }
              : t
          )
        );
        loadHistory();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Test failed to run";
        setError(msg);
      } finally {
        setRunningId(null);
      }
    },
    [loadHistory]
  );

  const handleRunAll = useCallback(async () => {
    setRunningAll(true);
    setError(null);
    try {
      const results = await runAllWorkflowTests();
      const resultMap: Record<string, RunTestResponse> = {};
      for (const r of results) {
        resultMap[r.test_id] = r;
      }
      setRunResults((prev) => ({ ...prev, ...resultMap }));
      setTests((prev) =>
        prev.map((t) => {
          const r = resultMap[t.id];
          if (!r) return t;
          return { ...t, last_result: r.result, last_run_at: r.ran_at };
        })
      );
      loadHistory();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Run all failed";
      setError(msg);
    } finally {
      setRunningAll(false);
    }
  }, [loadHistory]);

  const passCount = Object.values(runResults).filter((r) => r.result === "pass").length;
  const failCount = Object.values(runResults).filter((r) => r.result === "fail").length;
  const hasRunAny = Object.keys(runResults).length > 0;

  return (
    <div className="h-full overflow-y-auto scrollbar-thin px-4 pt-6 pb-20 lg:pb-8 max-w-3xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Workflows</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            System test runner
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { loadTests(); loadHistory(); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-colors min-h-[44px]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
          <button
            onClick={handleRunAll}
            disabled={runningAll || runningId !== null}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[var(--gold-400)] text-[#07111c] text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-40 min-h-[44px]"
          >
            <Zap
              className={cn("h-4 w-4", runningAll && "animate-pulse")}
            />
            {runningAll ? "Running..." : "Run All"}
          </button>
        </div>
      </div>

      {/* Summary bar (only after at least one run) */}
      {hasRunAny && (
        <div className="flex items-center gap-4 mb-5 p-3 bg-[#0d1926] border border-[#1a2a3d] rounded-xl">
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="h-4 w-4 text-green-400" />
            <span className="text-sm font-semibold text-green-400">{passCount} pass</span>
          </div>
          <div className="flex items-center gap-1.5">
            <XCircle className="h-4 w-4 text-red-400" />
            <span className="text-sm font-semibold text-red-400">{failCount} fail</span>
          </div>
          <div className="text-xs text-gray-500">
            {passCount + failCount} of {tests.length} run
          </div>
        </div>
      )}

      {error && (
        <div className="mb-5 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Test cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
        {tests.map((test) => (
          <TestCard
            key={test.id}
            test={test}
            runResult={runResults[test.id] ?? null}
            running={runningId === test.id || (runningAll)}
            onRun={handleRunTest}
          />
        ))}
      </div>

      {/* Test History */}
      <div className="bg-[#0d1926] border border-[#1a2a3d] rounded-xl p-4">
        <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Clock className="h-4 w-4 text-[var(--gold-400)]" />
          Test History
        </h2>
        <TestHistory entries={history} loading={historyLoading} />
      </div>
    </div>
  );
}
