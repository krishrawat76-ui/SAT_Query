"use client";

import { useRef } from "react";
import axios from "axios";
import * as maplibregl from "maplibre-gl";
import type { ProcessRasterResponse, RasterBBox, RasterLayers } from "@/types/api";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const BASE_SOURCE_ID = "raster-base";

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
 * Network call to the raster stub, plus imperative MapLibre control for the
 * uploaded image's base raster layer. Kept ref-based like `useMapCamera` —
 * visibility is a paint-property flip, never React state.
 *
 * There used to be three stacked layers here (base / structural_changes /
 * spectral_bands) with a tab switcher between them. The latter two were a
 * fixed image transform applied to any upload, with no real change-detection
 * or spectral model behind either — removed as fabricated data. Only the
 * real uploaded image (`base`) remains, so there is nothing left to switch
 * between.
 */
export function useRasterOverlay() {
    const mapRef = useRef<maplibregl.Map | null>(null);
    const layerAddedRef = useRef(false);

    const setMap = (map: maplibregl.Map) => {
        mapRef.current = map;
    };

    const processRaster = async (file: File): Promise<ProcessRasterResponse> => {
        const form = new FormData();
        form.append("image", file);
        const res = await axios.post(`${API}/api/process-raster`, form, { timeout: 60000 });
        return res.data as ProcessRasterResponse;
    };

    /** Adds/updates the base raster layer at full opacity. */
    const showRaster = (bbox: RasterBBox, layers: RasterLayers) => {
        const map = mapRef.current;
        if (!map) return;
        const coordinates = boxCoordinates(bbox);
        const url = resolveUrl(layers.base);
        const existingSource = map.getSource(BASE_SOURCE_ID) as maplibregl.ImageSource | undefined;

        if (existingSource) {
            existingSource.setCoordinates(coordinates);
            existingSource.updateImage({ url });
            map.setPaintProperty(BASE_SOURCE_ID, "raster-opacity", 1);
        } else {
            map.addSource(BASE_SOURCE_ID, { type: "image", url, coordinates });
            map.addLayer({
                id: BASE_SOURCE_ID,
                type: "raster",
                source: BASE_SOURCE_ID,
                paint: {
                    "raster-opacity": 1,
                    "raster-opacity-transition": { duration: 300 },
                },
            });
        }

        layerAddedRef.current = true;
    };

    /** Fades the layer out (source stays alive, cheap to bring back). */
    const hideRaster = () => {
        const map = mapRef.current;
        if (!map || !layerAddedRef.current || !map.getLayer(BASE_SOURCE_ID)) return;
        map.setPaintProperty(BASE_SOURCE_ID, "raster-opacity", 0);
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
        hideRaster,
        getScreenRect,
        resolveUrl,
    };
}
