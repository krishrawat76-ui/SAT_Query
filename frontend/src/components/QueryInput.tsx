"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, Loader2, Plus } from "lucide-react";
import ImageUpload, { AttachmentChips } from "./ImageUpload";
import LayerSwitcher from "./LayerSwitcher";
import RadiantCard from "./RadiantCard";
import type { LayerKey, RasterLayers, UploadedImage, Modality } from "@/types/api";

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
    /** Raster layer switcher — only rendered when the current turn has raster
     * data AND at least 2 of its layers actually have a real URL. */
    layerSwitcherVisible: boolean;
    activeLayer: LayerKey;
    onActiveLayerChange: (key: LayerKey) => void;
    layers: RasterLayers | null;
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
    layerSwitcherVisible,
    activeLayer,
    onActiveLayerChange,
    layers,
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

    const canSubmit = !loading && query.trim().length > 0;

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
                {/* Attach popover — no radiating halo here. Unlike the
                    suggestion list (mostly uniform dark rows), this card
                    sits directly over the busiest, highest-contrast part of
                    the map (the raw uploaded imagery), and a blur halo over
                    that reads as a hazy, uneven smudge rather than a soft
                    glow. The card's own backdrop-blur-xl (see ImageUpload)
                    already gives it a legible glass surface without one. */}
                {attachOpen && (
                    <div className="absolute bottom-full left-4 z-20 mb-3">
                        <ImageUpload
                            images={images}
                            onChange={onImagesChange}
                            onRequestClose={() => setAttachOpen(false)}
                        />
                    </div>
                )}

                {/* Compact attachment chips — hidden while the popover is open,
                    since its own thumbnail grid already shows the same images;
                    showing both at once duplicated the same info in two places. */}
                {!attachOpen && (
                    <AttachmentChips
                        images={images}
                        onRemove={removeImage}
                        onModalityChange={updateModality}
                    />
                )}

                {/* Hidden while typing/suggestions are open — the suggestion
                    list sits right where this would be, and showing both
                    made the bar read as awkwardly sandwiched between them. */}
                {!suggestOpen && (
                    <LayerSwitcher
                        visible={layerSwitcherVisible}
                        active={activeLayer}
                        onChange={onActiveLayerChange}
                        layers={layers}
                    />
                )}

                {/* Shared, unpadded alignment box for the suggestion popover
                    and the input pill — both reference this SAME box with
                    zero-offset (left-0/right-0/w-full), so they're
                    guaranteed pixel-identical width and centering rather
                    than relying on two different box-model reference points
                    (padding-box vs content-box) happening to coincide. */}
                <div className="relative">
                    {/* Halo for the suggestion popover — conditioned
                        directly on suggestOpen, deliberately outside
                        AnimatePresence, so it disappears the instant
                        suggestions close instead of lingering through the
                        card's own graceful exit animation below. */}
                    {suggestOpen && filteredSuggestions.length > 0 && (
                        <div className="pointer-events-none absolute bottom-full left-0 right-0 z-20 mb-3">
                            <div className="pointer-events-none absolute -inset-8 rounded-[3rem] backdrop-blur-2xl [mask-image:radial-gradient(closest-side,black_40%,transparent_100%)]" />
                        </div>
                    )}

                    {/* Dynamic autocomplete — filters as the user types, shows
                        defaults when empty. Pops up from the input bar like
                        macOS Spotlight: starts small and low (as if emerging
                        from the pill below it), then springs up to full size,
                        transform-origin pinned to the bottom edge it's rising
                        from. Same glass styling as the pill itself
                        (bg-slate-900/60, border-white/15) for a unified look. */}
                    <AnimatePresence>
                        {suggestOpen && filteredSuggestions.length > 0 && (
                            <div className="absolute bottom-full left-0 right-0 z-20 mb-3">
                                {/* The scale/y animation lives on this outer,
                                    unstyled wrapper — a Chromium rendering bug
                                    makes backdrop-filter + border-radius +
                                    overflow-hidden fail to clip correctly on an
                                    element that also carries a CSS transform,
                                    which is exactly what framer-motion applies
                                    here for the pop-in animation. Keeping the
                                    rounded/blurred surface on a separate, static
                                    inner div avoids that. */}
                                <motion.div
                                    initial={{ opacity: 0, scale: 0.85, y: 24 }}
                                    animate={{ opacity: 1, scale: 1, y: 0 }}
                                    exit={{ opacity: 0, scale: 0.9, y: 12 }}
                                    transition={{ type: "spring", stiffness: 420, damping: 32 }}
                                    style={{ transformOrigin: "bottom center" }}
                                >
                                    <div className="relative w-full overflow-hidden rounded-3xl border border-white/15 bg-slate-900/60 p-2 shadow-2xl backdrop-blur-xl">
                                        {filteredSuggestions.map((s) => (
                                            <button
                                                key={s}
                                                type="button"
                                                onMouseDown={(e) => e.preventDefault()}
                                                onClick={() => pickSuggestion(s)}
                                                className="block w-full rounded-2xl px-4 py-2.5 text-left text-sm text-white/90 transition-colors hover:bg-white/10"
                                            >
                                                {s}
                                            </button>
                                        ))}
                                    </div>
                                </motion.div>
                            </div>
                        )}
                    </AnimatePresence>

                    {/* Radiating blur behind the input bar itself — present at
                        all times (not just while typing), a permanent soft halo
                        so the pill reads clearly against the busy map behind it.
                        Sized tightly to just this pill via RadiantCard's own
                        relative wrapper (not the whole column above it).
                        Suppressed while a popover is open just above it — its
                        own halo already covers that area, and two overlapping
                        blur halos of different radii read as an uneven,
                        blotchy blur rather than one clean edge.
                        z-30 (above the popover/halo's z-20) so the pill's own
                        opaque surface always paints over any part of the
                        popover's halo that bleeds down into the small gap
                        between them — the halo should never visibly soften
                        the chat bar itself. */}
                    <RadiantCard className="z-30" haloInset={24} hideHalo={attachOpen || suggestOpen}>
                    <div
                        // A fixed radius rather than rounded-full: at one line
                        // (~56px tall) that still reads as a fully-rounded
                        // pill, but growing to 2-3 lines with rounded-full
                        // scaled the corner radius up with the box height,
                        // ballooning into an elongated stadium shape with
                        // large empty rounded caps above the (fixed-size)
                        // +/send buttons — reading as misaligned even though
                        // both buttons stay bottom-anchored together.
                        className={`flex items-end gap-2 rounded-[28px] border bg-slate-900/60 p-2.5 shadow-2xl backdrop-blur-xl transition-colors ${focused ? "border-white/25" : "border-white/15"
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
                    </RadiantCard>
                </div>

                {images.length === 0 && (
                    <p className="mt-2 px-2 text-center text-xs text-slate-500">
                        Tip: attach a satellite image with the + button for a
                        location-grounded analysis.
                    </p>
                )}
                </div>
            </div>
    );
}