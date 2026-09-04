"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

interface RawPayloadViewerProps {
    label: string;
    data: unknown;
}

/** Collapsible raw-JSON viewer with a copy button — same clipboard pattern as
 * MessageActions.tsx. Used for both the constructed request summary and the
 * full parsed response, so the debug panel never invents a value the actual
 * request/response didn't contain. */
export default function RawPayloadViewer({ label, data }: RawPayloadViewerProps) {
    const [copied, setCopied] = useState(false);
    const copyTimerRef = useRef<number | null>(null);

    // Memoized: `page.tsx` updates `focusRect` on every rendered frame of any
    // camera flight, so an expanded panel would otherwise re-serialize a
    // potentially multi-hundred-KB debug response dozens of times per second
    // while the map is animating.
    const json = useMemo(() => {
        try {
            return JSON.stringify(data, null, 2);
        } catch {
            // `data` is typed `unknown`; a circular ref or BigInt would throw.
            // A debug viewer must never be the thing that breaks the page.
            return "// payload could not be serialized";
        }
    }, [data]);

    useEffect(() => {
        return () => {
            if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
        };
    }, []);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(json);
            setCopied(true);
            if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
            copyTimerRef.current = window.setTimeout(() => setCopied(false), 1500);
        } catch {
            // Clipboard permission denied — nothing actionable client-side.
        }
    };

    return (
        <div>
            <div className="mb-1.5 flex items-center justify-between">
                <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    {label}
                </h4>
                <button
                    type="button"
                    onClick={handleCopy}
                    className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-200"
                    aria-label={`Copy ${label.toLowerCase()}`}
                    title={`Copy ${label.toLowerCase()}`}
                >
                    {copied ? (
                        <Check className="h-3 w-3 text-emerald-400" />
                    ) : (
                        <Copy className="h-3 w-3" />
                    )}
                    {copied ? "Copied" : "Copy"}
                </button>
            </div>
            {/* tabIndex/role make the scroll region reachable without a mouse —
                this is the first scrollable non-interactive block in the app.
                overscroll-contain stops a wheel that bottoms out here from
                chaining to the inspector panel and jumping to another card.
                pre-wrap avoids a third nested scrollbar on long sanitized
                strings (the backend truncates them at 512 chars). */}
            {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex --
                a scrollable region must be keyboard-focusable to be operable
                without a mouse (WCAG 2.1.1); the lint rule doesn't model that. */}
            <pre
                tabIndex={0}
                aria-label={`${label} JSON`}
                className="max-h-64 overflow-auto overscroll-contain whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-black/30 p-3 text-[11px] leading-relaxed text-slate-300 outline-none focus-visible:border-white/25"
            >
                {json}
            </pre>
        </div>
    );
}
