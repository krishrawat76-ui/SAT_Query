const EARTH_RADIUS_KM = 6371;

/** Great-circle distance between two [lng, lat] points, in kilometers. */
export function haversineDistanceKm(a: [number, number], b: [number, number]): number {
    const [lng1, lat1] = a;
    const [lng2, lat2] = b;
    const toRad = (deg: number) => (deg * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);
    const h =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
    return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * How far out (map zoom) Phase 2 pulls back to, scaled by hop distance — a
 * cross-continent hop (Mumbai -> DC, ~12,700km) pulls back to a near-global
 * view, while a same-spot retry barely needs to zoom out at all.
 */
export function macroZoomForDistance(distanceKm: number): number {
    if (distanceKm < 50) return 6;
    const z = 6 - Math.log2(Math.max(distanceKm, 1) / 300);
    return Math.min(6, Math.max(1.5, z));
}

const BASE_FLIGHT_MS = 750;
const MAX_EXTRA_FLIGHT_MS = 1750;
const EPIC_DISTANCE_REFERENCE_KM = 13000; // ~ Mumbai -> Washington DC

/**
 * Total camera-switch duration, scaled by distance: short local shifts stay
 * brisk (~750ms), while a cross-continent hop like Mumbai -> DC stretches
 * toward ~2.5s. A small random jitter (±10%) keeps consecutive flights from
 * ever feeling mechanically identical.
 */
export function flightDurationForDistance(distanceKm: number): number {
    const t = Math.min(distanceKm / EPIC_DISTANCE_REFERENCE_KM, 1);
    const base = BASE_FLIGHT_MS + t * MAX_EXTRA_FLIGHT_MS;
    const jitter = 0.9 + Math.random() * 0.2;
    return Math.round(base * jitter);
}
