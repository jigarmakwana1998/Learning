export type User = { id: string; email: string; role: "learner" | "admin" };
export type TopicIntent = { topic: string; level: "beginner" | "intermediate" | "advanced"; hoursPerWeek: number; weeks: number };
export type Source = { title: string; url: string; kind: "documentation" | "paper" | "book" | "lecture" | "slides" | "article" | "repository"; rationale: string; key_points?: string[] };
export type SourceVisit = { url: string; title?: string; status: "discovered" | "read" | "unavailable"; selected: boolean };
export type ResearchCoverage = { requirement_id: string; question: string; priority: "core" | "supporting"; depth: "overview" | "detailed"; evidence_policy: "single_source_ok" | "corroborate"; status: "covered" | "partial" | "missing"; confidence: number; supported_by: string[]; rationale: string };
export type ResearchStats = { rounds: number; searches: number; pages_attempted: number; pages_read: number; sources_selected: number };

export type AgentHarness = "deep-agents";
export type ResearchBrief = { topic: string; sources: Source[]; visited_sources?: SourceVisit[]; coverage?: ResearchCoverage[]; stop_reason?: "coverage_satisfied" | "budget_exhausted" | "no_new_evidence" | null; warnings?: string[]; research_stats?: ResearchStats };
export type LearningRun = { id: string; harness: AgentHarness; research: ResearchBrief; sessions: Record<string, string> };

export type AgentTrace = {
  run_id: string;
  sessions: Array<{
    id: string;
    agent_name: string;
    harness: AgentHarness;
    status: string;
    duration_ms?: number;
    transcript: Array<{ role: string; content: string; created_at: string }>;
    tool_invocations: Array<{
      tool_name: string;
      status: string;
      duration_ms?: number;
      metadata?: { query?: string; purpose?: string; urls?: string[]; domains?: string[]; result_count?: number; success_count?: number; page_results?: Array<{ url: string; status: "read" | "unavailable" }> };
      error?: string;
      created_at: string;
    }>;
  }>;
};

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
export async function createLearningRun(intent: TopicIntent, token: string): Promise<LearningRun> {
  const { id } = await request<{ id: string }>("/learning-runs", { method: "POST", body: JSON.stringify({ topic: intent.topic, level: intent.level, hours_per_week: intent.hoursPerWeek, weeks: intent.weeks }) }, token);
  // Research can take minutes; poll instead of holding one request open.
  // A status check can blip (e.g. a transient auth 502); only give up after 3 in a row.
  for (let failures = 0; ; ) {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    let run: { status: string; error?: string | null };
    try {
      run = await request(`/learning-runs/${id}/status`, {}, token);
      failures = 0;
    } catch (error) {
      if (++failures >= 3) throw error;
      continue;
    }
    if (run.status === "completed") return request<LearningRun>(`/learning-runs/${id}`, {}, token);
    if (run.status === "failed") throw new Error(run.error ?? "Research failed.");
  }
}
export const getLearningRunTrace = (runId: string, token: string) => request<AgentTrace>(`/learning-runs/${runId}/trace`, {}, token);
export const getTraceRuns = (token: string) => request<TraceRunListItem[]>("/observability/runs", {}, token);
export const getTraceRun = (runId: string, token: string) => request<TraceRun>(`/observability/runs/${runId}`, {}, token);
