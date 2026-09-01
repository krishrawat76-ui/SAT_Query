# SAT_Query Frontend — Component Documentation (Phase 1)

> Covers `feature/core-dashboard`. Ground truth for payload shapes is
> `backend/app/api/schemas.py`; this doc mirrors it via `src/types/api.ts`.

## Architecture

```text
src/
├── app/
│   └── page.tsx            — layout, owns `images` and `query` state
├── components/
│   ├── ImageUpload.tsx      — dropzone, up to 2 images, modality selector
│   ├── QueryInput.tsx       — prompt box, suggestion chips
│   ├── ResultPanel.tsx      — answer, confidence badge, evidence grid
│   └── ExecutionTrace.tsx   — collapsible agent trace
├── hooks/
│   └── useAnalysis.ts       — POST /api/analyze via axios (pre-existing)
└── types/
    └── api.ts               — TS mirror of backend/app/api/schemas.py
```

State flow: `page.tsx` owns `images: UploadedImage[]` and `query: string`.
On submit it calls `analyze(files, query, modalities)` from `useAnalysis`,
which owns `result` / `loading` / `error`. Child components are otherwise
stateless/presentational and receive everything via props.

## Styling system

- Background: `bg-slate-50`, primary text `text-slate-900`.
- Containers: `rounded-3xl` (or `rounded-[28px]`), `border-slate-200/80`,
  `bg-white/80` or `bg-white`, `shadow-sm` / `shadow-md`.
- Inner elements (image cards, badges, step rows): `rounded-2xl` / `rounded-xl`.
- Pills/chips (suggestions, modality select): `rounded-full`.
- Frosted surfaces (query bar, trace panel, header): `backdrop-blur-md` on a
  translucent white background.
- Accent color is neutral (`slate-900` for primary actions) — status color
  (confidence, warnings, step success/error) uses `emerald` / `amber` / `rose`
  sparingly, never as a brand accent.

## Component reference

### `ImageUpload`

```ts
interface ImageUploadProps {
  images: UploadedImage[];
  onChange: (images: UploadedImage[]) => void;
  maxImages?: number; // default 2
}
```

- Accepts `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff` via `react-dropzone`.
- PNG/JPEG get a real `<img>` preview via `URL.createObjectURL`; TIFF/GeoTIFF
  show a placeholder (browsers can't decode TIFF), matching
  `05-FRONTEND-PLAN.md`'s "placeholder handling for TIFF" requirement.
- Object URLs are revoked on remove to avoid leaking memory.
- Each card has an OPTICAL/SAR `<select>` — this becomes the per-image
  `modalities` array sent to `/api/analyze`.

### `QueryInput`

```ts
interface QueryInputProps {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  disabled?: boolean;
}
```

- `Enter` submits, `Shift+Enter` inserts a newline.
- Suggestion chips are drawn from the exact query strings used in
  `docs/workflow/09-DEMO-SCRIPT.md` (Demos 1–5) so they double as a demo
  rehearsal aid.
- Submit button shows a `Loader2` spinner while `loading` is true.

### `ResultPanel`

```ts
interface ResultPanelProps {
  result: AnalysisResponse | null;
  loading: boolean;
  error: string | null;
}
```

- Renders `result.answer`, a confidence badge (`≥0.8` emerald / `≥0.5` amber /
  else rose — thresholds match `05-FRONTEND-PLAN.md`'s low/medium/high spec),
  `result.evidence.images` as a 2-col grid, and `result.evidence.regions` as
  a labeled confidence list.
- Three mutually exclusive states: skeleton (`loading`), inline error
  (`error`), empty state (`!result`), populated result.

### `ExecutionTrace`

```ts
interface ExecutionTraceProps {
  trace: ExecutionTraceData | null;
}
```

- Returns `null` (renders nothing) until a trace exists — avoids an empty
  accordion before the first request.
- Closed by default; header always shows `detected_task`, task confidence,
  and total latency so the key trace facts are visible without expanding.
- Expanded body shows `reasoning`, validation summary (image count, modality,
  temporal/cross-modal flags, warnings), and per-step status/timing with
  `CheckCircle2` / `XCircle` icons per `PipelineStep.status`.

## Wiring (`page.tsx`)

- Two-column layout ≥ `lg`: fixed 380px upload rail + flexible result column.
- Submit is disabled until at least one image is present (`ImageUpload`
  itself does not block empty-state submission, so `page.tsx` gates it).
- `images.map((img) => img.modality)` is passed positionally into
  `analyze(files, query, modalities)`, matching how
  `backend/app/agent/validator.py` zips `modalities` to `image_paths` by
  index.

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
3. **Run backend** (separate terminal, from repo root):
```bash
   cd backend
   uvicorn app.main:app --reload --port 8000
```
4. **Run frontend**:
```bash
   npm run dev
```
   Open `http://localhost:3000`.
5. **Manual smoke test** (mirrors `09-DEMO-SCRIPT.md`):
   - Upload 1 PNG/JPEG → confirm thumbnail preview renders.
   - Upload a `.tif` → confirm the "GeoTIFF preview unavailable" placeholder
     renders instead of a broken image.
   - Try uploading a 3rd image → dropzone should disable at 2/2.
   - Click a suggestion chip → textarea populates; press `Enter` → request
     fires (Analyze button shows spinner).
   - Toggle a card's modality to SAR with a 2nd image present → verify router
     hits the `OPTICAL_SAR` pipeline (`execution_trace.detected_task`).
   - With backend stopped, submit → confirm the axios error message renders
     in `ResultPanel`'s error state (not a crash).
   - Expand `ExecutionTrace` → confirm all `pipeline_steps` show correct
     status icons and per-step timing.
6. **Type check**:
```bash
   npx tsc --noEmit
```