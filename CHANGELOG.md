# Changelog

All notable changes to the SatQuery backend are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] — Backend hardening, Phase 1 + Phase 2

Two audit-and-fix passes over the FastAPI backend. **Phase 1** hardened the HTTP boundary
(input validation, payload limits, error contracts). **Phase 2** hardened the internal
pipeline (spatial guards, task preconditions, event-loop safety, raster hygiene).

> **Status:** this is a pending change set on branch `version-1`, not a tagged release.
> At time of writing it is uncommitted, so no commit SHAs are referenced.
>
> **Scale:** 24 files modified, 9 added, 1 deleted, all under `backend/`. The test suite
> grew from 97 cases (93 passing, 4 failing) to **231, all passing** — 134 new cases.
>
> Every item below records the *observed* pre-fix behaviour. These were reproduced against
> the running app, not inferred from reading code.

---

## Phase 1 — HTTP Boundary

### Added

- **`backend/app/api/uploads.py`** — shared hardened upload handling for `/api/analyze`
  and `/api/process-raster`.
  - `safe_filename()` strips path separators and NUL bytes, and bounds the stem to 80
    chars. It deliberately **preserves the real extension** so `InputValidator`'s format
    check still sees what the client sent.
  - `save_upload_streamed()` enforces a per-file cap *and* a request-wide byte budget,
    raising `HTTPException` rather than letting `OSError` escape as a 500.
- **Request body size gate** (`main.py`) — rejects an oversized declared `Content-Length`
  before the multipart parser is handed anything. A chunked request carries none, which is
  why the streaming budget above is the real backstop.
- **Global exception handlers** (`main.py`) for `StarletteHTTPException`,
  `RequestValidationError`, `MultiPartException`, and bare `Exception`.
- **`sanitize.json_safe()`** — nulls every non-finite float in a response tree.
- Regression suite **`backend/tests/test_api_boundary.py`** (34 tests).

### Changed

- **Unified error envelope.** The API previously spoke two dialects — FastAPI's
  `{"detail": [{loc, msg, type}]}` for framework validation and
  `{"detail": {"errors": [...]}}` for hand-raised errors — forcing clients to branch on the
  shape of a failure. Everything now returns `{"detail": {"errors": [...]}}`.
  The frontend (`useAnalysis.ts`) only ever read `detail.errors`, so framework validation
  errors now produce real messages instead of falling through to
  `"Request failed with status code 422"`.
- **Image-count check moved ahead of the write loop** (`routes.py`). `InputValidator`
  enforced the same limit, but only *after* every file had been streamed to disk — 20
  uploads of 3 MB each cost 60 MB of disk I/O to produce one 422, and Starlette permits
  1000 files per request.
- **Field limits declared on the Form fields** — `query` (2000 chars), `modalities` and
  `dates` (512 chars) — so they are rejected at parse time rather than after disk I/O.
- **`modalities` / `dates` are now validated**: allowlisted against `{optical, sar}`,
  count-capped, and case-normalized. Dates must match `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.
- **`GET /api/health` returns 503, not 500**, before the lifespan has built the registry.
  An orchestrator kills a pod on 500 and merely drains it on 503.
- **CORS**: `allow_credentials` `True` → `False`; methods and headers narrowed from `*`.
  Paired with the `"null"` origin (kept, for `file://` demos), credentials let any
  sandboxed iframe issue credentialed cross-origin requests. The API uses no cookies.

### Fixed

- **500 on a long filename.** A 400-character filename raised
  `OSError: File name too long` from `tmp_path.open("wb")`, uncaught — the client got a
  plain-text 500 that breaks `res.json()`.
- **`/api/process-raster` leaked one temp directory per request** for the process
  lifetime. It had no cleanup at all, unlike `/api/analyze`. Verified: 3 calls → 3 leaked
  directories, now 0.
- **`/api/process-raster` buffered the entire upload in memory** via
  `write_bytes(await image.read())` and never consulted `MAX_UPLOAD_SIZE_MB`. A 60 MB body
  returned 200; it now streams and returns 413.
- **`/api/process-raster` fabricated geospatial output from garbage.** `b"junkjunk"` and a
  0-byte file both returned 200 with a confident bbox near Washington DC and a blank grey
  512×512 base layer. Both now 422.
- **`zoom_for_bbox` crashed on non-finite spans.** An infinite longitude span drove
  `math.log2(0)` → `ValueError` → 500; a NaN span silently returned `2.0`, a
  plausible-looking wrong answer. Both now return `DEFAULT_ZOOM`. Reachable from
  `_reproject_to_wgs84`, where pyproj returns `inf` for a malformed GeoTIFF tiepoint.
- **Evidence URL mismatch.** `evidence.RESULTS_DIR` was a CWD-relative `Path("results")`
  while `main.py` mounts the absolute `settings.RESULTS_DIR`. Launched from the repo root,
  evidence images were written where nothing served them — 404 URLs inside a 200 response.

### Security

- **`fastapi>=0.115.3,<0.116`** (was `==0.115.0`), pulling `starlette>=0.40.0` to close
  **CVE-2024-47874**. Below that version `MultiPartParser` has no `max_part_size`, so a
  form field such as `query` was buffered in memory **with no limit at all** before any
  handler code ran. Confirmed resolved: `MultiPartParser.max_part_size == 1048576`.
- **Internal filesystem paths removed from responses.** A corrupt upload returned a 422
  containing `cannot identify image file '/var/folders/f2/…/satquery_glsfvuyo/bad.png'`,
  disclosing the temp-dir scheme, the OS, and the account the server runs as. The raw
  exception is now logged, not echoed.
- **Same disclosure removed from the success path.** `router_metadata.intent_decomposition[].images[].path`
  embedded the absolute upload path in **every 200 response**. Nothing read the field;
  `filename` beside it is what is used.

### Note on tracebacks

Tracebacks were **never** exposed in response bodies — `FastAPI(debug=…)` is unset, so
Starlette returned the plain string `Internal Server Error`. The defects were the wrong
status code and the non-JSON body, not traceback leakage.

---

## Phase 2 — Pipeline Resilience

### Added

- **`backend/app/agent/exceptions.py`** — domain exceptions carrying their HTTP status and
  a machine-readable `code`. See [New API surface](#new-api-surface) below.
- **`backend/app/agent/preflight.py`** — all pipeline preconditions, checked **before any
  model loads**: task arity, modality compatibility, per-image raster guards, pair-wise
  band/aspect compatibility, and ground overlap.
- **`backend/app/agent/inference_lane.py`** — a single-worker executor with a bounded
  queue. One worker, not a general threadpool: `ModelRegistry` deliberately holds one major
  model at a time for an 8 GB card, so N concurrent inferences would thrash VRAM.
- **`backend/app/utils/raster_io.py`** — `probe_raster()` (header-only),
  `guard_decoded_size()`, `check_nodata()`, and `load_rgb()`, which percentile-stretches
  high-bit-depth rasters instead of clipping them.
- **`ModelRegistry.pin()`** — a context manager marking a model in-use so eviction cannot
  pull weights out from under a running inference.
- **`BaseModelWrapper.require_images()` / `.prior_step()`** — safe context accessors.
- **Spatial facts in the execution trace** — `input_composition.spatial` carries
  `bbox_iou`, `enforced`, per-image bbox source and `gsd_ratio`; `timings.preflight_ms` is
  new.
- Regression suites **`test_pipeline_resilience.py`** (23), **`test_spatial_guard.py`**
  (28), **`test_evidence_postprocess.py`** (13).

### Changed

- **The pipeline no longer runs on the event loop.** Validation, routing, integration and
  trace building moved to `run_in_threadpool`; model execution moved to the serialized
  inference lane. Measured before: a 1.5s forward pass froze the loop for 1.52s and an
  asyncio heartbeat due every 0.2s produced **no ticks at all** until it cleared. After,
  against a live server: `/api/health` answered in **13.6ms max** while an analyze request
  ran for 1350ms.
- **`ModelRegistry` is thread-safe** — an `RLock` guards every mutation, and `get()` now
  refreshes recency so `_ensure_vram` evicts genuinely cold models. It previously evicted
  `candidates[0]`, which was dict *insertion* order, so the most recently used model could
  be the first evicted. These races were masked by the synchronous event loop; fixing the
  blocking un-masked them, so both changes land together.
- **`PipelineExecutor` re-raises `PipelineInputError`** instead of swallowing it. Domain
  rejections must reach the client as a 4xx, not as a step marked `"error"` inside a 200.
- **Evidence generators return `Optional[str]`** — `None` on failure, was `""`. An empty
  string reads as a valid-but-blank URL, and callers were accepting it as evidence.
- **`SegmentationModel` reports the overlay it generates.** The return value of
  `overlay_bboxes` was assigned to a local and never used, so `evidence_images` was always
  `[]`. It now reports the overlay — but **only when there are boxes to draw**, since an
  overlay of zero detections is a byte-for-byte copy of the input.
- **`raster_stub.generate_layers` and `evidence.*` decode through `load_rgb`**, so a
  16-bit or float32 GeoTIFF no longer produces a near-black or near-white base layer.

### Fixed

- **The default router planned pipelines it could not feed.** `ShivenRouterAdapter` maps a
  planner task name straight through `_TASK_PIPELINE` and **never reads `num_images`**;
  `USE_SHIVEN_ROUTER` defaults to `true`, and the Shiven *fallback* planner is also
  query-text-only. Observed:

  | request | routed to | before |
  |---|---|---|
  | `"what changed between the two images?"` + 1 image | `change_detection` | `IndexError`, swallowed → **200** `"Model not available"` |
  | `"highlight the water body"` + 0 images | `grounding_dino` | `IndexError`, swallowed → **200** |
  | `"segment all the buildings"` + 0 images | `grounding_dino` | `IndexError`, swallowed → **200** |

  The in-repo `RuleBasedRouter` *is* arity-safe; that asymmetry was the bug.

- **Every model wrapper crashed on malformed context.** All eight of these raised, and all
  eight were converted into a failed step inside a 200:

  | call | exception |
  |---|---|
  | `ChangeDetectionModel.run` with 1 image | `IndexError` |
  | `GroundingModel.run` with 0 images | `IndexError` |
  | `OpticalSARFusionModel.run` with 0 images | `IndexError` |
  | `SegmentationModel.run`, no `step_1` | `KeyError: 'step_1'` |
  | `SegmentationModel.run`, `step_1` is a `str` | `AttributeError: 'str' has no 'get'` |
  | `QwenVLMWrapper._describe_changes`, `change_ratio=None` | `TypeError: NoneType * int` |
  | `QwenVLMWrapper._describe_changes`, `step_1` is a `str` | `AttributeError` |
  | `QwenVLMWrapper._caption` with 0 images | `IndexError` |

- **`OpticalSARFusionModel` silently fused an image with itself**, reusing `images[0]` as
  the SAR input when only one image arrived, and reporting it as a real cross-modal result.
- **No spatial guard existed anywhere.** Grepping `app/agent/` and `app/models/` for
  `crs|epsg|intersect|overlap|iou|resolution` returned **zero** real hits. Two rasters from
  disjoint continents were accepted for change detection or fusion without comment.
- **Rasters were silently mangled into 8-bit RGB.** `InputValidator` accepted every
  pathological raster as `valid=True` with zero warnings, and `.convert("RGB")` then
  destroyed the data without raising:

  | raster | after `.convert("RGB")` |
  |---|---|
  | 16-bit uint TIFF (values to 3.7M) | clipped to 0–255, **20 unique values** survive |
  | float32 all-NaN (nodata) | **min=0 max=0** — solid black |
  | float32 `1e30` | **min=255 max=255** — solid white |

  A model would "analyze" a black square and report a confident answer about it.
- **Decompression bombs passed validation.** `MAX_DIMENSION = 8192` only *warned*.
  Verified: a **136 KB** PNG expanding to 12000×12000 (144 MP, ~432 MB of RGB) passed and
  loaded in full — `PIL.MAX_IMAGE_PIXELS` only emits a warning below 2× its limit.
- **`?debug=true` leaked absolute temp paths.** `UnavailableModelExecutor` put
  `"image_paths"` in its output, which `TraceBuilder` snapshotted into `payload_snapshot`.
- **`_telemetry` crashed on a non-dict.** `last_telemetry` is a plain attribute a wrapper
  may assign anything to; a `str` raised `AttributeError` and took down trace building for
  an otherwise-successful request. Non-finite numbers now pass through `json_safe`.
- **Bounding-box post-processing mishandled every anomaly.** Out-of-bounds and zero-area
  boxes rendered meaningless overlays; inverted, NaN/inf and wrong-arity boxes raised
  inside the draw loop and returned `""`, **discarding every good box alongside the bad
  one**. `sanitize_boxes()` now clamps, normalizes, and drops individually.

### Removed

- **`backend/app/utils/image_utils.py`** (`load_image`, `get_image_info`) — zero callers;
  superseded by `app/utils/raster_io.py`. See the merge note below.

---

## Merging this branch

### Conflict hotspots, ranked

**1. `backend/app/models/vqa.py` — the only real hotspot, and a small one.**

Exactly **four hunks** changed: `import math`, and three methods:

| method | change |
|---|---|
| `_caption` | `context["images"][0]` → `self.require_images(context, 1, …)[0]` |
| `_describe_changes` | same for 2 images; `change_ratio` guarded against `None`/NaN/`bool` |
| `_analyze_fused` | same for 2 images; `prior_step(context, 1)` replaces `.get("step_1", {})` |

**Untouched:** `_try_load_model`, `_run_qwen_inference`, `_infer_single`, `_infer_multi`,
`_vqa`, `_mock_run`, `MAX_NEW_TOKENS`, and the class docstring body. Model loading,
inference, and telemetry are exactly as they were — which is where a captioning-model
branch does its work. **Resolution:** take both sides; these edits are on different lines
than model-loading changes.

**2. `backend/requirements.txt` and `requirements-lite.txt`** — both changed the same
line, `fastapi==0.115.0` → `fastapi>=0.115.3,<0.116`. **Resolution:** keep the ranged
constraint; it is a security fix (CVE-2024-47874), not a preference. Do not pin back
to 0.115.0.

**3. `backend/app/main.py`** — three hunks: imports, lifespan shutdown, and a large block
of middleware plus exception handlers. **The model-registration block is untouched**, so
adding a new captioning model there needs no conflict resolution.

**4. `backend/app/models/base.py`** — **purely additive**. `require_images()` and
`prior_step()` were added; nothing was removed or renamed. A new wrapper subclassing
`BaseModelWrapper` inherits both for free.

### Deleted file — check before merging

`backend/app/utils/image_utils.py` was deleted. It had no callers here, but an incoming
branch may import it. **This is the one deletion that can break a merge silently** — a
missing import surfaces at runtime, not at merge time.

```bash
git grep -n "image_utils" <incoming-branch>
```

Replacements in `app/utils/raster_io.py`:

| removed | replacement | difference |
|---|---|---|
| `load_image(path, max_size)` | `load_rgb(path, label=…)` | returns `(image, report)`; stretches high-bit-depth data; raises on a bomb or an all-nodata tile. Does **not** resize — callers that relied on `max_size` must resize themselves. |
| `get_image_info(path)` | `probe_raster(path)` | header-only; adds `pixels` and `high_bit_depth`; **raises** instead of returning `{"error": …}` |

### Changed internal contracts

These break callers silently rather than at import — worth grepping the incoming branch for
each.

| symbol | change |
|---|---|
| `evidence.overlay_bboxes`, `colorize_change_map`, `overlay_segmentation_mask`, `generate_land_cover_map` | return `Optional[str]`; **`None` on failure, was `""`**. A truthiness check still works; an `== ""` check does not. |
| `evidence.RESULTS_DIR` | absolute `settings.RESULTS_DIR`, was CWD-relative `Path("results")` |
| `TraceBuilder.build` | new keyword-only `spatial=` argument (optional, defaults `None`) |
| `TraceBuilder._input_composition` | new third positional parameter `spatial` |
| `ModelRegistry.get` | reorders `_models` for LRU — **`list_loaded()` now returns recency order, not insertion order** |
| `ModelRegistry` | every public method takes an internal `RLock`; new `pin()` context manager |
| `PipelineExecutor.execute` | **re-raises `PipelineInputError`** instead of swallowing it into a failed step |
| `preflight.run_preflight` | returns `{"pipeline", "warnings", "spatial"}` — **the returned pipeline may differ from the one passed in** (see the text-only coercion below) |
| `trace._telemetry` | returns `None` for a non-dict instead of raising |

### New API surface

All errors share one envelope: `{"detail": {"errors": [...], "code": "...", "context": {...}}}`.
`code` and `context` are present on domain rejections.

| status | `code` | raised when |
|---|---|---|
| 413 | `raster_too_large` | decoded pixel count exceeds 67 MP |
| 422 | `arity_mismatch` | the routed task needs more images than were sent |
| 422 | `modality_mismatch` | fusion planned over a pair that is not optical+SAR |
| 422 | `spatial_mismatch` | two **georeferenced** rasters with bbox IoU < 0.05 |
| 422 | `raster_incompatible` | all-nodata tile, incompatible aspect, or GSD ratio > 4× |
| 503 | `inference_overloaded` | the inference queue is full |
| 504 | `inference_timeout` | inference exceeded `INFERENCE_TIMEOUT_S` |

The existing frontend (`useAnalysis.ts`) reads `e.response.data?.detail?.errors?.join(", ")`,
so it **gains** messages rather than breaking. A merging frontend should read `code` to
branch, not parse prose.

### Behaviour changes that are not regressions

Requests that used to return 200 and now reject. If the incoming branch has tests
asserting 200 for any of these, the test is asserting the old bug:

- a change/comparison query with **one** image → 422 `arity_mismatch`
- fusion over **two optical** images → 422 `modality_mismatch`
- two **georeferenced** rasters with disjoint footprints → 422 `spatial_mismatch`
- an **all-nodata** raster → 422 `raster_incompatible`
- a **decompression bomb** → 413 `raster_too_large`

And one that goes the other way, deliberately: a **zero-image** request is **coerced to
the conversational path (200)**, not rejected. The planner routes `"describe the image"` to
CAPTIONING from the text alone; 422-ing that would break the text-only chat path this
codebase supports on purpose (`RuleBasedRouter`'s `text_only` rule, `synthesize_answer`'s
no-images branch). A 422 is reserved for *partially* supplied input.

### Spatial enforcement is conditional — read before changing it

The ground-overlap check is enforced **only when both rasters report
`source == "geotiff-tags"`**. `extract_bbox` falls back to a bbox synthesized from a
filename hash when GeoTIFF tags are absent — measured, `before.png` lands on Mumbai and
`after.png` on London. Enforcing overlap unconditionally would **422 every
non-georeferenced PNG demo upload**. An unreferenced pair warns and passes; the trace
reports `spatial.enforced: false` so the distinction is visible.

---

## New configuration

Added to `backend/app/utils/config.py`, all overridable by environment variable.

| setting | default | purpose |
|---|---|---|
| `MAX_UPLOAD_SIZE_MB` | 50 | per-image cap (pre-existing, now enforced) |
| `MAX_IMAGES_PER_REQUEST` | 2 | checked before any file is written |
| `MAX_REQUEST_SIZE_MB` | 110 | whole-body ceiling |
| `MAX_QUERY_CHARS` | 2000 | rejected at parse time |
| `MAX_METADATA_FIELD_CHARS` | 512 | `modalities` / `dates` |
| `ALLOWED_MODALITIES` | `{optical, sar}` | matches the frontend's `Modality` type |
| `MAX_MODALITY_ITEMS` / `MAX_DATE_ITEMS` | 2 | |
| `INFERENCE_TIMEOUT_S` | 180 | bounds the **client** wait — see caveat |
| `INFERENCE_QUEUE_DEPTH` | 4 | requests that may wait for the lane |
| `INFERENCE_QUEUE_WAIT_S` | 30 | queue wait before shedding as 503 |

> **Caveat:** `INFERENCE_TIMEOUT_S` bounds how long the client waits. It **cannot kill the
> worker thread** — Python has no safe thread termination — so a hung inference still
> occupies the lane until it returns on its own.

---

## Testing

```bash
cd backend && .venv/bin/python -m pytest tests/ -q     # 231 passed
```

| file | cases | covers |
|---|---|---|
| `test_api_boundary.py` | 41 | payload limits, filename sanitizing, error envelope, path disclosure |
| `test_pipeline_resilience.py` | 37 | arity/modality guards, wrapper robustness, telemetry, registry locking, event-loop responsiveness |
| `test_spatial_guard.py` | 31 | bbox IoU, the synthetic-bbox trap, GSD ratio, raster hygiene, decompression bombs |
| `test_evidence_postprocess.py` | 25 | bbox clamping/dropping, evidence failure reporting |

`tests/conftest.py` gained two fixtures worth knowing about if the incoming branch adds
router or model tests:

- **`rule_router`** — pins `USE_SHIVEN_ROUTER=False` for tests asserting the in-repo
  router's own contract (`rule_id`, `matched_keywords`, null planner fields).
- **`real_models`** — pins `SKIP_MODEL_INFERENCE=False` so tests that inject a fake model
  via `registry.get` actually see it called.

These fixed **four long-standing failures** that were not real bugs: those tests asserted
`RuleBasedRouter` contracts while the app defaults to the Shiven router, so they passed
only when Ollama happened to be unreachable *and* the Shiven import happened to fail. This
is the first fully-green run of the suite.

### Writing an event-loop test

Assert against a **shared `t0` heartbeat**, never per-request elapsed time. A blocked
concurrent request's own timer only starts once the loop frees up, so per-request elapsed
reports ~0s whether or not the loop was blocked — it cannot detect blocking at all.
`test_event_loop_stays_responsive_during_inference` has the working shape.

---

## Known gaps (deliberately out of scope)

- **Tensor / CUDA memory hygiene.** Five of six model wrappers are stubs returning empty
  literals (`change_ratio: 0.0`, `boxes: []`, `classes: {}`); only `QwenVLMWrapper` runs
  real inference, and only when weights exist. There is nothing allocating GPU memory to
  clean up yet. The inference lane and the registry `pin()`/lock work are the
  prerequisites for that milestone.
- **Multi-worker deployment.** The inference lane is per-process, so `uvicorn --workers N`
  gives N lanes and N model copies.
- **`/results` static mount has no access control** — it serves every request's output
  under a guessable 8-hex-character `request_id`.
- **Auth, authorization, and rate limiting** are absent by design at this stage.
