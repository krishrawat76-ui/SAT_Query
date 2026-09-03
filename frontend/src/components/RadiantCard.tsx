"use client";

import type { ReactNode } from "react";

interface RadiantCardProps {
    children: ReactNode;
    className?: string;
    /** How far the blur halo extends past the card's own edges, in px. */
    haloInset?: number;
    /** Suppresses the halo entirely (children still render) — for when a
     * nearby sibling already has its own overlapping halo (e.g. a popover
     * opening right above this card); two overlapping backdrop-blur halos
     * of different radii compound into a visibly blotchy, uneven blur
     * rather than one clean soft edge. */
    hideHalo?: boolean;
}

/**
 * Wraps a floating card with its own localized, edge-feathered blur halo —
 * a soft radial blur scoped tightly to just this card, instead of a global
 * full-width blur strip across the bottom of the screen. The halo is a
 * plain sibling positioned *before* the actual content in DOM order (both
 * inside this `relative` wrapper, both un-z-indexed) — that's what puts it
 * behind the card's own opaque glass surface while still letting it bleed
 * out past the card's rounded edges, feathered out via the radial mask.
 */
export default function RadiantCard({ children, className = "", haloInset = 32, hideHalo = false }: RadiantCardProps) {
    return (
        <div className={`relative ${className}`}>
            {!hideHalo && (
                <div
                    className="pointer-events-none absolute rounded-[3rem] backdrop-blur-2xl [mask-image:radial-gradient(closest-side,black_40%,transparent_100%)]"
                    style={{ inset: -haloInset }}
                />
            )}
            {children}
        </div>
    );
}
