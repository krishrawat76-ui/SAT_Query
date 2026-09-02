// Phase 2 demo camera anchors — hardcoded per turn order until the backend
// returns real geolocation metadata with each AnalysisResponse.

export interface MapTarget {
    center: [number, number];
    zoom: number;
    durationMs?: number;
}

export const MUMBAI: MapTarget = { center: [72.8777, 19.076], zoom: 14 };
export const WASHINGTON_DC: MapTarget = { center: [-77.0369, 38.8951], zoom: 14 };
export const LONDON: MapTarget = { center: [-0.1276, 51.5074], zoom: 14 };

/** Open Pacific, far from any island or coastline — a blank canvas start. */
export const OCEAN_START: MapTarget = { center: [-150.0, 5.0], zoom: 11 };

/** Establishing view shown before the first query is submitted. */
export const IDLE_VIEW: MapTarget = OCEAN_START;

const TURN_LOCATIONS: MapTarget[] = [MUMBAI, WASHINGTON_DC, LONDON];

/** Turns beyond the scripted demo trio keep recalling the last anchor (London). */
export function getTurnLocation(turnIndex: number): MapTarget {
    return TURN_LOCATIONS[Math.min(turnIndex, TURN_LOCATIONS.length - 1)];
}
