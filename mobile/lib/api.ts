import { clearToken, getToken, setToken } from "@/lib/token-store";

export type User = { id: string; email: string; role: "learner" | "admin" };
export type Source = { title: string; url: string; kind: string; rationale: string; key_points?: string[] };
export type SourceVisit = { url: string; title?: string; status: "discovered" | "read" | "unavailable"; selected: boolean };
export type ResearchCoverage = { requirement_id: string; question: string; priority: "core" | "supporting"; depth: "overview" | "detailed"; evidence_policy: "single_source_ok" | "corroborate"; status: "covered" | "partial" | "missing"; confidence: number; supported_by: string[]; rationale: string };
export type ResearchStats = { rounds: number; searches: number; pages_attempted: number; pages_read: number; sources_selected: number };
export type AgentHarness = "deep-agents";
export type LearningRun = { id: string; harness: AgentHarness; research: { topic: string; sources: Source[]; visited_sources?: SourceVisit[]; coverage?: ResearchCoverage[]; stop_reason?: "coverage_satisfied" | "budget_exhausted" | "no_new_evidence" | null; warnings?: string[]; research_stats?: ResearchStats }; sessions: Record<string, string> };
export type LearningRunTrace = { run_id: string; sessions: Array<{ id: string; agent_name: string; harness: AgentHarness; status: string; duration_ms?: number; transcript: Array<{ role: string; content: string; created_at: string }>; tool_invocations: Array<{ tool_name: string; status: string; duration_ms?: number; metadata?: { query?: string; purpose?: string; urls?: string[]; page_results?: Array<{ url: string; status: string }> }; created_at: string }> }> };

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
export async function createLearningRun(topic: string, hoursPerWeek: number): Promise<LearningRun> {
  const { id } = await request<{ id: string }>("/learning-runs", { method: "POST", body: JSON.stringify({ topic, hours_per_week: hoursPerWeek, weeks: 4, level: "beginner" }) });
  // Research can take minutes; poll instead of holding one request open.
  // A status check can blip (e.g. a transient auth 502); only give up after 3 in a row.
  for (let failures = 0; ; ) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    let run: { status: string; error?: string | null };
    try {
      run = await request(`/learning-runs/${id}/status`);
      failures = 0;
    } catch (error) {
      if (++failures >= 3) throw error;
      continue;
    }
    if (run.status === "completed") return request<LearningRun>(`/learning-runs/${id}`);
    if (run.status === "failed") throw new Error(run.error ?? "Research failed.");
  }
}
export const getLearningRunTrace = (id: string) => request<LearningRunTrace>(`/learning-runs/${id}/trace`);
