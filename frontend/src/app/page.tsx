"use client";

import { useEffect, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import QueryInput from "@/components/QueryInput";
import ResultPanel from "@/components/ResultPanel";
import ExecutionTrace from "@/components/ExecutionTrace";
import { useAnalysis } from "@/hooks/useAnalysis";
import type { ChatSession, ConversationTurn, UploadedImage } from "@/types/api";

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

  const [draftQuery, setDraftQuery] = useState("");
  const [draftImages, setDraftImages] = useState<UploadedImage[]>([]);
  const pendingTurnRef = useRef<{ sessionId: string; turnId: string } | null>(null);
  const feedEndRef = useRef<HTMLDivElement>(null);

  const { analyze, result, loading, error } = useAnalysis();

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? sessions[0];

  // Attribute the (single-shot) hook's async state to whichever turn triggered it.
  useEffect(() => {
    const pending = pendingTurnRef.current;
    if (!pending) return;

    setSessions((prev) =>
      prev.map((s) =>
        s.id === pending.sessionId
          ? {
            ...s,
            turns: s.turns.map((t) =>
              t.id === pending.turnId
                ? {
                  ...t,
                  loading,
                  result: result ?? t.result,
                  error: error ?? null,
                }
                : t
            ),
          }
          : s
      )
    );

    if (!loading && (result || error)) {
      pendingTurnRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, error, loading]);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.turns.length, loading]);

  const handleNewChat = () => {
    const session = createSession();
    setSessions((prev) => [session, ...prev]);
    setActiveSessionId(session.id);
    setDraftQuery("");
    setDraftImages([]);
  };

  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setDraftQuery("");
    setDraftImages([]);
  };

  const handleSubmit = () => {
    if (!draftQuery.trim() || draftImages.length === 0 || loading || !activeSession) return;

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
  };

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSession?.id ?? null}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
      />

      <div className="relative flex min-w-0 flex-1 flex-col">
        <main className="flex-1 overflow-y-auto px-6 py-8">
          <div className="mx-auto flex max-w-3xl flex-col gap-8 pb-40">
            {(!activeSession || activeSession.turns.length === 0) && (
              <div className="flex flex-col items-center justify-center gap-2 py-24 text-center">
                <h1 className="text-3xl font-medium text-slate-900">
                  Ready when you are.
                </h1>
                <p className="text-base text-slate-400">
                  Attach satellite imagery and ask a question to begin.
                </p>
              </div>
            )}

            {activeSession?.turns.map((turn) => (
              <div key={turn.id} className="flex flex-col gap-4">
                {/* User message */}
                <div className="flex justify-end">
                  <div className="max-w-xl space-y-2">
                    {turn.images.length > 0 && (
                      <div className="flex flex-wrap justify-end gap-2">
                        {turn.images.map((img) => (
                          <div
                            key={img.id}
                            className="h-14 w-14 overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-100"
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
                    <div className="rounded-3xl rounded-tr-lg bg-slate-900 px-4 py-2.5 text-sm text-white">
                      {turn.query}
                    </div>
                  </div>
                </div>

                {/* AI response */}
                <div className="space-y-4">
                  <ResultPanel
                    result={turn.result}
                    loading={turn.loading}
                    error={turn.error}
                  />
                  <ExecutionTrace trace={turn.result?.execution_trace ?? null} />
                </div>
              </div>
            ))}

            <div ref={feedEndRef} />
          </div>
        </main>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-slate-50 via-slate-50/95 to-transparent pb-6 pt-10">
          <div className="pointer-events-auto px-6">
            <QueryInput
              query={draftQuery}
              onQueryChange={setDraftQuery}
              images={draftImages}
              onImagesChange={setDraftImages}
              onSubmit={handleSubmit}
              loading={loading}
            />
          </div>
        </div>
      </div>
    </div>
  );
}