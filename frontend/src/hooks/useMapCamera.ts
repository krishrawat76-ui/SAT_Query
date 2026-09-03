"use client";

import { useRef } from "react";
import * as maplibregl from "maplibre-gl";
import { flightDurationForDistance, haversineDistanceKm, macroZoomForDistance } from "@/lib/flightPlan";

export interface MapTarget {
    center: [number, number];
    zoom: number;
    durationMs?: number;
}

/** CSS-pixel clearance to leave around a `fitBounds` target on each edge —
 * so pinned UI chrome (the query card near the top, the input bar/layer
 * switcher at the bottom) never overlaps the framed raster extent. */
export interface FramePadding {
    top: number;
    bottom: number;
    left: number;
    right: number;
}

type LngLatBounds = [[number, number], [number, number]];

const PIN_COLOR = "#ef4444";

// Chained easeTo calls each restart their own t=0->1 progression, so mixing
// easing shapes (quadratic-in here, linear there) leaves a velocity
// discontinuity at every phase boundary — the eye reads that as a jitter or
// stutter each time a new phase kicks in. Using the same ease-in-out curve
// for every intermediate phase means each one decelerates to ~0 velocity
// right as the next begins, so the chain reads as one continuous glide.
const SMOOTH_EASE = (t: number): number => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/**
 * Imperative camera controller for the satellite map. Centralizing control
 * here (instead of driving the camera reactively off React state) is what
 * makes cancellation deterministic: every new flight calls `map.stop()` and
 * bumps a flight id, so a stale, still-pending phase from a superseded
 * transition can never fire and fight the current one for the camera
 * (the "ping-pong / dual-location confusion" bug).
 */
export function useMapCamera() {
    const mapRef = useRef<maplibregl.Map | null>(null);
    const markerRef = useRef<maplibregl.Marker | null>(null);
    const flightIdRef = useRef(0);
    const timeoutsRef = useRef<number[]>([]);

    const setMap = (map: maplibregl.Map) => {
        mapRef.current = map;
    };

    const updateMarker = (center: [number, number] | null) => {
        const map = mapRef.current;
        if (!map) return;
        if (!center) {
            markerRef.current?.remove();
            markerRef.current = null;
            return;
        }
        if (markerRef.current) {
            markerRef.current.setLngLat(center);
        } else {
            markerRef.current = new maplibregl.Marker({ color: PIN_COLOR }).setLngLat(center).addTo(map);
        }
    };

    /**
     * Immediately halts any in-progress animation and invalidates every
     * pending phase callback from a previous flight. This is the single
     * choke point that guarantees two flights never fight over the camera —
     * call it before reading the map's position or starting a new sequence.
     */
    const cancelFlight = () => {
        flightIdRef.current += 1;
        timeoutsRef.current.forEach((id) => clearTimeout(id));
        timeoutsRef.current = [];
        mapRef.current?.stop();
    };

    /**
     * The map's true current position, read live right after `cancelFlight()`
     * so it reflects wherever the camera actually stopped rather than a
     * stale "intended" target — this is the deterministic `startCoords` lock.
     */
    const getCurrentPosition = (): { center: [number, number]; zoom: number } => {
        const map = mapRef.current;
        if (!map) return { center: [0, 0], zoom: 2 };
        const c = map.getCenter();
        return { center: [c.lng, c.lat], zoom: map.getZoom() };
    };

    /** Single-leg move — used for the ocean reset and scroll-driven recall. */
    const flyToSimple = (target: MapTarget, options?: { showMarker?: boolean }) => {
        const map = mapRef.current;
        if (!map) return;
        cancelFlight();
        map.flyTo({
            center: target.center,
            zoom: target.zoom,
            duration: target.durationMs ?? 1200,
            essential: true,
        });
        updateMarker(options?.showMarker === false ? null : target.center);
    };

    /** Same role as `flyToSimple`, but frames a raster's real bbox with
     * `fitBounds` instead of a plain center/zoom — used for scroll-driven
     * recall of a turn that has raster data, so revisiting it lands on
     * exactly the same UI-aware framing as the initial cinematic flight. */
    const flyToBoundsSimple = (bounds: LngLatBounds, padding: FramePadding, durationMs = 900) => {
        const map = mapRef.current;
        if (!map) return;
        cancelFlight();
        map.fitBounds(bounds, { padding, duration: durationMs, essential: true });
        const center: [number, number] = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
        updateMarker(center);
    };

    /**
     * 5 equal-duration phases: source breakout -> macro ascent -> high-
     * altitude traversal (tiles stay sharp — no blur) -> approach descent ->
     * precision zoom-in lock. `startCoords`/`startZoom` must be captured by
     * the caller via `getCurrentPosition()` immediately after `cancelFlight()`.
     */
    const runFivePhaseFlight = (
        startCoords: [number, number],
        startZoom: number,
        targetCoords: [number, number],
        targetZoom: number,
        onComplete?: () => void,
        targetBounds?: LngLatBounds,
        padding?: FramePadding
    ) => {
        const map = mapRef.current;
        if (!map) return;

        const myFlightId = flightIdRef.current;
        const isCurrent = () => flightIdRef.current === myFlightId;

        const distanceKm = haversineDistanceKm(startCoords, targetCoords);
        const totalMs = flightDurationForDistance(distanceKm);
        const phaseMs = totalMs / 5;
        const macroZoom = macroZoomForDistance(distanceKm);
        // Phase 1 covers 25% of the zoom-out delta toward macroZoom; Phase 2
        // finishes the remaining 75% down to macroZoom exactly.
        const breakoutZoom = startZoom - 0.25 * (startZoom - macroZoom);
        // Phase 4 covers half the descent from macroZoom to the target zoom;
        // Phase 5 finishes the rest with a precision snap.
        const approachZoom = macroZoom + (targetZoom - macroZoom) * 0.5;

        updateMarker(targetCoords);

        // Phase 1 — source breakout: smooth acceleration zoom-out.
        map.easeTo({
            center: startCoords,
            zoom: breakoutZoom,
            duration: phaseMs,
            easing: SMOOTH_EASE,
        });

        const t1 = window.setTimeout(() => {
            if (!isCurrent()) return;
            // Phase 2 — macro ascent to the distance-scaled high-altitude vantage.
            map.easeTo({
                center: startCoords,
                zoom: macroZoom,
                duration: phaseMs,
                easing: SMOOTH_EASE,
            });

            const t2 = window.setTimeout(() => {
                if (!isCurrent()) return;
                // Phase 3 — high-altitude globe traversal: pure pan, zoom held
                // constant, tiles stay completely sharp (no blur of any kind).
                map.easeTo({
                    center: targetCoords,
                    zoom: macroZoom,
                    duration: phaseMs,
                    easing: SMOOTH_EASE,
                });

                const t3 = window.setTimeout(() => {
                    if (!isCurrent()) return;
                    // Phase 4 — approach descent, halfway down to the target zoom.
                    map.easeTo({
                        center: targetCoords,
                        zoom: approachZoom,
                        duration: phaseMs,
                        easing: SMOOTH_EASE,
                    });

                    const t4 = window.setTimeout(() => {
                        if (!isCurrent()) return;
                        // Phase 5 — precision lock. With a real bbox, fitBounds
                        // frames the raster's true extent with UI-aware padding
                        // (letting MapLibre compute the exact zoom itself, sidestepping
                        // any manual zoom-formula error); otherwise a plain
                        // center/zoom flyTo (e.g. the ocean reset, which has
                        // no bbox to fit).
                        const snapEasing = (t: number) => 1 - Math.pow(1 - t, 3);
                        if (targetBounds && padding) {
                            map.fitBounds(targetBounds, {
                                padding,
                                duration: phaseMs,
                                essential: true,
                                easing: snapEasing,
                            });
                        } else {
                            map.flyTo({
                                center: targetCoords,
                                zoom: targetZoom,
                                duration: phaseMs,
                                essential: true,
                                easing: snapEasing,
                            });
                        }

                        const t5 = window.setTimeout(() => {
                            if (isCurrent()) onComplete?.();
                        }, phaseMs);
                        timeoutsRef.current.push(t5);
                    }, phaseMs);
                    timeoutsRef.current.push(t4);
                }, phaseMs);
                timeoutsRef.current.push(t3);
            }, phaseMs);
            timeoutsRef.current.push(t2);
        }, phaseMs);
        timeoutsRef.current.push(t1);
    };

    return { setMap, cancelFlight, getCurrentPosition, flyToSimple, flyToBoundsSimple, runFivePhaseFlight };
}
