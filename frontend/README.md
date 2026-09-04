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
| Synthetic analysis layers (Structural Changes / Spectral Bands PNGs) | Procedural blob overlay + channel remap | ⚠️ **Stub, flagged for removal** | `raster_stub.py::generate_layers` fabricates these two layers deterministically — not a real change-detection or spectral model. Tracked in [`docs/HARDCODED.md`](./docs/HARDCODED.md) as a pending cleanup, same category as the already-removed hardcoded water-mask demo |
| Health/diagnostics surface | `GET /api/health` | ⚠️ **Backend exists, unused by UI** | Returns `models_loaded`, `gpu_available`, `gpu_memory_used`, `registered_models` — not yet called from any frontend component. This is the natural integration point for the **Debug Mode** work this branch (`feature/phase-4-debug-mode`) exists to build |

**Why this matters for frontend work:** every UI surface that displays a model result (`ResultPanel`, `ExecutionTrace`, `LayerSwitcher`) is already built to render an honest "nothing here yet" state — empty evidence lists, hidden confidence badges, hidden layer tabs — rather than assuming a real model backs it. Wiring in a real model should require zero frontend changes beyond whatever richer data it starts returning.

---

## 3. Backend Integration & Handshake Protocol

Every conversational turn is driven by **two independent, parallel backend calls** — one for the actual answer, one for where to point the camera — plus a chain of frontend-only fallbacks when either is unreachable. Nothing in this handshake ever blocks the other: the analysis answer and the camera's destination can (and often do) resolve at different times.

| # | Trigger (frontend event) | Backend endpoint | Backend returns | Frontend action |
|---|---|---|---|---|
| 1 | User submits a query (with or without images) | `POST /api/analyze` — `multipart/form-data`: `images[]`, `query`, `modalities`, `dates?` | `AnalysisResponse` — `{ answer, confidence: number \| null, evidence: { images[], regions[] }, execution_trace }` | `useAnalysis` attributes the result to the triggering turn via `pendingTurnRef`; `ResultInspectorPanel` reveals with a typewriter-animated answer, a confidence badge (or "Not scored" if `null`), the evidence grid, and the collapsible `ExecutionTrace` |
| 2 | Same submit, **only if ≥1 image attached** | `POST /api/process-raster` — `multipart/form-data`: `image` | `ProcessRasterResponse` — `{ bbox, center, zoom, layers: {base, structural_changes, spectral_bands}, source: "geotiff-tags" \| "synthetic" }` | Drives the 5-phase cinematic camera flight to `center`/`zoom`, then `fitBounds`-locks onto the real `bbox`; shows the raster overlay, `FocusMask`, and `LayerSwitcher` once layers exist |
| 3 | `/api/process-raster` fails (backend down/unreachable) | *(no response)* | — | **Fallback tier 1:** `geotiffClient.ts::extractGeoTiffLocation` reads real GeoTIFF geo-tags client-side (`geotiff` + `proj4`) — camera still flies to the file's true location, no generated layer imagery |
| 4 | Tier 1 also fails (no usable geo-tags, or non-GeoTIFF file) | — | — | **Fallback tier 2:** `syntheticLocation.ts::syntheticRasterFallback` derives a deterministic per-file bbox from a filename/size hash — camera has *somewhere* real-feeling to go rather than freezing |
| 5 | `/api/analyze` fails at the network level (no HTTP response at all) | *(no response)* | — | `useAnalysis` surfaces `"Couldn't reach the backend at {API} — make sure it's running."` as an inline error in `ResultPanel`; no camera impact |
| 6 | User submits with **0 images** | `POST /api/analyze` with `images=[]` | `AnalysisResponse` from the router's dedicated text-only VQA path | `settleOnTextOnlyTurn()` — camera is deliberately left untouched (no panning when there's nowhere real to pan to); `/api/process-raster` is never called for this turn |
| 7 | *(not yet wired)* | `GET /api/health` | `{ status, models_loaded[], gpu_available, gpu_memory_used?, registered_models? }` | No current consumer — this is the intended hook for Debug Mode to surface real backend/model state instead of inferring it from response shape |

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
    "structural_changes": "/results/a1b2c3d4/raster_structural_changes.png",
    "spectral_bands": "/results/a1b2c3d4/raster_spectral_bands.png"
  },
  "source": "geotiff-tags"
}
```

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
                                                     hardcoded water-mask removed) ahead of
                                                     building Debug Mode
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
