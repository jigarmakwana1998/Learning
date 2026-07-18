import { supabase } from "@/lib/supabase";

export type User = { id: string; email: string; role: "learner" | "admin" };
export type LearningRun = { id: string; provider: "mock" | "codex" | "gemini-cli" | "antigravity-cli"; research: { sources: Array<{ title: string; url: string; kind: string; rationale: string }> }; curriculum: Array<{ week: number; title: string; outcomes: string[] }>; assessment: { quiz: string[]; assignment: string; project: string }; sessions: Record<string, string> };
export type AnalyticsOverview = { total_users: number; total_requests: number; completed_runs: number; failed_runs: number; active_sessions: number; transcript_entries: number; average_session_duration_ms: number };
export type Session = { id: string; agent_name: string; provider: string; status: string; learning_request_id: string; topic: string; duration_ms: number | null; started_at: string };
export type TranscriptSession = { id: string; run_id: string; agent_name: string; provider: string; status: string; transcript: Array<{ role: string; content: string; created_at: string }> };

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
export const createLearningRun = (topic: string, hoursPerWeek: number) => request<LearningRun>("/learning-runs", { method: "POST", body: JSON.stringify({ topic, hours_per_week: hoursPerWeek, weeks: 4, level: "beginner", provider: "mock" }) });
export const getOverview = () => request<AnalyticsOverview>("/analytics/overview");
export const getUsers = () => request<{ items: User[] }>("/analytics/users");
export const getSessions = () => request<Session[]>("/analytics/sessions");
export const getTranscript = (id: string) => request<TranscriptSession>(`/agent-sessions/${id}`);
