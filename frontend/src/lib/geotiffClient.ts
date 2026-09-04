"use client";

// Client-side real GeoTIFF coordinate extraction — a fallback tier used only
// when POST /api/process-raster fails, so a genuinely georeferenced upload
// (e.g. a true-color Sentinel-2 L2A GeoTIFF) still lands the camera on its
// real location instead of a synthetic guess, even with the backend fully
// down. Mirrors the backend's own tag-reading + reprojection logic
// (backend/app/output/raster_stub.py) using `geotiff` + `proj4` in the
// browser — Sentinel-2 L2A products ship in a UTM projected CRS, not plain
// lat/lon, so reprojection (not just tag-reading) is the part that matters.
import proj4 from "proj4";

export interface ClientGeoTiffLocation {
    bbox: { north: number; south: number; east: number; west: number };
    center: [number, number];
    zoom: number;
}

function isTiffFilename(name: string): boolean {
    return /\.(tif|tiff|geotiff)$/i.test(name);
}

function zoomForLngSpan(lngSpan: number): number {
    const span = Math.max(lngSpan, 1e-6);
    const assumedViewportPx = 900;
    const paddingFactor = 2.5; // ~150% padding
    const targetPx = assumedViewportPx / paddingFactor;
    // MapLibre GL's zoom-to-pixel scale is defined relative to 512px base
    // tiles, not the classic 256px XYZ raster-tile convention — using 256
    // here renders everything exactly one zoom level too tight (2x too big
    // on screen). Mirrors backend/app/output/raster_stub.py::zoom_for_bbox
    // exactly, so both paths agree on the same bbox.
    const raw = Math.log2((360 * targetPx) / (span * 512));
    // Outer safety bounds only, not a target range — a real Sentinel-2 tile
    // (~100km) should correctly land around zoom 6-9 (zoomed out to fit the
    // whole extent); only degenerate/near-zero spans should ever hit the
    // ceiling, and nothing should be forced past a sane minimum world view.
    return Math.min(18, Math.max(2, raw));
}

/** UTM zones (EPSG 32601-32660 north, 32701-32760 south) computed directly
 * from the EPSG code — no network EPSG lookup needed. */
function utmDefName(epsg: number): string | null {
    let zone: number;
    let south: boolean;
    if (epsg >= 32601 && epsg <= 32660) {
        zone = epsg - 32600;
        south = false;
    } else if (epsg >= 32701 && epsg <= 32760) {
        zone = epsg - 32700;
        south = true;
    } else {
        return null;
    }
    const name = `EPSG:${epsg}`;
    if (!proj4.defs(name)) {
        proj4.defs(name, `+proj=utm +zone=${zone}${south ? " +south" : ""} +datum=WGS84 +units=m +no_defs`);
    }
    return name;
}

/**
 * Reads real georeferencing out of an uploaded GeoTIFF, entirely client-side.
 * Returns null for non-TIFF files, TIFFs with no geo keys, or a projected
 * CRS this can't resolve (WGS84 and UTM zones cover the common cases,
 * including every Sentinel-2 L2A product) — callers should fall back to a
 * synthetic location in that case.
 */
export async function extractGeoTiffLocation(file: File): Promise<ClientGeoTiffLocation | null> {
    if (!isTiffFilename(file.name)) return null;

    try {
        const { fromArrayBuffer } = await import("geotiff");
        const buffer = await file.arrayBuffer();
        const tiff = await fromArrayBuffer(buffer);
        const image = await tiff.getImage();
        const rawBbox = image.getBoundingBox(); // [west, south, east, north] in the native CRS
        const geoKeys = image.getGeoKeys();
        const epsg: number | undefined = geoKeys?.ProjectedCSTypeGeoKey ?? geoKeys?.GeographicTypeGeoKey;
        if (!epsg) return null;

        let west: number, south: number, east: number, north: number;

        if (epsg === 4326) {
            [west, south, east, north] = rawBbox;
        } else {
            const defName = utmDefName(epsg);
            if (!defName) return null;
            const [lon1, lat1] = proj4(defName, "WGS84", [rawBbox[0], rawBbox[1]]);
            const [lon2, lat2] = proj4(defName, "WGS84", [rawBbox[2], rawBbox[3]]);
            west = Math.min(lon1, lon2);
            east = Math.max(lon1, lon2);
            south = Math.min(lat1, lat2);
            north = Math.max(lat1, lat2);
        }

        if (![west, south, east, north].every(Number.isFinite)) return null;
        if (Math.abs(west) > 180 || Math.abs(east) > 180 || Math.abs(north) > 90 || Math.abs(south) > 90) return null;

        return {
            bbox: { north, south, east, west },
            center: [(east + west) / 2, (north + south) / 2],
            zoom: zoomForLngSpan(east - west),
        };
    } catch (e) {
        console.warn("extractGeoTiffLocation: failed to read GeoTIFF georeferencing", e);
        return null;
    }
}
