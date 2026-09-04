"use client";

import { useState } from "react";
import {
    Plus,
    Search,
    LayoutGrid,
    PanelLeftClose,
    PanelLeftOpen,
    MessageSquare,
    Pin,
    Pencil,
    Trash2,
    Check,
    X,
    Bug,
} from "lucide-react";
import type { ChatSession } from "@/types/api";

interface SidebarProps {
    sessions: ChatSession[];
    activeSessionId: string | null;
    collapsed: boolean;
    onToggleCollapse: () => void;
    onNewChat: () => void;
    onSelectSession: (id: string) => void;
    onPinSession: (id: string) => void;
    onRenameSession: (id: string, title: string) => void;
    onDeleteSession: (id: string) => void;
    onOpenLibrary: () => void;
    debugMode: boolean;
    onToggleDebugMode: () => void;
}

export default function Sidebar({
    sessions,
    activeSessionId,
    collapsed,
    onToggleCollapse,
    onNewChat,
    onSelectSession,
    onPinSession,
    onRenameSession,
    onDeleteSession,
    onOpenLibrary,
    debugMode,
    onToggleDebugMode,
}: SidebarProps) {
    const [search, setSearch] = useState("");
    const [renamingId, setRenamingId] = useState<string | null>(null);
    const [renameValue, setRenameValue] = useState("");

    const filteredSessions = (
        search.trim()
            ? sessions.filter((s) => s.title.toLowerCase().includes(search.trim().toLowerCase()))
            : sessions
    ).slice().sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned));

    const startRename = (session: ChatSession) => {
        setRenamingId(session.id);
        setRenameValue(session.title);
    };

    const commitRename = () => {
        if (renamingId && renameValue.trim()) {
            onRenameSession(renamingId, renameValue.trim());
        }
        setRenamingId(null);
    };

    const handleDelete = (session: ChatSession) => {
        if (window.confirm(`Delete "${session.title}"?`)) {
            onDeleteSession(session.id);
        }
    };

    return (
        <aside
            className={`flex h-screen shrink-0 flex-col border-r border-white/10 bg-slate-900/40 text-slate-200 backdrop-blur-xl transition-[width] duration-300 ease-in-out ${collapsed ? "w-[72px]" : "w-72"
                }`}
        >
            <div
                className={`flex items-center gap-2 px-3 pt-4 ${collapsed ? "justify-center" : "justify-between"
                    }`}
            >
                {!collapsed && (
                    <span className="px-2 text-sm font-semibold text-slate-100">
                        SAT_Query
                    </span>
                )}
                <button
                    type="button"
                    onClick={onToggleCollapse}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-100"
                    aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                >
                    {collapsed ? (
                        <PanelLeftOpen className="h-4 w-4" />
                    ) : (
                        <PanelLeftClose className="h-4 w-4" />
                    )}
                </button>
            </div>

            {!collapsed && (
                <div className="px-3 pt-4">
                    <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                        <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                        <input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search chats"
                            className="w-full bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-500"
                        />
                    </div>
                </div>
            )}

            <div className="space-y-1 px-3 pt-3">
                <button
                    type="button"
                    onClick={onNewChat}
                    className={`flex w-full items-center gap-3 rounded-2xl border border-white/10 bg-white/10 text-slate-100 transition-colors hover:bg-white/15 ${collapsed ? "justify-center px-0 py-2.5" : "px-4 py-2.5"
                        }`}
                >
                    <Plus className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="text-sm font-medium">New chat</span>}
                </button>

                <button
                    type="button"
                    onClick={onOpenLibrary}
                    className={`flex w-full items-center gap-3 rounded-2xl text-slate-300 transition-colors hover:bg-white/10 ${collapsed ? "justify-center px-0 py-2.5" : "px-4 py-2.5"
                        }`}
                >
                    <LayoutGrid className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="text-sm">Library</span>}
                </button>

                {/* Debug Mode — surfaces real router/model telemetry in the
                    result panel (see DebugPanel.tsx). No switch-style control
                    exists anywhere else in this app, so this stays a ghost
                    button with an active tint, same language as Pin's
                    on-state, rather than inventing a new toggle affordance. */}
                <button
                    type="button"
                    onClick={onToggleDebugMode}
                    className={`flex w-full items-center gap-3 rounded-2xl transition-colors ${collapsed ? "justify-center px-0 py-2.5" : "px-4 py-2.5"
                        } ${debugMode
                            ? "bg-white/10 text-amber-300"
                            : "text-slate-300 hover:bg-white/10"
                        }`}
                    aria-pressed={debugMode}
                    // The label span is hidden when the sidebar is collapsed,
                    // which would otherwise leave an icon-only button with no
                    // accessible name.
                    aria-label="Debug Mode"
                    title="Debug Mode"
                >
                    <Bug className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="text-sm">Debug Mode</span>}
                </button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto px-3 pb-4">
                {!collapsed && (
                    <p className="px-2 pb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                        Chats
                    </p>
                )}
                <div className="space-y-0.5">
                    {filteredSessions.map((session) => (
                        <div
                            key={session.id}
                            className={`group flex w-full items-center gap-2 rounded-2xl text-left transition-colors ${collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2"
                                } ${session.id === activeSessionId
                                    ? "bg-white/10 text-slate-100"
                                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                                }`}
                        >
                            {renamingId === session.id ? (
                                <>
                                    <MessageSquare className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                                    <input
                                        autoFocus
                                        value={renameValue}
                                        onChange={(e) => setRenameValue(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === "Enter") commitRename();
                                            if (e.key === "Escape") setRenamingId(null);
                                        }}
                                        onBlur={commitRename}
                                        className="min-w-0 flex-1 rounded-lg bg-white/10 px-2 py-0.5 text-sm text-slate-100 outline-none"
                                    />
                                    <button
                                        type="button"
                                        onMouseDown={(e) => e.preventDefault()}
                                        onClick={commitRename}
                                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-emerald-400 hover:bg-white/10"
                                        aria-label="Save name"
                                    >
                                        <Check className="h-3.5 w-3.5" />
                                    </button>
                                    <button
                                        type="button"
                                        onMouseDown={(e) => e.preventDefault()}
                                        onClick={() => setRenamingId(null)}
                                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-white/10"
                                        aria-label="Cancel rename"
                                    >
                                        <X className="h-3.5 w-3.5" />
                                    </button>
                                </>
                            ) : (
                                <>
                                    <button
                                        type="button"
                                        onClick={() => onSelectSession(session.id)}
                                        title={session.title}
                                        className={`flex min-w-0 flex-1 items-center gap-3 ${collapsed ? "justify-center" : ""}`}
                                    >
                                        <MessageSquare className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                                        {!collapsed && (
                                            <span className="truncate text-sm">{session.title}</span>
                                        )}
                                    </button>

                                    {!collapsed && (
                                        <div className="flex shrink-0 items-center gap-0.5">
                                            <button
                                                type="button"
                                                onClick={() => onPinSession(session.id)}
                                                className={`flex h-6 w-6 items-center justify-center rounded-full opacity-0 transition-opacity hover:bg-white/10 group-hover:opacity-100 ${session.pinned ? "opacity-100 text-amber-400" : "text-slate-400"
                                                    }`}
                                                aria-label={session.pinned ? "Unpin chat" : "Pin chat"}
                                                title={session.pinned ? "Unpin chat" : "Pin chat"}
                                            >
                                                <Pin className={`h-3 w-3 ${session.pinned ? "fill-current" : ""}`} />
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => startRename(session)}
                                                className="flex h-6 w-6 items-center justify-center rounded-full text-slate-400 opacity-0 transition-opacity hover:bg-white/10 group-hover:opacity-100"
                                                aria-label="Rename chat"
                                                title="Rename chat"
                                            >
                                                <Pencil className="h-3 w-3" />
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => handleDelete(session)}
                                                className="flex h-6 w-6 items-center justify-center rounded-full text-slate-400 opacity-0 transition-opacity hover:bg-rose-500/20 hover:text-rose-400 group-hover:opacity-100"
                                                aria-label="Delete chat"
                                                title="Delete chat"
                                            >
                                                <Trash2 className="h-3 w-3" />
                                            </button>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    ))}
                    {!collapsed && filteredSessions.length === 0 && (
                        <p className="px-3 py-2 text-xs text-slate-500">No chats found</p>
                    )}
                </div>
            </div>
        </aside>
    );
}
