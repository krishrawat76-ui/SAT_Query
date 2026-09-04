"use client";

import { motion, type PanInfo } from "framer-motion";
import type { LayerKey } from "@/types/api";

export type SwitcherKey = LayerKey;

interface LayerSwitcherProps {
    visible: boolean;
    active: SwitcherKey;
    onChange: (key: SwitcherKey) => void;
    /** Whether the turn has real backend-generated layer imagery — false
     * when running fully offline/without the backend. */
    hasBaseLayers?: boolean;
}

const BASE_TABS: { key: SwitcherKey; label: string }[] = [
    { key: "base", label: "Base Map" },
    { key: "structural_changes", label: "Structural Changes" },
    { key: "spectral_bands", label: "Spectral Bands" },
];

/**
 * Floating glass tab switcher for the raster layers. Purely a paint-property
 * flip on the map (via `onChange` -> `useRasterOverlay.setActiveLayer`) —
 * never touches the camera, so switching tabs cannot retrigger a flight.
 *
 * Cycling by scroll now lives on the map/mask area itself (see page.tsx's
 * hover-wheel zone over the focused raster rect) — this pill only handles
 * clicks and the swipe gesture, so scrolling over the taskbar itself does
 * nothing (no competing/duplicate scroll behavior between the two).
 */
export default function LayerSwitcher({ visible, active, onChange, hasBaseLayers }: LayerSwitcherProps) {
    if (!visible) return null;

    const tabs = hasBaseLayers ? BASE_TABS : [];
    if (tabs.length === 0) return null;

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
