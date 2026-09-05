"use client";

import { useMemo, useState } from "react";
import { Bug, ChevronDown } from "lucide-react";
import RouterMetricsHeader from "./RouterMetricsHeader";
import ModelChoiceReasoner from "./ModelChoiceReasoner";
import PipelineWaterfall from "./PipelineWaterfall";
import RawPayloadViewer from "./RawPayloadViewer";
import type { AnalysisResponse, StageTimings } from "@/types/api";

interface DebugPanelProps {
    query: string;
    imageNames: string[];
    /** Per-image modality actually sent as the `modalities` form field. */
    modalities: string[];
    /** Null when the request failed before returning a body. */
    result: AnalysisResponse | null;
    error: string | null;
    /** Whether `?debug=true` was sent for this specific turn. */
    debugRequested: boolean;
}

function formatMs(ms: number): string {
    if (ms === 0) return "0";
    if (ms < 1) return `${(ms * 1000).toFixed(0)}µs`;
    if (ms < 10) return `${ms.toFixed(2)}ms`;
    return `${ms.toFixed(0)}ms`;
}

const STAGE_LABELS: { key: keyof StageTimings; label: string }[] = [
    { key: "upload_ms", label: "upload" },
    { key: "validation_ms", label: "validate" },
    { key: "routing_ms", label: "route" },
    { key: "execution_ms", label: "execute" },
    { key: "integration_ms", label: "integrate" },
    { key: "other_ms", label: "other" },
];

/** Server-side wall-clock breakdown. `total_time_ms` was previously the sum of
 * step times, which excluded upload/validation/routing/integration and so was
 * never request latency; the old figure survives as `pipeline_steps_ms`, and
 * showing both side by side is the point of this strip. */
function StageTimingStrip({ timings, totalMs }: { timings: StageTimings; totalMs: number }) {
    return (
        <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                Where the time went
            </h4>
            <div className="flex flex-wrap gap-1.5">
                {STAGE_LABELS.map(({ key, label }) => (
                    <span
                        key={key}
                        className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300"
                    >
                        {label} {formatMs(timings[key])}
                    </span>
                ))}
            </div>
            <p className="mt-1.5 text-[10px] text-slate-500">
                handler total {formatMs(totalMs)} · of which pipeline steps{" "}
                {formatMs(timings.pipeline_steps_ms)}
            </p>
        </div>
    );
}

/**
 * Debug Mode's inspector card — router decision, model selection, per-step
 * timing, and raw request/response JSON. Everything shown is either a real
 * measurement or an explicit "not reported" state; nothing is a placeholder.
 *
 * Renders for failed turns too (no trace, request side only) — a failure is
 * exactly when this panel is most worth having.
 */
export default function DebugPanel({
    query,
    imageNames,
    modalities,
    result,
    error,
    debugRequested,
}: DebugPanelProps) {
    const [open, setOpen] = useState(false);

    // `useAnalysis` casts the response without validating it, so a malformed
    // 200 (older deploy, proxy, mock) can arrive with no execution_trace. Every
    // other consumer in this app degrades rather than throwing; without this
    // guard the panel would take down the whole page — and only for the users
    // who turned Debug Mode on to diagnose that very response.
    const trace = result?.execution_trace ?? null;

    // Memoized because `page.tsx` updates `focusRect` on every rendered frame
    // of any camera flight, so an expanded panel would otherwise re-serialize
    // this object dozens of times per second during an animation.
    const requestPayload = useMemo(
        () => ({ query, images: imageNames, modalities, debug: debugRequested }),
        [query, imageNames, modalities, debugRequested]
    );

    const snapshotSteps = trace?.pipeline_steps.filter((s) => s.payload_snapshot != null) ?? [];

    return (
        <div className="overflow-hidden rounded-[28px] border border-amber-500/20 bg-slate-900/70 shadow-2xl backdrop-blur-xl">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex w-full items-center justify-between px-5 py-4 text-left"
                aria-expanded={open}
            >
                <div className="flex items-center gap-2">
                    <Bug className="h-3.5 w-3.5 text-amber-400" />
                    <span className="rounded-full bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-300">
                        Debug
                    </span>
                    <span className="text-xs text-slate-400">
                        {trace
                            ? `${trace.pipeline_steps.length} step${trace.pipeline_steps.length !== 1 ? "s" : ""}`
                            : "request failed"}
                        {trace?.request_id && ` · ${trace.request_id}`}
                    </span>
                </div>
                <ChevronDown
                    className={`h-4 w-4 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
                />
            </button>

            {open && (
                <div className="space-y-4 border-t border-white/10 px-5 py-4">
                    {error && (
                        <div>
                            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                                Error
                            </h4>
                            <p className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-300">
                                {error}
                            </p>
                        </div>
                    )}

                    {!trace && !error && (
                        <p className="text-[11px] text-slate-500">
                            The response arrived without an execution trace, so there's no
                            router or timing data to show for this turn.
                        </p>
                    )}

                    {trace && (
                        <>
                            <RouterMetricsHeader meta={trace.router_metadata} />
                            {trace.router_metadata?.intent_decomposition != null &&
                                trace.router_metadata.intent_decomposition.length > 0 && (
                                <div>
                                    <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                                        Intent decomposition
                                    </h4>
                                    <div className="space-y-1.5">
                                        {trace.router_metadata.intent_decomposition.map((intent, idx) => {
                                            const taskId = String(intent.task_id ?? `task_${idx + 1}`);
                                            const task = String(intent.task ?? "?");
                                            const models = Array.isArray(intent.assigned_models)
                                                ? (intent.assigned_models as string[])
                                                : [];
                                            const q = intent.query != null ? String(intent.query) : "";
                                            const deps = Array.isArray(intent.depends_on)
                                                ? (intent.depends_on as string[])
                                                : [];
                                            const imgs = Array.isArray(intent.images)
                                                ? (intent.images as { filename?: string }[])
                                                : [];
                                            return (
                                                <div
                                                    key={taskId}
                                                    className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-[11px] text-slate-300"
                                                >
                                                    <p className="font-medium text-slate-200">
                                                        {taskId}: {task}
                                                        {deps.length > 0 && (
                                                            <span className="ml-2 font-normal text-slate-500">
                                                                depends on {deps.join(", ")}
                                                            </span>
                                                        )}
                                                    </p>
                                                    {q && (
                                                        <p className="mt-0.5 text-slate-400">
                                                            query → {q}
                                                        </p>
                                                    )}
                                                    {models.length > 0 && (
                                                        <p className="mt-0.5 text-slate-400">
                                                            models → {models.join(", ")}
                                                        </p>
                                                    )}
                                                    {imgs.length > 0 && (
                                                        <p className="mt-0.5 text-slate-500">
                                                            images →{" "}
                                                            {imgs
                                                                .map((im) => im.filename ?? "?")
                                                                .join(", ")}
                                                        </p>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                            <ModelChoiceReasoner models={trace.selected_models} />
                            {trace.pipeline_steps.some(
                                (s) =>
                                    s.telemetry?.execution === "REMOTE" ||
                                    (s.payload_snapshot as { execution?: string } | null)
                                        ?.execution === "REMOTE"
                            ) && (
                                <div>
                                    <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                                        Remote execution
                                    </h4>
                                    <div className="space-y-1.5">
                                        {trace.pipeline_steps
                                            .filter(
                                                (s) =>
                                                    s.telemetry?.execution === "REMOTE" ||
                                                    (s.payload_snapshot as { execution?: string } | null)
                                                        ?.execution === "REMOTE"
                                            )
                                            .map((s) => {
                                                const tel = (s.telemetry || {}) as Record<
                                                    string,
                                                    unknown
                                                >;
                                                const snap = (s.payload_snapshot || {}) as Record<
                                                    string,
                                                    unknown
                                                >;
                                                return (
                                                    <div
                                                        key={s.step}
                                                        className="rounded-xl border border-sky-500/20 bg-sky-500/10 px-3 py-2 text-[11px] text-slate-300"
                                                    >
                                                        <p className="font-medium text-sky-200">
                                                            Step {s.step}: {s.action} · REMOTE
                                                        </p>
                                                        <p>
                                                            Node:{" "}
                                                            {String(
                                                                tel.node_id ??
                                                                    snap.node_id ??
                                                                    "—"
                                                            )}
                                                        </p>
                                                        <p>
                                                            Runtime:{" "}
                                                            {String(
                                                                tel.runtime ??
                                                                    snap.runtime ??
                                                                    "ollama"
                                                            )}{" "}
                                                            · Model:{" "}
                                                            {String(
                                                                tel.model ??
                                                                    snap.model ??
                                                                    s.model
                                                            )}
                                                        </p>
                                                        <p>
                                                            Status:{" "}
                                                            {s.status === "success"
                                                                ? "SUCCESS"
                                                                : s.error || "FAILED"}
                                                        </p>
                                                    </div>
                                                );
                                            })}
                                    </div>
                                </div>
                            )}
                            <PipelineWaterfall steps={trace.pipeline_steps} />
                            {trace.timings && (
                                <StageTimingStrip
                                    timings={trace.timings}
                                    totalMs={trace.total_time_ms}
                                />
                            )}

                            {snapshotSteps.length > 0 && (
                                <div>
                                    <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                                        Step payloads
                                    </h4>
                                    <div className="flex flex-wrap gap-1.5">
                                        {snapshotSteps.map((s) => (
                                            <span
                                                key={s.step}
                                                className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300"
                                            >
                                                step {s.step}: {s.payload_bytes ?? "?"} B
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {!trace.debug && (
                                <p className="text-[11px] text-slate-500">
                                    Payload snapshots weren&apos;t captured for this request — enable
                                    Debug Mode before submitting to include them next time.
                                </p>
                            )}
                        </>
                    )}

                    <RawPayloadViewer label="Request" data={requestPayload} />
                    {result && <RawPayloadViewer label="Response" data={result} />}
                </div>
            )}
        </div>
    );
}
