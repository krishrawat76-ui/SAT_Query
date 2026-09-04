# 🛰️ SAT_Query UI — Frontend Documentation

> Companion documents: [`docs/CHANGELOG.md`](./docs/CHANGELOG.md) (full build history, phase by phase), [`docs/COMPONENT_DOCS.md`](./docs/COMPONENT_DOCS.md) (exhaustive component/hook reference), [`docs/HARDCODED.md`](./docs/HARDCODED.md) (every stub/synthetic value, and what's since been removed). This README is the entry point; those three are the ground truth for anything it summarizes.

---

## 1. Overview & Architecture

**SAT_Query UI** is the frontend for an AI-powered multimodal satellite imagery analysis system. A user uploads one or two satellite images (optical and/or SAR, including GeoTIFF), asks a natural-language question about them, and the UI presents the agent's answer, its supporting evidence, and a transparent trace of how it reasoned — all staged on top of a live, cinematic 3D satellite map that flies to the imagery's real (or best-guess) geographic location.

Concretely, the frontend does three jobs at once:

1. **Chat surface** — a scroll-driven conversational feed (one turn per query), with a floating glass result panel, execution-trace inspector, and session/library management (pin, rename, delete, cross-session search).
2. **Geospatial visualization** — a MapLibre GL globe that is never manually controlled by the user; instead it's driven entirely by application state (`useMapCamera`), flying a 5-phase cinematic sequence to whatever location the current turn resolves to, overlaying the analyzed raster, dimming everything outside its extent, and exposing a tab switcher between analysis layers.
3. **Backend orchestration client** — every query fires two independent, parallel backend calls (the actual analysis, and a raster/geolocation resolution), and the UI is built to degrade gracefully through multiple fallback tiers when the backend is partially or fully unreachable, so the demo experience never simply breaks.

### High-level architecture

```text
┌─────────────────────────────── Browser ───────────────────────────────┐
│                                                                         │
│  page.tsx (orchestrator: session/turn state, camera + raster wiring)  │
│    ├── SatelliteMap.tsx ─── useMapCamera ─── useRasterOverlay          │
│    │      (MapLibre GL)      (5-phase flight)   (image layers, focus  │
│    │                                              rect projection)    │
│    ├── QueryInput.tsx ─── ImageUpload.tsx / LayerSwitcher.tsx         │
│    ├── ResultInspectorPanel.tsx ─── ResultPanel / ExecutionTrace       │
│    ├── PinnedQueryCard.tsx / FocusMask.tsx / CloudTransition.tsx      │
│    └── Sidebar.tsx / LibraryDrawer.tsx                                 │
│                                                                         │
└───────────────┬───────────────────────────────────────┬───────────────┘
                │ POST /api/analyze                     │ POST /api/process-raster
                │ (multipart: images + query + …)       │ (multipart: image)
                ▼                                        ▼
┌─────────────────────────────── FastAPI Backend ────────────────────────┐
│ InputValidator → RuleBasedRouter → PipelineExecutor → OutputIntegrator │
│                         │                    │                         │
│                         ▼                    ▼                         │
│              Model Registry (VQA / Grounding / Change / Fusion)        │
│                                                                         │
│  raster_stub.py: GeoTIFF tag extraction + reprojection, or synthetic  │
│                  bbox fallback; generates base/structural/spectral    │
│                  layer PNGs                                            │
└──────────────────────────────────────────────────────────────────────┘
```

### Frontend directory structure

```text
frontend/src/
├── app/
│   ├── page.tsx              — owns all session/turn/camera/raster state;
│   │                            the single orchestrator every other piece
│   │                            plugs into
│   ├── layout.tsx, globals.css
├── components/
│   ├── SatelliteMap.tsx       — creates the MapLibre map once
│   ├── CloudTransition.tsx    — smoke-puff overlay at flight start
│   ├── FocusMask.tsx          — 4 blur/dim bands framing the raster rect
│   ├── LayerSwitcher.tsx      — Base / Structural Changes / Spectral Bands tabs
│   ├── PinnedQueryCard.tsx    — active turn's query, pinned over the map
│   ├── ResultInspectorPanel.tsx — floating right-side result stack
│   ├── RadiantCard.tsx        — reusable localized blur-halo wrapper
│   ├── QueryInput.tsx         — the chat input pill + suggestions + attach
│   ├── ImageUpload.tsx        — attach popover + attachment chips
│   ├── ResultPanel.tsx        — answer, confidence badge, evidence grid
│   ├── ExecutionTrace.tsx     — collapsible agent reasoning trace
│   ├── MessageActions.tsx     — copy / retry
│   ├── Sidebar.tsx            — session list (search, pin, rename, delete)
│   └── LibraryDrawer.tsx      — read-only cross-session turn log
├── hooks/
│   ├── useAnalysis.ts         — POST /api/analyze client
│   ├── useMapCamera.ts        — imperative MapLibre camera controller
│   ├── useRasterOverlay.ts    — POST /api/process-raster client + raster layers
│   └── useTypewriter.ts       — progressive word-reveal for answer text
├── lib/
│   ├── flightPlan.ts          — distance/zoom/duration math for camera flights
│   ├── geotiffClient.ts       — client-side GeoTIFF tag reading + reprojection
│   └── syntheticLocation.ts   — last-resort per-file synthetic bbox
└── types/
    └── api.ts                 — TS mirror of backend/app/api/schemas.py
```

---

## 2. Machine Learning & Backend Capabilities Required

The frontend is built against the full model stack specified in [`docs/workflow/08-MODEL-RECOMMENDATIONS.md`](../docs/workflow/08-MODEL-RECOMMENDATIONS.md) (target hardware: a single RTX 4060, 8 GB VRAM — models are loaded, run, and unloaded one at a time, never all simultaneously). **Most of the ML layer is currently a stub**; the table below marks exactly what's real today versus what the UI is already wired to consume once it exists.

| Capability | Model / approach | Status | Notes |
|---|---|---|---|
| Input validation (count/format/modality checks) | Rule-based | ✅ **Implemented** | Real, deterministic — `InputValidator` |
| Task routing (VQA / Caption / Grounding / Change / Fusion) | Rule-based keyword router | ✅ **Implemented** | Real, deterministic, zero-VRAM — exactly the recommended POC approach. As of Phase 4, it no longer reports a fabricated confidence score alongside the routing decision |
| GeoTIFF coordinate extraction | Pillow geo-tags (backend) + `geotiff.js` (frontend) | ✅ **Implemented** | Real tag parsing on both sides |
| UTM → WGS84 reprojection | `pyproj` (backend) + `proj4` (frontend) | ✅ **Implemented** | Real — required because Sentinel-2 L2A products ship in a projected UTM CRS, not raw lat/lon |
| VQA & Captioning | Qwen2.5-VL-7B-Instruct-AWQ (~5.5 GB, 4-bit) | ⚠️ **Stub** | `QwenVLMWrapper` has a complete real-inference code path, but falls back to a synthesized, input-aware placeholder answer (`_mock_run`) since no model weights are downloaded in this environment |
| Change VQA (bi-temporal Q&A) | Shared Qwen2.5-VL backbone | ⚠️ **Stub** | Same fallback as above |
| Grounding (text → bounding box) | Grounding DINO Tiny (~0.7 GB) | ❌ **Not implemented** | `GroundingModel` always returns empty detections |
| Segmentation (box → mask) | SAM 2.1 Hiera Tiny (~0.35 GB) | ❌ **Not implemented** | `SegmentationModel` always returns zero regions |
| Change Detection (bi-temporal diff) | TinyCD (~0.15 GB) | ❌ **Not implemented** | Always returns `change_ratio: 0.0` |
| Optical–SAR Fusion (land-cover classification) | EfficientNet-B0 dual encoder (~0.5 GB, trained on BigEarthNet-MM) | ❌ **Not implemented** | Always returns an empty class distribution |
| Confidence scoring | — | ✅ **Implemented as "honest null"** | Phase 4 removed every fabricated confidence number (router, word-count heuristic, fixed `0.3` placeholders, integrator defaults) in favor of `null` whenever no real model produced a genuine score. The UI renders "Not scored" instead of a fake percentage |
| Synthetic analysis layers (Structural Changes / Spectral Bands PNGs) | — | ✅ **Implemented as "honest null"** | `raster_stub.py::generate_layers` used to fabricate these two layers (a fixed blob overlay and a fixed channel remap, drawn identically regardless of image content) — that fabrication has since been removed. Both are now returned as `null` since there is no real change-detection or spectral model in this repo to back them. `LayerSwitcher.tsx` renders a tab only when a layer's value is a real URL, so no tab appears for either today. See [`docs/HARDCODED.md`](./docs/HARDCODED.md) |
| Health/diagnostics surface | `GET /api/health` | ✅ **Backend exists; not yet consumed by the UI** | Returns `models_loaded`, `gpu_available`, `gpu_memory_used`, `registered_models`. Debug Mode (§6) surfaces the equivalent per-request state instead — `router_metadata`, `selected_models[].registered/.loaded`, and step timings straight from the execution trace — so this endpoint remains available for a future standalone health widget rather than being Debug Mode's data source |

**Why this matters for frontend work:** every UI surface that displays a model result (`ResultPanel`, `ExecutionTrace`, `LayerSwitcher`) is already built to render an honest "nothing here yet" state — empty evidence lists, hidden confidence badges, hidden layer tabs — rather than assuming a real model backs it. Wiring in a real model should require zero frontend changes beyond whatever richer data it starts returning.

---

## 3. Backend Integration & Handshake Protocol

Every conversational turn is driven by **two independent, parallel backend calls** — one for the actual answer, one for where to point the camera — plus a chain of frontend-only fallbacks when either is unreachable. Nothing in this handshake ever blocks the other: the analysis answer and the camera's destination can (and often do) resolve at different times.

| # | Trigger (frontend event) | Backend endpoint | Backend returns | Frontend action |
|---|---|---|---|---|
| 1 | User submits a query (with or without images) | `POST /api/analyze` — `multipart/form-data`: `images[]`, `query`, `modalities`, `dates?` | `AnalysisResponse` — `{ answer, confidence: number \| null, evidence: { images[], regions[] }, execution_trace }` | `useAnalysis` attributes the result to the triggering turn via `pendingTurnRef`; `ResultInspectorPanel` reveals with a typewriter-animated answer, a confidence badge (or "Not scored" if `null`), the evidence grid, and the collapsible `ExecutionTrace` |
| 2 | Same submit, **only if ≥1 image attached** | `POST /api/process-raster` — `multipart/form-data`: `image` | `ProcessRasterResponse` — `{ bbox, center, zoom, layers: {base, structural_changes, spectral_bands}, source: "geotiff-tags" \| "synthetic" }` | Drives the 5-phase cinematic camera flight to `center`/`zoom`, then `fitBounds`-locks onto the real `bbox`; shows the raster overlay, `FocusMask`, and `LayerSwitcher` once layers exist |
| 3 | `/api/process-raster` fails (backend down/unreachable) | *(no response)* | — | **Fallback tier 1:** `geotiffClient.ts::extractGeoTiffLocation` reads real GeoTIFF geo-tags client-side (`geotiff` + `proj4`) — camera still flies to the file's true location, no generated layer imagery |
| 4 | Tier 1 also fails (no usable geo-tags, or non-GeoTIFF file) | — | — | **Fallback tier 2:** `syntheticLocation.ts::syntheticRasterFallback` hashes the filename+size and picks one of 3 hardcoded real-world anchors (Mumbai, Washington DC, London) plus a small jitter — camera has *somewhere* real-feeling to go rather than freezing. **This is not geolocation** — the image content is never read; see the callout below the payload example |
| 5 | `/api/analyze` fails at the network level (no HTTP response at all) | *(no response)* | — | `useAnalysis` surfaces `"Couldn't reach the backend at {API} — make sure it's running."` as an inline error in `ResultPanel`; no camera impact |
| 6 | User submits with **0 images** | `POST /api/analyze` with `images=[]` | `AnalysisResponse` from the router's dedicated text-only VQA path | `settleOnTextOnlyTurn()` — camera is deliberately left untouched (no panning when there's nowhere real to pan to); `/api/process-raster` is never called for this turn |
| 7 | *(not called by any component)* | `GET /api/health` | `{ status, models_loaded[], gpu_available, gpu_memory_used?, registered_models? }` | No current consumer. Debug Mode (§6) gets its backend/model state per-request from `execution_trace` instead, so this stays free for a future standalone health widget |

### Payload contracts (mirrored 1:1 in `src/types/api.ts`)

```jsonc
// AnalysisResponse — POST /api/analyze
{
  "answer": "Built-up area increased in the eastern portion.",
  "confidence": null,               // null unless a real model reports one (Phase 4)
  "evidence": {
    "images": [{ "type": "change_map", "url": "/results/abc/change.png", "caption": "Changes in red" }],
    "regions": []
  },
  "execution_trace": {
    "input_validation": { "image_count": 2, "format": ["GeoTIFF", "GeoTIFF"], "modality": ["optical", "optical"], "temporal": true, "cross_modal": false, "compatible": true, "warnings": [] },
    "detected_task": "change_detection",
    "task_confidence": null,        // the rule-based router never fabricates one
    "reasoning": "Bi-temporal input + general query → Change Detection pipeline",
    "selected_models": [{ "name": "change_detection", "version": "1.0" }],
    "pipeline_steps": [{ "step": 1, "model": "change_detection", "action": "generate_change_map", "status": "success", "time_ms": 12.4, "error": null }],
    "total_time_ms": 12.4
  }
}
```

```jsonc
// ProcessRasterResponse — POST /api/process-raster
{
  "bbox": { "north": 19.09, "south": 19.06, "east": 72.90, "west": 72.86 },
  "center": [72.8777, 19.076],
  "zoom": 14.2,
  "layers": {
    "base": "/results/a1b2c3d4/raster_base.png",
    // Always null today — no change-detection or spectral model exists in
    // this repo to produce them. See the capability table in §2.
    "structural_changes": null,
    "spectral_bands": null
  },
  "source": "geotiff-tags"
}
```

> **`source` is real but invisible today.** It's `"geotiff-tags"` when the
> location came from actually reading the file's own georeferencing, and
> `"synthetic"` for both fallback tiers (§3, rows 3–4) — including the
> anchor-city guess in `syntheticRasterFallback`, which never inspects the
> image content at all. No frontend component currently reads `.source` (a
> repo-wide grep for `.source` on this type turns up nothing), so a synthetic
> guess and a real geolocation render identically: same cinematic flight,
> same-looking bbox and marker. A viewer watching the camera confidently fly
> to Mumbai has no on-screen way to tell that from a real result — the field
> exists specifically to make that distinguishable, it's just not wired to
> anything yet.

---

## 4. Key UI Components & Design System

### Design system

- **Palette:** near-black slate (`bg-slate-950`, `#020617`) throughout, with `bg-slate-900/60–80` glass panels layered on top.
- **Blur:** `backdrop-blur-xl` standardized across every floating surface (sidebar, popovers, cards, the query pill).
- **Corners:** `rounded-3xl`/`rounded-2xl` for primary containers, progressively smaller radii for nested elements — matches Apple's own nesting convention.
- **Radiating halo pattern (`RadiantCard.tsx`):** floating cards over the busy satellite imagery get a localized, edge-feathered blur halo (a plain sibling `div` behind the card's own opaque surface, radially masked) instead of a global blur strip — scoped tightly per-card so overlapping halos of different radii never compound into a blotchy blur.
- **Known rendering quirks handled:** (1) `backdrop-filter` + `border-radius` + `overflow-hidden` fails to clip correctly on any element that also carries a CSS `transform` (breaks under Framer Motion's `animate`/`drag`) — fixed everywhere by splitting the transform-bearing wrapper from the rounded/blurred visual surface; (2) a CSS `mask-image` on an ancestor of `backdrop-filter` elements breaks backdrop-filter compositing entirely — avoided by never combining the two. See [`docs/CHANGELOG.md`](./docs/CHANGELOG.md) for the full writeups.
- **Camera is never user-controlled.** All MapLibre interaction (`dragPan`, `scrollZoom`, etc.) is disabled; the globe moves only in response to application state via `useMapCamera`.

### Component reference (abridged — see [`docs/COMPONENT_DOCS.md`](./docs/COMPONENT_DOCS.md) for full props/behavior)

| Component / Hook | Role |
|---|---|
| `SatelliteMap` | Creates the MapLibre map once, hands the instance up via `onMapReady` |
| `useMapCamera` | Imperative camera controller — the scripted 5-phase cinematic flight (breakout → macro ascent → traversal → approach → precision lock via `fitBounds`), plus `flyToSimple`/`flyToBoundsSimple` for quick recalls |
| `useRasterOverlay` | `POST /api/process-raster` client + imperative MapLibre control for the 3 stacked analysis-layer image sources, crossfaded via MapLibre's own opacity transitions |
| `CloudTransition` | Brief smoke-puff overlay masking only the first ~300ms of a camera switch |
| `FocusMask` | 4 blur/dim bands framing the sharp raster rect, so the analyzed extent reads as the focal point |
| `LayerSwitcher` | Floating glass tab pill (Base Map / Structural Changes / Spectral Bands), swipe + click + hover-wheel to cycle, never touches the camera |
| `PinnedQueryCard` | The active turn's query, pinned over the map during the "landing" stage |
| `ResultInspectorPanel` | Floating right-side panel holding the query header, `ResultPanel`, `ExecutionTrace`, and retry/copy actions as one scrollable stack — replaces an in-flow chat card so the map stays visible |
| `RadiantCard` | Reusable localized blur-halo wrapper (see Design System above) |
| `QueryInput` | The chat input pill — suggestions popover (Spotlight-style pop-in), attach popover, layer switcher slot |
| `ImageUpload` | Attach popover (dropzone + thumbnails) and the compact attachment-chip strip |
| `useTypewriter` | Purely client-side progressive word-reveal for an already-arrived answer string (the backend has no real token streaming) |
| `Sidebar` / `LibraryDrawer` | Session management (search/pin/rename/delete) and a read-only cross-session turn log |

---

## 5. Development Setup & Branch Structure

- **Framework:** Next.js (App Router), TypeScript, Tailwind CSS, MapLibre GL JS, Framer Motion, Lucide Icons, Axios.
- **Current active branch:** `feature/phase-4-debug-mode`

### Branch history

```text
main
 └─ phase-1-baseline                          — initial POC UI layout
     └─ feature/phase-2-glass-scroll-animation — dark glass redesign + scripted camera tour
         └─ feature/phase-3-tiff-pipeline      — real/synthetic raster overlay, layer switcher,
         │                                       floating result panel, water-mask demo (later removed)
         └─ feature/phase-4-debug-mode  ◄ current — fake-data cleanup (nullable confidence,
                                                     hardcoded water-mask removed), then
                                                     Debug Mode & Telemetry itself (§6):
                                                     backend trace telemetry (Stage 1) +
                                                     the frontend inspector UI (Stage 2)
```

### Installation

```bash
npm install
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Run the backend (optional for most UI work — the frontend degrades through the fallback tiers in §3 when it's unreachable):

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Run the frontend:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Verification

```bash
npx tsc --noEmit
```

See [`docs/COMPONENT_DOCS.md`](./docs/COMPONENT_DOCS.md)'s "Testing instructions" section for the full manual smoke-test checklist (submit → cinematic flight → scroll recall → retry → new chat → library/sidebar management).

---

## 6. Debug Mode & Telemetry (Phase 4)

A per-request inspector that surfaces exactly what the backend actually did —
which rule routed the query, which models it selected and whether they were
really registered/loaded, real load-vs-inference timing per pipeline step,
and (opt-in) the raw sanitized payload each step produced. See
[`backend/README.md`](../backend/README.md) for the server side of this
feature (the trace schema, the honest-data-contract rule, and a full real
`ExecutionTrace` example) — this section covers only how the frontend
consumes it.

### Toggle & data flow

```text
Sidebar.tsx (Bug icon, aria-pressed)
  → page.tsx: debugMode state (localStorage-persisted, hydration-safe — see below)
    → useAnalysis().analyze(images, query, modalities, debugMode)
      → axios GET/POST param ?debug=true  (never a form field — see §3)
        → backend attaches payload_snapshot/payload_bytes per step
    ← AnalysisResponse (with or without snapshots)
  → ResultInspectorPanel: debugMode && !turn.loading && (turn.result || turn.error)
    → DebugPanel (only mounted when that condition holds)
```

- **The toggle** lives in `Sidebar.tsx` as a ghost button with an active tint
  (`bg-white/10 text-amber-300` when on), matching the existing on-state
  language `Pin` already uses elsewhere in the sidebar rather than inventing
  a new switch-style control. It's icon-only when the sidebar is collapsed,
  with `aria-label="Debug Mode"` so it still has an accessible name.
- **Hydration safety** (`page.tsx`): `debugMode` is declared as
  `useState(false)` and hydrated from `localStorage.satquery.debug` inside a
  mount `useEffect` — deliberately *not* read inside a lazy `useState(() =>
  ...)` initializer. Next.js still prerenders this client component on the
  server, where the initializer would return `false`, while the client's
  first hydration render would return `true` for a user who'd previously
  turned it on. That mismatch reaches the DOM (the Debug button's className
  and `aria-pressed` differ), and React 19 responds by discarding the whole
  server-rendered tree and re-rendering the root from scratch on the client
  — a real bug this session hit and fixed, not a hypothetical.
- **`useAnalysis.ts`** takes `debugMode` as a plain fourth argument and
  passes it as an axios `params: { debug: true }` only when set — the
  `FormData` body is unaffected either way, so toggling Debug Mode never
  changes what bytes go over the wire for the multipart part of the request.
- **Rendering, including the failure case:** `ResultInspectorPanel` mounts
  `DebugPanel` whenever `debugMode` is on and the turn has *either* a result
  *or* an error — not only on success. A failed request still has a fully
  known client-side request shape (query, image names, modalities, whether
  `?debug` was sent), and a failure is exactly the moment this panel is most
  worth having open.

### Component reference

- **`DebugPanel.tsx`** — the collapsible container card. Composes
  `RouterMetricsHeader`, `ModelChoiceReasoner`, `PipelineWaterfall`, a
  "Where the time went" stage-timing strip, a step-payload-size summary, and
  two `RawPayloadViewer`s (request, response). Guards against a missing
  `execution_trace` (`result?.execution_trace ?? null`) — `useAnalysis`
  casts the response without runtime validation, so a malformed 200 from an
  older deploy or a proxy could otherwise throw and take down the whole
  page, for exactly the users who opened Debug Mode to diagnose that
  response. The constructed request-summary object is wrapped in `useMemo`
  for the same reason described for `RawPayloadViewer` below.
- **`RouterMetricsHeader.tsx`** — renders the real router chips
  (`router_type`, `rule_id`, `routing_time_ms`, `matched_keywords`, a
  `fallback rule` badge when `fallback_used`). For the LLM-planner fields
  (`planner_type`, `tokens_per_sec`, `prompt_tokens`, etc.), it does **not**
  render `0` or `—` when they're `null` — that would read as a real
  measurement of zero. Instead it shows an explicit sentence, gated on
  `router_type`: `"Not reported — this router is deterministic keyword
  matching, with no language model in the loop"` for the known
  `rule_based_keyword` router, or the more conservative `"Not reported by
  this router"` for any other `router_type` the component doesn't have
  specific knowledge of — asserting *why* a router it can't see the internals
  of reported nothing would be inventing a fact.
- **`ModelChoiceReasoner.tsx`** — one row per selected model: a status badge
  (`not registered` / `loaded` / `registered`, colored rose/emerald/neutral)
  from real `ModelRegistry` state, `vram_gb` (trimmed via
  `Number(v.toFixed(2))` to avoid rendering float noise like
  `3.9500000000000002`), and the mechanically-composed `selection_reason`
  string verbatim from the backend — never client-side prose.
- **`PipelineWaterfall.tsx`** — the per-step timing bars. Rendering rules,
  called out explicitly because they encode two real bugs this session found
  and fixed:
  - **Adaptive µs/ms formatting** (`formatMs`): microseconds when `<1ms`, 2
    decimals when `<10ms`, whole ms above that. The backend measures with
    `perf_counter` and rounds to 3 decimals; a flat `.toFixed(0)` would
    report tens-of-microseconds stub-model steps as a meaningless `"0ms"`.
  - **Zero-duration tick vs. floored bar:** a step with `time_ms === 0`
    renders a 0.5px tick marker (`title="Completed in under 1µs — too fast
    to measure"`), never a bar with a `MIN_BAR_PCT`-floored width — flooring
    a genuinely-zero duration would visually claim elapsed time that never
    happened. The floor only ever applies to a *non-zero* measurement that
    would otherwise be sub-pixel.
  - **Failure-bar clamping:** the executor `break`s the pipeline loop on the
    first failure, so a failed step is always last and, if it died during
    `load_time_ms`, has `inference_time_ms === 0` — which without clamping
    positions its bar at exactly `left: 100%`, clipped to invisibility by
    the track's `overflow-hidden` in the one case this timeline exists to
    surface. Fixed with `inferLeft = Math.min(startPct + loadPct, 100 -
    MIN_BAR_PCT)`, plus a dedicated rose-colored stub bar when a failed step
    has zero inference time, and the step's `error` text rendered beneath
    the row.
  - **`left`/`width`-only positioning, never `transform`:** every bar is
    positioned with plain `left`/`width` percentages. A CSS `transform` on a
    descendant of this card's `backdrop-blur-xl` ancestor would re-trigger
    the Chromium `backdrop-filter` + `border-radius` clipping bug already
    documented for `LayerSwitcher.tsx`/`PinnedQueryCard.tsx`/`QueryInput.tsx`
    (§4) — so the waterfall deliberately avoids the one CSS property known to
    break glass-panel clipping in this codebase.
  - When every step in a trace measured `0ms`, the component skips the
    per-step axis math entirely (`hasTimeline = measuredSpan > 0`) and shows
    a footer message instead of synthesizing a fake shared timeline that
    would render identical, meaningless stub bars.
- **`RawPayloadViewer.tsx`** — collapsible raw-JSON panel with a copy
  button, used for both the constructed request summary and the full parsed
  response. **The `useMemo` optimization**, called out explicitly: `page.tsx`
  updates `focusRect` on every rendered `'move'` frame of any camera flight
  (§1), so without memoizing `JSON.stringify(data, null, 2)` on `[data]`, an
  expanded Debug Panel would re-serialize a potentially multi-hundred-KB
  response dozens of times per second purely because the map was panning —
  a cost with zero relationship to whether the debug JSON itself changed.
  **Caveat for callers:** the memo only helps if `data` is referentially
  stable — `DebugPanel` passes its request-summary object through its own
  `useMemo` for exactly this reason; passing a fresh object literal
  (`{ query, images, ... }`) inline on every render would give `RawPayloadViewer`
  a new reference every time and defeat the memo entirely, silently
  reintroducing the same per-frame re-serialization cost this was written to
  avoid.

### Type mirroring (`src/types/api.ts`)

The file's own header states the rule: *"Mirrors backend/app/api/schemas.py
exactly — keep in sync with any backend schema change."* Two conventions
make that mirroring precise rather than approximate:

- **Nullable fields are always `T | null`, never optional `?:`.** A Pydantic
  `Optional[X] = None` field is *always present* in the JSON body — FastAPI
  serializes it as `"field": null`, not an omitted key. Typing it as an
  optional TS property (`field?: X`) would let calling code use a `"field"
  in obj` presence check that always succeeds, masking the real question
  ("is there a value?") behind a check that can't answer it. Declaring it
  `field: X | null` forces every consumer toward `obj.field ?? fallback` or
  `obj.field != null`, which is the check that's actually correct — and
  matches how every debug component above reads these fields (e.g.
  `RouterMetricsHeader`'s `meta.planner_type != null` gate).
- **`ModelTelemetry`'s 6 keys are always all present**, mirroring the
  backend's `_telemetry()` normalizer (`backend/app/output/trace.py`), which
  takes whatever partial dict a model wrapper sets on `last_telemetry` and
  fills every missing key with `None` before it reaches the response. The TS
  interface declares all 6 fields as required (`prompt_tokens: number |
  null`, not `prompt_tokens?: number | null`) — it can rely on that shape
  being complete because the backend actively guarantees it, not because the
  frontend defensively fills gaps itself.
- Every other Phase 4 addition (`PipelineStep.load_time_ms` /
  `.inference_time_ms` / `.model_was_cached` / `.started_at_ms` /
  `.payload_snapshot` / `.payload_bytes` / `.depends_on`, the full
  `RouterMetadata` split, `StageTimings`, `ImageComposition` /
  `InputComposition`) follows the same pattern: a field that's `null` here
  is `null` because the corresponding Pydantic field really is
  `Optional[...] = None` in `schemas.py`, never because the frontend
  couldn't be bothered to type it precisely.
