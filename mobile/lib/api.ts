import { clearToken, getToken, setToken } from "@/lib/token-store";

export type User = { id: string; email: string; role: "learner" | "admin" };
export type CoverageItem = { id: string; question: string; status: "missing" | "partial" | "covered" };
export type SavedPage = { url: string; title: string; kind: string; why: string; key_points: string[]; covers: string[] };
export type ResearchRun = { id: string; topic: string; status: "running" | "completed" | "failed"; error?: string | null; activity?: string | null; coverage: CoverageItem[]; pages: SavedPage[] };
export type Sentence = { text: string; kind: "fact" | "explanation"; cites: Array<{ passage: string; quote: string }>; warning: string | null };
export type Chapter = { id: string; title: string; sections: Array<{ id: string; title: string; covers: string[] }> };
export type CourseVersion = { id: string; version: number; status: ResearchRun["status"]; created_at: string };
export type Course = CourseVersion & { research_run_id: string; topic: string; error: string | null; activity: string | null; gaps: string[]; chapters: Chapter[]; sections: Record<string, Sentence[][]>; sources: Array<{ id: string; url: string; title: string }> };

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, options: RequestInit = {}, authenticated = true): Promise<T> {
  const token = authenticated ? await getToken() : null;
  const response = await fetch(`${API_URL}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "Request failed");
  return response.json() as Promise<T>;
}

async function authenticate(mode: "login" | "register", email: string, password: string): Promise<User> {
  const result = await request<{ access_token: string | null; message?: string | null }>(
    `/auth/${mode}`,
    { method: "POST", body: JSON.stringify({ email, password }) },
    false,
  );
  if (!result.access_token) throw new Error(result.message ?? "Check your inbox to confirm your email, then sign in.");
  await setToken(result.access_token);
  return getMe();
}

export const login = (email: string, password: string) => authenticate("login", email, password);
export const register = (email: string, password: string) => authenticate("register", email, password);
export const logout = clearToken;
export const getMe = () => request<User>("/auth/me");
export const startResearchRun = (topic: string, hoursPerWeek: number) =>
  request<{ id: string }>("/research-runs", { method: "POST", body: JSON.stringify({ topic, hours_per_week: hoursPerWeek, weeks: 4, level: "beginner" }) });
export const getResearchRun = (id: string) => request<ResearchRun>(`/research-runs/${id}`);
export const buildCourse = (researchRunId: string) => request<{ id: string }>(`/research-runs/${researchRunId}/courses`, { method: "POST" });
export const getCourseVersions = (researchRunId: string) => request<CourseVersion[]>(`/research-runs/${researchRunId}/courses`);
export const getCourse = (id: string) => request<Course>(`/courses/${id}`);
