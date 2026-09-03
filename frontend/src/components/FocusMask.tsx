"use client";

interface FocusMaskProps {
    rect: { left: number; top: number; right: number; bottom: number } | null;
}

/**
 * Four blurred/dimmed bands framing the sharp raster rect, so the uploaded
 * extent reads as the focal point against the rest of the globe. Returns
 * null when idle (mirrors `CloudTransition`'s convention).
 *
 * Left/right bands run the full viewport height; top/bottom bands are
 * constrained to the rect's own left..right span and sit between them —
 * this keeps every band's edge locked exactly to the rect's outer pixels
 * with no double-covered corners (the previous full-width top/bottom
 * version could read as unevenly blurred along the right edge once it
 * overlapped the right band's region).
 */
export default function FocusMask({ rect }: FocusMaskProps) {
    if (!rect) return null;

    // Barely-there — just enough to read as "not the focus," not a fog.
    const bandClass = "fixed z-[5] pointer-events-none backdrop-blur-[0.7px] bg-slate-950/2";
    const rectWidth = rect.right - rect.left;

    return (
        <>
            <div className={bandClass} style={{ top: 0, bottom: 0, left: 0, width: rect.left }} />
            <div className={bandClass} style={{ top: 0, bottom: 0, left: rect.right, right: 0 }} />
            <div className={bandClass} style={{ top: 0, height: rect.top, left: rect.left, width: rectWidth }} />
            <div className={bandClass} style={{ top: rect.bottom, bottom: 0, left: rect.left, width: rectWidth }} />
        </>
    );
}
