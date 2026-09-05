"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import Sidebar from "@/components/Sidebar";
import QueryInput from "@/components/QueryInput";
import ResultInspectorPanel from "@/components/ResultInspectorPanel";
import LibraryDrawer from "@/components/LibraryDrawer";
import SatelliteMap from "@/components/SatelliteMap";
import CloudTransition, { type CloudPhase } from "@/components/CloudTransition";
import FocusMask from "@/components/FocusMask";
import PinnedQueryCard from "@/components/PinnedQueryCard";
import { useAnalysis } from "@/hooks/useAnalysis";
import { useMapCamera, type MapTarget, type FramePadding } from "@/hooks/useMapCamera";
import { useRasterOverlay, availableLayerKeys } from "@/hooks/useRasterOverlay";
import { syntheticRasterFallback } from "@/lib/syntheticLocation";
import { extractGeoTiffLocation } from "@/lib/geotiffClient";
import type { ChatSession, ConversationTurn, LayerKey, ProcessRasterResponse, RasterBBox, UploadedImage } from "@/types/api";

const SIDEBAR_EXPANDED_WIDTH = 288;
const SIDEBAR_COLLAPSED_WIDTH = 72;

// Open-ocean establishing view shown before any turn has a real location —
// the original Phase 2 idle/"New chat" view.
const IDLE_OCEAN_VIEW: MapTarget = { center: [-150.0, 5.0], zoom: 11 };

function boundsFromBbox(bbox: RasterBBox): [[number, number], [number, number]] {
  return [
    [bbox.west, bbox.south],
    [bbox.east, bbox.north],
  ];
}

// ResultInspectorPanel's fixed footprint (`right-6` + `w-[440px]`, see
// ResultInspectorPanel.tsx) plus a little breathing room — kept in the right
// padding below so the raster frame clears it too, not just the bottom bar.
const RESULT_PANEL_CLEARANCE_PX = 24 + 440 + 36;

// Two framing profiles for the same raster bbox, matched to which section of
// the turn is in view: "landing" is the first stage the camera settles on
// (roughly centered — nothing but the pinned query card above it yet), and
// "result" is a quick re-fit that shifts the frame left once the user
// scrolls down, clearing room for the ResultInspectorPanel on the right.
// `sidebarWidthPx` extends the left margin so framing isn't pushed under
// the docked sidebar.
function landingFramePadding(sidebarWidthPx: number): FramePadding {
  return { top: 120, bottom: 180, left: 60 + sidebarWidthPx, right: 60 };
}
function resultFramePadding(sidebarWidthPx: number): FramePadding {
  return { top: 120, bottom: 180, left: 60 + sidebarWidthPx, right: RESULT_PANEL_CLEARANCE_PX };
}

function createSession(): ChatSession {
  return {
    id: `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: "New chat",
    turns: [],
    createdAt: Date.now(),
  };
}

export default function Home() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => [createSession()]);
  const [activeSessionId, setActiveSessionId] = useState<string>(() => sessions[0].id);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  // Debug Mode — surfaces real router/model telemetry per turn (see
  // DebugPanel.tsx). Persisted across reloads like a normal app setting.
  //
  // Deliberately initialized to `false` and hydrated from localStorage in an
  // effect, NOT in a lazy useState initializer: this is a client component
  // but Next still prerenders it on the server, where the initializer would
  // return false while the client's hydration render returned true. That
  // mismatch reaches the DOM (Sidebar's Debug button renders a different
  // className and aria-pressed), and React 19 responds by discarding the
  // whole SSR tree and client-rendering the root. Reading after mount keeps
  // the first client render identical to the server's.
  const [debugMode, setDebugMode] = useState(false);
  useEffect(() => {
    try {
      if (window.localStorage.getItem("satquery.debug") === "true") {
        setDebugMode(true);
      }
    } catch {
      // Storage unavailable (private browsing, blocked cookies) — Debug Mode
      // still works for this session, it just won't persist.
    }
  }, []);

  const handleToggleDebugMode = () => {
    const next = !debugMode;
    setDebugMode(next);
    try {
      window.localStorage.setItem("satquery.debug", String(next));
    } catch {
      // Storage disabled — debug mode still works for this session.
    }
  };

  const [draftQuery, setDraftQuery] = useState("");
  const [draftImages, setDraftImages] = useState<UploadedImage[]>([]);
  const pendingTurnRef = useRef<{ sessionId: string; turnId: string } | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const landingElementsRef = useRef<Map<string, HTMLDivElement>>(new Map());
  const resultElementsRef = useRef<Map<string, HTMLDivElement>>(new Map());

  const camera = useMapCamera();
  const rasterOverlay = useRasterOverlay();
  const [cloudPhase, setCloudPhase] = useState<CloudPhase>("idle");
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [revealedTurnId, setRevealedTurnId] = useState<string | null>(null);
  // The currently-framed turn's raster payload — null when there's nothing
  // to show (text-only turn, or a synthetic/client-only fallback location
  // with no imagery at all). Read by the layer switcher to know which of
  // its tabs actually have a real URL for this turn.
  const [activeRaster, setActiveRaster] = useState<ProcessRasterResponse | null>(null);
  const [activeLayerKey, setActiveLayerKey] = useState<LayerKey>("base");
  const [focusRect, setFocusRect] = useState<{ left: number; top: number; right: number; bottom: number } | null>(null);
  const isTransitioningRef = useRef(false);
  const activeMapTurnIdRef = useRef<string | null>(null);
  // Which fitBounds padding profile the camera is currently framed with —
  // "landing" (centered, first stage) vs "result" (shifted left to clear
  // the ResultInspectorPanel). Tracked separately from activeMapTurnIdRef
  // since the stage can change (scrolling landing<->result) without the
  // active turn itself changing.
  const framedStageRef = useRef<"landing" | "result" | null>(null);
  const cloudTimeoutsRef = useRef<number[]>([]);
  const preFlightDelayRef = useRef<number | null>(null);
  // Per-turn raster data, read imperatively at flight-completion/recall time
  // so the camera system never waits on a React re-render to know about it.
  // A turn with no entry here is either text-only or its raster call hasn't
  // resolved yet — either way, the camera never moves for it.
  const turnRasterDataRef = useRef<Map<string, ProcessRasterResponse>>(new Map());

  const { analyze, result, loading, error } = useAnalysis();

  const sidebarWidthPx = sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH;

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? sessions[0];
  const activeTurnIndex = activeSession?.turns.findIndex((t) => t.id === activeTurnId) ?? -1;
  const canGoUp = activeTurnIndex > 0;
  const canGoDown =
    activeTurnIndex !== -1 && activeTurnIndex < (activeSession?.turns.length ?? 0) - 1;

  // Attribute the (single-shot) hook's async state to whichever turn triggered it.
  useEffect(() => {
    const pending = pendingTurnRef.current;
    if (!pending) return;

    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== pending.sessionId) return s;
        return {
          ...s,
          turns: s.turns.map((t) =>
            t.id === pending.turnId
              ? { ...t, loading, result: result ?? t.result, error: error ?? null }
              : t
          ),
        };
      })
    );

    if (!loading && (result || error)) {
      pendingTurnRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, error, loading]);

  // Land on the newly-created turn's arrival section first — the result stays
  // hidden until the user scrolls further down into it (see the observer below).
  useEffect(() => {
    const last = activeSession?.turns.at(-1);
    if (!last) return;
    landingElementsRef.current.get(last.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [activeSession?.id, activeSession?.turns.length]);

  // Clear any in-flight cloud/camera-sequence timers on unmount.
  useEffect(() => {
    return () => {
      cloudTimeoutsRef.current.forEach((id) => clearTimeout(id));
      if (preFlightDelayRef.current) clearTimeout(preFlightDelayRef.current);
      camera.cancelFlight();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Shows a turn's raster overlay on the map and (re)computes the focus-mask
  // screen rect. `recomputeDelayMs` accounts for an in-flight camera move —
  // the geographic bbox is unchanged, but its screen-space projection is
  // only valid once the camera actually lands there.
  const showRasterForTurn = (turnId: string, raster: ProcessRasterResponse, recomputeDelayMs = 0) => {
    const hasBase = !!raster.layers.base;

    // Nothing real to show at all — no backend imagery for this turn (e.g.
    // a synthetic/client-only fallback location with no generated layers).
    if (!hasBase) {
      setActiveRaster(null);
      setFocusRect(null);
      return;
    }

    rasterOverlay.showRaster(raster.bbox, raster.layers, "base");
    setActiveRaster(raster);
    setActiveLayerKey("base");

    if (recomputeDelayMs > 0) {
      window.setTimeout(() => {
        if (activeMapTurnIdRef.current === turnId) {
          setFocusRect(rasterOverlay.getScreenRect(raster.bbox));
        }
      }, recomputeDelayMs);
    } else {
      setFocusRect(rasterOverlay.getScreenRect(raster.bbox));
    }
  };

  // Whichever layer tabs actually exist right now, in display order — the
  // same computation LayerSwitcher does internally, needed here too so
  // wheel-cycling (below) can step through exactly the visible tabs. Only
  // real (non-null) layer URLs count — a layer a real model hasn't produced
  // yet is never included, so cycling never lands on nothing.
  const availableSwitcherTabs = (): LayerKey[] =>
    activeRaster ? availableLayerKeys(activeRaster.layers) : [];

  const handleActiveLayerChange = (key: LayerKey) => {
    setActiveLayerKey(key);
    rasterOverlay.setActiveLayer(key);
  };

  // Scrolling while hovering over the focused raster/mask area cycles
  // through its available layers — the taskbar itself no longer has its own
  // wheel handler (see LayerSwitcher.tsx), so this is the only place scroll
  // drives layer switching now. A trackpad swipe fires many wheel events
  // (not just one), so without a cooldown a single gesture would race
  // through several layers at once — this locks to one step per gesture,
  // then briefly ignores further deltas until the gesture has clearly ended.
  const wheelCooldownRef = useRef(false);
  const cycleActiveLayerFromWheel = (deltaY: number) => {
    if (wheelCooldownRef.current) return;
    const tabs = availableSwitcherTabs();
    if (tabs.length < 2) return;
    const currentIndex = Math.max(0, tabs.indexOf(activeLayerKey));
    const nextIndex = ((currentIndex + (deltaY > 0 ? 1 : -1)) % tabs.length + tabs.length) % tabs.length;
    if (tabs[nextIndex] === activeLayerKey) return;
    handleActiveLayerChange(tabs[nextIndex]);
    wheelCooldownRef.current = true;
    window.setTimeout(() => {
      wheelCooldownRef.current = false;
    }, 700);
  };

  // Settles all the non-camera bookkeeping for a turn that has no location —
  // a text-only query, or one whose raster stub call failed. The camera is
  // deliberately left untouched: no panning when there's nothing to pan to.
  const settleOnTextOnlyTurn = (turnId: string) => {
    cloudTimeoutsRef.current.forEach((id) => clearTimeout(id));
    cloudTimeoutsRef.current = [];
    if (preFlightDelayRef.current) {
      clearTimeout(preFlightDelayRef.current);
      preFlightDelayRef.current = null;
    }
    isTransitioningRef.current = false;
    activeMapTurnIdRef.current = turnId;
    framedStageRef.current = null;
    setActiveTurnId(turnId);
    setRevealedTurnId(null);
    setCloudPhase("idle");
    rasterOverlay.hideRaster();
    setActiveRaster(null);
    setFocusRect(null);
  };

  // Map-first camera recall: settle the camera on whichever turn's arrival
  // section is in view. Only turns with real raster-derived coordinates move
  // the camera — a text-only turn just hides any prior overlay in place.
  // `stage` matters because scrolling *backward* through turns reaches a
  // turn's "result" section before its "landing" section (DOM order per turn
  // is landing-then-result, so going up from turn N you land on turn N-1's
  // result next) — without this, that turn would only ever get framed once
  // you scrolled one snap-step further to its landing section, leaving the
  // map stuck showing the previous turn's raster while the panel already
  // shows this turn's result.
  const recallCamera = (turnId: string, stage: "landing" | "result" = "landing") => {
    if (isTransitioningRef.current) return;
    if (activeMapTurnIdRef.current === turnId) {
      // Already the active turn on the map — just make sure it's framed for
      // the stage being scrolled into.
      reframeForStage(turnId, stage);
      return;
    }

    activeMapTurnIdRef.current = turnId;
    setActiveTurnId(turnId);
    setRevealedTurnId(stage === "result" ? turnId : null);

    const raster = turnRasterDataRef.current.get(turnId);
    if (raster) {
      const padding = stage === "landing" ? landingFramePadding(sidebarWidthPx) : resultFramePadding(sidebarWidthPx);
      camera.flyToBoundsSimple(boundsFromBbox(raster.bbox), padding, 900);
      framedStageRef.current = stage;
      showRasterForTurn(turnId, raster, 900);
    } else {
      framedStageRef.current = null;
      rasterOverlay.hideRaster();
      setActiveRaster(null);
      setFocusRect(null);
    }
  };

  // Quick re-fit between the "landing" (centered) and "result" (shifted left
  // to clear the ResultInspectorPanel) framing profiles for the SAME turn —
  // used when the user scrolls between a turn's own landing/result sections,
  // as opposed to recallCamera's full switch to a different turn entirely.
  const reframeForStage = (turnId: string, stage: "landing" | "result") => {
    if (framedStageRef.current === stage) return;
    const raster = turnRasterDataRef.current.get(turnId);
    if (!raster) return;
    const padding = stage === "landing" ? landingFramePadding(sidebarWidthPx) : resultFramePadding(sidebarWidthPx);
    const durationMs = 700;
    camera.flyToBoundsSimple(boundsFromBbox(raster.bbox), padding, durationMs);
    framedStageRef.current = stage;
    window.setTimeout(() => {
      if (activeMapTurnIdRef.current === turnId) setFocusRect(rasterOverlay.getScreenRect(raster.bbox));
    }, durationMs);
  };

  // Both padding profiles above are sidebar-width-aware — without this, an
  // already-framed rect would go stale (no longer actually centered/offset
  // correctly) the moment the sidebar collapses or expands, since nothing
  // else would trigger a re-fit. Re-fits at whatever stage is currently
  // framed, for the currently active turn only.
  useEffect(() => {
    const turnId = activeMapTurnIdRef.current;
    const stage = framedStageRef.current;
    if (!turnId || !stage) return;
    const raster = turnRasterDataRef.current.get(turnId);
    if (!raster) return;
    const padding = stage === "landing" ? landingFramePadding(sidebarWidthPx) : resultFramePadding(sidebarWidthPx);
    // Matches Sidebar.tsx's own `duration-300` width transition exactly —
    // previously this ran 500ms against a 300ms sidebar animation, so the
    // map (and everything derived from focusRect, like the nav arrow) kept
    // visibly sliding for 200ms after the sidebar had already stopped,
    // reading as two disjointed phases of motion instead of one.
    const durationMs = 300;
    camera.flyToBoundsSimple(boundsFromBbox(raster.bbox), padding, durationMs);
    window.setTimeout(() => {
      if (activeMapTurnIdRef.current === turnId) setFocusRect(rasterOverlay.getScreenRect(raster.bbox));
    }, durationMs);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidebarWidthPx]);

  // Scroll-driven behavior: the "landing" section recalls the camera (framed
  // centered, the first stage); the "result" section (reached only by
  // scrolling further down) reveals the card and re-frames left to clear
  // room for it.
  useEffect(() => {
    const root = scrollContainerRef.current;
    if (!root || !activeSession) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const el = entry.target as HTMLElement;
          const turnId = el.dataset.turnId;
          const section = el.dataset.section;
          if (!turnId) continue;
          if (!activeSession.turns.some((t) => t.id === turnId)) continue;

          if (section === "landing") {
            if (isTransitioningRef.current) continue;
            if (activeMapTurnIdRef.current === turnId) {
              // Scrolled back up from this same turn's result section —
              // retract the panel too, not just the camera framing, so the
              // whole "first stage" presentation comes back together.
              setRevealedTurnId((prev) => (prev === turnId ? null : prev));
              reframeForStage(turnId, "landing");
            } else {
              recallCamera(turnId);
            }
          } else if (section === "result") {
            if (isTransitioningRef.current) continue;
            setRevealedTurnId(turnId);
            // Scrolling backward can reach a turn's result section directly,
            // before its own landing section — recallCamera handles both the
            // "already active, just reframe" and "switch to a different
            // turn, framed straight for result" cases.
            recallCamera(turnId, "result");
          }
        }
      },
      { root, threshold: 0.5 }
    );

    landingElementsRef.current.forEach((el) => observer.observe(el));
    resultElementsRef.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession, activeSession?.turns.length]);

  const jumpToTurn = (turnIndex: number) => {
    const target = activeSession?.turns[turnIndex];
    if (!target) return;
    landingElementsRef.current.get(target.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    recallCamera(target.id);
    // The smooth scroll above passes through whatever sections sit between
    // here and the target — e.g. jumping forward crosses the CURRENT
    // turn's own "result" section along the way — and each one crossing
    // the 0.5 intersection threshold would otherwise fire the scroll
    // observer mid-transit, redirecting the camera to THAT section's turn
    // instead of the one actually requested. isTransitioningRef is exactly
    // the guard the observer already checks for this; jumpToTurn just
    // wasn't setting it, so this race was live on every arrow click. It's
    // set *after* the recallCamera call above (not before) since
    // recallCamera has this same guard at its own top — setting it first
    // would make that direct call a no-op too.
    isTransitioningRef.current = true;
    window.setTimeout(() => {
      isTransitioningRef.current = false;
    }, 700);
  };

  // Quick smoke puff masks only the very start of the switch — the flight
  // itself (the hook's 5-phase sequence) runs fully visible and sharp,
  // landing directly on the target with no result card yet. Only ever called
  // for a turn with real raster-derived coordinates.
  const runCloudFlight = (raster: ProcessRasterResponse, turnId: string) => {
    cloudTimeoutsRef.current.forEach((id) => clearTimeout(id));
    cloudTimeoutsRef.current = [];
    isTransitioningRef.current = true;
    activeMapTurnIdRef.current = turnId;
    setActiveTurnId(turnId);
    setRevealedTurnId(null);

    // Lock the starting vector: stop whatever the camera was doing, then
    // read its true resting position — never a possibly-stale React value.
    camera.cancelFlight();
    const { center: startCoords, zoom: startZoom } = camera.getCurrentPosition();

    // Hide whatever the previous turn was showing for the duration of the
    // flight — it re-appears (for this turn) on arrival.
    rasterOverlay.hideRaster();
    setActiveRaster(null);
    setFocusRect(null);

    const coverMs = 300;
    const clearMs = 900;

    setCloudPhase("covering");
    // Phase 5 fits the raster's real bbox with UI-aware padding via
    // fitBounds — `raster.center`/`raster.zoom` still drive the earlier
    // breakout/ascent/traversal/approach phases. Lands framed in the
    // centered "landing" stage — the result panel isn't shown yet, so
    // there's no need to shift left for it until the user actually scrolls
    // down (see reframeForStage).
    camera.runFivePhaseFlight(
      startCoords,
      startZoom,
      raster.center,
      raster.zoom,
      () => {
        isTransitioningRef.current = false;
        const latest = turnRasterDataRef.current.get(turnId);
        if (latest) showRasterForTurn(turnId, latest);
      },
      boundsFromBbox(raster.bbox),
      landingFramePadding(sidebarWidthPx)
    );
    framedStageRef.current = "landing";

    const clearTimer = window.setTimeout(() => setCloudPhase("clearing"), coverMs);
    const idleTimer = window.setTimeout(() => setCloudPhase("idle"), coverMs + clearMs);
    cloudTimeoutsRef.current.push(clearTimer, idleTimer);
  };

  // Simulates a brief AI routing/processing beat before the camera commits to
  // a destination — 60-300ms, randomized per call so it never feels canned.
  // Only called once a turn's raster data has actually resolved, so the
  // target coordinates are guaranteed to exist by the time this fires.
  const scheduleCameraFlight = (turnId: string) => {
    if (preFlightDelayRef.current) clearTimeout(preFlightDelayRef.current);
    const delay = Math.floor(Math.random() * 240) + 60;
    preFlightDelayRef.current = window.setTimeout(() => {
      preFlightDelayRef.current = null;
      const raster = turnRasterDataRef.current.get(turnId);
      if (!raster) return;
      runCloudFlight(raster, turnId);
    }, delay);
  };

  // Fires the Phase 3 raster stub for a turn's first attached image, then
  // kicks off the cinematic flight once real coordinates are known. If the
  // stub call fails (e.g. the backend isn't running), the flight still needs
  // somewhere to go — an image was attached, so this isn't a text-only turn
  // and the camera shouldn't just sit frozen. A synthetic, file-derived
  // location (no scripted per-turn city, no generated layer imagery) keeps
  // the choreography working offline; it upgrades to the real thing the
  // moment the backend responds to a later turn.
  const applyRasterData = (sessionId: string, turnId: string, data: ProcessRasterResponse) => {
    turnRasterDataRef.current.set(turnId, data);
    setSessions((prev) =>
      prev.map((s) =>
        s.id === sessionId
          ? { ...s, turns: s.turns.map((t) => (t.id === turnId ? { ...t, raster: data } : t)) }
          : s
      )
    );
    scheduleCameraFlight(turnId);
  };

  // Resolves a location for the turn's first image, trying three tiers in
  // order: the real backend stub (also returns generated layer imagery) ->
  // real client-side GeoTIFF tag extraction (no imagery, but a genuine
  // location — works fully offline, including UTM-projected products like
  // Sentinel-2 L2A) -> a synthetic per-file guess as the last resort.
  const resolveRasterLocation = async (file: File): Promise<ProcessRasterResponse> => {
    try {
      return await rasterOverlay.processRaster(file);
    } catch {
      const real = await extractGeoTiffLocation(file);
      if (real) {
        return {
          bbox: real.bbox,
          center: real.center,
          zoom: real.zoom,
          layers: { base: "", structural_changes: null, spectral_bands: null },
          source: "geotiff-tags",
        };
      }
      return syntheticRasterFallback(file);
    }
  };

  const fetchRasterAndFly = async (sessionId: string, turnId: string, images: UploadedImage[]) => {
    const data = await resolveRasterLocation(images[0].file);
    applyRasterData(sessionId, turnId, data);
  };

  // Drops all pending camera/cloud state and returns to the open-ocean idle
  // view — used when starting a brand new chat or switching to an empty one.
  const resetToOceanView = () => {
    cloudTimeoutsRef.current.forEach((id) => clearTimeout(id));
    cloudTimeoutsRef.current = [];
    if (preFlightDelayRef.current) {
      clearTimeout(preFlightDelayRef.current);
      preFlightDelayRef.current = null;
    }
    isTransitioningRef.current = false;
    activeMapTurnIdRef.current = null;
    framedStageRef.current = null;
    setActiveTurnId(null);
    setRevealedTurnId(null);
    setCloudPhase("idle");
    camera.flyToSimple(IDLE_OCEAN_VIEW, { showMarker: false });
    rasterOverlay.hideRaster();
    setActiveRaster(null);
    setFocusRect(null);
  };

  const handleNewChat = () => {
    const session = createSession();
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(session.id);
    setDraftQuery("");
    setDraftImages([]);
    resetToOceanView();
  };

  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setDraftQuery("");
    setDraftImages([]);

    const target = sessions.find((s) => s.id === id);
    if (!target || target.turns.length === 0) {
      // Fresh/empty chat — always land back on the open-ocean idle view,
      // never stuck on whatever coordinates the previous chat left behind.
      resetToOceanView();
      return;
    }

    if (preFlightDelayRef.current) {
      clearTimeout(preFlightDelayRef.current);
      preFlightDelayRef.current = null;
    }
    const lastTurn = target.turns[target.turns.length - 1];
    const raster = turnRasterDataRef.current.get(lastTurn.id);
    if (raster) {
      // Same standardized camera switch used for submissions/retries —
      // runCloudFlight's own cancelFlight() guarantees this never fights an
      // in-progress flight from the chat just left.
      runCloudFlight(raster, lastTurn.id);
    } else {
      settleOnTextOnlyTurn(lastTurn.id);
    }
  };

  const handlePinSession = (id: string) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, pinned: !s.pinned } : s)));
  };

  const handleRenameSession = (id: string, title: string) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
  };

  const handleDeleteSession = (id: string) => {
    const remaining = sessions.filter((s) => s.id !== id);
    const nextSessions = remaining.length > 0 ? remaining : [createSession()];
    setSessions(nextSessions);
    if (activeSessionId === id) {
      setActiveSessionId(nextSessions[0].id);
      setDraftQuery("");
      setDraftImages([]);
    }
  };

  const handleSubmit = () => {
    if (!draftQuery.trim() || loading || !activeSession) return;

    const turn: ConversationTurn = {
      id: `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      query: draftQuery.trim(),
      images: draftImages,
      result: null,
      loading: true,
      error: null,
      createdAt: Date.now(),
      raster: null,
    };

    pendingTurnRef.current = { sessionId: activeSession.id, turnId: turn.id };

    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeSession.id
          ? {
            ...s,
            title: s.turns.length === 0 ? turn.query.slice(0, 48) : s.title,
            turns: [...s.turns, turn],
          }
          : s
      )
    );

    const files = draftImages.map((img) => img.file);
    const modalities = draftImages.map((img) => img.modality);
    analyze(files, turn.query, modalities, debugMode);

    if (draftImages.length > 0) {
      fetchRasterAndFly(activeSession.id, turn.id, draftImages);
    } else {
      settleOnTextOnlyTurn(turn.id);
    }

    setDraftQuery("");
    setDraftImages([]);
  };

  const handleRetry = (turnId: string) => {
    if (loading || !activeSession) return;
    const turnIndex = activeSession.turns.findIndex((t) => t.id === turnId);
    if (turnIndex === -1) return;
    const turn = activeSession.turns[turnIndex];

    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeSession.id
          ? {
            ...s,
            turns: s.turns.map((t) =>
              t.id === turnId ? { ...t, loading: true, result: null, error: null, raster: null } : t
            ),
          }
          : s
      )
    );

    pendingTurnRef.current = { sessionId: activeSession.id, turnId };

    const files = turn.images.map((img) => img.file);
    const modalities = turn.images.map((img) => img.modality);
    analyze(files, turn.query, modalities, debugMode);

    landingElementsRef.current.get(turnId)?.scrollIntoView({ behavior: "smooth", block: "start" });

    if (turn.images.length > 0) {
      fetchRasterAndFly(activeSession.id, turnId, turn.images);
    } else {
      settleOnTextOnlyTurn(turnId);
    }
  };

  return (
    <div className="relative flex h-full w-full select-none overflow-hidden bg-slate-950">
      <SatelliteMap
        initialTarget={IDLE_OCEAN_VIEW}
        onMapReady={(map) => {
          camera.setMap(map);
          rasterOverlay.setMap(map);
          // Keeps focusRect (and everything derived from it — the focus
          // mask, the wheel-cycle zone, the nav-arrow rail) tracking the
          // map continuously during ANY camera movement, not just updated
          // once a flight finishes. Previously that single end-of-flight
          // update was the only thing moving these elements, which read as
          // a sudden, disconnected jump rather than a fluid reaction to the
          // map actually moving — 'move' fires on every rendered frame of
          // any pan/zoom/flyTo, so this makes them ride along in real time.
          map.on("move", () => {
            const turnId = activeMapTurnIdRef.current;
            if (!turnId) return;
            const raster = turnRasterDataRef.current.get(turnId);
            if (!raster) return;
            setFocusRect(rasterOverlay.getScreenRect(raster.bbox));
          });
        }}
      />
      <CloudTransition phase={cloudPhase} />
      <FocusMask rect={focusRect} />
      {focusRect && availableSwitcherTabs().length >= 2 && (
        // Sits above the scrolling feed (z-10) so hovering the sharp raster
        // area captures the wheel event for layer-cycling instead of the
        // page scrolling underneath it. Only mounted when there are 2+ real
        // tabs to cycle through — otherwise there's nothing to capture for.
        <div
          className="fixed z-20"
          style={{
            left: focusRect.left,
            top: focusRect.top,
            width: focusRect.right - focusRect.left,
            height: focusRect.bottom - focusRect.top,
          }}
          onWheel={(e) => cycleActiveLayerFromWheel(e.deltaY)}
        />
      )}
      <PinnedQueryCard
        turn={activeSession?.turns.find((t) => t.id === activeTurnId) ?? null}
        rect={focusRect}
        sidebarWidthPx={sidebarWidthPx}
        hidden={revealedTurnId !== null && revealedTurnId === activeTurnId}
      />
      <ResultInspectorPanel
        turn={activeSession?.turns.find((t) => t.id === revealedTurnId) ?? null}
        retryDisabled={loading}
        onRetry={handleRetry}
        debugMode={debugMode}
      />

      <div className="relative z-30 flex h-full">
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSession?.id ?? null}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          onNewChat={handleNewChat}
          onSelectSession={handleSelectSession}
          onPinSession={handlePinSession}
          onRenameSession={handleRenameSession}
          onDeleteSession={handleDeleteSession}
          onOpenLibrary={() => setLibraryOpen(true)}
          debugMode={debugMode}
          onToggleDebugMode={handleToggleDebugMode}
        />
      </div>

      <div className="relative z-10 flex h-full min-w-0 flex-1 flex-col">
        <main
          ref={scrollContainerRef}
          className="flex-1 snap-y snap-mandatory overflow-y-auto scroll-smooth px-6"
        >
          {(!activeSession || activeSession.turns.length === 0) && (
            <div className="flex h-full min-h-full snap-start flex-col items-center justify-center gap-2 text-center">
              <h1 className="text-3xl font-medium text-slate-100">
                Ready when you are.
              </h1>
              <p className="text-base text-slate-400">
                Ask a question, optionally with satellite imagery, to begin.
              </p>
            </div>
          )}

          {activeSession?.turns.map((turn) => {
            return (
              <Fragment key={turn.id}>
                {/* Landing section — camera arrives here first; just the prompt. */}
                <div
                  data-turn-id={turn.id}
                  data-section="landing"
                  ref={(el) => {
                    if (el) landingElementsRef.current.set(turn.id, el);
                    else landingElementsRef.current.delete(turn.id);
                  }}
                  className="flex h-full min-h-full snap-start flex-col items-center justify-end pb-20"
                >
                  {/* The query card itself is rendered separately as a
                      pinned overlay (PinnedQueryCard) — this section stays
                      as the scroll-snap anchor + landing cue. */}
                  <div className="mx-auto flex w-full max-w-3xl justify-center pt-6">
                    <ChevronDown className="h-5 w-5 animate-bounce text-slate-300/70" />
                  </div>
                </div>

                {/* Result section — reached only by scrolling further; reveals
                    ResultInspectorPanel (a floating side panel, rendered once
                    at the top level) rather than an in-flow card, so the map
                    stays visible. This section is now just the scroll-snap
                    anchor + reveal trigger. */}
                <div
                  data-turn-id={turn.id}
                  data-section="result"
                  ref={(el) => {
                    if (el) resultElementsRef.current.set(turn.id, el);
                    else resultElementsRef.current.delete(turn.id);
                  }}
                  className="h-full min-h-full snap-start"
                />
              </Fragment>
            );
          })}
        </main>
      </div>

      {activeSession && activeSession.turns.length > 1 && (canGoUp || canGoDown) && (() => {
        // Docked a fixed, small offset outside the map's own left edge —
        // equidistant-with-the-sidebar looked right only by coincidence in
        // the "result" stage (where the map sits close to the sidebar
        // anyway); in the "landing" stage the map is framed more centered,
        // so that same math left the arrow floating far from the map,
        // reading as disconnected from it. Hugging the map directly reads
        // right in both stages. Vertically centered on the map's own rect
        // (not the screen).
        //
        // No CSS transition here on purpose — `focusRect` now updates on
        // every 'move' event during a flight (see onMapReady above), so
        // this position already moves in many small real steps in sync
        // with the map itself. Adding a transition on top would make each
        // of those per-frame updates kick off its own brief animation,
        // which queues up faster than they can finish and reads as a
        // laggy, rubber-banding chase instead of the map's own smooth
        // motion. Falls back to a fixed offset from the sidebar's own edge
        // when there's no mask at all (e.g. a text-only turn) — anchored on
        // the SAME left side as the focusRect position above, not the right
        // (previously it jumped all the way over to hug the ResultInspectorPanel,
        // reading as an arbitrary shift to the opposite side of the screen
        // the instant a turn had no imagery).
        const GAP = 8;
        const style: React.CSSProperties = focusRect
          ? { left: focusRect.left - GAP, top: (focusRect.top + focusRect.bottom) / 2, transform: "translate(-100%, -50%)" }
          : { left: sidebarWidthPx + 24, top: "50%", transform: "translateY(-50%)" };
        return (
        <div
          className="fixed z-30 flex flex-col gap-2"
          style={style}
        >
          {canGoUp && (
            <button
              type="button"
              onClick={() => jumpToTurn(activeTurnIndex - 1)}
              className="flex h-11 w-11 items-center justify-center rounded-full border border-white/15 bg-slate-900/60 text-slate-200 shadow-xl backdrop-blur-xl transition-colors hover:bg-white/10"
              aria-label="Go to previous turn"
              title="Previous turn"
            >
              <ChevronUp className="h-5 w-5" />
            </button>
          )}
          {canGoDown && (
            <button
              type="button"
              onClick={() => jumpToTurn(activeTurnIndex + 1)}
              className="flex h-11 w-11 items-center justify-center rounded-full border border-white/15 bg-slate-900/60 text-slate-200 shadow-xl backdrop-blur-xl transition-colors hover:bg-white/10"
              aria-label="Go to next turn"
              title="Next turn"
            >
              <ChevronDown className="h-5 w-5" />
            </button>
          )}
        </div>
        );
      })()}

      <LibraryDrawer open={libraryOpen} onClose={() => setLibraryOpen(false)} sessions={sessions} />

      <QueryInput
        query={draftQuery}
        onQueryChange={setDraftQuery}
        images={draftImages}
        onImagesChange={setDraftImages}
        onSubmit={handleSubmit}
        loading={loading}
        sidebarWidth={sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH}
        layerSwitcherVisible={activeRaster !== null}
        activeLayer={activeLayerKey}
        onActiveLayerChange={handleActiveLayerChange}
        layers={activeRaster?.layers ?? null}
      />
    </div>
  );
}
