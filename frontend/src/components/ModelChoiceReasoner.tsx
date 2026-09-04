"use client";

import type { SelectedModel } from "@/types/api";

interface ModelChoiceReasonerProps {
    models: SelectedModel[];
}

/**
 * Why each specialist model was selected — `selection_reason` is composed
 * server-side purely from the router's own rule and this model's assigned
 * pipeline actions (see backend/app/output/trace.py::_selection_reason),
 * never hand-written per-model prose. `registered`/`loaded`/`vram_gb` are
 * real ModelRegistry state, not inferred.
 */
export default function ModelChoiceReasoner({ models }: ModelChoiceReasonerProps) {
    if (models.length === 0) return null;

    return (
        <div>
            <h4 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                Model selection
            </h4>
            <div className="space-y-1.5">
                {models.map((m) => (
                    <div
                        key={m.name}
                        className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs"
                    >
                        <div className="mb-1 flex flex-wrap items-center gap-1.5">
                            <span className="font-medium text-slate-200">{m.name}</span>
                            <span
                                className={`rounded-full px-2 py-0.5 text-[10px] ${!m.registered
                                        ? "bg-rose-500/10 text-rose-300"
                                        : m.loaded
                                            ? "bg-emerald-500/10 text-emerald-300"
                                            : "bg-white/10 text-slate-400"
                                    }`}
                            >
                                {!m.registered ? "not registered" : m.loaded ? "loaded" : "registered"}
                            </span>
                            {m.vram_gb != null && (
                                // Trimmed: a raw float renders as 3.9500000000000002.
                                <span className="text-[10px] text-slate-500">
                                    {Number(m.vram_gb.toFixed(2))} GB
                                </span>
                            )}
                            <span className="text-[10px] text-slate-500">
                                {m.version ?? "no version reported"}
                            </span>
                        </div>
                        <p className="text-[11px] text-slate-400">{m.selection_reason}</p>
                    </div>
                ))}
            </div>
        </div>
    );
}
