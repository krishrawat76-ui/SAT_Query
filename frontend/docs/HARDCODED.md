# SAT_Query — Hardcoded & Synthetic Values (Testing/Demo)

> **Update (Phase 4, debug-mode prep):** a cleanup pass removed most of the
> "Stand-ins for missing real functionality" entries below — every
> fabricated confidence number, and the entire hardcoded water-mask demo
> feature — ahead of implementing Debug Mode, so fake-looking data can't be
> mistaken for real diagnostic signal. Entries below are marked
> **[REMOVED]** where this happened; the rest of each entry is kept for
> historical context (why the code once looked the way it did), not because
> it's still true. Anything not marked REMOVED is still present as
> described. One notable exception was deliberately **kept**: the synthetic
> per-file location fallback (both `raster_stub.py::_synthetic_bbox`/
> `ANCHORS` and `syntheticLocation.ts`) — without it the camera would have
> nowhere to fly for an unrecognized upload, so it stays until Debug Mode
> has a real "no location" state to show instead.

> Every place in the codebase — backend and frontend — that fakes, stubs,
> synthesizes, or fixes a value instead of computing/inferring it for real.
> Organized by the phase each was introduced in. Companion to `CHANGELOG.md`
> (the narrative of *what was built*) and `COMPONENT_DOCS.md` (the reference
> of *what each piece does*) — this file exists so nothing here is mistaken
> for real model output, real geodata, or a load-bearing design decision when
> a real pipeline eventually replaces it.

Two kinds of entries appear below:
- **Stand-ins for missing real functionality** — a value that pretends to be
  a model's or a service's real output. These are the ones that matter most
  to replace.
- **Fixed tuning constants** — a literal pixel/ms/degree number picked by
  eye for animation or layout. Not "fake" in the same sense, but still a
  number someone should know is arbitrary, not derived, if the surrounding
  design changes.

---

## Phase 1 — Backend POC (M3 handoff, pre-dates this UI entirely)

All of the following live in `backend/app/`. Original context: M3 (agent/
router) built the pipeline shell before M4 (ML pipelines) had real model
weights to plug in, so every model class is a placeholder wrapper. Still
current except where a later phase changed them (noted inline).

### Stand-ins for missing real functionality

- **[REMOVED] `agent/router.py` (`RuleBasedRouter`)** — task classification
  is still pure keyword matching (`GROUNDING_KW`, `CAPTION_KW`, `CHANGE_KW`,
  `SPECIFIC_QUESTION_PREFIXES` word lists — that part is real logic, not
  fake data, and is unchanged), but `RoutingDecision` used to also carry a
  **fixed, hand-picked confidence** regardless of how the match was made:
  grounding `0.95`, caption `0.90`, change-VQA `0.90`, change-detection
  `0.90`, optical-SAR `0.92`, default VQA `0.85`, text-only VQA `0.7`. The
  `confidence` field was removed from `RoutingDecision` entirely (Phase 4) —
  a deterministic rule-based classifier has no real notion of "how sure" it
  is, so it no longer fabricates one; `reasoning` (a real string, unchanged)
  carries the actual justification. `ExecutionTrace.task_confidence` (the
  wire-facing field this fed) is now `Optional[float] = None`, always `None`
  coming from this router.
- **`models/grounding.py` (`GroundingModel`)** — always returns **empty**
  `boxes`/`scores`/`labels` (`# No model available — return empty
  detections`). No Grounding DINO inference happens at all; `_extract_target`
  is a fixed prefix-stripping heuristic (`"highlight the "`, `"show the "`,
  etc.), not NLP.
- **`models/grounding.py` (`SegmentationModel`)** — reads `context
  ["intermediate"]["step_1"]`'s (always-empty) boxes, so it always draws
  **zero** boxes via `overlay_bboxes`, then returns `evidence_images: []`,
  `regions: []`. No SAM inference happens.
- **`models/change_detection.py` (`ChangeDetectionModel`)** — despite the
  class docstring's claim ("generates a random but plausible change mask"),
  the actual `run()` returns **fixed zeros**: `change_ratio: 0.0`,
  `changed_pixels: 0`, `total_pixels: 0`, `evidence_images: []`. No TinyCD
  inference, and not even the random mask the docstring describes.
- **`models/optical_sar.py` (`OpticalSARFusionModel`)** — `CLASS_NAMES`
  (`Built-up`/`Water`/`Vegetation`/`Bare soil`/`Agriculture`) and
  `CLASS_COLORS` are fixed constants for a land-cover legend that's never
  actually populated — `run()` always returns `classes: {}`,
  `evidence_images: []`. No EfficientNet-B0 fusion inference happens.
- **[REMOVED] `models/vqa.py` (`QwenVLMWrapper._estimate_confidence`)** —
  confidence for a *real* Qwen answer used to be a **word-count heuristic**,
  not a model probability: `>50 words → 0.88`, `>30 → 0.82`, `>15 → 0.75`,
  `>5 → 0.65`, else `0.50` (empty answer → `0.3`). Longer ≠ more correct —
  the method was deleted entirely (Phase 4); every `QwenVLMWrapper` code
  path (real inference and `_mock_run`) now returns `confidence: None`.
- **Every stub model pre-Phase-3** returned the literal fixed string
  `"Model output not available"` with `confidence: 0.0` when no real model
  was loaded — replaced in Phase 3 by `synthesize_answer` (see below), but
  worth knowing this was the original baseline every model wrapper had.

---

## Phase 2 — Glass Scroll Animation (frontend)

Both of these were **removed in Phase 3** (files deleted) — listed here for
history/context since old demo recordings or screenshots may reference them.

- **`lib/mapLocations.ts`** *(deleted)* — every conversation turn's camera
  target was one of exactly 3 fixed coordinates, chosen purely by the turn's
  position in the chat (1st → Mumbai `[72.8777, 19.076]`, 2nd → Washington DC
  `[-77.0369, 38.8951]`, 3rd+ → London `[-0.1276, 51.5074]`), regardless of
  what was actually uploaded or asked. `OCEAN_START`/`IDLE_VIEW`
  (`[-150, 5]`, zoom 11) was the fixed blank-landing coordinate — this one
  constant *is* still in use today, inlined as `IDLE_OCEAN_VIEW` in
  `page.tsx`.
- **`lib/mockResults.ts`** *(deleted)* — a fully scripted `AnalysisResponse`
  per location (Mumbai + one shared DC/London answer) shown whenever the
  real `/api/analyze` call failed, so the demo never visibly errored. Phase
  3 replaced this with a real, actionable error message instead (see below).

---

## Phase 3 — Dynamic Raster Overlay, Focus Mask & Layer Switcher

### Backend — stand-ins for missing real functionality

- **`app/utils/synthesize.py` (`synthesize_answer`)** — every stub model's
  answer text is a **template string** built from the real query text and
  real uploaded filename(s), still present unchanged (it's not fake data in
  the deceptive sense — it explicitly says "This stub environment has no
  live vision-language model loaded"). **[REMOVED]** every call site used to
  pair it with a **fixed confidence of `0.3`**, regardless of task or input
  — `models/vqa.py::_mock_run`, `models/vqa.py::_vqa` (text-only path),
  `models/grounding.py::SegmentationModel`, `models/change_vqa.py`,
  `models/optical_sar.py` all now return `confidence: None` instead.
- **[REMOVED] `app/output/integrator.py` (`OutputIntegrator.integrate`)** —
  found and fixed in the same pass, not originally documented above: a
  default confidence of `0.5` when no pipeline step reported one (today,
  every step), and `0.0` on total pipeline failure. Both are now `None` —
  confidence is only ever a real averaged number when at least one step
  actually reports one.
- **`app/output/raster_stub.py` (`ANCHORS`)** — 3 fixed demo coordinates,
  the *exact same* Mumbai/DC/London points Phase 2's now-deleted
  `mapLocations.ts` used — reused here as **fallback anchors** for a
  synthetic bbox, not a per-turn script anymore (picked by hashing the
  uploaded filename+size, so the same file always lands on the same
  anchor, different files scatter across the 3).
- **`app/output/raster_stub.py` (`_synthetic_bbox`)** — when a file has no
  usable GeoTIFF geo-tags: `ground_span_km = 1.2` (fixed ground footprint
  size, regardless of the image's real resolution/extent) and a
  `±0.2°`-range jitter (`(h // 3) % 1000 / 1000` etc.) around the chosen
  anchor, both fixed constants, not derived from anything about the file
  besides its name/size (used only to seed the hash).
- **`app/output/raster_stub.py` (`zoom_for_bbox`)** — `assumed_viewport_px =
  900`, `padding_factor = 2.5` (~150% padding) are fixed assumptions about
  the map's actual on-screen size, not read from a real viewport. Outer
  clamp `[2, 18]` (was `[14, 16]` before this phase — see `CHANGELOG.md`).
- **`app/output/raster_stub.py` (`generate_layers`)** — `structural_changes
  .png` draws **two fixed-position circular blobs** (`cx1,cy1 = 0.3w,0.35h`
  radius `0.12·min(w,h)`; `cx2,cy2 = 0.65w,0.6h` radius `0.09·min(w,h)`) in a
  fixed red tint (`(255,60,60)` at `alpha=0.55`) — not a real change-
  detection model, always the same two blob positions relative to any
  image's size. `spectral_bands.png` is a fixed, arbitrary channel remap
  (`R = luminance*1.3`, `G` rolled by `w/3` pixels, `B = 255-luminance`) —
  cosmetic, not a real NDVI/thermal band computation.
- **`app/output/raster_stub.py` (`_epsg_from_geokey_directory`)** — only
  resolves EPSG codes stored directly in the GeoKeyDirectory's 4th field
  (`TIFFTagLocation == 0`); a file storing its CRS key indirectly (via the
  ASCII or DOUBLE sub-tag arrays) silently falls through to the synthetic
  bbox instead of raising — a narrowing of "real" GeoTIFF support, not a
  hardcoded value per se, but worth knowing the tag-parsing is partial.

### Frontend — stand-ins for missing real functionality

- **[REMOVED] `lib/hardcodedMask.ts`** (entire file deleted, Phase 4) — the
  *entire* "highlight the water body" feature was a fixed regex trigger
  (`isWaterHighlightQuery`: `/\bwater\b/i` AND one of
  `highlight|show|locate|find|mark|outline|point out`) that, when matched,
  drew a **fixed translucent blue ellipse** (`drawWaterEllipse`: center
  `(0.52w, 0.58h)`, radii `(0.26w, 0.17h)`, rotation `0.3` radians) at the
  same relative position on every image regardless of content — identically
  whether the source showed an ocean, a desert, or a city — with a
  **fixed flat slate background** (`generatePlaceholderMaskUrl`, `#1e293b`)
  standing in for the image entirely when no real preview could be decoded.
  No real segmentation model was ever involved. Removed along with its
  "Water Mask" `LayerSwitcher` tab, `useRasterOverlay`'s
  `showWaterMask`/`hideWaterMask`, and `page.tsx`'s
  `maybeGenerateWaterMask`/`turnWaterMaskRef`/`waterMaskAvailable` state.
  `geotiffClient.ts`'s `decodeGeoTiffPreview`/`getGeoTiffDimensions` were
  also deleted as dead code, since they existed only to feed this feature.
- **(kept)** `lib/syntheticLocation.ts` (`syntheticRasterFallback`) — same 3 fixed
  `ANCHORS` as the backend's `raster_stub.py` (kept in sync by hand, not
  shared code), same filename/size hash-and-jitter scheme, but a **fixed
  `±0.03°` half-extent** (backend's synthetic tier instead derives size from
  the image's real aspect ratio) and a **fixed `zoom: 15`** — this tier never
  has a real image to measure at all (it only runs once the network call to
  the backend has already failed), so there's nothing to derive size from.
- **`hooks/useAnalysis.ts`** — on a network-level failure (no HTTP response
  at all), the error message is a **fixed hardcoded string** referencing
  `NEXT_PUBLIC_API_URL`: `` `Couldn't reach the backend at ${API} — make
  sure it's running.` `` — accurate for the demo's actual failure mode, but
  a canned message, not derived from the real Axios error.

### Frontend — fixed tuning constants (layout/animation, not fake data)

Grouped by concern; each is a value picked by eye against the current
screenshots, not computed from anything, and could drift out of sync with
each other if changed independently.

- **Camera/flight timing** (`app/page.tsx`): pre-flight "AI routing" delay
  jittered `60–300ms` (`scheduleCameraFlight`); cloud-puff cover `300ms` /
  clear `900ms` (`runCloudFlight`); scroll-driven quick recall `900ms`
  (`recallCamera`/`showRasterForTurn`); landing↔result re-frame `700ms`
  (`reframeForStage`); sidebar-collapse camera re-fit `300ms` (`useEffect`
  keyed on `sidebarWidthPx` — must match `Sidebar.tsx`'s own CSS
  `duration-300`, see `CHANGELOG.md`); `jumpToTurn`'s transition-guard window
  `700ms`.
- **Frame padding** (`app/page.tsx`): `landingFramePadding` = `{top:120,
  bottom:180, left:60+sidebarWidthPx, right:60}`; `resultFramePadding`
  swaps `right` for `RESULT_PANEL_CLEARANCE_PX = 24+440+36 = 500` (must stay
  in sync with `ResultInspectorPanel`'s own `PANEL_SIDE_MARGIN`/
  `PANEL_WIDTH` constants below — duplicated by hand, not derived).
- **`components/ResultInspectorPanel.tsx`**: `PANEL_TOP_MARGIN = 40`,
  `PANEL_SIDE_MARGIN = 24` (exported, reused by the nav-arrow fallback
  position), `PANEL_BOTTOM_CLEARANCE = 200`, `PANEL_WIDTH = 440` (exported,
  same reuse).
- **Nav-arrow rail** (`app/page.tsx`): `GAP = 8` (px offset from the raster
  rect's left edge; was `16`, then briefly computed as equidistant with the
  sidebar, reverted — see `CHANGELOG.md`); fallback-position offset
  `PANEL_SIDE_MARGIN + PANEL_WIDTH + 16` when there's no raster rect.
- **`components/PinnedQueryCard.tsx`**: pinned position `rect.top - 60`,
  clamped to a minimum of `16`px from the top when there's no rect (`24`px).
- **`components/RadiantCard.tsx`**: default `haloInset = 32`; the chat
  input's own instance overrides it to `24`; the suggestion popover's
  separately-managed halo uses `-inset-8` directly (not via `RadiantCard`).
- **`components/FocusMask.tsx`**: `backdrop-blur-[0.7px] bg-slate-950/2` —
  deliberately barely-there dimming, picked to read as "not the focus"
  without looking like fog.
- **Wheel-cycle layer switching** (`app/page.tsx::cycleActiveLayerFromWheel`):
  `700ms` cooldown after each step, so one trackpad swipe (which fires many
  wheel events) advances exactly one layer instead of racing through several.
- **`hooks/useTypewriter.ts`**: default `wordsPerTick = 2`, `tickMs = 28`.
- **`components/LayerSwitcher.tsx`**: swipe-to-switch drag threshold `40`px;
  each tab is a fixed `w-[132px]` regardless of label length.
- **`hooks/useMapCamera.ts`**: `PIN_COLOR = "#ef4444"` (the red target-marker
  color, unchanged since Phase 2).

---

## Not hardcoded (for clarity)

To avoid over-flagging: real GeoTIFF tag reading (`ModelPixelScaleTag`/
`ModelTiepointTag`/`GeoKeyDirectoryTag` parsing, both backend and
`geotiffClient.ts`) and the UTM↔WGS84 reprojection (`pyproj` backend,
`proj4` frontend) are genuine computations over the actual uploaded file,
not stand-ins — they only get skipped in favor of the synthetic/fallback
tiers listed above when the file lacks usable geo-tags or uses a CRS that
can't be resolved.
