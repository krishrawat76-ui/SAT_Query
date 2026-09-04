import { useState } from "react";
import axios from "axios";
import type { AnalysisResponse } from "@/types/api";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function useAnalysis() {
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = async (
    images: File[],
    query: string,
    modalities: string[],
    debug = false
  ) => {
    setLoading(true);
    setError(null);
    setResult(null);

    const form = new FormData();
    images.forEach((img) => form.append("images", img));
    form.append("query", query);
    form.append("modalities", modalities.join(","));

    try {
      // debug is a query param, not a form field, so the multipart body
      // stays identical for every client regardless of whether Debug Mode
      // is on — it only asks the backend to attach sanitized per-step
      // payload snapshots to the execution trace (see backend/app/api/routes.py).
      const res = await axios.post(`${API}/api/analyze`, form, {
        timeout: 120000,
        params: debug ? { debug: true } : undefined,
      });
      setResult(res.data as AnalysisResponse);
    } catch (e: any) {
      if (e.response) {
        setError(e.response.data?.detail?.errors?.join(", ") || e.message || "An error occurred");
      } else {
        // No response at all — the request never reached the server (backend
        // down, wrong NEXT_PUBLIC_API_URL, CORS, etc). Axios's own message
        // for this is just "Network Error", which isn't actionable.
        setError(`Couldn't reach the backend at ${API} — make sure it's running.`);
      }
    } finally {
      setLoading(false);
    }
  };

  return { analyze, result, loading, error };
}
