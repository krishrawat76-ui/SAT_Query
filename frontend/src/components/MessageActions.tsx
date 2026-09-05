"use client";

import { useState } from "react";
import { Check, Copy, RotateCw } from "lucide-react";

interface MessageActionsProps {
    text: string | null;
    onRetry: () => void;
    retryDisabled?: boolean;
}

export default function MessageActions({ text, onRetry, retryDisabled }: MessageActionsProps) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        if (!text) return;
        try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            // Clipboard permission denied — nothing actionable client-side.
        }
    };

    return (
        // Previously bare — icons floating with no surface of their own,
        // legible only against a dark enough patch of whatever satellite
        // imagery happened to be behind them. Same glass-card language as
        // the other panels above it (rounded-[28px], slate-900/70 +
        // backdrop-blur) so it reads as part of the same stack rather than
        // loose controls sitting directly on the map.
        <div className="flex w-fit items-center gap-1 rounded-[28px] border border-white/10 bg-slate-900/70 p-1 shadow-2xl backdrop-blur-xl">
            {text && (
                <button
                    type="button"
                    onClick={handleCopy}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-100"
                    aria-label="Copy response"
                    title="Copy response"
                >
                    {copied ? (
                        <Check className="h-3.5 w-3.5 text-emerald-400" />
                    ) : (
                        <Copy className="h-3.5 w-3.5" />
                    )}
                </button>
            )}
            <button
                type="button"
                onClick={onRetry}
                disabled={retryDisabled}
                className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Retry analysis"
                title="Retry analysis"
            >
                <RotateCw className="h-3.5 w-3.5" />
            </button>
        </div>
    );
}
