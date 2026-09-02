"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import Sidebar from "@/components/Sidebar";
import QueryInput from "@/components/QueryInput";
import ResultPanel from "@/components/ResultPanel";
import ExecutionTrace from "@/components/ExecutionTrace";
import MessageActions from "@/components/MessageActions";
import LibraryDrawer from "@/components/LibraryDrawer";
import SatelliteMap from "@/components/SatelliteMap";
import CloudTransition, { type CloudPhase } from "@/components/CloudTransition";
import { useAnalysis } from "@/hooks/useAnalysis";
import { useMapCamera } from "@/hooks/useMapCamera";
import { getTurnLocation, IDLE_VIEW } from "@/lib/mapLocations";
import { getMockResult } from "@/lib/mockResults";
import type { ChatSession, ConversationTurn, UploadedImage } from "@/types/api";

const SIDEBAR_EXPANDED_WIDTH = 288;
const SIDEBAR_COLLAPSED_WIDTH = 72;

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

  const [draftQuery, setDraftQuery] = useState("");
  const [draftImages, setDraftImages] = useState<UploadedImage[]>([]);
  const pendingTurnRef = useRef<{ sessionId: string; turnId: string } | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const landingElementsRef = useRef<Map<string, HTMLDivElement>>(new Map());
  const resultElementsRef = useRef<Map<string, HTMLDivElement>>(new Map());

  const camera = useMapCamera();
  const [cloudPhase, setCloudPhase] = useState<CloudPhase>("idle");
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [revealedTurnId, setRevealedTurnId] = useState<string | null>(null);
  const isTransitioningRef = useRef(false);
  const activeMapTurnIdRef = useRef<string | null>(null);
  const cloudTimeoutsRef = useRef<number[]>([]);
  const preFlightDelayRef = useRef<number | null>(null);

  const { analyze, result, loading, error } = useAnalysis();

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? sessions[0];
  const activeTurnIndex = activeSession?.turns.findIndex((t) => t.id === activeTurnId) ?? -1;
  const canGoUp = activeTurnIndex > 0;
  const canGoDown =
    activeTurnIndex !== -1 && activeTurnIndex < (activeSession?.turns.length ?? 0) - 1;

  // Attribute the (single-shot) hook's async state to whichever turn triggered it.
  // A network error falls back to the scripted demo result so the Mumbai/DC
  // camera choreography stays visually verifiable without a live backend.
  useEffect(() => {
    const pending = pendingTurnRef.current;
    if (!pending) return;

    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== pending.sessionId) return s;
        const turnIndex = s.turns.findIndex((t) => t.id === pending.turnId);
        return {
          ...s,
          turns: s.turns.map((t) => {
            if (t.id !== pending.turnId) return t;
            if (!loading && error) {
              return { ...t, loading: false, result: getMockResult(turnIndex), error: null };
            }
            return { ...t, loading, result: result ?? t.result, error: error ?? null };
          }),
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

  // Map-first camera recall: settle the camera on whichever turn's arrival
  // section is in view. The result card for that turn only appears once its
  // own section is scrolled into view (handled by the observer below).
  const recallCamera = (turnId: string, turnIndex: number) => {
    if (isTransitioningRef.current || activeMapTurnIdRef.current === turnId) return;

    activeMapTurnIdRef.current = turnId;
    setActiveTurnId(turnId);
    setRevealedTurnId(null);

    const location = getTurnLocation(turnIndex);
    camera.flyToSimple({ center: location.center, zoom: location.zoom, durationMs: 900 });
  };

  // Scroll-driven behavior: the "landing" section recalls the camera; the
  // "result" section (reached only by scrolling further down) reveals the card.
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

          const turnIndex = activeSession.turns.findIndex((t) => t.id === turnId);
          if (turnIndex === -1) continue;

          if (section === "landing") {
            if (!isTransitioningRef.current) recallCamera(turnId, turnIndex);
          } else if (section === "result") {
            setRevealedTurnId(turnId);
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
    recallCamera(target.id, turnIndex);
  };

  // Quick smoke puff masks only the very start of the switch — the flight
  // itself (the hook's 5-phase sequence) runs fully visible and sharp,
  // landing directly on the target with no result card yet.
  const runCloudFlight = (location: { center: [number, number]; zoom: number }, turnId: string) => {
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

    const coverMs = 300;
    const clearMs = 900;

    setCloudPhase("covering");
    camera.runFivePhaseFlight(startCoords, startZoom, location.center, location.zoom, () => {
      isTransitioningRef.current = false;
    });

    const clearTimer = window.setTimeout(() => setCloudPhase("clearing"), coverMs);
    const idleTimer = window.setTimeout(() => setCloudPhase("idle"), coverMs + clearMs);
    cloudTimeoutsRef.current.push(clearTimer, idleTimer);
  };

  // Simulates a brief AI routing/processing beat before the camera commits to
  // a destination — 60-300ms, randomized per call so it never feels canned.
  const scheduleCameraFlight = (location: { center: [number, number]; zoom: number }, turnId: string) => {
    if (preFlightDelayRef.current) clearTimeout(preFlightDelayRef.current);
    const delay = Math.floor(Math.random() * 240) + 60;
    preFlightDelayRef.current = window.setTimeout(() => {
      preFlightDelayRef.current = null;
      runCloudFlight(location, turnId);
    }, delay);
  };

  // Drops all pending camera/cloud state and returns to the blank ocean
  // establishing view — used when starting a brand new chat.
  const resetMapToOcean = () => {
    cloudTimeoutsRef.current.forEach((id) => clearTimeout(id));
    cloudTimeoutsRef.current = [];
    if (preFlightDelayRef.current) {
      clearTimeout(preFlightDelayRef.current);
      preFlightDelayRef.current = null;
    }
    isTransitioningRef.current = false;
    activeMapTurnIdRef.current = null;
    setActiveTurnId(null);
    setRevealedTurnId(null);
    setCloudPhase("idle");
    camera.flyToSimple(IDLE_VIEW, { showMarker: false });
  };

  const handleNewChat = () => {
    const session = createSession();
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(session.id);
    setDraftQuery("");
    setDraftImages([]);
    resetMapToOcean();
  };

  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setDraftQuery("");
    setDraftImages([]);

    const target = sessions.find((s) => s.id === id);
    if (!target || target.turns.length === 0) {
      // Fresh/empty chat — always land back on the blank ocean view, never
      // stuck on whatever coordinates the previous chat left behind.
      resetMapToOcean();
      return;
    }

    // Non-empty chat — run the same standardized camera switch used for
    // submissions/retries; runCloudFlight's own cancelFlight() guarantees
    // this never fights an in-progress flight from the chat just left.
    if (preFlightDelayRef.current) {
      clearTimeout(preFlightDelayRef.current);
      preFlightDelayRef.current = null;
    }
    const lastIndex = target.turns.length - 1;
    const lastTurn = target.turns[lastIndex];
    runCloudFlight(getTurnLocation(lastIndex), lastTurn.id);
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
    if (!draftQuery.trim() || draftImages.length === 0 || loading || !activeSession) return;

    const turnIndex = activeSession.turns.length;
    const location = getTurnLocation(turnIndex);

    const turn: ConversationTurn = {
      id: `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      query: draftQuery.trim(),
      images: draftImages,
      result: null,
      loading: true,
      error: null,
      createdAt: Date.now(),
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
    analyze(files, turn.query, modalities);

    setDraftQuery("");
    setDraftImages([]);

    scheduleCameraFlight(location, turn.id);
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
              t.id === turnId ? { ...t, loading: true, result: null, error: null } : t
            ),
          }
          : s
      )
    );

    pendingTurnRef.current = { sessionId: activeSession.id, turnId };

    const files = turn.images.map((img) => img.file);
    const modalities = turn.images.map((img) => img.modality);
    analyze(files, turn.query, modalities);

    landingElementsRef.current.get(turnId)?.scrollIntoView({ behavior: "smooth", block: "start" });
    scheduleCameraFlight(getTurnLocation(turnIndex), turnId);
  };

  return (
    <div className="relative flex h-full w-full select-none overflow-hidden bg-slate-950">
      <SatelliteMap initialTarget={IDLE_VIEW} onMapReady={camera.setMap} />
      <CloudTransition phase={cloudPhase} />

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
                Attach satellite imagery and ask a question to begin.
              </p>
            </div>
          )}

          {activeSession?.turns.map((turn) => {
            const revealed = revealedTurnId === turn.id;
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
                  className="flex h-full min-h-full snap-start flex-col items-end justify-end gap-3 pb-20"
                >
                  <div className="mx-auto flex w-full max-w-3xl justify-end">
                    <div className="max-w-xl space-y-2 rounded-3xl rounded-tr-sm border border-white/10 bg-slate-800/80 px-3 py-3 text-sm text-slate-100 backdrop-blur-xl">
                      {turn.images.length > 0 && (
                        <div className="flex flex-wrap justify-end gap-2">
                          {turn.images.map((img) => (
                            <div
                              key={img.id}
                              className="h-14 w-14 overflow-hidden rounded-2xl border border-white/15 bg-slate-800/60"
                            >
                              {img.preview && (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img
                                  src={img.preview}
                                  alt={img.file.name}
                                  className="h-full w-full object-cover"
                                />
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="px-1">{turn.query}</div>
                    </div>
                  </div>
                  <div className="mx-auto flex w-full max-w-3xl justify-center pt-6">
                    <ChevronDown className="h-5 w-5 animate-bounce text-slate-300/70" />
                  </div>
                </div>

                {/* Result section — reached only by scrolling further; reveals on arrival. */}
                <div
                  data-turn-id={turn.id}
                  data-section="result"
                  ref={(el) => {
                    if (el) resultElementsRef.current.set(turn.id, el);
                    else resultElementsRef.current.delete(turn.id);
                  }}
                  className="flex h-full min-h-full snap-start flex-col justify-center gap-4 py-16"
                >
                  <div className="mx-auto flex w-full max-w-3xl justify-start pb-24">
                    <div
                      className={`w-full max-w-2xl space-y-3 rounded-3xl bg-slate-950/40 p-3 backdrop-blur-xl transition-all duration-700 ease-[cubic-bezier(0.25,0.1,0.25,1)] ${revealed ? "translate-y-0 opacity-100" : "translate-y-10 opacity-0"
                        }`}
                    >
                      <ResultPanel
                        result={turn.result}
                        loading={turn.loading}
                        error={turn.error}
                      />
                      <ExecutionTrace trace={turn.result?.execution_trace ?? null} />
                      {!turn.loading && (
                        <MessageActions
                          text={turn.result?.answer ?? null}
                          onRetry={() => handleRetry(turn.id)}
                          retryDisabled={loading}
                        />
                      )}
                    </div>
                  </div>
                </div>
              </Fragment>
            );
          })}
        </main>
      </div>

      {activeSession && activeSession.turns.length > 1 && (canGoUp || canGoDown) && (
        <div className="fixed right-6 top-1/2 z-30 flex -translate-y-1/2 flex-col gap-2">
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
      )}

      <LibraryDrawer open={libraryOpen} onClose={() => setLibraryOpen(false)} sessions={sessions} />

      <QueryInput
        query={draftQuery}
        onQueryChange={setDraftQuery}
        images={draftImages}
        onImagesChange={setDraftImages}
        onSubmit={handleSubmit}
        loading={loading}
        sidebarWidth={sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH}
      />
    </div>
  );
}
