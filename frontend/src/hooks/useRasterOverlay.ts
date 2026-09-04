"use client";

import { useRef } from "react";
import axios from "axios";
import * as maplibregl from "maplibre-gl";
import type { LayerKey, ProcessRasterResponse, RasterBBox, RasterLayers } from "@/types/api";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const LAYER_IDS: Record<LayerKey, string> = {
    base: "raster-base",
    structural_changes: "raster-structural",
    spectral_bands: "raster-spectral",
};

function boxCoordinates(
    bbox: RasterBBox
): [[number, number], [number, number], [number, number], [number, number]] {
    return [
        [bbox.west, bbox.north],
        [bbox.east, bbox.north],
        [bbox.east, bbox.south],
        [bbox.west, bbox.south],
    ];
}

function resolveUrl(path: string): string {
    return path.startsWith("http") ? path : `${API}${path}`;
}

/** Layer keys that actually have a real URL for this turn — everything else
 * is `null` until a real model produces it (see `RasterLayers` in
 * types/api.ts). Shared by `page.tsx` (wheel-cycle order) and
 * `LayerSwitcher` (which tabs to render). */
export function availableLayerKeys(layers: RasterLayers): LayerKey[] {
    return (Object.keys(LAYER_IDS) as LayerKey[]).filter((key) => !!layers[key]);
}

/**
 * Network call to the raster stub, plus imperative MapLibre control for the
 * stacked analysis layers it returns. Kept ref-based like `useMapCamera` —
 * layer visibility is a paint-property flip, never React state, so tab
 * switches never trigger a re-render of the map itself.
 *
 * Only `base` is guaranteed to have a real URL today — `structural_changes`/
 * `spectral_bands` are `null` until a real model (TinyCD, a spectral
 * pipeline) actually produces one. `ensureLayers` skips adding a source for
 * any layer that's null, and hides a previous turn's leftover layer if the
 * current turn doesn't have one at that key.
 */
export function useRasterOverlay() {
    const mapRef = useRef<maplibregl.Map | null>(null);
    const layersAddedRef = useRef(false);

    const setMap = (map: maplibregl.Map) => {
        mapRef.current = map;
    };

    const processRaster = async (file: File): Promise<ProcessRasterResponse> => {
        const form = new FormData();
        form.append("image", file);
        const res = await axios.post(`${API}/api/process-raster`, form, { timeout: 60000 });
        return res.data as ProcessRasterResponse;
    };

    const ensureLayers = (bbox: RasterBBox, layers: RasterLayers, active: LayerKey) => {
        const map = mapRef.current;
        if (!map) return;
        const coordinates = boxCoordinates(bbox);

        (Object.keys(LAYER_IDS) as LayerKey[]).forEach((key) => {
            const sourceId = LAYER_IDS[key];
            const url = layers[key];

            if (!url) {
                // Not available for this turn — if a previous turn's source
                // is still sitting there, hide it rather than leaving it
                // visible on top of the new turn's imagery.
                if (map.getLayer(sourceId)) {
                    map.setPaintProperty(sourceId, "raster-opacity", 0);
                }
                return;
            }

            const resolved = resolveUrl(url);
            const existingSource = map.getSource(sourceId) as maplibregl.ImageSource | undefined;

            if (existingSource) {
                existingSource.setCoordinates(coordinates);
                existingSource.updateImage({ url: resolved });
            } else {
                map.addSource(sourceId, { type: "image", url: resolved, coordinates });
                map.addLayer({
                    id: sourceId,
                    type: "raster",
                    source: sourceId,
                    paint: {
                        "raster-opacity": key === active ? 1 : 0,
                        "raster-opacity-transition": { duration: 300 },
                    },
                });
            }
        });

        layersAddedRef.current = true;
    };

    /** Adds/updates whichever layers this turn actually has and shows `active` on top. */
    const showRaster = (bbox: RasterBBox, layers: RasterLayers, active: LayerKey = "base") => {
        ensureLayers(bbox, layers, active);
        setActiveLayer(active);
    };

    /** Crossfades to `active` via MapLibre's own opacity transition — no camera movement. */
    const setActiveLayer = (active: LayerKey) => {
        const map = mapRef.current;
        if (!map || !layersAddedRef.current) return;
        (Object.keys(LAYER_IDS) as LayerKey[]).forEach((key) => {
            const sourceId = LAYER_IDS[key];
            if (!map.getLayer(sourceId)) return;
            map.setPaintProperty(sourceId, "raster-opacity", key === active ? 1 : 0);
        });
    };

    /** Fades all layers out (sources stay alive, cheap to bring back). */
    const hideRaster = () => {
        const map = mapRef.current;
        if (!map || !layersAddedRef.current) return;
        Object.values(LAYER_IDS).forEach((sourceId) => {
            if (!map.getLayer(sourceId)) return;
            map.setPaintProperty(sourceId, "raster-opacity", 0);
        });
    };

    /** Screen-space bounding rect of the bbox's 4 corners, for the focus mask. */
    const getScreenRect = (
        bbox: RasterBBox
    ): { left: number; top: number; right: number; bottom: number } | null => {
        const map = mapRef.current;
        if (!map) return null;
        const corners = boxCoordinates(bbox).map((c) => map.project(c));
        const xs = corners.map((p) => p.x);
        const ys = corners.map((p) => p.y);
        return {
            left: Math.min(...xs),
            right: Math.max(...xs),
            top: Math.min(...ys),
            bottom: Math.max(...ys),
        };
    };

    return {
        setMap,
        processRaster,
        showRaster,
        setActiveLayer,
        hideRaster,
        getScreenRect,
        resolveUrl,
    };
}
