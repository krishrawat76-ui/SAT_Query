"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import ResultPanel from "./ResultPanel";
import ExecutionTrace from "./ExecutionTrace";
import DebugPanel from "./DebugPanel";
import MessageActions from "./MessageActions";
import type { ConversationTurn } from "@/types/api";

interface ResultInspectorPanelProps {
    /** The turn currently scrolled into view (`revealedTurnId` in page.tsx). */
    turn: ConversationTurn | null;
    retryDisabled: boolean;
    onRetry: (turnId: string) => void;
    /** Renders DebugPanel below ExecutionTrace when true and the turn has a
     * result. Off by default — see Sidebar.tsx's Debug Mode toggle. */
    debugMode: boolean;
}

// The panel sits vertically centered in the band between the top margin and
// the layer-switcher/chat-input cluster at the bottom (BOTTOM_CLEARANCE
// clears that cluster's own height plus its own bottom-6 margin) — never
// pinned to the top, never able to overlap the bar below it. Top margin is
// deliberately larger than the side margin so it reads as sitting clearly
// below the top edge, not flush to it.
const PANEL_TOP_MARGIN = 40;
export const PANEL_SIDE_MARGIN = 24;
const PANEL_BOTTOM_CLEARANCE = 200;
export const PANEL_WIDTH = 440;

/**
 * Floating right-side inspector for the active turn — deliberately not a
 * large centered card, so the map, the raster extent, and the focus mask
 * stay fully visible on the left. The query itself lives inside this same
 * scrollable stack (not a separately-pinned card) so the query, the result,
 * and the pipeline trace all move together as one unit. Vertically centered
 * in the band between the top margin and the layer-switcher/chat-input
 * cluster, and internally scrollable if content ever exceeds that band.
 *
 * The scrollable stack itself (`overflow-y-auto`) carries no `mask-image` —
 * putting one on an element that's an *ancestor* of `backdrop-blur-xl` cards
 * breaks the browser's backdrop-filter compositing (they'd render as solid,
 * opaque fills instead of translucent glass the moment the mask activates —
 * see `docs/CHANGELOG.md`'s rendering-bug-fixes section, where an earlier
 * version of this exact fade was removed for that reason). The top/bottom
 * fade below instead follows the same safe pattern already used for
 * `RadiantCard`'s halo and `QueryInput`'s popover blur: `mask-image` is
 * applied to a small standalone sibling layer that has no card descendants
 * of its own, so there's nothing for it to break.
 */
export default function ResultInspectorPanel({ turn, retryDisabled, onRetry, debugMode }: ResultInspectorPanelProps) {
    const scrollRef = useRef<HTMLDivElement>(null);
    const [canScrollUp, setCanScrollUp] = useState(false);
    const [canScrollDown, setCanScrollDown] = useState(false);

    // Tracks real scroll position so the fade (below) only shows on the edge
    // that actually has more content behind it — otherwise it permanently
    // softens the query pill's top edge and the retry-row's bottom edge even
    // when the whole stack fits with nothing to scroll to. A ResizeObserver
    // is needed alongside the scroll listener because expanding an
    // accordion inside the stack (ExecutionTrace, DebugPanel) changes
    // scrollHeight without firing a 'scroll' event.
    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;

        const update = () => {
            setCanScrollUp(el.scrollTop > 1);
            setCanScrollDown(el.scrollTop + el.clientHeight < el.scrollHeight - 1);
        };

        update();
        el.addEventListener("scroll", update);
        const observer = new ResizeObserver(update);
        observer.observe(el);
        return () => {
            el.removeEventListener("scroll", update);
            observer.disconnect();
        };
        // Re-run whenever the panel switches to a different turn — the
        // scrollable div is recreated (AnimatePresence keys on turn.id) and
        // debugMode changes the stack's total height.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [turn?.id, debugMode]);

    return (
        // Always pointer-events-none — this wrapper spans up to 440px wide
        // on the right at all times (even before any turn exists), so it
        // must never itself capture clicks/wheel; only the scrollable
        // content (below, once a turn exists) opts back in.
        <div
            className="pointer-events-none fixed z-30 flex items-center"
            style={{
                top: PANEL_TOP_MARGIN,
                bottom: PANEL_BOTTOM_CLEARANCE,
                right: PANEL_SIDE_MARGIN,
                width: PANEL_WIDTH,
                maxWidth: `calc(100vw - ${PANEL_SIDE_MARGIN * 2}px)`,
            }}
        >
            <AnimatePresence>
                {turn && (
                    <motion.div
                        key={turn.id}
                        initial={{ opacity: 0, y: 48 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 24 }}
                        transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        className="relative w-full"
                    >
                        {/* Progressive-blur scroll edges. Each is a standalone
                            layer with no children of its own — the mask-image
                            lives on the SAME element that carries the
                            backdrop-filter, never on an ancestor of the cards
                            underneath, which is what breaks compositing (see
                            the component doc comment above). Gated on real
                            scroll position (canScrollUp/canScrollDown) rather
                            than always rendered — otherwise it permanently
                            softens the query pill's top edge and the retry
                            row's bottom edge even when the whole stack fits
                            with nothing behind either edge to hide. */}
                        {canScrollUp && (
                            <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-10 rounded-t-[28px] backdrop-blur-md [mask-image:linear-gradient(to_bottom,black,transparent)]" />
                        )}
                        {canScrollDown && (
                            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-10 rounded-b-[28px] backdrop-blur-md [mask-image:linear-gradient(to_top,black,transparent)]" />
                        )}
                        <div
                            ref={scrollRef}
                            style={{
                                pointerEvents: "auto",
                                // Computed directly rather than a percentage —
                                // this div's ancestors are auto-height (so the
                                // stack can shrink-wrap and vertically center
                                // when the content is short), and percentages
                                // don't resolve against an auto-height parent.
                                maxHeight: `calc(100vh - ${PANEL_TOP_MARGIN}px - ${PANEL_BOTTOM_CLEARANCE}px)`,
                            }}
                            className="space-y-4 overflow-y-auto"
                        >
                            <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-2 shadow-2xl backdrop-blur-xl">
                                {turn.images.map((img) =>
                                    img.preview ? (
                                        // eslint-disable-next-line @next/next/no-img-element
                                        <img
                                            key={img.id}
                                            src={img.preview}
                                            alt={img.file.name}
                                            className="h-10 w-10 shrink-0 rounded-lg object-cover"
                                        />
                                    ) : null
                                )}
                                <span className="truncate text-sm font-medium text-white/90">{turn.query}</span>
                            </div>
                            <ResultPanel result={turn.result} loading={turn.loading} error={turn.error} />
                            <ExecutionTrace trace={turn.result?.execution_trace ?? null} />
                            {/* Also renders for a failed turn (result null, error
                                set) — a failure is exactly when this panel is
                                most worth having, and the request side is fully
                                known client-side even with no trace. */}
                            {debugMode && !turn.loading && (turn.result || turn.error) && (
                                <DebugPanel
                                    query={turn.query}
                                    imageNames={turn.images.map((img) => img.file.name)}
                                    modalities={turn.images.map((img) => img.modality)}
                                    result={turn.result}
                                    error={turn.error}
                                    debugRequested={turn.result?.execution_trace?.debug ?? false}
                                />
                            )}
                            {!turn.loading && (
                                <MessageActions
                                    text={turn.result?.answer ?? null}
                                    onRetry={() => onRetry(turn.id)}
                                    retryDisabled={retryDisabled}
                                />
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
