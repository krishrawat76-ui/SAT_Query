"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { ConversationTurn } from "@/types/api";

interface PinnedQueryCardProps {
    /** The currently active turn (`activeTurnId` in page.tsx) — this is the
     * same state that already updates exactly on turn navigation (up/down
     * arrows) and on the active landing section changing via the scroll
     * IntersectionObserver, so no separate "unpin" logic is needed here:
     * the card's content simply follows whichever turn is currently active. */
    turn: ConversationTurn | null;
    rect: { left: number; top: number; right: number; bottom: number } | null;
    /** Width (px) of the docked sidebar — centers the card within the
     * remaining workspace (not the full viewport), matching QueryInput's
     * own `left: sidebarWidth; right: 0` convention. */
    sidebarWidthPx: number;
    /** True once this same turn's result section has been scrolled into
     * view — the query is now shown inside ResultInspectorPanel's own
     * scrollable stack instead (so the query, result, and pipeline trace
     * all scroll together as one unit), so this card exits rather than
     * repositioning itself. */
    hidden: boolean;
}

/**
 * A pinned header showing the active turn's query, centered over the map
 * during the "landing" stage. Lives outside the scrolling chat feed
 * entirely — `position: fixed` (not CSS `sticky`) is what actually makes
 * "stay put while following a JS-computed, map-derived position" work,
 * since sticky only tracks scroll offset within its own container, not
 * arbitrary state.
 */
export default function PinnedQueryCard({ turn, rect, sidebarWidthPx, hidden }: PinnedQueryCardProps) {
    const top = rect ? Math.max(16, rect.top - 60) : 24;
    const visibleTurn = hidden ? null : turn;

    return (
        // Always pointer-events-none — this wrapper spans the full width of
        // the workspace so it can center its content, but must never itself
        // capture clicks/wheel; only the actual pill (below) opts back in.
        <div
            className="pointer-events-none fixed z-30"
            style={{ top, left: sidebarWidthPx, right: 0 }}
        >
            <div className="flex justify-center px-4">
                <AnimatePresence mode="popLayout">
                    {visibleTurn && (
                        // The layout/scale/y animation lives on this outer,
                        // unstyled wrapper — a Chromium rendering bug makes
                        // backdrop-filter + border-radius + overflow fail to
                        // clip correctly on an element that also carries a
                        // CSS transform, which framer-motion applies here.
                        // Keeping the rounded/blurred surface on a separate,
                        // static inner div avoids that.
                        <motion.div
                            key={visibleTurn.id}
                            layout
                            initial={{ opacity: 0, y: 220, scale: 0.7 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{ opacity: 0, y: -10, scale: 0.95 }}
                            transition={{ type: "spring", stiffness: 280, damping: 30 }}
                        >
                            <div className="relative flex max-w-xl items-center gap-2 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-2 shadow-2xl backdrop-blur-xl">
                                {visibleTurn.images.map((img) =>
                                    // No thumbnail wrapper at all when there's no preview
                                    // (e.g. a GeoTIFF the browser can't render) — an empty
                                    // bordered box reads as a broken image, not "no image."
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
                                <span className="truncate text-sm font-medium text-white/90">{visibleTurn.query}</span>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </div>
    );
}
