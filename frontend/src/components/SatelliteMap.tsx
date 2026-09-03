"use client";

import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { MapTarget } from "@/hooks/useMapCamera";

interface SatelliteMapProps {
    /** Only used for the very first render — all movement after mount is
     * driven imperatively via `onMapReady` + the `useMapCamera` hook. */
    initialTarget: MapTarget;
    onMapReady: (map: maplibregl.Map) => void;
}

// Esri World Imagery — free, keyless raster satellite basemap. Swap for the
// backend's tile source once `docs/` defines one.
const SATELLITE_STYLE: StyleSpecification = {
    version: 8,
    sources: {
        satellite: {
            type: "raster",
            tiles: [
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            ],
            tileSize: 256,
            attribution: "Esri, Maxar, Earthstar Geographics",
        },
    },
    layers: [{ id: "satellite", type: "raster", source: "satellite" }],
};

export default function SatelliteMap({ initialTarget, onMapReady }: SatelliteMapProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);

    useEffect(() => {
        if (!containerRef.current || mapRef.current) return;

        const map = new maplibregl.Map({
            container: containerRef.current,
            style: SATELLITE_STYLE,
            center: initialTarget.center,
            zoom: initialTarget.zoom,
            attributionControl: false,
        });

        // Camera stays strictly synced to chat scroll position — no manual control.
        map.dragPan.disable();
        map.scrollZoom.disable();
        map.boxZoom.disable();
        map.doubleClickZoom.disable();
        map.touchZoomRotate.disable();
        map.keyboard.disable();

        mapRef.current = map;
        map.once("load", () => onMapReady(map));

        return () => {
            map.remove();
            mapRef.current = null;
        };
        // Only ever runs once — the map is created a single time for the
        // component's lifetime; all subsequent camera control is imperative.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        // maplibre-gl.css ships `.maplibregl-map { position: relative }`, which
        // ties with Tailwind's `.fixed` at equal specificity — force it inline
        // so the map stays pinned to the viewport regardless of cascade order.
        <div
            ref={containerRef}
            className="z-0 h-screen w-screen"
            style={{ position: "fixed", inset: 0 }}
            aria-hidden="true"
        />
    );
}
