"use client";

import { motion, type PanInfo } from "framer-motion";
import type { LayerKey, RasterLayers } from "@/types/api";

interface LayerSwitcherProps {
    visible: boolean;
    active: LayerKey;
    onChange: (key: LayerKey) => void;
    /** The current turn's real layer URLs. A tab renders only when its key
     * has a genuine (non-null) value here — never guessed, never shown just
     * because the backend theoretically supports it. `null` (no raster at
     * all for this turn) renders nothing. */
    layers: RasterLayers | null;
}

const ALL_TABS: { key: LayerKey; label: string }[] = [
    { key: "base", label: "Base Map" },
    { key: "structural_changes", label: "Structural Changes" },
    { key: "spectral_bands", label: "Spectral Bands" },
];

/**
 * Floating glass tab switcher for the raster layers. Purely a paint-property
 * flip on the map (via `onChange` -> `useRasterOverlay.setActiveLayer`) —
 * never touches the camera, so switching tabs cannot retrigger a flight.
 *
 * Only `base` has a real URL today — `structural_changes`/`spectral_bands`
 * are `null` until a real model (TinyCD for change detection, a real
 * spectral pipeline) actually produces one. With fewer than 2 real tabs
 * there is nothing to switch between, so this renders nothing at all; the
 * day a second real layer shows up in the response, its tab appears here
 * automatically with no code change.
 *
 * Cycling by scroll lives on the map/mask area itself (see page.tsx's
 * hover-wheel zone over the focused raster rect) — this pill only handles
 * clicks and the swipe gesture, so scrolling over the taskbar itself does
 * nothing (no competing/duplicate scroll behavior between the two).
 */
export default function LayerSwitcher({ visible, active, onChange, layers }: LayerSwitcherProps) {
    if (!visible || !layers) return null;

    const tabs = ALL_TABS.filter((t) => !!layers[t.key]);
    if (tabs.length < 2) return null;

    const activeIndex = Math.max(0, tabs.findIndex((t) => t.key === active));
    const goToIndex = (index: number) => {
        const wrapped = ((index % tabs.length) + tabs.length) % tabs.length;
        if (tabs[wrapped].key !== active) onChange(tabs[wrapped].key);
    };

    // Swipe gesture — the pill snaps back to place (dragConstraints pins it
    // at 0,0); only the drag direction/distance decides whether it steps.
    const handleDragEnd = (_: unknown, info: PanInfo) => {
        const threshold = 40;
        if (info.offset.x <= -threshold) goToIndex(activeIndex + 1);
        else if (info.offset.x >= threshold) goToIndex(activeIndex - 1);
    };

    return (
        <div className="mb-2 flex justify-center px-4">
            {/* Drag lives on this outer, unstyled wrapper — a Chromium
                rendering bug makes backdrop-filter + border-radius fail to
                clip correctly on an element that also carries a CSS
                transform, which framer-motion applies while dragging.
                Keeping the rounded/blurred surface on a separate, static
                inner div avoids that. */}
            <motion.div
                drag="x"
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.15}
                onDragEnd={handleDragEnd}
            >
                <div className="flex gap-1.5 rounded-[22px] border border-white/10 bg-slate-900/60 p-1.5 shadow-2xl backdrop-blur-xl">
                    {tabs.map((tab) => (
                        <button
                            key={tab.key}
                            type="button"
                            onClick={() => onChange(tab.key)}
                            // Fixed, equal width for every tab — a squircle, not a
                            // pill — so tabs read as uniform equidistant tiles
                            // regardless of how long each label is.
                            className="relative flex h-9 w-[132px] items-center justify-center rounded-2xl text-xs font-medium text-slate-300 transition-colors"
                        >
                            {active === tab.key && (
                                <motion.div
                                    layoutId="activeLayerTab"
                                    className="absolute inset-0 rounded-2xl bg-slate-700/80"
                                    transition={{ type: "spring", stiffness: 400, damping: 32 }}
                                />
                            )}
                            <span className={`relative z-10 truncate px-2 ${active === tab.key ? "text-slate-100" : ""}`}>
                                {tab.label}
                            </span>
                        </button>
                    ))}
                </div>
            </motion.div>
        </div>
    );
}
