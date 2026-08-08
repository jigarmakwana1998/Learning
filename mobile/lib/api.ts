import { supabase } from "@/lib/supabase";

export type User = { id: string; email: string; role: "learner" | "admin" };
export type Source = { title: string; url: string; kind: string; rationale: string; key_points?: string[] };
export type SourceVisit = { url: string; title?: string; status: "discovered" | "read" | "unavailable"; selected: boolean };
export type LessonParagraph = { text: string; source_urls: string[] };
export type CourseLesson = { id: string; title: string; objective: string; content?: string; paragraphs?: LessonParagraph[]; practice: string; estimated_minutes: number; source_urls: string[] };
export type CourseModule = { week: number; title: string; outcomes: string[]; source_urls?: string[]; overview?: string; estimated_hours?: number; lessons?: CourseLesson[] };
export type QuizItem = { id: string; module_week: number; prompt: string; choices: string[] };
export type AssignmentPrompt = { title: string; prompt: string; deliverables: string[]; rubric: string[] };
export type AgentHarness = "codex" | "gemini-cli" | "antigravity-cli";
export type LearningRun = { id: string; harness: AgentHarness; research: { topic: string; sources: Source[]; visited_sources?: SourceVisit[] }; curriculum: CourseModule[]; assessment: { quiz: QuizItem[]; quiz_items?: QuizItem[]; assignment: AssignmentPrompt; project: string }; sessions: Record<string, string> };
export type AnalyticsOverview = { total_users: number; total_requests: number; completed_runs: number; failed_runs: number; active_sessions: number; transcript_entries: number; average_session_duration_ms: number };
export type Session = { id: string; agent_name: string; harness: AgentHarness; status: string; learning_request_id: string; topic: string; duration_ms: number | null; started_at: string };
export type TranscriptSession = { id: string; run_id: string; agent_name: string; harness: AgentHarness; status: string; transcript: Array<{ role: string; content: string; created_at: string }> };
export type LearningRunTrace = { run_id: string; sessions: Array<{ id: string; agent_name: string; harness: AgentHarness; status: string; duration_ms?: number; transcript: Array<{ role: string; content: string; created_at: string }>; tool_invocations: Array<{ tool_name: string; status: string; duration_ms?: number; metadata?: { query?: string; purpose?: string; urls?: string[]; page_results?: Array<{ url: string; status: string }> }; created_at: string }> }> };

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, options: RequestInit = {}, authenticated = true): Promise<T> {
  const { data: { session } } = authenticated ? await supabase.auth.getSession() : { data: { session: null } };
  const token = session?.access_token;
  const response = await fetch(`${API_URL}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "Request failed");
  return response.json() as Promise<T>;
}

async function authenticate(mode: "login" | "register", email: string, password: string): Promise<User> {
  const result = mode === "login"
    ? await supabase.auth.signInWithPassword({ email, password })
    : await supabase.auth.signUp({ email, password });
  if (result.error) throw result.error;
  if (!result.data.session) throw new Error("Check your inbox to confirm your email, then sign in.");
  return getMe();
}

export const login = (email: string, password: string) => authenticate("login", email, password);
export const register = (email: string, password: string) => authenticate("register", email, password);
export const logout = () => supabase.auth.signOut();
export const getMe = () => request<User>("/auth/me");
export const createLearningRun = (topic: string, hoursPerWeek: number) => request<LearningRun>("/learning-runs", { method: "POST", body: JSON.stringify({ topic, hours_per_week: hoursPerWeek, weeks: 4, level: "beginner" }) });
export const getOverview = () => request<AnalyticsOverview>("/analytics/overview");
export const getUsers = () => request<{ items: User[] }>("/analytics/users");
export const getSessions = () => request<Session[]>("/analytics/sessions");
export const getTranscript = (id: string) => request<TranscriptSession>(`/agent-sessions/${id}`);
export const getLearningRunTrace = (id: string) => request<LearningRunTrace>(`/learning-runs/${id}/trace`);
export const getAgentHarness = () => request<{ harness: AgentHarness }>("/analytics/settings/agent-harness");
export const setAgentHarness = (harness: AgentHarness) => request<{ harness: AgentHarness }>("/analytics/settings/agent-harness", { method: "PUT", body: JSON.stringify({ harness }) });
