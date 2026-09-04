# SAT_Query Frontend — Component Documentation (Phase 2)

> Covers `feature/phase-2-glass-scroll-animation`. Ground truth for
> payload shapes is `backend/app/api/schemas.py`; this doc mirrors it via
> `src/types/api.ts`. See `CHANGELOG.md` for the full narrative writeup of
> this phase.

## Architecture

```text
src/
├── app/
│   ├── page.tsx              — owns session/turn state, wires the camera
│   │                            system to chat submit/retry/scroll events
│   ├── layout.tsx            — html/body sizing, fonts
│   └── globals.css           — dark theme tokens, cloud-drift keyframes
├── components/
│   ├── SatelliteMap.tsx       — creates the MapLibre map once, hands the
│   │                            instance to the parent via `onMapReady`
│   ├── CloudTransition.tsx    — brief smoke puff overlay at flight start
│   ├── Sidebar.tsx            — session list: search, pin, rename, delete
│   ├── LibraryDrawer.tsx      — read-only log of every past turn
│   ├── QueryInput.tsx         — floating glass pill, prompt + suggestions
│   ├── ImageUpload.tsx        — attach popover + compact attachment chips
│   ├── ResultPanel.tsx        — answer, confidence badge, evidence grid
│   ├── ExecutionTrace.tsx     — collapsible agent trace
│   └── MessageActions.tsx     — copy / retry buttons under each answer
├── hooks/
│   ├── useAnalysis.ts         — POST /api/analyze via axios (pre-existing)
│   └── useMapCamera.ts        — imperative MapLibre camera controller
├── lib/
│   ├── mapLocations.ts        — MUMBAI / WASHINGTON_DC / LONDON / OCEAN_START
│   ├── flightPlan.ts          — distance/zoom/duration math for flights
│   └── mockResults.ts         — offline fallback AnalysisResponse data
└── types/
    └── api.ts                 — TS mirror of backend/app/api/schemas.py
```

State flow: `page.tsx` owns `sessions: ChatSession[]`, `activeSessionId`,
`draftQuery`/`draftImages`, and the camera/animation state
(`cloudPhase`, `activeTurnId`, `revealedTurnId`). It calls
`analyze(...)` from `useAnalysis` and attributes the result back to
whichever turn triggered it via `pendingTurnRef`. All map movement is
delegated to the `useMapCamera` hook — `page.tsx` never touches the
MapLibre instance directly.

## Styling system

- Background: `bg-slate-950` (`#020617`) everywhere; `html`/`body` match
  it exactly to avoid any seam at the page edge.
- Glass panels: `bg-slate-900/60`–`/80` (or `bg-slate-800/80` for the
  user's own chat bubble) with `backdrop-blur-xl` and `border-white/10`–
  `/12`, standardized across every floating surface — sidebar, popovers,
  cards, library, the query pill.
- Corners: `rounded-3xl` (24px) for primary containers (result card,
  execution trace, upload popover, library entries, attachment chips);
  smaller nested elements use `rounded-2xl`/`rounded-xl`. Chat bubbles add
  a single sharp corner (`rounded-tl-sm` / `rounded-tr-sm`) for the
  iMessage tail effect.
- Accent color is neutral — status color (confidence, warnings,
  step success/error) uses `emerald`/`amber`/`rose` sparingly.
- The satellite map sits at `z-0`, the cloud puff at `z-20`, the chat feed
  at `z-10`, and the sidebar/query pill/nav arrows/library at `z-30`/`z-40`.

## Component reference

### `SatelliteMap`

```ts
interface SatelliteMapProps {
  initialTarget: MapTarget; // only used for the very first paint
  onMapReady: (map: maplibregl.Map) => void;
}
```

- Creates the map exactly once (mount-only effect), using Esri World
  Imagery raster tiles (free, no API key).
- Disables all manual interaction (`dragPan`, `scrollZoom`, `boxZoom`,
  `doubleClickZoom`, `touchZoomRotate`, `keyboard`) — the camera is
  strictly synced to chat/scroll state, never user-dragged.
- Renders as a `fixed inset-0` div behind everything else. Note:
  `maplibre-gl.css` ships `.maplibregl-map { position: relative }`, which
  ties with Tailwind's `.fixed` at equal specificity — position is forced
  via an inline `style` so it always wins the cascade.
- Does **not** re-fly reactively on prop changes after mount; all
  subsequent camera control goes through `useMapCamera`.

### `useMapCamera` (hook)

```ts
function useMapCamera(): {
  setMap: (map: maplibregl.Map) => void;
  cancelFlight: () => void;
  getCurrentPosition: () => { center: [number, number]; zoom: number };
  flyToSimple: (target: MapTarget, options?: { showMarker?: boolean }) => void;
  runFivePhaseFlight: (
    startCoords: [number, number],
    startZoom: number,
    targetCoords: [number, number],
    targetZoom: number,
    onComplete?: () => void
  ) => void;
};
```

- Holds the map instance and the red target marker in refs; nothing here
  is React state, so there is no re-render on every animation frame.
- `cancelFlight()` calls `map.stop()` and bumps an internal flight id —
  call this (or a function that calls it, like `flyToSimple` /
  `runFivePhaseFlight`) before starting any new movement so a stale
  flight's pending phases can never fire on top of a new one.
- `runFivePhaseFlight` is the cinematic 5-phase sequence described in
  `CHANGELOG.md`; `flyToSimple` is the plain single-leg move used for
  scroll recall and the ocean reset.

### `CloudTransition`

```ts
type CloudPhase = "idle" | "covering" | "clearing";
interface CloudTransitionProps { phase: CloudPhase; }
```

Renders `null` when idle. A brief two-layer grey smoke overlay otherwise —
purely decorative, masks only the first ~300ms of a flight.

### `Sidebar`

```ts
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
}
```

- Pinned sessions sort first; search filters by title.
- Hover reveals Pin/Rename/Delete per row (Pin stays visible once pinned).
  Rename swaps the row for an inline `<input>`; Delete confirms via
  `window.confirm` before calling `onDeleteSession`.

### `LibraryDrawer`

```ts
interface LibraryDrawerProps {
  open: boolean;
  onClose: () => void;
  sessions: ChatSession[];
}
```

Read-only right-side drawer. Flattens every session's turns into one
list (query, thumbnails, detected task, confidence, timestamp) — no
separate storage, just a view over the same session state `page.tsx`
already holds.

Animated via `AnimatePresence`: backdrop fades in/out (`duration: 0.2`),
panel slides from the right (`x: "100%" → 0`, spring `stiffness: 300,
damping: 30` — matching `ResultInspectorPanel`'s turn-card timing). Surface
styling (`bg-slate-900/40 backdrop-blur-xl border-white/10 text-slate-200`)
deliberately mirrors `Sidebar.tsx`'s `<aside>` via a shared `PANEL_SURFACE`
constant, so the two docked glass panels read as one visual family. See
`CHANGELOG.md`'s Library section for why this replaced an unanimated
`if (!open) return null`.

### `QueryInput`

```ts
interface QueryInputProps {
  query: string;
  onQueryChange: (value: string) => void;
  images: UploadedImage[];
  onImagesChange: (images: UploadedImage[]) => void;
  onSubmit: () => void;
  loading: boolean;
  sidebarWidth: number; // px, so the pill centers in the non-sidebar pane
}
```

- Fixed pill (`bottom-6`), spanning `left: sidebarWidth` to `right: 0`
  with an inner `mx-auto max-w-3xl`, so it stays centered in the map
  viewport as the sidebar collapses/expands.
- `Enter` submits, `Shift+Enter` inserts a newline; suggestion chips
  filter live as the user types.

### `ImageUpload` / `AttachmentChips`

```ts
interface ImageUploadProps {
  images: UploadedImage[];
  onChange: (images: UploadedImage[]) => void;
  maxImages?: number; // default 2
  onRequestClose?: () => void;
}
```

- `ImageUpload` is the attach popover (dropzone + 2-column thumbnail
  grid); `AttachmentChips` is the compact strip shown above the pill once
  images exist, independent of whether the popover is open.
- Chip thumbnails use a fixed-height container (`h-14`) matched exactly
  to the image's own height, so previews keep their natural aspect ratio
  without overflowing the chip or being force-cropped to a square.

### `ResultPanel`

```ts
interface ResultPanelProps {
  result: AnalysisResponse | null;
  loading: boolean;
  error: string | null;
}
```

- Renders `result.answer`, a confidence badge (`≥0.8` emerald / `≥0.5`
  amber / else rose), `result.evidence.images` as a 2-col grid, and
  `result.evidence.regions` as a labeled confidence list.
- Four mutually exclusive states: skeleton (`loading`), inline error
  (`error`), empty state (`!result`), populated result.

### `ExecutionTrace`

```ts
interface ExecutionTraceProps { trace: ExecutionTraceData | null; }
```

- Returns `null` until a trace exists. Closed by default; header always
  shows `detected_task`, task confidence, and total latency. Expanded
  body shows reasoning, validation summary, and per-step status/timing.

### `MessageActions`

```ts
interface MessageActionsProps {
  text: string | null;      // null hides the Copy button
  onRetry: () => void;
  retryDisabled?: boolean;
}
```

Copy writes `text` to the clipboard and shows a checkmark for 1.5s; Retry
calls the parent's retry handler (which re-runs the analysis and replays
the full camera choreography for that turn).

## Wiring (`page.tsx`)

- Each turn renders as two scroll-snapped sections — `data-section=
  "landing"` (prompt only, camera lands here first) and `data-section=
  "result"` (the answer card, revealed only once scrolled into view).
- A single `IntersectionObserver` (`threshold: 0.5`) drives both: a
  landing section recalls the camera (`flyToSimple`, 900ms); a result
  section sets `revealedTurnId`, triggering that card's fade/slide-in.
- `runCloudFlight(location, turnId)` is the shared entry point for every
  "real" camera switch — submit, retry, and non-empty chat switches all
  go through it. It locks the starting vector (`cancelFlight` +
  `getCurrentPosition`), starts the cloud puff, and calls
  `runFivePhaseFlight`.
- `scheduleCameraFlight` wraps `runCloudFlight` in a randomized 60–300ms
  delay (simulated AI routing time) before submit/retry.
- `resetMapToOcean()` returns to `IDLE_VIEW` with the marker hidden —
  used by "New chat" and by switching to any empty chat.
- Up/down nav arrows (fixed to the right edge) jump between turns,
  scrolling to the target's landing section and recalling the camera.

## Testing instructions

1. **Install deps** (already in `frontend/package.json`):
   ```bash
   cd frontend
   npm install
   ```
2. **Env**: create `frontend/.env.local`:
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```
3. **Run backend** (optional — `lib/mockResults.ts` supplies a scripted
   answer for each location if the backend is unreachable):
   ```bash
   cd backend
   uvicorn app.main:app --reload --port 8000
   ```
4. **Run frontend**:
   ```bash
   npm run dev
   ```
   Open `http://localhost:3000`.
5. **Manual smoke test**:
   - Land on the blank ocean view, attach an image, submit a query →
     smoke puff, five-phase flight to Mumbai, scroll down to reveal the
     answer card.
   - Submit a follow-up → flight to Washington DC; a third → London.
   - Scroll back up through the feed → camera recalls each turn's
     location; use the up/down arrows as a shortcut.
   - Click Retry on a card → full choreography replays for that turn.
   - Pin/rename/delete a chat in the sidebar; open the Library drawer;
     click New Chat and confirm the map resets to the ocean view.
6. **Type check**:
   ```bash
   npx tsc --noEmit
   ```

---
---

# SAT_Query Frontend — Component Documentation (Phase 3 addendum)

> Covers `feature/phase-3-tiff-pipeline`, **appended on top of** the Phase 2
> reference above (nothing above this line changed meaning — `mapLocations.ts`
> and `mockResults.ts` it references were deleted this phase; see below).
> Ground truth for the new `/api/process-raster` payload shape is
> `backend/app/api/schemas.py`'s `ProcessRasterResponse`, mirrored in
> `src/types/api.ts`. For a consolidated list of every hardcoded/synthetic
> value across both phases, see `HARDCODED.md`.

## Updated architecture

```text
src/
├── components/
│   ├── FocusMask.tsx           — 4 blur/dim bands framing the sharp raster rect
│   ├── LayerSwitcher.tsx       — Base/Structural/Spectral/(Water Mask) tab pill
│   ├── PinnedQueryCard.tsx     — active turn's query pill, pinned over the map
│   ├── RadiantCard.tsx         — reusable localized blur-halo wrapper
│   └── ResultInspectorPanel.tsx — floating right-side result stack (replaces
│                                  Phase 2's in-flow result card)
├── hooks/
│   ├── useRasterOverlay.ts     — POST /api/process-raster + imperative
│   │                              MapLibre control for the raster/mask layers
│   └── useTypewriter.ts        — progressive word-reveal for the answer text
└── lib/
    ├── geotiffClient.ts        — client-side GeoTIFF tag/pixel reading
    ├── hardcodedMask.ts        — the "highlight the water body" demo overlay
    └── syntheticLocation.ts    — last-resort per-file synthetic bbox
```

`lib/mapLocations.ts` (the Mumbai/DC/London scripted tour) and
`lib/mockResults.ts` (the offline-mock-answer fallback) are **deleted** —
`MapTarget` now lives in `hooks/useMapCamera.ts` itself, and a failed
`/api/analyze` call surfaces a real error instead of a scripted answer.

State flow addition: `page.tsx` now also owns `activeRaster`,
`hasBaseLayers`, `waterMaskAvailable`, `activeLayerKey`, and `focusRect`,
plus two imperative refs mirroring the per-turn map: `turnRasterDataRef`
(each turn's resolved `ProcessRasterResponse`) and `turnWaterMaskRef` (each
turn's hardcoded mask object URL, if the query triggered one). All raster/
mask map control is delegated to `useRasterOverlay`, the same way
`useMapCamera` already owns all camera control — `page.tsx` never touches
MapLibre sources/layers directly.

## Component reference — new in Phase 3

### `useRasterOverlay` (hook)

```ts
function useRasterOverlay(): {
  setMap: (map: maplibregl.Map) => void;
  processRaster: (file: File) => Promise<ProcessRasterResponse>;
  showRaster: (bbox: RasterBBox, layers: RasterLayers, active?: LayerKey) => void;
  setActiveLayer: (active: LayerKey) => void;
  hideRaster: () => void;
  getScreenRect: (bbox: RasterBBox) => { left: number; top: number; right: number; bottom: number } | null;
  showWaterMask: (bbox: RasterBBox, url: string) => void;
  hideWaterMask: () => void;
  resolveUrl: (path: string) => string;
};
```

- Adds/updates three stacked MapLibre `image` sources (`raster-base`,
  `raster-structural`, `raster-spectral`) plus a separate
  `raster-water-mask` source for the hardcoded overlay. Existing sources are
  updated in place (`setCoordinates` + `updateImage`) rather than
  removed/re-added, avoiding a flash when a turn is revisited.
- `setActiveLayer` only flips `raster-opacity` (0/1) per layer — MapLibre's
  own `raster-opacity-transition: {duration: 300}` animates the crossfade;
  no camera movement, no manual rAF loop.
- `getScreenRect` projects the bbox's 4 corners with `map.project(...)` and
  returns their screen-space bounding rect, or `null` before the map is
  ready — the single source of truth `FocusMask`, the nav-arrow rail, and
  the wheel-cycle hover zone all read from (via `page.tsx`'s `focusRect`
  state, kept live by a `map.on("move", ...)` listener).

### `FocusMask`

```ts
interface FocusMaskProps {
  rect: { left: number; top: number; right: number; bottom: number } | null;
}
```

Renders `null` when `rect` is `null` (mirrors `CloudTransition`'s idle
convention). Otherwise 4 `fixed z-[5]` bands (`backdrop-blur-[0.7px]
bg-slate-950/2`) covering everywhere outside `rect` — left/right run full
viewport height; top/bottom are constrained to `rect`'s own left..right
span so no band double-covers a corner.

### `LayerSwitcher`

```ts
type SwitcherKey = LayerKey | "water_mask";
interface LayerSwitcherProps {
  visible: boolean;
  active: SwitcherKey;
  onChange: (key: SwitcherKey) => void;
  hasBaseLayers?: boolean;
  waterMaskAvailable?: boolean;
}
```

- Tab list is `[...(hasBaseLayers ? 3 base tabs : []), ...(waterMaskAvailable
  ? [waterMaskTab] : [])]` — a turn with only a hardcoded mask (backend
  never ran) shows just that one tab, not 3 dead ones pointing at imagery
  that doesn't exist.
- `onChange` only ever calls `useRasterOverlay`'s paint-property setters —
  never anything in `useMapCamera` — so switching tabs structurally cannot
  retrigger a camera flight.
- Supports a left/right swipe gesture (`drag="x"`, snaps back via
  `dragConstraints`) in addition to click; wheel-to-cycle was moved off this
  component and onto hovering the raster/mask area on the map itself (see
  `page.tsx::cycleActiveLayerFromWheel`).

### `PinnedQueryCard`

```ts
interface PinnedQueryCardProps {
  turn: ConversationTurn | null;
  rect: { left: number; top: number; right: number; bottom: number } | null;
  sidebarWidthPx: number;
  hidden: boolean;
}
```

Positioned `rect.top - 60` (clamped to a minimum of 16px from the top) so it
sits just above the framed raster extent; `hidden` (true once the same
turn's result section is revealed) drives its exit animation rather than
unmounting abruptly, since the query then continues to live inside
`ResultInspectorPanel`'s own header.

### `ResultInspectorPanel`

```ts
interface ResultInspectorPanelProps {
  turn: ConversationTurn | null; // revealedTurnId in page.tsx
  retryDisabled: boolean;
  onRetry: (turnId: string) => void;
}
// exports PANEL_SIDE_MARGIN = 24, PANEL_WIDTH = 440
```

Fixed-width (440px) floating right-side panel, vertically centered between
`PANEL_TOP_MARGIN` (40px) and `PANEL_BOTTOM_CLEARANCE` (200px, clears the
layer-switcher/chat-input cluster). Holds the query header + `ResultPanel` +
`ExecutionTrace` + (when Debug Mode is on) `DebugPanel` + `MessageActions` as
one internally-scrollable stack (`overflow-y-auto`, with a top/bottom
progressive-blur fade — two standalone sibling `div`s with their own
`mask-image`, not a mask on the scroll container itself, each shown only
when `scrollTop`/`scrollHeight`/`clientHeight` (tracked via a `scroll`
listener + `ResizeObserver`, the latter needed since expanding an
accordion changes `scrollHeight` with no `scroll` event) says there's
real content behind that edge — see
`CHANGELOG.md`'s rendering-bug-fixes section for why it has to be built that
way). Replaces Phase 2's in-flow result card entirely; the map/raster/focus-
mask remain visible on the left at all times.

### `RadiantCard`

```ts
interface RadiantCardProps {
  children: ReactNode;
  className?: string;
  haloInset?: number;   // default 32
  hideHalo?: boolean;   // default false
}
```

Generic wrapper: renders an unstyled `relative` div containing (1) an
optional blur-halo sibling (`-inset-{haloInset}`, `rounded-[3rem]`,
`backdrop-blur-2xl`, radial `mask-image` feathering the edge) positioned
*before* `children` in DOM order so it paints behind them, then (2)
`children` itself. Used by the chat input pill; deliberately *not* used by
the attach/upload popover (a halo read as a hazy smudge against busy
uploaded imagery there) or the suggestion popover (which manages its own
halo directly, outside `AnimatePresence`, for instant removal on close).

### `useTypewriter` (hook)

```ts
function useTypewriter(text: string | null | undefined, wordsPerTick?: number, tickMs?: number): string;
```

Defaults: 2 words per 28ms tick. Purely a client-side reveal effect over an
already-fully-arrived string — the backend has no real token streaming.

### `useMapCamera` — Phase 3 additions

```ts
flyToBoundsSimple(bounds: [[number, number], [number, number]], padding: FramePadding, durationMs?: number): void;
```

`fitBounds`-based counterpart to `flyToSimple`, used for scroll-driven
recall of a turn with real raster data so revisiting it reproduces the same
UI-aware framing as the original cinematic flight. `runFivePhaseFlight`
gained two optional trailing params (`targetBounds`, `padding`) — when both
are given, phase 5 ("precision lock") calls `fitBounds` against the real
bbox instead of a manual `flyTo(center, zoom)`.

## `lib/` reference — new in Phase 3

### `geotiffClient.ts`

- `extractGeoTiffLocation(file): Promise<ClientGeoTiffLocation | null>` —
  real GeoTIFF tag reading + WGS84/UTM reprojection, entirely client-side
  (`geotiff` + `proj4`), used as the fallback tier when
  `/api/process-raster` is unreachable.
- `getGeoTiffDimensions(file): Promise<{width, height} | null>` — tag-only
  (no pixel decode), succeeds even for compression codecs the library can't
  decode pixels for; used to size a placeholder mask.
- `decodeGeoTiffPreview(file, maxDim=1024): Promise<string | null>` —
  actual pixel decode to a PNG object URL, downsampled; returns `null` (not
  a throw) for an unsupported codec such as JPEG2000.

### `hardcodedMask.ts`

- `isWaterHighlightQuery(query): boolean` — regex trigger, see `HARDCODED.md`.
- `generateWaterBodyMaskUrl(sourceUrl): Promise<string>` — draws the fixed
  translucent ellipse over a real preview image.
- `generatePlaceholderMaskUrl(width, height): Promise<string>` — same
  ellipse over a flat slate background, for when no real preview could be
  decoded at all.

### `syntheticLocation.ts`

- `syntheticRasterFallback(file): ProcessRasterResponse` — deterministic,
  file-hashed bbox anchored to one of 3 fixed demo cities, with
  `layers.base` left empty as a signal to skip the raster overlay entirely.

## Updated component props

- **`QueryInput`** gained `layerSwitcherVisible`, `activeLayer`,
  `onActiveLayerChange`, `hasBaseLayers`, `waterMaskAvailable` (renders
  `LayerSwitcher` in its existing popover slot, above the pill) — also
  restructured internally around a single shared alignment wrapper for the
  suggestion popover and the input pill, see `CHANGELOG.md`.
- **`ResultPanel`** now runs `result.answer` through `useTypewriter` before
  rendering it.
- **`SatelliteMap`**'s `MapTarget` import moved from the now-deleted
  `lib/mapLocations.ts` to `hooks/useMapCamera.ts`, where the type is now
  defined.
