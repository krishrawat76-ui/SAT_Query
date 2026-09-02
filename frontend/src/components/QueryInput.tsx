"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, Plus } from "lucide-react";
import ImageUpload, { AttachmentChips } from "./ImageUpload";
import type { UploadedImage, Modality } from "@/types/api";

interface QueryInputProps {
    query: string;
    onQueryChange: (value: string) => void;
    images: UploadedImage[];
    onImagesChange: (images: UploadedImage[]) => void;
    onSubmit: () => void;
    loading: boolean;
    /** Width (px) of the sidebar currently docked on the left, so the pill
     * centers within the remaining satellite workspace, not the full viewport. */
    sidebarWidth: number;
}

const SUGGESTIONS = [
    "What objects are present in this image?",
    "Highlight the water body in this image.",
    "What changed between these two dates?",
    "Has the built-up area increased, decreased, or remained unchanged?",
    "Use both images to identify built-up and water-covered regions.",
];

export default function QueryInput({
    query,
    onQueryChange,
    images,
    onImagesChange,
    onSubmit,
    loading,
    sidebarWidth,
}: QueryInputProps) {
    const [focused, setFocused] = useState(false);
    const [attachOpen, setAttachOpen] = useState(false);
    const [suggestOpen, setSuggestOpen] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Close both popovers on outside click.
    useEffect(() => {
        function handleClick(e: MouseEvent) {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                setAttachOpen(false);
                setSuggestOpen(false);
            }
        }
        document.addEventListener("mousedown", handleClick);
        return () => document.removeEventListener("mousedown", handleClick);
    }, []);

    // Auto-grow the textarea as the user types.
    useEffect(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }, [query]);

    const filteredSuggestions = query.trim()
        ? SUGGESTIONS.filter((s) =>
            s.toLowerCase().includes(query.trim().toLowerCase())
        )
        : SUGGESTIONS;

    const canSubmit = !loading && query.trim().length > 0 && images.length > 0;

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (canSubmit) {
                setSuggestOpen(false);
                onSubmit();
            }
        }
        if (e.key === "Escape") setSuggestOpen(false);
    };

    const pickSuggestion = (s: string) => {
        onQueryChange(s);
        setSuggestOpen(false);
        textareaRef.current?.focus();
    };

    const removeImage = (id: string) => {
        const target = images.find((img) => img.id === id);
        if (target?.preview) URL.revokeObjectURL(target.preview);
        onImagesChange(images.filter((img) => img.id !== id));
    };

    const updateModality = (id: string, modality: Modality) => {
        onImagesChange(
            images.map((img) => (img.id === id ? { ...img, modality } : img))
        );
    };

    return (
        <div
            className="fixed bottom-6 z-30 transition-[left] duration-300 ease-in-out"
            style={{ left: sidebarWidth, right: 0 }}
        >
            <div ref={containerRef} className="relative mx-auto w-full max-w-3xl px-4">
                {/* Dynamic autocomplete — filters as the user types, shows defaults when empty */}
                {suggestOpen && filteredSuggestions.length > 0 && (
                    <div className="absolute bottom-full left-4 right-4 z-20 mb-3 overflow-hidden rounded-3xl border border-white/12 bg-slate-900/80 p-2 shadow-2xl backdrop-blur-xl">
                        {filteredSuggestions.map((s) => (
                            <button
                                key={s}
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => pickSuggestion(s)}
                                className="block w-full rounded-2xl px-4 py-2.5 text-left text-sm text-slate-200 transition-colors hover:bg-white/10"
                            >
                                {s}
                            </button>
                        ))}
                    </div>
                )}

                {/* Attach popover */}
                {attachOpen && (
                    <div className="absolute bottom-full left-4 z-20 mb-3">
                        <ImageUpload
                            images={images}
                            onChange={onImagesChange}
                            onRequestClose={() => setAttachOpen(false)}
                        />
                    </div>
                )}

                {/* Compact attachment chips, visible whether or not the popover is open */}
                <AttachmentChips
                    images={images}
                    onRemove={removeImage}
                    onModalityChange={updateModality}
                />

                <div
                    className={`flex items-end gap-2 rounded-full border bg-slate-900/60 p-2.5 shadow-2xl backdrop-blur-xl transition-colors ${focused ? "border-white/25" : "border-white/15"
                        }`}
                >
                    <button
                        type="button"
                        onClick={() => {
                            setSuggestOpen(false);
                            setAttachOpen((v) => !v);
                        }}
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border transition-colors ${attachOpen
                                ? "border-white/25 bg-white/15 text-slate-100"
                                : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
                            }`}
                        aria-label="Attach satellite imagery"
                    >
                        <Plus className="h-4 w-4" />
                    </button>

                    <textarea
                        ref={textareaRef}
                        value={query}
                        onChange={(e) => {
                            onQueryChange(e.target.value);
                            setAttachOpen(false);
                            setSuggestOpen(true);
                        }}
                        onKeyDown={handleKeyDown}
                        onFocus={() => {
                            setFocused(true);
                            setAttachOpen(false);
                            setSuggestOpen(true);
                        }}
                        onBlur={() => setFocused(false)}
                        rows={1}
                        placeholder="Ask about your satellite imagery..."
                        className="max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent px-1 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500"
                    />

                    <button
                        type="button"
                        onClick={() => {
                            setSuggestOpen(false);
                            onSubmit();
                        }}
                        disabled={!canSubmit}
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-900 transition-colors enabled:hover:bg-white disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-slate-500"
                        aria-label="Send"
                    >
                        {loading ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <ArrowUp className="h-4 w-4" />
                        )}
                    </button>
                </div>

                {images.length === 0 && (
                    <p className="mt-2 px-2 text-center text-xs text-slate-500">
                        Attach at least one satellite image with the + button to run an
                        analysis.
                    </p>
                )}
            </div>
        </div>
    );
}