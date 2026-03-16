import { toast } from "sonner";

const FALLBACK_API_BASE_URL = "http://127.0.0.1:8000";
export const AUTH_STORAGE_KEY = "botardium-auth";

export type StoredSession = {
  token: string;
  workspace_id: number;
  workspace_name: string;
  workspace_slug: string;
};

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

export const getStoredSession = (): StoredSession | null => {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (!parsed.token || !parsed.workspace_id || !parsed.workspace_name || !parsed.workspace_slug) {
      return null;
    }
    return {
      token: String(parsed.token),
      workspace_id: Number(parsed.workspace_id),
      workspace_name: String(parsed.workspace_name),
      workspace_slug: String(parsed.workspace_slug),
    };
  } catch {
    return null;
  }
};

export const setStoredSession = (session: StoredSession) => {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
};

export const clearStoredSession = () => {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
};

export const apiFetch = async (input: string, init?: RequestInit): Promise<Response> => {
  const session = getStoredSession();
  const headers = new Headers(init?.headers ?? {});
  if (session?.token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${session.token}`);
  }
  const target = /^https?:\/\//i.test(input) ? input : apiUrl(input);
  
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000);
  
  try {
    const response = await fetch(target, {
      ...init,
      headers,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (response.status === 401) {
      clearStoredSession();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent('botardium-session-expired'));
      }
      return response;
    }

    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('La solicitud tardó demasiado tiempo');
    }
    throw error;
  }
};
