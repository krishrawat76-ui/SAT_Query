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

---
---

# Changelog — Phase 3: Dynamic Raster Overlay, Focus Mask & Layer Switcher

> Branch: `feature/phase-3-tiff-pipeline`. This section covers everything
> built **on top of** the Phase 2 build documented above — it does not
> replace it. Phase 3 replaces Phase 2's scripted 3-city tour
> (`mapLocations.ts`, now deleted) with a camera system driven by the
> *actual uploaded file*: a bbox extracted from real GeoTIFF geo-tags when
> present, or synthesized from the file itself otherwise. It also replaces
> the single in-flow result card with a floating side inspector panel, adds
> a raster layer switcher (Base / Structural Changes / Spectral Bands) plus
> a hardcoded "highlight the water body" demo mask, and closes out a long
> tail of glassmorphism/positioning polish. See `HARDCODED.md` for a
> consolidated, phase-by-phase list of every hardcoded/synthetic/stub value
> in the app (nothing here is a trained model).

## Backend: `/api/process-raster` stub

New endpoint `POST /api/process-raster` (`app/api/raster.py`, registered in
`app/main.py`), following the exact upload pattern already used by
`/api/analyze`. For an uploaded image it returns a 4-corner geographic
bounding box, a center/zoom, and three generated PNG layers.

- **`app/output/raster_stub.py::extract_bbox`** — real GeoTIFF
  georeferencing first: reads `ModelPixelScaleTag`(33550)/`ModelTiepointTag`
  (33922) via Pillow's `tag_v2`, and — new since the original Phase 3 plan —
  reprojects to WGS84 via `pyproj` when the file's `GeoKeyDirectoryTag`
  (34735) identifies a projected CRS (UTM zones, which is what real
  Sentinel-2 L2A products ship in). Falls back to a deterministic synthetic
  bbox (anchored to one of 3 fixed demo cities, hashed from the filename) for
  any file without usable geo-tags, or a projected CRS `pyproj` can't
  resolve.
- **`zoom_for_bbox`** — maps the bbox's longitude span to a MapLibre zoom.
  Originally clamped to `[14, 16]` (tuned only for ~1.2km synthetic demo
  chips); a real ~100km-wide tile was forced into that same tight range,
  zooming in far past what fit the image. Widened to `[2, 18]` as outer
  safety bounds only — the formula's own math now produces the correct
  zoomed-out value for a real large tile instead of being overridden by the
  floor.
- **`generate_layers`** — saves the original upload as `base.png`, plus two
  synthetic stand-ins: `structural_changes.png` (two fixed-position blob
  regions blended with a red tint — not a real change-detection model) and
  `spectral_bands.png` (a channel remap/roll standing in for false-color
  NIR/thermal). All three saved under the existing `results/{request_id}/`
  static mount.

## Backend: text-only queries & dynamic placeholder answers

- **`agent/router.py`** — a request with 0 images now routes to a dedicated
  conversational VQA path instead of being rejected; **`agent/validator.py`**
  no longer errors on an empty image list (`test_reject_no_images` renamed to
  `test_allow_no_images`).
- **`app/utils/synthesize.py`** (new) — every stub model
  (`vqa.py`, `grounding.py`, `change_vqa.py`, `optical_sar.py`) previously
  returned the literal fixed string `"Model output not available"` with
  `confidence: 0.0` regardless of input. Replaced with `synthesize_answer(...)`,
  which builds a templated sentence that actually echoes the real query text
  and uploaded filename(s) (still not a real model output — confidence is a
  fixed `0.3` in every case, not a genuine score).
- **`api/routes.py`** — uploaded temp files now keep their original filename
  (sanitized via `Path(...).name`) instead of a generic `image_0.png`, since
  the filename is now echoed back in synthesized answers.

## Frontend: raster overlay, focus mask & layer switcher

- **`hooks/useRasterOverlay.ts`** (new) — `processRaster()` POSTs to the new
  endpoint; imperative, ref-based MapLibre control (mirrors `useMapCamera`'s
  philosophy) for three stacked `image` sources/layers plus a separate
  hardcoded water-mask source, crossfaded via MapLibre's own
  `raster-opacity-transition` (300ms) — tab switches never touch the camera.
- **`components/FocusMask.tsx`** (new) — four `fixed` blur/dim bands framing
  the sharp raster rect (`backdrop-blur-[0.7px] bg-slate-950/2` — deliberately
  barely-there, "not the focus" rather than a heavy fog), sized to lock
  exactly to the rect's outer pixels with no corner overlap.
- **`components/LayerSwitcher.tsx`** (new) — floating glass tab pill (Base
  Map / Structural Changes / Spectral Bands, plus a frontend-only "Water
  Mask" tab when available), a `framer-motion` `layoutId` sliding highlight,
  and a swipe-to-switch drag gesture. Tabs are computed from
  `hasBaseLayers`/`waterMaskAvailable` independently, so a turn with only a
  hardcoded mask (backend down) shows just the one relevant tab instead of
  three dead ones. Layer cycling by mouse wheel was later moved off the pill
  itself and onto hovering the raster/mask area on the map (see `page.tsx`'s
  `cycleActiveLayerFromWheel`), since the two competed when both were wired
  to scroll.
- **`hooks/useMapCamera.ts`** — added `flyToBoundsSimple(bounds, padding,
  duration)`, a `fitBounds`-based counterpart to `flyToSimple` for recalling
  a turn's real bbox with UI-aware padding (`FramePadding`: separate
  top/bottom/left/right clearances so the query card and chat/switcher
  cluster are never overlapped). `runFivePhaseFlight`'s final "precision
  lock" phase now uses `fitBounds` against the real bbox (when available)
  instead of a manual `flyTo(center, zoom)` — letting MapLibre compute the
  exact frame itself rather than trusting a hand-derived zoom number.
- **Real-time position tracking** — `focusRect` (and everything derived from
  it: the focus mask, the wheel-cycle hover zone, the nav-arrow rail) used to
  update only once, via a `setTimeout` matching a flight's total duration,
  which made all of it appear frozen mid-flight then jump abruptly at the
  end. Fixed by adding a `map.on("move", ...)` listener in `page.tsx`'s
  `onMapReady` that recomputes `focusRect` on every rendered frame during any
  camera movement.

## Frontend: offline-capable location resolution (replaces the Phase 2 tour)

Three-tier fallback in `page.tsx::resolveRasterLocation`, used whenever a
turn has an attached image (text-only turns are unaffected and never call
any of this):

1. Real backend call (`/api/process-raster`) — also returns generated layer
   imagery.
2. **`lib/geotiffClient.ts`** — client-side GeoTIFF tag reading (via
   `geotiff` + `proj4`, mirroring the backend's own tag/reprojection logic)
   when the backend is unreachable. Handles WGS84 and UTM zones (computed
   directly from the EPSG code, no network lookup) — covers real Sentinel-2
   L2A products fully offline.
3. **`lib/syntheticLocation.ts`** — last resort: a deterministic,
   file-hashed bbox anchored to one of the same 3 demo cities Phase 2 used
   for its scripted tour, but now picked from the *uploaded file's own*
   name/size rather than the turn's position in the conversation, with no
   generated layer imagery (`layers.base` left empty as a signal to skip the
   overlay/switcher).

`lib/mapLocations.ts` and `lib/mockResults.ts` (Phase 2's scripted-tour and
offline-mock-answer modules) are deleted — no code path uses a turn's index
to pick a location anymore, and a failed `/api/analyze` call now surfaces a
real, actionable error (`useAnalysis.ts`: "Couldn't reach the backend at
{API} — make sure it's running.") instead of a scripted fake answer.

## Frontend: hardcoded "highlight the water body" demo

**`lib/hardcodedMask.ts`** (new) — when a submitted query matches
`isWaterHighlightQuery` (regex: contains "water" AND a highlight/show/
locate/find/mark/outline verb), a fixed translucent blue ellipse is drawn
over whatever preview image is available and stored per-turn
(`turnWaterMaskRef`), surfaced as an additional "Water Mask" layer-switcher
tab. This is a placeholder proving the masking pipeline end-to-end, **not**
a real segmentation model. See `HARDCODED.md` for the full detail (trigger
pattern, ellipse geometry, and the placeholder-background fallback for
undecodable files).

## Frontend: result presentation — floating panel replaces the in-flow card

- **`components/ResultInspectorPanel.tsx`** (new) — replaces Phase 2's
  in-flow result card with a floating, vertically-centered right-side panel
  (fixed width 440px) holding the query header, `ResultPanel`,
  `ExecutionTrace`, and `MessageActions` together as one scrollable stack, so
  the map/raster/focus-mask stay visible on the left at all times. Exports
  `PANEL_SIDE_MARGIN`/`PANEL_WIDTH` for reuse by other fixed-position UI
  (the nav-arrow rail) that needs to avoid overlapping it.
- **`components/PinnedQueryCard.tsx`** (new) — the active turn's query
  pill, pinned over the map during the "landing" stage (before scrolling to
  the result), positioned relative to the raster's on-screen rect. Exits
  once the same turn's result section is revealed (query moves into
  `ResultInspectorPanel`'s own header instead of existing in two places).
- **`components/RadiantCard.tsx`** (new) — reusable localized "radiating"
  blur halo (a plain sibling `div` behind the card's own opaque surface,
  edge-feathered via a radial `mask-image`) for floating glass surfaces over
  busy map imagery, replacing an earlier global full-width blur strip across
  the bottom of the screen. Used by the chat input pill (permanent halo,
  suppressed via `hideHalo` whenever the attach or suggestion popover is
  open, to avoid two overlapping halos of different radii compounding into a
  visibly blotchy blur).
- **`hooks/useTypewriter.ts`** (new) — reveals `result.answer` progressively,
  a couple words at a time, purely client-side (the backend returns one full
  JSON response, not a real token stream) — used by `ResultPanel`.

## Rendering-bug fixes (Chromium/WebKit)

Two non-obvious compositing bugs, hit and fixed in several places over the
course of this phase:

- **`backdrop-filter` + `border-radius` + `overflow-hidden` fails to clip
  correctly on an element that also carries a CSS `transform`** (which
  Framer Motion applies for any `animate`/`initial`/`drag` usage). Fixed by
  splitting the transform-bearing element (an outer, unstyled `motion.div`)
  from the rounded/blurred visual surface (an inner, static `div`) in three
  places: `QueryInput.tsx`'s suggestion popover, `PinnedQueryCard.tsx`'s
  pill, and `LayerSwitcher.tsx`'s draggable pill.
- **`mask-image` on an ancestor of `backdrop-filter` elements breaks
  backdrop-filter compositing** — cards render as solid/opaque instead of
  translucent the moment the mask becomes non-`none`. This was the root
  cause of a reported "transparency looks inconsistent after scrolling"
  bug; fixed by removing `ResultInspectorPanel`'s scroll-edge fade masking
  mechanism entirely in favor of a plain hard-clip `overflow-y-auto`.

## Query input & suggestion popover polish

- Suggestion popover pops in Spotlight-style (`framer-motion` spring:
  `scale 0.85→1`, `y 24→0`, origin pinned to the bottom edge it rises from).
- Popover and the input pill now share one unpadded, zero-offset reference
  box so their width/centering are pixel-identical by construction, rather
  than relying on two separate box-model calculations happening to agree.
- The popover's own blur halo is unmounted the instant it closes (kept
  outside `AnimatePresence`, conditioned directly on `suggestOpen`) instead
  of lingering through the card's own graceful exit animation.
- The attach/upload popover's `RadiantCard` halo was removed entirely
  (relies on `ImageUpload`'s own existing `backdrop-blur-xl`) — a blur halo
  read as a hazy, uneven smudge against the busy, high-contrast uploaded
  imagery it usually sits over, unlike the popover's mostly-uniform dark
  rows.

## Nav-arrow rail — final positioning

Went through several complete reversals of approach based on direct visual
feedback before landing on the current behavior (`page.tsx`, the up/down
`ChevronUp`/`ChevronDown` rail): fixed **8px** offset from the raster rect's
own left edge (not equidistant with the sidebar — that only coincidentally
looked right in the "result" stage), vertically centered on the rect itself,
with no CSS transition — position now comes directly from the same
per-frame `focusRect` updates described above, so it visibly tracks the
camera in real time instead of jumping once at the end of a flight. Falls
back to a fixed offset from `ResultInspectorPanel`'s own right edge when
there's no raster rect at all (a text-only active turn).

## Camera/sidebar timing sync

The sidebar-width-aware camera re-fit effect (re-frames the active turn
whenever the sidebar collapses/expands) originally ran a 500ms
`flyToBoundsSimple`, visibly mismatched against `Sidebar.tsx`'s own
`duration-300` CSS width transition — the map (and the nav arrow riding on
`focusRect`) kept sliding for ~200ms after the sidebar had already stopped,
reading as two disjointed phases of motion. Matched to exactly 300ms.

## Scroll/navigation race-condition fix

`recallCamera` was generalized to handle being reached via either a turn's
"landing" **or** "result" section (scrolling backward through turns reaches
the *previous* turn's result section before its own landing section, since
DOM order per turn is landing-then-result). Separately, `jumpToTurn` (the
up/down arrow handler)'s `scrollIntoView({behavior:"smooth"})` was found to
scroll *through* intermediate sections on the way to its target, each
crossing re-firing the scroll `IntersectionObserver` mid-transit and
redirecting the camera to the wrong turn — fixed by engaging the existing
`isTransitioningRef` guard for the duration of the programmatic scroll
(set *after* the `recallCamera` call, not before, since `recallCamera` itself
checks that same guard at its own top).
