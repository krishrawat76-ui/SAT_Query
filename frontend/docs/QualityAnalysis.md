# Debug Module — Quality Analysis

> Review of the Phase 4 Debug Mode feature: **Stage 1** (backend telemetry,
> committed `70378a4`) and **Stage 2** (Debug Mode UI, uncommitted at time of
> review). Method: three independent adversarial reviews — backend
> correctness, frontend components, and tests + contract consistency — plus a
> direct pass over the wired feature. Findings are deduplicated and ranked by
> whether they bite **now**, **soon**, or are **latent**.
>
> The architecture is sound: honest-nulls telemetry, per-field gating on real
> data, screen-space DOM instead of MapLibre layers. Nothing below argues for
> a rewrite — these are defects, gaps, and polish.

---

## Status — remediation pass

All of §1–§4, the §5 test gaps, and the whole §7 polish backlog are **fixed
and verified**. Backend suite: **90 → 97 passing**. `tsc --noEmit` clean.
Verified live against the running backend and in a real browser session.

One fix found a further bug the review hadn't caught: strengthening
`test_failure_during_load_reports_no_inference_time` (§5.2) revealed that
`executor.py` assigned `load_ms` only *after* `registry.get()` returned, so a
model load that **failed** reported `load_time_ms: 0.0` — indistinguishable
from an instant failure, despite the code comment promising exactly that
distinction. Fixed by moving the measurement into a `finally`.

Deferred (documented, not fixed) — each needs a decision rather than a patch:

| Item | Why deferred |
|---|---|
| §3.3 event-loop blocking | Making `analyze` sync moves inference to a threadpool and immediately opens the three races described. The right fix is a job queue or an explicit lock around the registry, which is an architecture decision, not a patch. The invariant is now documented in code. |
| §5.5 frontend test infra | Adding vitest + a schema↔types drift check is its own piece of work with new dependencies. |
| §3.6 `upload_ms` naming | Renaming a wire field is a contract change affecting M1/M3 per CONTRIBUTING.md; the misleading semantics are now documented in-code instead. |

---

## 1. Live bugs — reproducible today

### 1.1 ✅ FIXED — Hydration mismatch on every reload with Debug Mode on

> **Fixed** in `page.tsx`: `useState(false)` + a mount `useEffect` that reads
> `localStorage`, so the first client render matches the server byte-for-byte.
> Verified by pre-seeding `satquery.debug=true` and reloading — previously
> reproduced the error every time, now zero hydration errors and zero console
> errors, with the toggle still correctly restoring to `aria-pressed="true"`.

**`page.tsx:70-77` → `Sidebar.tsx:145-153`**

`debugMode` is initialized from `localStorage` inside a lazy `useState`
initializer. On the server that branch returns `false`; during the client's
hydration render it runs again and returns `true`. Both the conditional
`className` (`:148-152`) and `aria-pressed` (`:153`) then differ between the
server HTML and the client render.

React 19 reports *"A tree hydrated but some attributes of the server rendered
HTML didn't match the client properties"* — `+ aria-pressed={true}` vs
`- aria-pressed="false"` at `Sidebar.tsx (145:17)` — discards the SSR output,
and client-renders the root.

The `typeof window === "undefined"` guard does **not** prevent this. It only
makes the *server* branch safe; the mismatch is inherent to reading
client-only state during the hydration render.

**Fix:** initialize `useState(false)` unconditionally, read `localStorage` in
a mount `useEffect`. The first client render then matches the server exactly
and the value flips on the next commit.

### 1.2 ✅ FIXED — A failed pipeline step renders an invisible bar

> **Fixed** in `PipelineWaterfall.tsx`: the inference bar's `left` is now
> clamped to `100 - MIN_BAR_PCT` so it can never start past the track edge,
> and a failed step that died during load gets an explicit minimum-width red
> bar. Step errors also render beneath the row.

**`PipelineWaterfall.tsx:56`**

The bar is positioned `left: ${startPct + loadPct}%`. When the span-defining
step has `inference_time_ms === 0`, that resolves to `left: 100%` — the div
starts at the right edge of the `overflow-hidden` track (`:46`) and is fully
clipped. The `Math.max(inferPct, 0.75)` floor doesn't rescue it: a
0.75%-wide box at `left:100%` is still outside.

Not hypothetical: `executor.py:149-172` `break`s on failure, so **a failed
step is always the last step**, and a step dying inside `registry.get()` has
`load_ms = 0.0, infer_ms = 0.0`. The pipeline fails, the row shows an empty
track, and the legend says "red = failed step". The one thing the waterfall
exists to show is the one thing it can't.

### 1.3 ✅ FIXED — `DebugPanel` can crash the whole page

> **Fixed**: `DebugPanel` now reads `result?.execution_trace ?? null` and
> renders a plain message when there's no trace; `RouterMetricsHeader` bails
> on a partial `meta` and guards every field it formats.

**`DebugPanel.tsx:26,41`** — and the same class at **`RouterMetricsHeader.tsx:35,37,45`**

`useAnalysis.ts:36` does an unchecked `res.data as AnalysisResponse`. Every
other consumer defends against that: `ResultInspectorPanel.tsx:102` uses
`turn.result?.execution_trace ?? null`; `ExecutionTrace.tsx:14` bails on
`!trace`. `DebugPanel` alone does `result.execution_trace` then
`trace.pipeline_steps.length` unguarded.

A 200 response missing `execution_trace` (older deploy, proxy, mock) throws
`Cannot read properties of undefined`. There's no `app/error.tsx` and no
error boundary, so it takes down the page — only for users who enabled Debug
Mode, i.e. exactly the people trying to diagnose a bad response.

---

## 2. ✅ FIXED — Honesty regressions

> **All four fixed.** 2.1: `trace.py` now emits `registered`/`loaded` as
> `None` with no registry (schema fields made `Optional`), covered by a new
> test. 2.2: the "deterministic keyword matching" sentence is now gated on
> `router_type === "rule_based_keyword"`; any other router gets a plain
> "Not reported by this router." 2.3: the Request viewer now includes
> `modalities` and the real `debug` flag that was sent — verified live as
> `{query, images, modalities: ["optical"], debug: true}`. 2.4: rounding
> raised to 3 decimals backend-side and adaptive formatting (`39µs`,
> `0.62ms`) frontend-side; zero-duration steps render a tick marked "too
> fast to measure" instead of a floored bar, and the all-zero case says so
> explicitly rather than plotting a synthesized span.

The governing rule is *measured or null, never fabricated*. Four places break it.

| # | Location | Fabrication |
|---|---|---|
| 2.1 | `trace.py:176-177` | With `registry=None` (a path the docstring explicitly blesses), `info.get("registered", True)` / `("loaded", False)` assert every model **is registered and not loaded** — two positive claims from zero observation. `vram_gb`/`version` correctly degrade to `None`; these can't, because `schemas.py:94-95` types them non-`Optional`. |
| 2.2 | `RouterMetricsHeader.tsx:66-69` | The "not reported" fallback hardcodes *"…is deterministic keyword matching, with no language model in the loop"* for **any** router whose planner fields are null, interpolating `router_type` into a sentence true only of `RuleBasedRouter`. An LLM planner that doesn't report tokens would make the UI state a falsehood. |
| 2.3 | `DebugPanel.tsx:62-65` | The "Request" viewer shows `{query, images, debug}`, but `useAnalysis.ts:22-26` actually sends **`modalities`** too — omitted entirely. And `debug` shown is `trace.debug` (the response's echo), not the param that was sent. Omitting a real field is the same failure as inventing one, in a component whose docstring promises it "never invents a value the actual request/response didn't contain." |
| 2.4 | `trace.py:201` + `PipelineWaterfall.tsx:32,41` | Precision destroyed twice, then a bar drawn for work that took no time. `trace.py` rounds to 0.1ms (sub-100µs → `0.0`); `PipelineWaterfall.tsx:41` renders `.toFixed(0)` → whole ms, so a real 1.1ms step shows **"1ms"** and a real 0.4ms step shows **"0ms"**. `RouterMetricsHeader.tsx:37` meanwhile uses `.toFixed(2)` — inconsistent inside the same card. The `Math.max(inferPct, 0.75)` floor then paints a visible bar for a genuinely 0ms step. |

**Compounding this:** with today's sub-millisecond stub models every `time_ms`
is ~0, so `spanMs` falls back to the literal `1` (`PipelineWaterfall.tsx:21`)
and every row renders an identical ~3px stub. No axis, no total, nothing
saying the span is synthesized — the waterfall silently implies measurement
where its sibling components go out of their way to print "Not reported by
this router." A `spanMs` threshold → *"all steps completed in under 1ms"*
would match the rest of the feature.

---

## 3. Robustness — backend

### 3.1 ✅ FIXED — `sanitize.py` caps bound the output, not the work

**`sanitize.py:22-25, 113-136, 152-155`**

The depth guard fires at `depth >= 6`, so containers expand across six levels
of 25-way branching: 25⁶ ≈ **244 million** leaves. `MAX_TOTAL_BYTES` is only
checked *after* the whole tree is built and serialized, so it cannot prevent
any of that work.

Trigger — a ~200-byte **DAG, not a cycle**:

```python
x = [1] * 25
for _ in range(6):
    x = [x] * 25      # ~7 objects total
```

`seen = seen | {id(obj)}` correctly tracks ancestors (true cycles do
terminate — see §6), but each of the 25 siblings re-expands the shared child.
Minutes of CPU, tens of GB transient, ending in `MemoryError` or the OOM
killer — and since `sanitize_payload` runs synchronously inside an `async def`
handler, it stalls the **entire event loop**, not one request.

### 3.2 ✅ FIXED — Every upload leaks a temp dir; size cap checked after the write

**`routes.py:54-64`** — and the identical bug again at **`raster.py:27-29`**

`tempfile.mkdtemp()` with no `finally`, no `rmtree` — `shutil` isn't even
imported. `await img_file.read()` pulls the whole file into RAM unbounded, and
`settings.MAX_UPLOAD_SIZE_MB` is **never referenced outside `config.py`**. The
only size check (`validator.py:100-106`) runs *after* the bytes are in memory
and on disk.

POST a 2 GB `.png`: 2 GB allocated, 2 GB written, 422 returned, directory
never removed. `settings.TEMP_DIR` is `mkdir`'d at import then never used —
`mkdtemp()` ignores it, so there isn't even one directory an operator could
sweep.

### 3.3 Event loop blocking, and a latent race one keyword away

**`routes.py:23,113`**

`async def analyze` calls the **synchronous** `executor.execute(...)` on the
loop thread. A 7B generation with `max_new_tokens=512` blocks everything —
`/api/health` included — for tens of seconds. The telemetry feature exists to
make latency legible, and total request serialization is invisible in it.

The `last_telemetry` channel is safe **today** only because `execute()` never
yields. Deleting `async` (the standard fix for the blocking) opens three races
at once: telemetry cross-contamination (`executor.py:122-143`), a
check-then-act double model load (`registry.py:61-64` — two concurrent 5.5 GB
loads on an 8 GB card), and concurrent `generate()` on one HF model.
`base.py:20-30` documents the design but never states the invariant it rests on.

### 3.4 ✅ FIXED — `_ensure_vram` reintroduces the bug its docstring claims to fix

**`registry.py:82-114`**

The docstring says the old code broke because a non-`ImportError` "escaped
`_load()` and made every model load fail." The new code is structurally
identical: `mem_get_info()` at `:99`/`:108`, `except ImportError` at `:110`.
`mem_get_info()` raises `RuntimeError` on a bad CUDA context, post-fork, or
unhealthy driver → escapes `_ensure_vram` → escapes `_load` (which wraps only
the loader call, `:75-80`) → the step fails with a raw CUDA string, forever,
for the process lifetime. The same narrow catch at `routes.py:174-187` makes
`/api/health` return **500** on a sick GPU — orchestrators kill the pod
instead of draining it.

*(Not a defect: `torch>=2.4.0` is pinned and `mem_get_info()` has existed
since 1.13.)*

**Related** (`:101-108`): eviction's exit condition is driver free-memory, but
its only lever is dropping a Python reference. If a step's CUDA tensor is
still held in `context["intermediate"]`, the loop evicts **every** other
model, frees nothing, and OOMs anyway — having destroyed a warm cache.
`settings.MAX_VRAM_GB` is dead config that reads like an enforced budget.

### 3.5 ✅ FIXED — Two ways a bad model output escalates to a 500

- **Non-dict output** — `integrator.py:55` does `if "answer" in out`; for a
  string that's a *substring* test that can pass, then `out["answer"]` raises
  `TypeError`. The integrator runs at `routes.py:124`, **outside** the
  executor's try/except, so the whole request 500s instead of degrading to a
  failed step.
- **NaN in `confidence`** — `sanitize.py:80-83` nulls non-finite floats, but
  only for `payload_snapshot`. `integrator.py:73` passes model floats straight
  through and FastAPI's default encoder emits bare `NaN`, which `JSON.parse`
  rejects. The comment at `sanitize.py:81-82` diagnoses this exact problem and
  fixes it only for the field that doesn't matter.

### 3.6 Timing labels don't measure what their names claim

**`routes.py:45` vs `:54-64`** — FastAPI resolves `File(...)`/`Form(...)`
dependencies (fully receiving and spooling the body) *before* the handler body
runs, so `request_t0` is captured after network receive. `upload_ms` times
only the spool→disk copy. A 45 MB upload over 2 Mbps: the client waits ~3
minutes, `upload_ms` reports ~40, and `total_time_ms` omits ~180 s of real
latency.

**`trace.py:95`** — `total_time_ms` is computed at the *top* of `build()`, so
trace assembly (including `sanitize_payload`, the priciest non-inference op
under debug), response assembly, and JSON serialization all fall outside it.
`schemas.py:187-188` claims "upload read → response assembled" and `:145-147`
claims `other_ms` covers "trace building" — neither is true, and
trace-building can never appear in `other_ms` by construction.

---

## 4. ✅ FIXED — Completeness: captured but unreachable

> **Fixed.** `DebugPanel` now renders a "Where the time went" strip
> (`StageTimings` — verified live as *"handler total 5.21ms · of which
> pipeline steps 2.65ms"*, the contrast Stage 1 created and then hid), a
> "Step payloads" row surfacing `payload_bytes` per step, and each step's
> `error` beneath its waterfall row. `ResultInspectorPanel` now renders the
> card for **failed** turns too (`debugMode && !loading && (result || error)`),
> degrading to a request-only view plus the error message.
>
> Still open by choice: `InputComposition` largely duplicates ExecutionTrace's
> existing chips, and wiring `GET /api/health` is a new fetch with its own
> lifecycle — both are additive features rather than defects, tracked below.

The backend measures more than the UI shows. Grep confirms `timings`,
`input_composition`, `payload_snapshot`, `payload_bytes`, and `depends_on`
appear **only** in `types/api.ts` — no component dereferences them.

| Data | Status | Why it matters |
|---|---|---|
| `StageTimings` | never rendered | The original brief asked the Router Metrics card for a "planning vs model execution time split" — this is exactly that. Stage 1's headline fix made `total_time_ms` real wall-clock *with the old step-sum preserved as `pipeline_steps_ms`*, and that contrast is invisible without expanding raw JSON. |
| `InputComposition` | never rendered | Per-image dimensions/bands/size, total pixels. Partly duplicates ExecutionTrace's chips, but the per-image detail is new. |
| `payload_snapshot` / `payload_bytes` | only inside the whole-response blob | The entire payoff of `?debug=true` is reachable only by scrolling a 256px-tall `<pre>`. `payload_bytes` would show at a glance whether the size cap truncated. |
| `PipelineStep.error` | rendered by neither `ExecutionTrace` nor `PipelineWaterfall` | A step goes red with no way to read the exception message. |
| `GET /api/health` | no frontend consumer at all | `README.md:104` records it as *"the natural integration point for the Debug Mode work this branch exists to build"*, `:122` as *"the intended hook … to surface real backend/model state."* Debug Mode shipped without it, so `gpu_available` / `gpu_memory_used` / full `registered_models` stay invisible — the answer to the first question anyone asks ("why is every answer a stub?") still requires curling by hand. |

**Also:** `ResultInspectorPanel.tsx:103` gates on `debugMode && turn.result`,
so a **failed** turn (error, `result === null`) renders no debug card at all —
precisely when you most want to see what was sent. The request side is fully
known client-side; only the trace is missing.

---

## 5. ✅ MOSTLY FIXED — Tests and contract

> **Fixed.** Suite went **90 → 97**. Added: schema validation of the three
> risky shapes (populated *partial* telemetry, a failed step, `?debug=true`);
> a NaN test that can actually fail (drives a model returning `NaN`/`inf`
> through both the snapshot and confidence aggregation); a non-dict-output
> test proving the request degrades instead of 500-ing; a `?debug=false`
> override test; a node-budget test for the DAG blowup; and a
> sub-millisecond precision test. Fixed the two tests that couldn't fail:
> `test_failure_during_load` now sets `load_delay` (**which immediately
> exposed a real executor bug**), and `test_snapshots_are_off_by_default`
> now monkeypatches `settings.DEBUG_TRACE` instead of inheriting the
> environment.
>
> `ModelTelemetry` drift (§5.4) fixed at the source: `trace.py` normalizes
> every wrapper-supplied telemetry dict to all six declared keys, dropping
> unknown ones — so a partial dict can no longer ship keys the TS type
> promises are present. §5.5 (frontend test infra) remains deferred.

### 5.1 The schema tests are the stated safety net, and they miss the three riskiest shapes

Routes carry **no `response_model=`** (zero hits repo-wide), so `schemas.py` is
documentation, not a runtime contract — `AnalysisResponse`, `ExecutionTrace`,
and `HealthResponse` never execute. `test_trace_builder.py:222` and
`test_api_analyze.py:31` are therefore *the* enforcement point. But their
fixtures use `telemetry=None`, `error=None`, `success=True`, and never pass
`?debug=true`. Across the whole suite:

- `ModelTelemetry` is **never validated**, not once.
- A **failed step** never goes through `model_validate` or the API.
- `payload_snapshot` is never validated over the wire.

### 5.2 Tests that can't catch what they're named for

| Test | Problem |
|---|---|
| `test_api_analyze.py:38` `test_response_is_strictly_valid_json` | Targets NaN leaking via `payload_snapshot`, but never sets `?debug=true` — snapshots are all `None`. Delete `sanitize.py`'s NaN handling and it still passes. |
| `test_executor_telemetry.py:79` `test_failure_during_load_reports_no_inference_time` | Built with no `load_delay`, so `load_time_ms ≈ 0`. The property it exists to protect (load-vs-inference distinguishable on the error path) is unasserted; `inference_time_ms == 0.0` is trivially true since it's initialized to `0.0` before the raise. |
| `test_api_analyze.py:77` `test_snapshots_are_off_by_default` | The default comes from `settings.DEBUG_TRACE`; a dev or CI job with `SATQUERY_DEBUG=1` exported gets a spurious failure. No test covers `?debug=false` overriding a `True` setting. |
| `test_trace_builder.py:81` | `'"1.0"' not in json.dumps(...)` — a whole-document substring scan. Passes only because `ROUTER_VERSION` is `"rule_based_keyword/1"`; a regression emitting `version: 1.0` as a **float** slips straight through. |
| `test_trace_builder.py:190-194` | `execution_ms=15.5` coincidentally equals `sum(step.time_ms)`, so the assertion would still pass if `pipeline_steps_ms` were wired to the wrong source. Use distinct numbers. |
| `test_executor_telemetry.py:61` | `started_at_ms == 0.0 or … < 5` — the first disjunct is dead; `(perf_counter() - t0)*1000` is never exactly `0.0`. |

### 5.3 Tautological assertions

`other_ms >= 0` (×2), `upload_ms >= 0`, `routing_time_ms >= 0` — all
`perf_counter` deltas or `max(0.0, …)` clamps. `task_confidence is None`,
seven planner fields `is None`, `depends_on is None`, `crs is None` — all
mirror a literal `None` in `trace.py`. Defensible as anti-fabrication
tripwires (that *is* the feature's invariant), but they're implementation
assertions: they pass forever until someone edits the exact line they mirror.
Worth labelling as such rather than counting toward coverage.

### 5.4 Contract drift

- **`ModelTelemetry` is where TS actually lies.** `trace.py:204` passes
  `r.telemetry` through raw — whatever a wrapper assigned. `types/api.ts:24-31`
  declares all 6 keys **required**; `schemas.py:38-43` defaults all 6 to
  `None`, so a partial dict is valid Pydantic — and your own fixture
  (`test_executor_telemetry.py:102`) uses a 3-key dict. Today only `vqa.py`
  populates it and happens to emit all 6, so this is latent, not live.
- **`PipelineStep.error`** is `error?:` in TS while `trace.py:199` always emits
  it — the lone inconsistency against this file's own "explicitly null rather
  than absent" convention.
- **`HealthResponse` has no TS mirror at all**, so `api.ts:2`'s "Mirrors
  backend/app/api/schemas.py exactly" is false.
- **`_input_composition` can mislabel** (`trace.py:235-238`): the positional
  zip is length-guarded against `IndexError` but produces *wrong data* if
  image 0 fails and image 1 succeeds — index 0 gets the failed image's
  modality/date. Unreachable today (a read failure 422s first), latent and
  untested. Carrying a source index in `format_info` is the honest fix.
- **Key presence is otherwise clean.** `TraceBuilder.build()` returns one dict
  literal with no conditional keys, so the TS "required but nullable"
  declarations are honest and `.foo.bar` won't throw. Counts match 1:1 across
  all 9 models.

### 5.5 No frontend test infrastructure — at all

`package.json` has exactly `dev`, `build`, `start`. No `test`, no lint script,
no jest/vitest/playwright/testing-library, no `*.test.*`/`*.spec.*` anywhere.
The only automated check on frontend code is the implicit `tsc` inside
`next build` — and per §4 that can't detect drift in `StageTimings` /
`InputComposition` / `payload_snapshot`, because nothing dereferences them.
Nothing anywhere cross-checks `types/api.ts` against `schemas.py`, which is
exactly how §5.4 stays invisible.

---

## 6. Verified clean

Balance matters — these were checked and are correct:

- **Cycle detection** (`sanitize.py:117-119,129-131`) is the *right* algorithm.
  A true reference cycle always passes through an ancestor, so ancestor-only
  tracking catches every cycle. `id()` reuse isn't a risk: every id in `seen`
  belongs to an object held alive by an active stack frame. (The *cost*
  problem in §3.1 is separate.)
- **`json.dumps(..., allow_nan=False)`** — every path into `safe` nulls
  non-finite floats; remaining raisers are contained by the outer `try`.
- **`payload_bytes` is honestly labelled** — `ensure_ascii=True` means
  `len(encoded)` really is bytes.
- **No double-counting in `timings`** — `pipeline_steps_ms` is excluded from
  the `measured` sum, so `other_ms` doesn't subtract execution twice.
- **Stale-telemetry guard** (`executor.py:122-123`) is correct *and* has a real
  regression test that genuinely fails if deleted.
- **`_ensure_vram` terminates** — `candidates` shrinks monotonically.
- **Chromium `backdrop-filter` bug: no new violation.** The documented failure
  is a transform on the *same* element carrying `backdrop-filter` +
  `border-radius`. `DebugPanel.tsx:45`'s `rotate-180` is on a descendant and is
  character-for-character `ExecutionTrace.tsx:32` — established precedent.
  `ResultInspectorPanel.tsx:67`'s `motion.div` animates an unstyled outer
  wrapper, which is exactly the prescribed workaround.
- **No stale-closure bug** in `debugMode` threading — handlers are recreated
  each render and `analyze` takes it as a parameter.
- **`result: any → AnalysisResponse | null` broke nothing** (`tsc` exits 0).
- **Empty-state guards** in all three new leaf components are correct.
- **React keys** (`m.name`, `step.step`) are unique across every current
  routing branch.
- **Text-only (0-image) requests** through `input_composition` are covered by a
  real test.
- **`sanitize.py` is the best-tested module in the repo** — cycles, NaN, numpy,
  and every size cap are genuinely behavior-tested.

---

## 7. ✅ FIXED — Polish backlog

> **All applied.** `RawPayloadViewer`: `useMemo`'d serialization (with the
> Request object memoized at its source in `DebugPanel`, since a fresh
> literal would defeat the memo), `whitespace-pre-wrap break-words`,
> `overscroll-contain`, `tabIndex`/`aria-label` for keyboard scrolling, and a
> cleared copy timer on unmount. `ModelChoiceReasoner`: VRAM trimmed via
> `Number(x.toFixed(2))`. `Sidebar`: `aria-label="Debug Mode"` so the
> collapsed icon-only button has an accessible name. `DebugPanel`: added
> `aria-expanded`. `page.tsx`: the `localStorage` write moved out of the
> state updater. Waterfall load-bar floor made consistent with the inference
> bar.
>
> Not changed: `open` state still resets when scrolling between a turn's
> sections (`ExecutionTrace` has the identical long-standing behavior — worth
> fixing for both at once, not just here), and the `DebugPanel`/`ExecutionTrace`
> step-list overlap remains a design call.

| Location | Issue |
|---|---|
| `RawPayloadViewer.tsx:17` | Unmemoized `JSON.stringify` ×2 per render. `page.tsx`'s `map.on("move")` → `setFocusRect` fires **every frame** of any flight, so an expanded panel re-stringifies a multi-hundred-KB object ~42× during a 700ms reframe. Zero cost while collapsed. `useMemo` fixes it — but note `DebugPanel.tsx:62` passes a **fresh object literal** for the Request viewer, so that one needs memoizing at the source too. |
| `RawPayloadViewer.tsx:50` | Nested-scroll trap (inner `pre` inside the panel's `overflow-y-auto` inside a wheel-intercepting page), plus `<pre>` doesn't wrap so 512-char sanitized strings add a horizontal scrollbar. `whitespace-pre-wrap break-words` + `overscroll-contain`. |
| `RawPayloadViewer.tsx:50` | Not keyboard-reachable — no `tabIndex={0}`/`role`, so keyboard-only users can't scroll it (WCAG 2.1.1). First scrollable non-interactive block in the codebase, no precedent to inherit. |
| `RawPayloadViewer.tsx:23` | `setTimeout` never cleared on unmount; combined with the next row, the "Copied" state can be torn down mid-flight. |
| `DebugPanel.tsx:25` | `open` resets on every scroll between a turn's sections — `AnimatePresence` keys on `turn.id` and `revealedTurnId` flips to `null` on the landing section. `ExecutionTrace.tsx:12` has the identical flaw; lifting `open` to `page.tsx` fixes both. |
| `PipelineWaterfall.tsx:47` | Inconsistent floors — the green/red bar has a 0.75% minimum, the amber load bar has none, so a genuinely cold 0.4ms load in a 5000ms span is invisible while the label says "cold". |
| `ModelChoiceReasoner.tsx:43` | `{m.vram_gb} GB` unformatted — a float like `3.9500000000000002` renders raw; every other numeric uses `.toFixed()`. |
| `Sidebar.tsx:153` | No `aria-label`, so the collapsed icon-only button has no accessible name. ("New chat"/"Library" share the flaw — consistent-but-wrong.) `aria-pressed` is also the codebase's only one; the pin toggle at `:230` swaps `aria-label` instead, so the two toggles speak differently to screen readers. |
| `page.tsx:79-88` | `localStorage.setItem` inside the `setDebugMode` updater. Updaters must be pure; StrictMode double-invokes in dev, so the write fires twice. Idempotent today, but the side effect belongs outside. |
| `DebugPanel` vs `ExecutionTrace` | Both render the pipeline steps when Debug Mode is on — two stacked cards showing overlapping data. Worth deciding which one owns it. |

---

## 8. Outcome

Fixed and verified in this pass: **§1.1, §1.2, §1.3, §2.1–2.4, §3.1, §3.2,
§3.4, §3.5, §4 (rendering), §5.1–5.4, §7 (all)** — plus the executor
`load_time_ms` bug that surfaced while strengthening a test.

Verification: `pytest` 97 passed · `tsc --noEmit` clean · live request against
the running backend showing microsecond-resolution step timings, nullable
registry fields, and normalized telemetry · browser session confirming every
new panel section renders with zero console errors and no hydration warning.

Remaining, each needing a decision rather than a patch:

1. **§3.3** — event-loop blocking. Fixing it properly means a job queue or an
   explicit registry lock, not just dropping `async`. Invariant now documented.
2. **§5.5** — frontend test infrastructure (vitest + a schema↔types drift
   check). New dependencies, own piece of work.
3. **§4** — wire `GET /api/health` into the debug card for GPU/weights state;
   render `InputComposition`'s genuinely-new per-image detail.
4. **§3.6** — `upload_ms` measures spool-to-disk, not network receive.
   Renaming is a wire-contract change; semantics documented in-code for now.
5. **§7** — lift `open` state so the debug card survives scrolling (fix
   alongside `ExecutionTrace`, which shares the behavior).
