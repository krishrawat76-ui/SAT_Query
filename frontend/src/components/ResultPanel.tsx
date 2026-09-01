"use client";

import { ImageOff } from "lucide-react";
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
            classes: "bg-emerald-50 text-emerald-700 border-emerald-200/80",
        };
    if (confidence >= 0.5)
        return {
            label: "Medium confidence",
            classes: "bg-amber-50 text-amber-700 border-amber-200/80",
        };
    return {
        label: "Low confidence",
        classes: "bg-rose-50 text-rose-700 border-rose-200/80",
    };
}

function Skeleton() {
    return (
        <div className="animate-pulse space-y-4">
            <div className="h-4 w-24 rounded-full bg-slate-100" />
            <div className="space-y-2">
                <div className="h-3 w-full rounded-full bg-slate-100" />
                <div className="h-3 w-11/12 rounded-full bg-slate-100" />
                <div className="h-3 w-4/5 rounded-full bg-slate-100" />
            </div>
            <div className="grid grid-cols-2 gap-3 pt-2">
                <div className="aspect-video rounded-2xl bg-slate-100" />
                <div className="aspect-video rounded-2xl bg-slate-100" />
            </div>
        </div>
    );
}

export default function ResultPanel({ result, loading, error }: ResultPanelProps) {
    return (
        <div className="rounded-3xl border border-slate-200/80 bg-white p-6 shadow-md">
            <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-medium text-slate-900">Result</h2>
                {result && (
                    <span
                        className={`rounded-full border px-3 py-1 text-xs font-medium ${confidenceTone(result.confidence).classes
                            }`}
                    >
                        {Math.round(result.confidence * 100)}% ·{" "}
                        {confidenceTone(result.confidence).label}
                    </span>
                )}
            </div>

            {loading && <Skeleton />}

            {!loading && error && (
                <div className="rounded-2xl border border-rose-200/80 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {error}
                </div>
            )}

            {!loading && !error && !result && (
                <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 py-14 text-center">
                    <p className="text-sm text-slate-500">No analysis yet</p>
                    <p className="max-w-xs text-xs text-slate-400">
                        Upload imagery and ask a question to see the answer and evidence
                        here.
                    </p>
                </div>
            )}

            {!loading && !error && result && (
                <div className="space-y-5">
                    <p className="text-sm leading-relaxed text-slate-800">
                        {result.answer}
                    </p>

                    {result.evidence.images.length > 0 && (
                        <div>
                            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">
                                Evidence
                            </h3>
                            <div className="grid grid-cols-2 gap-3">
                                {result.evidence.images.map((img, i) => (
                                    <figure
                                        key={`${img.url}-${i}`}
                                        className="overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-50"
                                    >
                                        <div className="aspect-video overflow-hidden bg-slate-100">
                                            {img.url ? (
                                                // eslint-disable-next-line @next/next/no-img-element
                                                <img
                                                    src={img.url}
                                                    alt={img.caption}
                                                    className="h-full w-full object-cover"
                                                />
                                            ) : (
                                                <div className="flex h-full w-full items-center justify-center text-slate-300">
                                                    <ImageOff className="h-5 w-5" />
                                                </div>
                                            )}
                                        </div>
                                        <figcaption className="px-3 py-2 text-[11px] text-slate-500">
                                            {img.caption}
                                        </figcaption>
                                    </figure>
                                ))}
                            </div>
                        </div>
                    )}

                    {result.evidence.regions.length > 0 && (
                        <div>
                            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">
                                Detected regions
                            </h3>
                            <div className="space-y-1.5">
                                {result.evidence.regions.map((region, i) => (
                                    <div
                                        key={`${region.label}-${i}`}
                                        className="flex items-center justify-between rounded-xl border border-slate-200/80 bg-slate-50/60 px-3 py-2 text-xs"
                                    >
                                        <span className="text-slate-700">{region.label}</span>
                                        <span className="text-slate-400">
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