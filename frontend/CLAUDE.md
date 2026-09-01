# Project Context: SAT_Query AI Dashboard

# 1. Ground Truth & Conflict Resolution Policy
- **Primary Source of Truth**: The Markdown specification files located inside the `docs/` folder (`docs/*.md`) serve as the absolute authority for system requirements, backend contract definitions, pipeline workflows, and UI specifications.
- **Conflict Handling**: If any discrepancy or contradiction arises between general code implementations, `CLAUDE.md`, user prompts, or component logic, ALWAYS defer to and prioritize the specifications in the `docs/` folder.

## 2. Overview
SAT_Query is an AI-powered multimodal satellite imagery analysis dashboard. It allows users to upload satellite imagery (Optical & SAR), enter natural language queries, and view intelligent detection results, confidence scores, evidence images, and execution pipeline traces from a FastAPI backend.

## 3. Tech Stack & Architecture
- **Frontend Framework**: Next.js 14+ (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS (Dark theme: `bg-slate-950`, `text-slate-100`, `border-slate-800`)
- **Icons**: Lucide React (`lucide-react`)
- **HTTP Client**: Axios (`axios`)
- **File Uploads**: `react-dropzone`
- **Backend API**: FastAPI running locally at `http://localhost:8000` (`NEXT_PUBLIC_API_URL`)

## 4. Directory Structure
```
frontend/
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx            # Main dashboard container
│   │   └── globals.css
│   ├── components/
│   │   ├── ImageUpload.tsx     # Dropzone & modality (OPTICAL/SAR) selector
│   │   ├── QueryInput.tsx      # Textarea prompt box & example prompt chips
│   │   ├── ResultPanel.tsx     # Answer, confidence score, and evidence grid
│   │   └── ExecutionTrace.tsx  # Collapsible pipeline steps & step-time trace
│   └── hooks/
│       └── useAnalysis.ts      # Custom hook calling FastAPI /api/analyze
├── .env.local                  # NEXT_PUBLIC_API_URL=http://localhost:8000
├── package.json
└── tsconfig.json
```

## 5. Key Component Contracts & Interfaces
- **`useAnalysis.ts`**: Handles payload formatting, FormData creation for file/modality pairs, timeout (120s), and managing `loading`, `error`, and `result` states.
- **`ImageUpload.tsx`**: Accepts up to 2 satellite images (`.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`). Each file is paired with a modality (`optical` | `sar`).
- **`QueryInput.tsx`**: Receives query text, supports example chip clicks, and triggers analysis.
- **`ResultPanel.tsx`**: Renders `result.answer`, `result.confidence`, and `result.evidence.images`.
- **`ExecutionTrace.tsx`**: Displays collapsible execution metrics: `detected_task`, `total_time_ms`, and `pipeline_steps` array.

## 6. Coding & Workflow Guidelines
- Always use `"use client";` directives for interactive Client Components in Next.js.
- Ensure strict TypeScript typing for all props, states, and API responses.
- Maintain a modern, sleek dark UI aesthetic using Tailwind CSS slate colors (`slate-900`, `slate-950`).
- Keep code clean, modular, and self-contained within `src/components/`.
