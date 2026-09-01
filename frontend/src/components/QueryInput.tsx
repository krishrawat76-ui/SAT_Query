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
        <div ref={containerRef} className="relative mx-auto w-full max-w-3xl">
            {/* Dynamic autocomplete — filters as the user types, shows defaults when empty */}
            {suggestOpen && filteredSuggestions.length > 0 && (
                <div className="absolute bottom-full left-0 right-0 z-20 mb-3 overflow-hidden rounded-3xl border border-slate-200/80 bg-white/95 p-2 shadow-lg backdrop-blur-md">
                    {filteredSuggestions.map((s) => (
                        <button
                            key={s}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => pickSuggestion(s)}
                            className="block w-full rounded-2xl px-4 py-2.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-50"
                        >
                            {s}
                        </button>
                    ))}
                </div>
            )}

            {/* Attach popover */}
            {attachOpen && (
                <div className="absolute bottom-full left-0 z-20 mb-3">
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
                className={`flex items-end gap-2 rounded-[28px] border bg-white/95 p-2.5 shadow-lg backdrop-blur-md transition-colors ${focused ? "border-slate-300" : "border-slate-200/80"
                    }`}
            >
                <button
                    type="button"
                    onClick={() => {
                        setSuggestOpen(false);
                        setAttachOpen((v) => !v);
                    }}
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border transition-colors ${attachOpen
                            ? "border-slate-300 bg-slate-100 text-slate-900"
                            : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
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
                    className="max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent px-1 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400"
                />

                <button
                    type="button"
                    onClick={() => {
                        setSuggestOpen(false);
                        onSubmit();
                    }}
                    disabled={!canSubmit}
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-slate-900 text-white transition-colors enabled:hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
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
                <p className="mt-2 px-2 text-center text-xs text-slate-400">
                    Attach at least one satellite image with the + button to run an
                    analysis.
                </p>
            )}
        </div>
    );
}