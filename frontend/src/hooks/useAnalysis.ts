import { useState } from "react";
import axios from "axios";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function useAnalysis() {
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = async (images: File[], query: string, modalities: string[]) => {
    setLoading(true);
    setError(null);
    setResult(null);

    const form = new FormData();
    images.forEach((img) => form.append("images", img));
    form.append("query", query);
    form.append("modalities", modalities.join(","));

    try {
      const res = await axios.post(`${API}/api/analyze`, form, { timeout: 120000 });
      setResult(res.data);
    } catch (e: any) {
      setError(e.response?.data?.detail?.errors?.join(", ") || e.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return { analyze, result, loading, error };
}
