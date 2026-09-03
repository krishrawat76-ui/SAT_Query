"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Reveals `text` progressively, one word at a time, instead of popping in
 * all at once — the backend is a single JSON response (not real token
 * streaming), so this simulates "text arriving as it's generated" purely
 * client-side once the full answer has already arrived.
 */
export function useTypewriter(text: string | null | undefined, wordsPerTick = 2, tickMs = 28): string {
    const [visibleWordCount, setVisibleWordCount] = useState(0);
    const wordsRef = useRef<string[]>([]);

    useEffect(() => {
        wordsRef.current = text ? text.split(/(\s+)/) : [];
        setVisibleWordCount(0);

        if (!text) return;

        const id = window.setInterval(() => {
            setVisibleWordCount((prev) => {
                const next = prev + wordsPerTick;
                if (next >= wordsRef.current.length) {
                    window.clearInterval(id);
                    return wordsRef.current.length;
                }
                return next;
            });
        }, tickMs);

        return () => window.clearInterval(id);
    }, [text, wordsPerTick, tickMs]);

    if (!text) return "";
    return wordsRef.current.slice(0, visibleWordCount).join("");
}
