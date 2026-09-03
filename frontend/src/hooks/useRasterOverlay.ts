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

// Hardcoded water-mask demo overlay — kept outside the generic LayerKey
// plumbing since it's a frontend-only stand-in (see lib/hardcodedMask.ts),
// not one of the three layers the backend actually returns.
const WATER_MASK_SOURCE_ID = "raster-water-mask";

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

/**
 * Network call to the Phase 3 raster stub, plus imperative MapLibre control
 * for the three stacked analysis layers it returns. Kept ref-based like
 * `useMapCamera` — layer visibility is a paint-property flip, never React
 * state, so tab switches never trigger a re-render of the map itself.
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
            const url = resolveUrl(layers[key]);
            const existingSource = map.getSource(sourceId) as maplibregl.ImageSource | undefined;

            if (existingSource) {
                existingSource.setCoordinates(coordinates);
                existingSource.updateImage({ url });
            } else {
                map.addSource(sourceId, { type: "image", url, coordinates });
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

    /** Adds/updates the three stacked raster layers and shows `active` on top. */
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

    /** Fades all three layers out (sources stay alive, cheap to bring back). */
    const hideRaster = () => {
        const map = mapRef.current;
        hideWaterMask();
        if (!map || !layersAddedRef.current) return;
        Object.values(LAYER_IDS).forEach((sourceId) => {
            if (!map.getLayer(sourceId)) return;
            map.setPaintProperty(sourceId, "raster-opacity", 0);
        });
    };

    /** Shows the hardcoded water-mask overlay on top of everything else —
     * it's a full repaint of the source image plus the mask, so it doesn't
     * need the other layers' opacities touched at all. */
    const showWaterMask = (bbox: RasterBBox, url: string) => {
        const map = mapRef.current;
        if (!map) return;
        const coordinates = boxCoordinates(bbox);
        const existing = map.getSource(WATER_MASK_SOURCE_ID) as maplibregl.ImageSource | undefined;
        if (existing) {
            existing.setCoordinates(coordinates);
            existing.updateImage({ url });
        } else {
            map.addSource(WATER_MASK_SOURCE_ID, { type: "image", url, coordinates });
            map.addLayer({
                id: WATER_MASK_SOURCE_ID,
                type: "raster",
                source: WATER_MASK_SOURCE_ID,
                paint: { "raster-opacity": 0, "raster-opacity-transition": { duration: 300 } },
            });
        }
        map.setPaintProperty(WATER_MASK_SOURCE_ID, "raster-opacity", 1);
    };

    const hideWaterMask = () => {
        const map = mapRef.current;
        if (!map || !map.getLayer(WATER_MASK_SOURCE_ID)) return;
        map.setPaintProperty(WATER_MASK_SOURCE_ID, "raster-opacity", 0);
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
        showWaterMask,
        hideWaterMask,
        resolveUrl,
    };
}
