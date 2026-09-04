"use client";

import type { RouterMetadata } from "@/types/api";

interface RouterMetricsHeaderProps {
    meta: RouterMetadata | null;
}

const chipClass =
    "rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300";

/**
 * Real router facts (type, rule, matched keywords, routing time) plus an
 * explicit "not reported" state for the LLM-planner fields. Those fields
 * are `null` for this repo's deterministic RuleBasedRouter — rendering `0`
 * or `—` there would read as a real measurement of zero; a sentence saying
 * why there's nothing to report is the honest version.
 */
export default function RouterMetricsHeader({ meta }: RouterMetricsHeaderProps) {
    // Defensive: `useAnalysis` casts the response without validating it, so a
    // partial `router_metadata` can arrive from an older deploy or a proxy.
    // Reading `.router_type`/`.routing_time_ms` off it unguarded would throw
    // and, with no error boundary in this app, take down the page.
    if (!meta?.router_type) return null;

    const hasPlannerData =
        meta.planner_type != null ||
        meta.tokens_per_sec != null ||
        meta.prompt_tokens != null ||
        meta.completion_tokens != null ||
        meta.planning_time_ms != null;

    return (
        <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                Router
            </h4>
            <div className="flex flex-wrap gap-1.5">
                <span className={chipClass}>{meta.router_type.replace(/_/g, " ")}</span>
                {meta.rule_id && <span className={chipClass}>{meta.rule_id}</span>}
                {meta.routing_time_ms != null && (
                    <span className={chipClass}>{meta.routing_time_ms.toFixed(2)}ms routing</span>
                )}
                {meta.fallback_used && (
                    <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-300">
                        fallback rule
                    </span>
                )}
            </div>

            {meta.matched_keywords?.length > 0 && (
                <p className="mt-1.5 text-[11px] text-slate-500">
                    matched: {meta.matched_keywords.map((k) => `"${k}"`).join(", ")}
                </p>
            )}

            <div className="mt-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                    LLM planner
                </p>
                {hasPlannerData ? (
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-300">
                        {meta.planner_type && <span>{meta.planner_type}</span>}
                        {meta.tokens_per_sec != null && <span>{meta.tokens_per_sec.toFixed(1)} tok/s</span>}
                        {meta.prompt_tokens != null && <span>{meta.prompt_tokens} prompt tok</span>}
                        {meta.completion_tokens != null && <span>{meta.completion_tokens} completion tok</span>}
                        {meta.planning_time_ms != null && (
                            <span>{meta.planning_time_ms.toFixed(1)}ms planning</span>
                        )}
                    </div>
                ) : (
                    <p className="text-[11px] text-slate-500">
                        {/* The explanatory clause is gated on the router we actually
                            know the internals of. For any other router we can only
                            report that it sent no planner metrics — asserting *why*
                            would be inventing a fact about code we haven't seen,
                            which is the exact failure this panel exists to avoid. */}
                        {meta.router_type === "rule_based_keyword"
                            ? "Not reported — this router is deterministic keyword matching, with no language model in the loop."
                            : "Not reported by this router."}
                    </p>
                )}
            </div>
        </div>
    );
}
