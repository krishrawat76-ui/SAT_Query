"use client";

import { X, Image as ImageIcon, Clock } from "lucide-react";
import type { ChatSession } from "@/types/api";

interface LibraryDrawerProps {
    open: boolean;
    onClose: () => void;
    sessions: ChatSession[];
}

export default function LibraryDrawer({ open, onClose, sessions }: LibraryDrawerProps) {
    if (!open) return null;

    const entries = sessions.flatMap((session) =>
        session.turns.map((turn) => ({ session, turn }))
    );

    return (
        <>
            <div
                className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
                onClick={onClose}
                aria-hidden="true"
            />
            <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-white/10 bg-slate-950/80 shadow-2xl backdrop-blur-xl">
                <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
                    <h2 className="text-sm font-medium text-slate-100">Library</h2>
                    <button
                        type="button"
                        onClick={onClose}
                        className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-100"
                        aria-label="Close library"
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto px-5 py-4">
                    {entries.length === 0 && (
                        <p className="pt-10 text-center text-sm text-slate-500">
                            Saved prompts, snapshots, and execution logs will appear here once you
                            run an analysis.
                        </p>
                    )}

                    <div className="space-y-3">
                        {entries.map(({ session, turn }) => (
                            <div
                                key={turn.id}
                                className="rounded-3xl border border-white/12 bg-white/5 p-4"
                            >
                                <div className="mb-2 flex items-center justify-between gap-2">
                                    <span className="truncate text-xs font-medium uppercase tracking-wide text-slate-500">
                                        {session.title}
                                    </span>
                                    <span className="flex shrink-0 items-center gap-1 text-[11px] text-slate-500">
                                        <Clock className="h-3 w-3" />
                                        {new Date(turn.createdAt).toLocaleTimeString([], {
                                            hour: "2-digit",
                                            minute: "2-digit",
                                        })}
                                    </span>
                                </div>

                                <p className="text-sm text-slate-200">{turn.query}</p>

                                {turn.images.length > 0 && (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                        {turn.images.map((img) => (
                                            <div
                                                key={img.id}
                                                className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg border border-white/15 bg-slate-800/60"
                                            >
                                                {img.preview ? (
                                                    // eslint-disable-next-line @next/next/no-img-element
                                                    <img
                                                        src={img.preview}
                                                        alt={img.file.name}
                                                        className="h-full w-full object-cover"
                                                    />
                                                ) : (
                                                    <ImageIcon className="h-4 w-4 text-slate-500" />
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {turn.result && (
                                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                                        <span className="rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-slate-200">
                                            {turn.result.execution_trace.detected_task.replace(/_/g, " ")}
                                        </span>
                                        <span className="text-[11px] text-slate-500">
                                            {turn.result.confidence != null &&
                                                `${Math.round(turn.result.confidence * 100)}% confidence · `}
                                            {turn.result.execution_trace.total_time_ms.toFixed(0)}ms
                                        </span>
                                    </div>
                                )}

                                {turn.error && !turn.result && (
                                    <p className="mt-2 text-[11px] text-rose-400">{turn.error}</p>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </>
    );
}
