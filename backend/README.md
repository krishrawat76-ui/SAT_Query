# SatQuery AI — Backend

FastAPI backend for the agentic remote-sensing analysis pipeline. See the
project root [README](../README.md) for the overall system and
[CONTRIBUTING.md](../CONTRIBUTING.md) for the team workflow.

> Companion reading: [`frontend/README.md`](../frontend/README.md) documents
> this API from the consumer side, including which capabilities are real vs.
> stub today.

---

## 1. Request flow

`POST /api/analyze` is the main endpoint. Its handler is split into two
functions in [`app/api/routes.py`](app/api/routes.py):

```text
analyze()                     ── owns cleanup only
  └── tmp_dirs: list[Path] = []
  └── try:
        return await _run_analysis(..., tmp_dirs=tmp_dirs)
      finally:
        for d in tmp_dirs: shutil.rmtree(d, ignore_errors=True)

_run_analysis()                ── the actual pipeline
  1. Save uploads      → app/agent/validator.py doesn't run yet; this just
                          streams each file to a temp dir with a running
                          size cap (rejects before finishing the write)
  2. Parse metadata     → modalities/dates CSV → lists
  3. Validate query     → non-empty, length bounds
  4. Validate images    → InputValidator.validate()
  5. Route               → RuleBasedRouter.route()
  6. Execute pipeline    → PipelineExecutor.execute()
  7. Integrate output    → OutputIntegrator.integrate()
  8. Build trace         → TraceBuilder.build()
  9. Return response
```

The `analyze()`/`_run_analysis()` split exists for one reason: every
temp directory created for this request must be removed exactly once,
**regardless of how the request ends** — success, a 422 validation
rejection, a 413 oversized upload, or an unhandled exception. Putting the
`finally` in the outer function and threading a mutable `tmp_dirs` list into
the inner one is what makes that guarantee hold no matter which `raise` or
`return` fires inside `_run_analysis`.

---

## 2. Image validation

[`app/agent/validator.py`](app/agent/validator.py) — `InputValidator`:

- Extension check (`.png`/`.jpg`/`.jpeg`/`.tif`/`.tiff`/`.geotiff`), file size
  (`MAX_IMAGE_SIZE_MB`), and readability (`PIL.Image.open` succeeding).
- **0 images is valid.** A text-only query is a legitimate request — it
  routes to a dedicated conversational path (see §3) rather than being
  rejected. 3+ images is rejected (max 2, for single/bi-temporal/cross-modal).
- Builds `format_info`: one dict per successfully-read image, with
  `filename`, `size`, `bands`, `format`, `file_size_mb`, and an **`index`**
  field carrying the image's position in the *original* upload list. That
  index matters downstream: if image 0 fails a check and image 1 succeeds,
  `format_info` has exactly one entry — and without a carried index, a
  positional zip against `modalities`/`dates` in the trace builder would
  silently attach image 0's metadata to the surviving image. The index is
  what keeps that correlation correct.

---

## 3. Rule-based routing

[`app/agent/router.py`](app/agent/router.py) — `RuleBasedRouter`:

Deterministic keyword matching over the query text plus input shape (image
count, modality, temporal/cross-modal flags). **No LLM, and no fabricated
confidence** — `RoutingDecision` has no `confidence` field at all, enforced
by `tests/test_router.py::test_routing_decisions_have_no_fabricated_confidence`
(`assert not hasattr(result, "confidence")`). A deterministic classifier has
no real notion of "how sure" it is; `reasoning` carries the actual
justification instead.

Every decision carries two pieces of real, checkable evidence:

- **`rule_id`** — which of 7 stable branches fired: `text_only`,
  `cross_modal`, `bitemporal_specific`, `bitemporal_general`,
  `grounding_keywords`, `caption_keywords`, `default_vqa`.
- **`matched_keywords`** — the actual substrings from the query that matched,
  not a copy of the keyword list.

| Images | Modality | Keywords | `rule_id` |
|---|---|---|---|
| 0 | — | any | `text_only` |
| 2 | optical+sar | any | `cross_modal` |
| 2 | same | specific change question | `bitemporal_specific` |
| 2 | same | general | `bitemporal_general` |
| 1 | any | highlight/show/locate/... | `grounding_keywords` |
| 1 | any | describe/caption/... | `caption_keywords` |
| 1 | any | anything else | `default_vqa` |

---

## 4. Execution & timing

[`app/agent/executor.py`](app/agent/executor.py) — `PipelineExecutor.execute()`
walks the router's pipeline steps in a strict linear loop and records real,
`time.perf_counter()`-based timing per step:

- **`load_time_ms`** vs. **`inference_time_ms`** — split because
  `ModelRegistry.get()` (a cold load) and `model.run()` (inference) have
  very different cost profiles. A 5.5 GB VLM's cold load can dominate a
  step entirely; folding it into one number misreports it as inference
  cost. The load timer is captured in a `finally` so a load that **raises**
  still reports the time it burned, rather than `0.0`.
- **`model_was_cached`** — read from `registry.list_loaded()` *before*
  calling `get()`, so it reflects whether this step paid a cold-load cost.
- **`started_at_ms`** — offset from the pipeline's own start, for rendering
  a real timeline instead of assuming steps are contiguous.
- **Telemetry side-channel** — a model wrapper that can genuinely measure
  something (currently only `QwenVLMWrapper`, for real token counts) sets
  `self.last_telemetry` after `run()`. The executor clears it to `None`
  *before* every call, so a wrapper that doesn't report can never silently
  inherit a previous step's numbers (regression-tested in
  `tests/test_executor_telemetry.py`).

On failure, the loop stops (no partial continuation) and the failing step's
`StepResult` still carries whatever `load_time_ms`/`inference_time_ms` it
measured before the exception — so a step that died mid-load is
distinguishable from one that died instantly.

---

## 5. Payload sanitization

[`app/output/sanitize.py`](app/output/sanitize.py) — `sanitize_payload()`
turns a model step's raw output (which can hold numpy arrays, PIL images,
bytes, `Path`s, NaN floats, or cyclic/DAG structures) into something
JSON-safe and bounded, for the debug `payload_snapshot` field.

| Cap | Value | Purpose |
|---|---|---|
| `MAX_STRING` | 512 chars | truncate long strings |
| `MAX_ITEMS` | 25 | truncate long lists/dicts |
| `MAX_DEPTH` | 6 | stop deep nesting |
| `MAX_TOTAL_BYTES` | 32 KB | cap the serialized output size |
| `MAX_NODES` | 20,000 | cap the **work**, checked *during* traversal |

The node budget exists because the other four caps bound the *output* but
not the *walk*: a ~200-byte DAG like `x = [x] * 25` repeated 6 times
legitimately expands to 25⁶ ≈ 244 million nodes under the item/depth caps
alone, because sibling branches each re-expand the same shared child (this
is a DAG, not a cycle — true cycles are caught separately via an
ancestor-tracking `seen` set and turn into `{"__cycle__": true}`). Since
sanitizing runs synchronously inside the request handler, an unbounded walk
would stall the whole event loop.

Non-finite floats (`NaN`/`Infinity`) become `null` — FastAPI's default
encoder emits them as bare JSON literals otherwise, which `JSON.parse`
rejects on the client. The function is wrapped so **it never raises**: a
debug feature must not be able to fail a real request.

---

## 6. Trace & output integration

[`app/output/trace.py`](app/output/trace.py) — `TraceBuilder.build()`
assembles the full `ExecutionTrace` dict (see §8 for the schema and a real
example). Two things worth knowing if you're extending it:

- **`_telemetry()`** normalizes whatever a wrapper put on `last_telemetry`
  to exactly the 6 keys `ModelTelemetry` declares, filling missing ones with
  `None` and dropping unknown ones. Without this, a wrapper reporting a
  partial dict would ship a step whose `telemetry` object is missing keys
  the frontend type promises are always present.
- **`_selection_reason()`** is composed mechanically from the router's own
  `reasoning` plus the specific pipeline actions a model was assigned —
  never hand-written per-model justification text. The router never claimed
  "GroundingDINO was chosen for its open-vocabulary detection"; saying so in
  the UI would be inventing a fact the code doesn't know.
- With no `registry` passed in (the parameter is optional so `TraceBuilder`
  works standalone in tests), `selected_models[].registered`/`.loaded` are
  `None`, not an optimistic default — there's nothing to observe, so nothing
  is asserted.

[`app/output/integrator.py`](app/output/integrator.py) — `OutputIntegrator`
runs *outside* the executor's try/except, so it degrades rather than 500ing
on a malformed model output: a non-`dict` step output is skipped with a
warning (previously `"answer" in out` on a string could pass and then raise
on indexing), and a non-finite `confidence` is dropped rather than being
averaged into a NaN.

---

## 7. Debug Mode & Telemetry

The governing rule for every field below: **measured, or `null` — never
fabricated.** This replaced an earlier version of the trace that hardcoded a
per-branch router confidence, a word-count confidence heuristic, a fixed
`"version": "1.0"` for every model, and a `total_time_ms` that was actually
just the sum of step times (silently excluding upload/validation/routing/
integration). See [`frontend/docs/HARDCODED.md`](../frontend/docs/HARDCODED.md)
for the full history of what was removed and why.

### The `?debug` query param

```
POST /api/analyze?debug=true
```

A query param, not a form field, so the multipart body stays byte-identical
regardless of Debug Mode — and so the frontend's toggle can change server
behavior without a restart. Defaults to the `DEBUG_TRACE` setting
(`SATQUERY_DEBUG` env var) when omitted. It gates **only**
`payload_snapshot`/`payload_bytes` per step — everything else in the trace
(router metadata, timings, registry state) is always populated, since it's
cheap and telling the truth about it costs nothing.

### `RouterMetadata`'s forward-compatible split

```python
class RouterMetadata(BaseModel):
    # Real — this repo's deterministic RuleBasedRouter reports these:
    router_type: str
    router_version: str
    rule_id: str
    matched_rule: str
    matched_keywords: list[str] = []
    fallback_used: bool = False
    routing_time_ms: float = 0.0

    # Null here by design, not by omission — only an LLM planner could
    # report these, and this router has no language model in the loop:
    planner_type: Optional[str] = None
    planning_time_ms: Optional[float] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    tokens_per_sec: Optional[float] = None
    intent_decomposition: Optional[list[dict]] = None
    planner_raw_output: Optional[str] = None
```

The point of keeping the LLM-planner fields in the schema at all, always
`null`, is that a future LLM-based router could populate them with zero
breaking change — the frontend already renders an explicit "not reported by
this router" message when they're null, gated on `router_type`, rather than
asserting that *no* router could ever report them.

### What `registered`/`loaded` actually mean — and don't

**`registered`/`loaded` are honest about the `ModelRegistry`, not about
whether real ML inference happened.** This is the single easiest place to
misread the trace, so it's worth being explicit: `ModelRegistry.get(name)`
([`app/models/registry.py`](app/models/registry.py)) calls whatever loader
function was passed to `register()`. For most models in this repo today,
that loader is `lambda: SomeStubModel()` — a plain Python object with no
weights, no download, no GPU allocation:

```python
# app/main.py — every model this repo currently registers:
registry.register("rs_vlm", lambda: QwenVLMWrapper(), vram_gb=5.5)
registry.register("grounding_dino", lambda: GroundingModel(), vram_gb=0.7)
registry.register("sam", lambda: SegmentationModel(), vram_gb=0.35)
registry.register("change_detection", lambda: ChangeDetectionModel(), vram_gb=0.15)
registry.register("change_vqa", lambda: ChangeVQAModel(), vram_gb=5.5)
registry.register("optical_sar_fusion", lambda: OpticalSARFusionModel(), vram_gb=0.5)
```

`registered: true` means the name above really was registered at startup.
`loaded: true` means `get()` was called for it and the resulting object is
cached in `self._models` — by that definition it's a true fact, but the
object itself may be a stub whose `run()` returns hardcoded empty output
with no weights ever touched. `vram_gb` is the static estimate passed into
`register()` for the registry's own eviction bookkeeping — not a measured
GPU reading, since a stub never allocates any.

| Registered name | Wrapper class | Status today |
|---|---|---|
| `rs_vlm` | `QwenVLMWrapper` ([`app/models/vqa.py`](app/models/vqa.py)) | ⚠️ Real inference code path exists (`_run_qwen_inference`, with genuine token-count/throughput telemetry); falls back to `_mock_run` — a synthesized, input-aware placeholder answer — whenever `settings.QWEN_MODEL_PATH` doesn't exist, which is every environment with no downloaded weights |
| `grounding_dino` | `GroundingModel` ([`app/models/grounding.py`](app/models/grounding.py)) | ❌ Stub — always returns empty `boxes`/`scores`/`labels` |
| `sam` | `SegmentationModel` ([`app/models/grounding.py`](app/models/grounding.py)) | ❌ Stub — always returns empty `regions`; the visible cost in a trace is real image I/O in `overlay_bboxes()`, not segmentation |
| `change_detection` | `ChangeDetectionModel` ([`app/models/change_detection.py`](app/models/change_detection.py)) | ❌ Stub — always returns `change_ratio: 0.0` |
| `change_vqa` | `ChangeVQAModel` ([`app/models/change_vqa.py`](app/models/change_vqa.py)) | ❌ Stub — always a synthesized placeholder answer |
| `optical_sar_fusion` | `OpticalSARFusionModel` ([`app/models/optical_sar.py`](app/models/optical_sar.py)) | ❌ Stub — always an empty class distribution |

Every one of these classes says so in its own module docstring (e.g.
`grounding.py`: *"Grounding Model Stubs — Placeholder for Grounding DINO +
SAM... Status: STUB"*). None of that is a documentation gap to fix later —
it's the intentional current state of an orchestration layer built ahead of
the ML layer landing (see [`frontend/README.md`](../frontend/README.md) §2
for the same table from the consumer side). The telemetry work in this
section reports that state honestly rather than hiding it: a stub finishing
in 34µs and reporting `loaded: true` is not a bug in the trace — it's the
trace correctly describing a fast, real Python function call to a stub.

The same caveat extends to `model_was_cached` (rendered as "warm"/"cold" in
`PipelineWaterfall.tsx`). It's read straight from `registry.list_loaded()`
before the step runs, so it's real about *the registry* — but for a stub,
"warm" only ever means "the placeholder object from a previous call is still
sitting in the registry's dict." It carries none of the weight it would for
a real model (avoiding a multi-second weights-to-VRAM transfer); for a stub
that costs microseconds either way, warm vs. cold is close to a non-event.

### A complete real `ExecutionTrace`

Captured live from a running instance of this backend (`POST
/api/analyze?debug=true`, a single optical image, query "Highlight the water
body"). Every value below is a genuine measurement or registry read —
nothing in this example was written by hand:

```jsonc
{
  "request_id": "1c6f030a",
  "debug": true,
  "input_validation": {
    "image_count": 1, "format": [".png"], "modality": ["optical"],
    "temporal": false, "cross_modal": false, "compatible": true, "warnings": []
  },
  "input_composition": {
    "images": [{
      "filename": "sq_test.png", "width": 64, "height": 48, "bands": 3,
      "format": ".png", "file_size_mb": 0.0, "modality": "optical", "date": null
    }],
    "total_pixels": 3072, "total_size_mb": 0.0,
    "is_temporal": false, "is_cross_modal": false, "crs": null
  },
  "detected_task": "grounding",
  "task_confidence": null,
  "reasoning": "Grounding keywords detected in query → Grounding pipeline (DINO + SAM)",
  "router_metadata": {
    "router_type": "rule_based_keyword",
    "router_version": "rule_based_keyword/1",
    "rule_id": "grounding_keywords",
    "matched_rule": "Grounding keywords detected in query → Grounding pipeline (DINO + SAM)",
    "matched_keywords": ["highlight"],
    "fallback_used": false,
    "routing_time_ms": 0.04,
    "planner_type": null, "planning_time_ms": null, "prompt_tokens": null,
    "completion_tokens": null, "tokens_per_sec": null,
    "intent_decomposition": null, "planner_raw_output": null
  },
  "selected_models": [
    {
      "name": "grounding_dino", "actions": ["detect_regions"], "steps": [1],
      "registered": true, "loaded": true, "vram_gb": 0.7, "version": null,
      "selection_reason": "Selected for task 'grounding' to run step 1: detect_regions. Router rule [grounding_keywords]: Grounding keywords detected in query → Grounding pipeline (DINO + SAM)"
    },
    {
      "name": "sam", "actions": ["segment_regions"], "steps": [2],
      "registered": true, "loaded": true, "vram_gb": 0.35, "version": null,
      "selection_reason": "Selected for task 'grounding' to run step 2: segment_regions. Router rule [grounding_keywords]: Grounding keywords detected in query → Grounding pipeline (DINO + SAM)"
    }
  ],
  "pipeline_steps": [
    {
      "step": 1, "model": "grounding_dino", "action": "detect_regions",
      "status": "success", "time_ms": 0.045, "error": null,
      "load_time_ms": 0.005, "inference_time_ms": 0.04,
      "model_was_cached": true, "started_at_ms": 0.036, "telemetry": null,
      "payload_snapshot": {
        "type": "detections", "boxes": [], "scores": [], "labels": [],
        "target": "water body"
      },
      "payload_bytes": 87, "depends_on": null
    },
    {
      "step": 2, "model": "sam", "action": "segment_regions",
      "status": "success", "time_ms": 1.309, "error": null,
      "load_time_ms": 0.001, "inference_time_ms": 1.308,
      "model_was_cached": true, "started_at_ms": 0.155, "telemetry": null,
      "payload_snapshot": {
        "answer": "Analyzing the uploaded file `sq_test.png` for the query...",
        "confidence": null, "evidence_images": [], "regions": []
      },
      "payload_bytes": 427, "depends_on": null
    }
  ],
  "timings": {
    "upload_ms": 0.952, "validation_ms": 0.292, "routing_ms": 0.017,
    "execution_ms": 1.594, "integration_ms": 0.014,
    "pipeline_steps_ms": 1.354, "other_ms": 0.627
  },
  "total_time_ms": 3.496
}
```

Notes on reading this example:

- **`telemetry: null`** on both steps — neither `grounding_dino` nor `sam`
  is a real model with real inference; only `QwenVLMWrapper` populates this,
  and only when real weights are loaded.
- **Sub-millisecond precision matters.** These steps completed in tens of
  microseconds; rounding to 1 decimal place (the pre-Phase-4 behavior) would
  have reported both as `0.0`. Every timing field is rounded to 3 decimals.
- **`total_time_ms` (3.496) ≠ `pipeline_steps_ms` (1.354).** The former is
  real request wall-clock (upload → response assembled); the latter is
  preserved specifically because it used to *be* `total_time_ms`, and the
  gap between them is exactly what `timings` breaks down.
- **`registered`/`loaded` are `true` here** because a real `ModelRegistry`
  was passed to `TraceBuilder`. Call it without one (as some tests do) and
  both become `null` — never an optimistic default. **`true` describes
  registry state, not real inference** — `grounding_dino` and `sam` are both
  stub classes (see the table above), which is also why they finish in
  34µs and 1.3ms respectively rather than the seconds a real GroundingDINO +
  SAM 2.1 pass would take.

---

## 8. Endpoints

| Method | Path | Purpose | Notes |
|---|---|---|---|
| `POST` | `/api/analyze` | Main analysis endpoint — image(s) + query in, answer + evidence + execution trace out | `?debug=true` attaches payload snapshots; 0 images is a valid text-only request |
| `POST` | `/api/process-raster` | Extracts (or synthesizes) a geographic bbox for an uploaded image, for the frontend's map overlay | Real GeoTIFF tag reading + UTM reprojection when present; synthetic fallback otherwise — see `app/output/raster_stub.py` and the callout below |
| `GET` | `/api/health` | Server/GPU/model-registry status | `gpu_available`/`gpu_memory_used` degrade to `false`/`null` on a GPU query failure rather than 500ing |

**A note on the synthetic fallback, since it's easy to over-read.** When
`raster_stub.py` can't read real GeoTIFF geo-tags (`ModelPixelScale`/
`ModelTiepoint` absent — a plain PNG/JPEG, most of the time), `_synthetic_bbox()`
does **not** analyze the image content at all. It hashes the filename +
dimensions and uses that to pick one of 3 hardcoded real-world anchor
coordinates —

```python
ANCHORS = [
    (72.8777, 19.076),    # Mumbai
    (-77.0369, 38.8951),  # Washington DC
    (-0.1276, 51.5074),   # London
]
```

— then adds a small deterministic jitter and returns `source: "synthetic"`
alongside it. This is honestly labeled in the response (`source` exists
precisely so a caller can tell the two cases apart), but as of this writing
**no frontend component reads that field** (confirmed by grep — see
[`frontend/README.md`](../frontend/README.md) §3), so a synthetic guess and
a real geolocation currently look identical to anyone watching the UI: same
cinematic camera flight, same-looking bounding box. If you're consuming this
endpoint directly, always branch on `source` rather than assuming a returned
bbox reflects anything read from the image.

---

## 9. Running the tests

```bash
cd backend
python -m pytest tests/ -v
```

97 tests, all passing. What each file covers:

| File | Covers |
|---|---|
| `test_router.py` | Every routing branch, `rule_id`/`matched_keywords` correctness, no fabricated confidence |
| `test_validator.py` | Format/size/count checks, the 0-images-is-valid path |
| `test_sanitize.py` | Cycles, DAG node-budget bound, NaN/Infinity, numpy arrays, every size cap, never-raises |
| `test_executor_telemetry.py` | Load-vs-inference split (including on the failure path), stale-telemetry regression, caching |
| `test_trace_builder.py` | Full trace shape against the Pydantic schema, including a populated `telemetry` dict and a failed step |
| `test_registry_vram.py` | VRAM eviction logic and `/api/health` against an injected fake CUDA device |
| `test_api_analyze.py` | End-to-end contract: schema validation, `?debug` gating (both directions), non-finite values never reaching the client, a non-dict model output degrading instead of 500ing |
