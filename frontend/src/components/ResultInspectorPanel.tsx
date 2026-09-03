"use client";

import { AnimatePresence, motion } from "framer-motion";
import ResultPanel from "./ResultPanel";
import ExecutionTrace from "./ExecutionTrace";
import MessageActions from "./MessageActions";
import type { ConversationTurn } from "@/types/api";

interface ResultInspectorPanelProps {
    /** The turn currently scrolled into view (`revealedTurnId` in page.tsx). */
    turn: ConversationTurn | null;
    retryDisabled: boolean;
    onRetry: (turnId: string) => void;
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
 * Deliberately a plain `overflow-y-auto` with no scroll-edge fade mask:
 * applying a CSS `mask-image` to an ancestor of elements using
 * `backdrop-filter` (every card here is `backdrop-blur-xl`) breaks the
 * browser's backdrop-filter compositing — the cards would render as solid,
 * opaque fills instead of the intended translucent glass the moment the
 * mask became active (i.e. exactly when scrolling made one active), which
 * is worse than the hard clip this trades it for. Always sharp/crisp — no
 * dimming or blur treatment tied to the input's own suggestion state.
 */
export default function ResultInspectorPanel({ turn, retryDisabled, onRetry }: ResultInspectorPanelProps) {
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
                        <div
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
