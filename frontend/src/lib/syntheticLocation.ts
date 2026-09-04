// Final fallback tier when a turn has an image but no real location could be
// found: POST /api/process-raster failed (backend unreachable) AND the file
// wasn't a georeferenced GeoTIFF geotiffClient.ts could read (see
// resolveRasterLocation in page.tsx). Mirrors the backend's own synthetic-
// bbox logic (backend/app/output/raster_stub.py) — a location derived from
// the actual uploaded file, not a scripted per-turn sequence. Without this,
// the camera would have nowhere to go and the flight would silently never
// start, which read as "transitions are broken."
import type { ProcessRasterResponse } from "@/types/api";

const ANCHORS: [number, number][] = [
    [72.8777, 19.076],   // Mumbai
    [-77.0369, 38.8951], // Washington DC
    [-0.1276, 51.5074],  // London
];

function stableHash(key: string): number {
    let h = 0;
    for (let i = 0; i < key.length; i++) {
        h = (Math.imul(31, h) + key.charCodeAt(i)) | 0;
    }
    return Math.abs(h);
}

/**
 * A deterministic (per-file) location + bbox, with no real analysis layers
 * (the backend never ran, so there's nothing to overlay) — just enough for
 * the camera to have somewhere real to fly to. `layers.base` is left empty
 * so callers know to skip the raster overlay/focus mask/layer switcher.
 */
export function syntheticRasterFallback(file: File): ProcessRasterResponse {
    const h = stableHash(`${file.name}:${file.size}`);

    const [anchorLng, anchorLat] = ANCHORS[h % ANCHORS.length];
    const jitterLng = (((h >>> 3) % 1000) / 1000 - 0.5) * 0.2;
    const jitterLat = (((h >>> 7) % 1000) / 1000 - 0.5) * 0.2;
    const centerLng = anchorLng + jitterLng;
    const centerLat = anchorLat + jitterLat;

    const halfDeg = 0.03;

    return {
        bbox: {
            north: centerLat + halfDeg,
            south: centerLat - halfDeg,
            east: centerLng + halfDeg,
            west: centerLng - halfDeg,
        },
        center: [centerLng, centerLat],
        zoom: 15,
        layers: { base: "", structural_changes: null, spectral_bands: null },
        source: "synthetic",
    };
}
