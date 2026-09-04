"use client";

import { ImageOff } from "lucide-react";
import { useTypewriter } from "@/hooks/useTypewriter";
import type { AnalysisResponse } from "@/types/api";

interface ResultPanelProps {
    result: AnalysisResponse | null;
    loading: boolean;
    error: string | null;
}

function confidenceTone(confidence: number): { label: string; classes: string } {
    if (confidence >= 0.8)
        return {
            label: "High confidence",
            classes: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
        };
    if (confidence >= 0.5)
        return {
            label: "Medium confidence",
            classes: "bg-amber-500/10 text-amber-300 border-amber-500/30",
        };
    return {
        label: "Low confidence",
        classes: "bg-rose-500/10 text-rose-300 border-rose-500/30",
    };
}

function Skeleton() {
    return (
        <div className="animate-pulse space-y-4">
            <div className="h-4 w-24 rounded-full bg-white/10" />
            <div className="space-y-2">
                <div className="h-3 w-full rounded-full bg-white/10" />
                <div className="h-3 w-11/12 rounded-full bg-white/10" />
                <div className="h-3 w-4/5 rounded-full bg-white/10" />
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2">
                <div className="aspect-video rounded-2xl bg-white/10" />
                <div className="aspect-video rounded-2xl bg-white/10" />
            </div>
        </div>
    );
}

export default function ResultPanel({ result, loading, error }: ResultPanelProps) {
    const typedAnswer = useTypewriter(result?.answer);

    return (
        <div className="rounded-2xl border border-white/10 bg-slate-900/70 p-5 shadow-2xl backdrop-blur-xl">
            <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-100">Result</h2>
                {result && (
                    result.confidence != null ? (
                        <span
                            className={`rounded-full border px-3 py-1 text-xs font-medium ${confidenceTone(result.confidence).classes
                                }`}
                        >
                            {Math.round(result.confidence * 100)}% ·{" "}
                            {confidenceTone(result.confidence).label}
                        </span>
                    ) : (
                        <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs font-medium text-slate-500">
                            Not scored
                        </span>
                    )
                )}
            </div>

            {loading && <Skeleton />}

            {!loading && error && (
                <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
                    {error}
                </div>
            )}

            {!loading && !error && !result && (
                <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-white/15 bg-white/[0.03] py-14 text-center">
                    <p className="text-sm text-slate-300">No analysis yet</p>
                    <p className="max-w-xs text-xs text-slate-500">
                        Upload imagery and ask a question to see the answer and evidence
                        here.
                    </p>
                </div>
            )}

            {!loading && !error && result && (
                <div className="space-y-5">
                    <p className="text-sm leading-relaxed text-slate-200">
                        {typedAnswer}
                    </p>

                    {result.evidence.images.length > 0 && (
                        <div>
                            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                                Evidence
                            </h3>
                            <div className="grid grid-cols-2 gap-3">
                                {result.evidence.images.map((img, i) => (
                                    <figure
                                        key={`${img.url}-${i}`}
                                        className="overflow-hidden rounded-2xl border border-white/10 bg-white/5"
                                    >
                                        <div className="aspect-video overflow-hidden bg-slate-800/60">
                                            {img.url ? (
                                                // eslint-disable-next-line @next/next/no-img-element
                                                <img
                                                    src={img.url}
                                                    alt={img.caption}
                                                    className="h-full w-full object-cover"
                                                />
                                            ) : (
                                                <div className="flex h-full w-full items-center justify-center text-slate-600">
                                                    <ImageOff className="h-5 w-5" />
                                                </div>
                                            )}
                                        </div>
                                        <figcaption className="px-3 py-2 text-[11px] text-slate-400">
                                            {img.caption}
                                        </figcaption>
                                    </figure>
                                ))}
                            </div>
                        </div>
                    )}

                    {result.evidence.regions.length > 0 && (
                        <div>
                            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                                Detected regions
                            </h3>
                            <div className="space-y-1.5">
                                {result.evidence.regions.map((region, i) => (
                                    <div
                                        key={`${region.label}-${i}`}
                                        className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs"
                                    >
                                        <span className="text-slate-300">{region.label}</span>
                                        <span className="text-slate-500">
                                            {Math.round(region.confidence * 100)}%
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
