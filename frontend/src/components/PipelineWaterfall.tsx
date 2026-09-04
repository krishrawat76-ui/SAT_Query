"use client";

import type { PipelineStep } from "@/types/api";

interface PipelineWaterfallProps {
    steps: PipelineStep[];
}

/** Minimum visible width for a non-zero bar, as a % of the track. Only ever
 * applied to work that genuinely took time — a zero-duration step renders a
 * tick instead, so the floor can't imply elapsed time that didn't happen. */
const MIN_BAR_PCT = 0.75;

/** Adaptive precision: the backend measures with `perf_counter` and rounds to
 * microseconds, so rendering `.toFixed(0)` would report real sub-millisecond
 * work as "0ms". */
function formatMs(ms: number): string {
    if (ms === 0) return "0";
    if (ms < 1) return `${(ms * 1000).toFixed(0)}µs`;
    if (ms < 10) return `${ms.toFixed(2)}ms`;
    return `${ms.toFixed(0)}ms`;
}

/**
 * Horizontal timeline of real per-step timing: amber segment for
 * `load_time_ms` (cold model load), emerald/rose segment for
 * `inference_time_ms` (green on success, red on failure).
 *
 * Positions are set via `left`/`width`, never a CSS `transform` — a transform
 * on a descendant of this card's `backdrop-blur-xl` ancestor would re-trigger
 * the Chromium clipping bug documented elsewhere in this codebase
 * (LayerSwitcher.tsx, PinnedQueryCard.tsx, QueryInput.tsx).
 *
 * Two cases are handled explicitly rather than papered over:
 *  - A step that took literally 0ms renders a tick, not a bar. Drawing a
 *    floored sliver there would imply measured duration that never happened.
 *  - A bar whose start lands at the far edge is pulled back so it stays
 *    inside the `overflow-hidden` track. This matters most for a *failed*
 *    step: the executor breaks on failure, so a failed step is always last,
 *    and one that died during load has 0ms inference — previously that bar
 *    was positioned at exactly `left: 100%` and clipped to invisibility, in
 *    the one case the timeline exists to show.
 */
export default function PipelineWaterfall({ steps }: PipelineWaterfallProps) {
    if (steps.length === 0) return null;

    const measuredSpan = Math.max(...steps.map((s) => s.started_at_ms + s.time_ms));
    // Every step finished too fast to place on a shared axis — a synthesized
    // span would render identical stubs that read as real measurement.
    const hasTimeline = measuredSpan > 0;
    const spanMs = hasTimeline ? measuredSpan : 1;

    return (
        <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                Pipeline timeline
            </h4>
            <div className="space-y-2">
                {steps.map((step) => {
                    const startPct = (step.started_at_ms / spanMs) * 100;
                    const loadPct = (step.load_time_ms / spanMs) * 100;
                    const rawInferPct = (step.inference_time_ms / spanMs) * 100;
                    const failed = step.status !== "success";

                    // Clamp so a bar can never begin past the track's right
                    // edge and get clipped away entirely.
                    const inferLeft = Math.min(startPct + loadPct, 100 - MIN_BAR_PCT);
                    const inferWidth = Math.min(
                        Math.max(rawInferPct, MIN_BAR_PCT),
                        100 - inferLeft
                    );

                    return (
                        <div key={step.step}>
                            <div className="mb-1 flex items-center justify-between text-[11px]">
                                <span className="font-medium text-slate-300">
                                    {step.model} <span className="text-slate-500">· {step.action}</span>
                                </span>
                                <span className="text-slate-500">
                                    {step.model_was_cached ? "warm" : "cold"} · {formatMs(step.time_ms)}
                                    {step.telemetry?.tokens_per_sec != null &&
                                        ` · ${step.telemetry.tokens_per_sec.toFixed(1)} tok/s`}
                                </span>
                            </div>

                            <div className="relative h-2 w-full overflow-hidden rounded-full bg-white/5">
                                {step.time_ms === 0 ? (
                                    // Too fast to measure — a tick, not a bar.
                                    <div
                                        className={`absolute top-0 h-full w-0.5 ${failed ? "bg-rose-400" : "bg-slate-500"
                                            }`}
                                        style={{ left: `${Math.min(startPct, 99.5)}%` }}
                                        title="Completed in under 1µs — too fast to measure"
                                    />
                                ) : (
                                    <>
                                        {step.load_time_ms > 0 && (
                                            <div
                                                className="absolute top-0 h-full rounded-full bg-amber-500/50"
                                                style={{
                                                    left: `${startPct}%`,
                                                    // Same floor as the inference bar — otherwise a
                                                    // genuinely cold sub-ms load renders invisible
                                                    // while the row's own label says "cold".
                                                    width: `${Math.max(loadPct, MIN_BAR_PCT)}%`,
                                                }}
                                            />
                                        )}
                                        {step.inference_time_ms > 0 && (
                                            <div
                                                className={`absolute top-0 h-full rounded-full ${failed ? "bg-rose-500/60" : "bg-emerald-500/60"
                                                    }`}
                                                style={{ left: `${inferLeft}%`, width: `${inferWidth}%` }}
                                            />
                                        )}
                                        {failed && step.inference_time_ms === 0 && (
                                            // Died during load — no inference happened, but the
                                            // failure still has to be visible.
                                            <div
                                                className="absolute top-0 h-full rounded-full bg-rose-500/60"
                                                style={{ left: `${inferLeft}%`, width: `${MIN_BAR_PCT}%` }}
                                            />
                                        )}
                                    </>
                                )}
                            </div>

                            {failed && step.error && (
                                <p className="mt-1 truncate text-[10px] text-rose-400" title={step.error}>
                                    {step.error}
                                </p>
                            )}
                        </div>
                    );
                })}
            </div>

            <p className="mt-1.5 text-[10px] text-slate-500">
                {hasTimeline
                    ? "amber = model load · green = inference · red = failed step"
                    : "every step completed in under 1µs — no measurable timeline to plot"}
            </p>
        </div>
    );
}
