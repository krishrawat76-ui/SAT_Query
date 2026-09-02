# Changelog — Phase 2: Glass Scroll Animation

> Branch: `feature/phase-2-glass-scroll-animation`. This document describes
> the current state of the frontend after Phase 2: a dark glassmorphism
> redesign built around an animated MapLibre satellite-map backdrop whose
> camera flies to a scripted location for each turn, driven by chat state
> and scroll position.

## Overview

The dashboard is now a full-bleed satellite map with the chat UI floating
on top of it in glass panels. Every query is bound to a hardcoded demo
location (Mumbai, then Washington DC, then London); submitting a query,
retrying one, switching chats, or scrolling through the conversation all
move the same map camera through the same cinematic flight system.

---

## Design system

- **Palette**: near-black slate (`bg-slate-950`, `#020617`) everywhere,
  with `bg-slate-900/*` and `bg-slate-800/*` panels layered on top at
  varying opacity for depth.
- **Blur**: standardized to `backdrop-blur-xl` across every glass surface
  (sidebar, popovers, cards, library, pill) so no two containers look
  mismatched.
- **Corners**: primary containers (result card, execution trace, upload
  popover, library entries, attachment chips) use `rounded-3xl` (24px,
  "squircle"); nested/smaller elements use progressively smaller radii
  (`rounded-2xl`, `rounded-xl`), matching Apple's own nesting convention.
- **Chat bubbles**: iMessage-style — user prompt is right-aligned
  (`bg-slate-800/80`, `rounded-tr-sm`), the assistant response is
  left-aligned (`bg-slate-900/70`, `rounded-tl-sm`).
- `globals.css` / `layout.tsx`: `html`/`body` are `h-full w-full
  overflow-hidden` with zero margin and a background that exactly matches
  `bg-slate-950`, so there is no seam or stray border at the page edge.

---

## Satellite map & camera system

### `src/lib/mapLocations.ts`
Static demo data. Exports `MUMBAI`, `WASHINGTON_DC`, `LONDON`, and
`OCEAN_START` (open Pacific, `[-150, 5]`, zoom 11 — the blank landing
view). `IDLE_VIEW` aliases `OCEAN_START`. `getTurnLocation(turnIndex)`
maps a turn's position in the conversation to one of the three anchors in
order (Mumbai → DC → London), clamping to London for any turn beyond the
third.

### `src/lib/flightPlan.ts`
Pure math, no React/map dependencies:
- `haversineDistanceKm(a, b)` — great-circle distance between two
  `[lng, lat]` points.
- `macroZoomForDistance(distanceKm)` — how far out the camera pulls back
  for the high-altitude leg of a flight. Same-spot moves (< 50 km) barely
  zoom out (zoom 6); a cross-continent hop pulls back toward a near-global
  view (as low as zoom 1.5).
- `flightDurationForDistance(distanceKm)` — total flight duration, scaled
  by distance: ~750ms for a same-spot retry up to ~2.5s for a
  cross-continent hop (Mumbai ↔ DC/London scale), with a ±10% random
  jitter so no two flights are ever perfectly identical in timing.

### `src/hooks/useMapCamera.ts`
The imperative camera controller. Holds the live `maplibregl.Map` instance
in a ref and drives it directly — the camera is **not** controlled via
React state, which is what makes cancellation deterministic:
- `setMap(map)` — called once by `SatelliteMap` when the map instance is
  ready.
- `cancelFlight()` — calls `map.stop()` and bumps an internal
  monotonically-increasing flight id, invalidating every pending phase
  callback from whatever flight was previously in progress. This is the
  single choke point that guarantees two flights can never fight over the
  camera.
- `getCurrentPosition()` — reads the map's true current center/zoom live
  off the map instance. Always called immediately after `cancelFlight()`
  so it reflects exactly where the camera stopped, never a stale value.
- `flyToSimple(target, { showMarker })` — a single-leg `flyTo`, used for
  the ocean reset and for scroll-driven quick recall between turns.
- `runFivePhaseFlight(startCoords, startZoom, targetCoords, targetZoom,
  onComplete)` — the full cinematic sequence (see below). Marks the
  target with the red pin immediately, then runs five equal-duration legs
  chained with `setTimeout`, each guarded by the flight-id check so a
  superseded flight's leftover legs can never fire.

**The five phases** (each `totalDuration / 5`, all using the same
ease-in-out cubic curve so velocity returns to ~0 at every boundary —
this is what keeps the chained legs reading as one continuous glide
instead of a jittery sequence of stutters):

1. **Source breakout** — zoom out 25% of the way from the start zoom
   toward the macro zoom, center unchanged.
2. **Macro ascent** — finish the pull-back, from the 25% point to the
   full macro zoom, center still unchanged.
3. **High-altitude traversal** — pure horizontal pan from source to
   destination at the macro zoom; no zoom change, tiles stay fully sharp
   (no blur is ever applied during this or any other phase).
4. **Approach descent** — zoom in halfway from the macro zoom toward the
   target zoom, center on the destination.
5. **Precision lock** — final zoom-in to the exact target zoom, using a
   cubic ease-out (this phase intentionally differs from the other four —
   it's the deceleration into the final "snap" onto the pin).

### `src/components/SatelliteMap.tsx`
Thin wrapper: creates the MapLibre map exactly once (Esri World Imagery
raster tiles, no API key needed), disables every manual interaction
(`dragPan`, `scrollZoom`, `boxZoom`, `doubleClickZoom`, `touchZoomRotate`,
`keyboard`), and hands the live instance up to the parent via
`onMapReady`. Takes `initialTarget` only for the very first paint — all
movement after mount goes through `useMapCamera`.

### `src/components/CloudTransition.tsx`
A brief (~300ms in, ~900ms out) two-layer grey smoke "puff"
(`CloudPhase = "idle" | "covering" | "clearing"`) that masks only the very
start of a camera switch. The five-phase flight itself is always fully
visible underneath — the puff is a stylistic flourish, not a cover for
the whole flight.

---

## Chat feed, scroll behavior & orchestration (`src/app/page.tsx`)

Each conversation turn renders as **two full-height, scroll-snapped
sections** (`data-section="landing"` and `data-section="result"`):

- **Landing section**: the user's prompt bubble plus a bouncing
  chevron-down hint. This is where the camera lands first.
- **Result section**: the answer card, only reached by scrolling further
  down. It fades/slides in (`translate-y-10 opacity-0` → `translate-y-0
  opacity-100`) once its own section scrolls into view.

A single `IntersectionObserver` (`threshold: 0.5`) watches both kinds of
section: a landing section becoming visible calls `recallCamera` (a quick
`flyToSimple`, 900ms); a result section becoming visible sets
`revealedTurnId`, triggering that card's reveal animation.

Key functions in `page.tsx`:
- `runCloudFlight(location, turnId)` — the shared entry point for every
  "real" camera switch (submit, retry, chat switch). Locks the starting
  vector via `camera.cancelFlight()` + `camera.getCurrentPosition()`,
  starts the cloud puff, and kicks off `camera.runFivePhaseFlight(...)`.
- `scheduleCameraFlight(location, turnId)` — wraps `runCloudFlight` in a
  randomized 60–300ms delay to simulate AI routing/processing time before
  the camera commits to a destination. Used by `handleSubmit` and
  `handleRetry`.
- `resetMapToOcean()` — cancels all pending camera/cloud work and flies
  back to `IDLE_VIEW` with the marker hidden. Called by `handleNewChat`
  and by `handleSelectSession` whenever the target chat is empty.
- `handleSelectSession(id)` — switching to an empty chat always resets to
  the ocean view; switching to a chat with turns runs the same
  `runCloudFlight` to that chat's latest turn (never the abbreviated
  recall), and never gets stuck mid-flight on the chat just left.
- `jumpToTurn(turnIndex)` — used by the up/down nav arrows; scrolls to a
  turn's landing section and recalls the camera there.
- Up/down arrow buttons (`ChevronUp`/`ChevronDown`, fixed to the right
  edge) appear only when there is a turn above/below the current one.

---

## Sidebar (`src/components/Sidebar.tsx`)

- Collapsible (`72px` / `288px`), searchable chat list.
- Each chat row reveals Pin / Rename / Delete icons on hover (always
  visible when pinned). Pinned chats sort to the top of the list.
- Rename is inline (row turns into a text input, `Enter` to save, `Esc` to
  cancel). Delete asks for confirmation via `window.confirm`.
- "Library" button opens the `LibraryDrawer`.

## Library (`src/components/LibraryDrawer.tsx`)

A right-side drawer listing every past turn across all chat sessions —
query text, attached thumbnails, detected-task badge, confidence, and
timestamp — read directly from existing in-memory session state (no
separate persistence layer).

## Message actions (`src/components/MessageActions.tsx`)

Rendered under each answer card: **Copy** (writes the answer to the
clipboard, swaps to a checkmark for 1.5s) and **Retry** (re-runs
`handleRetry`, replaying the full camera choreography for that turn).

## Query input & image upload

- `QueryInput.tsx` — the floating glass pill, horizontally centered
  within the non-sidebar workspace (its wrapper spans `left: sidebarWidth`
  to `right: 0`, so it stays centered as the sidebar collapses/expands).
  Owns the suggestion-chip popover and the attach popover.
- `ImageUpload.tsx` — the attach popover (dropzone + thumbnail grid) and
  `AttachmentChips` (the compact preview strip shown above the pill once
  images are attached). Thumbnails use a fixed-height, natural-width box
  (`h-14` container matching an `h-14` image) so previews never overflow
  or force a square crop.

## Offline demo fallback (`src/lib/mockResults.ts`)

If the backend call in `useAnalysis` fails, the turn is completed with a
scripted `AnalysisResponse` (one for each of Mumbai/DC, London reuses the
DC result) instead of showing a raw error — this keeps the full camera
choreography and result-card UI demoable without a live backend.

## Data contracts (`src/types/api.ts`)

Unchanged mirror of the backend schema, plus one Phase 2 addition:
`ChatSession.pinned?: boolean` for the sidebar pin feature.
