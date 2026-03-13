const FALLBACK_API_BASE_URL = "http://127.0.0.1:8000";

declare global {
  interface Window {
    __BOTARDIUM_API_BASE_URL__?: string;
  }
}

const normalizeBaseUrl = (value?: string | null) => {
  const raw = String(value || "").trim();
  if (!raw) return "";
  return raw.replace(/\/+$/, "");
};

export const API_BASE_URL =
  normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL) ||
  normalizeBaseUrl(typeof window !== "undefined" ? window.__BOTARDIUM_API_BASE_URL__ : "") ||
  FALLBACK_API_BASE_URL;

export const apiUrl = (path: string) => {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
};
