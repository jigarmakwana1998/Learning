export type User = { id: string; email: string; role: "learner" | "admin" };
export type TopicIntent = { topic: string; level: "beginner" | "intermediate" | "advanced"; hoursPerWeek: number; weeks: number };
export type CoverageItem = { id: string; question: string; status: "missing" | "partial" | "covered" };
export type SavedPage = { url: string; title: string; kind: "documentation" | "paper" | "book" | "lecture" | "slides" | "article" | "repository"; why: string; key_points: string[]; covers: string[] };
export type ResearchRun = { id: string; topic: string; status: "running" | "completed" | "failed"; error?: string | null; activity?: string | null; coverage: CoverageItem[]; pages: SavedPage[] };

export type AgentHarness = "deep-agents";

export type TraceEvent = {
  id: string; session_id: string; sequence: number; event_type: "lifecycle" | "harness" | "model" | "tool";
  name: string; status: "started" | "completed" | "failed"; input_payload: Record<string, unknown> | null;
  output_payload: Record<string, unknown> | null; metadata: Record<string, unknown> | null;
  error_message: string | null; duration_ms: number | null; prompt_tokens: number | null;
  completion_tokens: number | null; total_cost_usd: number | null; created_at: string;
};
export type TraceRun = {
  id: string; topic: string; harness: string; status: string; started_at: string; event_count: number;
  total_cost_usd: number; sessions: Array<{ id: string; agent_name: string; status: string }>; events: TraceEvent[];
};
export type TraceRunListItem = Omit<TraceRun, "sessions" | "events">;

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? "The request could not be completed.");
  }
  return response.json() as Promise<T>;
}

export type AuthResult = { access_token: string | null; role: User["role"]; message?: string | null };
export const login = (email: string, password: string) => request<AuthResult>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
export const register = (email: string, password: string) => request<AuthResult>("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) });
export const getMe = (token: string) => request<User>("/auth/me", {}, token);
export const startResearchRun = (intent: TopicIntent, token: string) =>
  request<{ id: string }>("/research-runs", { method: "POST", body: JSON.stringify({ topic: intent.topic, level: intent.level, hours_per_week: intent.hoursPerWeek, weeks: intent.weeks }) }, token);
export const getResearchRun = (id: string, token: string) => request<ResearchRun>(`/research-runs/${id}`, {}, token);
export const getTraceRuns = (token: string) => request<TraceRunListItem[]>("/observability/runs", {}, token);
export const getTraceRun = (runId: string, token: string) => request<TraceRun>(`/observability/runs/${runId}`, {}, token);
