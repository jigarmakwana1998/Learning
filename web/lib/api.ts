export type User = { id: string; email: string; role: "learner" | "admin" };
export type TopicIntent = { topic: string; level: "beginner" | "intermediate" | "advanced"; hoursPerWeek: number; weeks: number };
export type Source = { title: string; url: string; kind: "documentation" | "paper" | "book" | "lecture" | "article" | "repository"; rationale: string };
export type LearningRun = {
  id: string;
  provider: "mock" | "codex" | "gemini-cli" | "antigravity-cli";
  research: { topic: string; sources: Source[] };
  curriculum: Array<{ week: number; title: string; outcomes: string[]; source_urls: string[] }>;
  assessment: { quiz: string[]; assignment: string; project: string };
  sessions: Record<string, string>;
};

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

export const login = (email: string, password: string) => request<{ access_token: string; role: User["role"] }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
export const register = (email: string, password: string) => request<{ access_token: string; role: User["role"] }>("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) });
export const getMe = (token: string) => request<User>("/auth/me", {}, token);
export const createLearningRun = (intent: TopicIntent, token: string) => request<LearningRun>("/learning-runs", { method: "POST", body: JSON.stringify({ topic: intent.topic, level: intent.level, hours_per_week: intent.hoursPerWeek, weeks: intent.weeks }) }, token);
