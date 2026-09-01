"use client";

import { useState } from "react";
import {
    Plus,
    Search,
    LayoutGrid,
    PanelLeftClose,
    PanelLeftOpen,
    MessageSquare,
} from "lucide-react";
import type { ChatSession } from "@/types/api";

interface SidebarProps {
    sessions: ChatSession[];
    activeSessionId: string | null;
    collapsed: boolean;
    onToggleCollapse: () => void;
    onNewChat: () => void;
    onSelectSession: (id: string) => void;
}

export default function Sidebar({
    sessions,
    activeSessionId,
    collapsed,
    onToggleCollapse,
    onNewChat,
    onSelectSession,
}: SidebarProps) {
    const [search, setSearch] = useState("");

    const filteredSessions = search.trim()
        ? sessions.filter((s) =>
            s.title.toLowerCase().includes(search.trim().toLowerCase())
        )
        : sessions;

    return (
        <aside
            className={`flex h-screen shrink-0 flex-col border-r border-slate-200/80 bg-white/70 backdrop-blur-md transition-[width] duration-300 ease-in-out ${collapsed ? "w-[72px]" : "w-72"
                }`}
        >
            <div
                className={`flex items-center gap-2 px-3 pt-4 ${collapsed ? "justify-center" : "justify-between"
                    }`}
            >
                {!collapsed && (
                    <span className="px-2 text-sm font-semibold text-slate-900">
                        SAT_Query
                    </span>
                )}
                <button
                    type="button"
                    onClick={onToggleCollapse}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
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
                    <div className="flex items-center gap-2 rounded-2xl border border-slate-200/80 bg-white px-3 py-2">
                        <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                        <input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search chats"
                            className="w-full bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400"
                        />
                    </div>
                </div>
            )}

            <div className="space-y-1 px-3 pt-3">
                <button
                    type="button"
                    onClick={onNewChat}
                    className={`flex w-full items-center gap-3 rounded-2xl bg-slate-900 text-white transition-colors hover:bg-slate-700 ${collapsed ? "justify-center px-0 py-2.5" : "px-4 py-2.5"
                        }`}
                >
                    <Plus className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="text-sm font-medium">New chat</span>}
                </button>

                <button
                    type="button"
                    className={`flex w-full items-center gap-3 rounded-2xl text-slate-600 transition-colors hover:bg-slate-100 ${collapsed ? "justify-center px-0 py-2.5" : "px-4 py-2.5"
                        }`}
                >
                    <LayoutGrid className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="text-sm">Library</span>}
                </button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto px-3 pb-4">
                {!collapsed && (
                    <p className="px-2 pb-2 text-xs font-medium uppercase tracking-wide text-slate-400">
                        Chats
                    </p>
                )}
                <div className="space-y-0.5">
                    {filteredSessions.map((session) => (
                        <button
                            key={session.id}
                            type="button"
                            onClick={() => onSelectSession(session.id)}
                            title={session.title}
                            className={`flex w-full items-center gap-3 rounded-2xl text-left transition-colors ${collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2"
                                } ${session.id === activeSessionId
                                    ? "bg-slate-100 text-slate-900"
                                    : "text-slate-600 hover:bg-slate-50"
                                }`}
                        >
                            <MessageSquare className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                            {!collapsed && (
                                <span className="truncate text-sm">{session.title}</span>
                            )}
                        </button>
                    ))}
                    {!collapsed && filteredSessions.length === 0 && (
                        <p className="px-3 py-2 text-xs text-slate-400">No chats found</p>
                    )}
                </div>
            </div>
        </aside>
    );
}