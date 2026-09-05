"use client";

import { useState } from "react";
import { ChevronDown, CheckCircle2, XCircle } from "lucide-react";
import type { ExecutionTraceData } from "@/types/api";

interface ExecutionTraceProps {
    trace: ExecutionTraceData | null;
}

export default function ExecutionTrace({ trace }: ExecutionTraceProps) {
    const [open, setOpen] = useState(false);

    if (!trace) return null;

    return (
        <div className="overflow-hidden rounded-[28px] border border-white/10 bg-slate-900/70 shadow-2xl backdrop-blur-xl">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="flex w-full items-center justify-between px-5 py-4 text-left"
            >
                <div className="flex items-center gap-3">
                    <span className="rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-slate-100">
                        {trace.detected_task.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-slate-400">
                        {trace.task_confidence != null && `${Math.round(trace.task_confidence * 100)}% confidence · `}
                        {trace.total_time_ms.toFixed(0)}ms
                    </span>
                </div>
                <ChevronDown
                    className={`h-4 w-4 text-slate-400 transition-transform ${open ? "rotate-180" : ""
                        }`}
                />
            </button>

            {open && (
                <div className="space-y-4 border-t border-white/10 px-5 py-4">
                    <div>
                        <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                            Reasoning
                        </h4>
                        <p className="text-sm text-slate-300">{trace.reasoning}</p>
                    </div>

                    <div>
                        <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                            Input validation
                        </h4>
                        <div className="flex flex-wrap gap-1.5">
                            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300">
                                {trace.input_validation.image_count} image
                                {trace.input_validation.image_count !== 1 ? "s" : ""}
                            </span>
                            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300">
                                {trace.input_validation.modality.join(" + ")}
                            </span>
                            {trace.input_validation.temporal && (
                                <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300">
                                    bi-temporal
                                </span>
                            )}
                            {trace.input_validation.cross_modal && (
                                <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-slate-300">
                                    cross-modal
                                </span>
                            )}
                        </div>
                        {trace.input_validation.warnings.length > 0 && (
                            <ul className="mt-2 space-y-1">
                                {trace.input_validation.warnings.map((w, i) => (
                                    <li key={i} className="text-[11px] text-amber-400">
                                        ⚠ {w}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>

                    <div>
                        <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                            Pipeline steps
                        </h4>
                        <div className="space-y-1.5">
                            {trace.pipeline_steps.map((step) => (
                                <div
                                    key={step.step}
                                    className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs"
                                >
                                    <div className="flex items-center gap-2">
                                        {step.status === "success" ? (
                                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                                        ) : (
                                            <XCircle className="h-3.5 w-3.5 text-rose-400" />
                                        )}
                                        <span className="font-medium text-slate-300">
                                            {step.model}
                                        </span>
                                        <span className="text-slate-500">{step.action}</span>
                                    </div>
                                    <span className="text-slate-500">
                                        {step.time_ms.toFixed(0)}ms
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
