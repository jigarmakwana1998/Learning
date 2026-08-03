export type User = { id: string; email: string; role: "learner" | "admin" };
export type TopicIntent = { topic: string; level: "beginner" | "intermediate" | "advanced"; hoursPerWeek: number; weeks: number };
export type Source = { title: string; url: string; kind: "documentation" | "paper" | "book" | "lecture" | "article" | "repository"; rationale: string };

export type LessonContent = {
  heading?: string;
  body?: string;
  bullets?: string[];
  type?: "reading" | "concept" | "practice" | "tip" | "warning";
};
export type Lesson = {
  id: string;
  title: string;
  summary?: string;
  estimatedMinutes?: number;
  outcomes: string[];
  content: LessonContent[];
  sourceUrls: string[];
  completed?: boolean;
};
export type CourseModule = { id: string; week: number; title: string; outcomes: string[]; lessons: Lesson[] };
export type QuizQuestion = {
  id: string;
  prompt: string;
  type: "multiple_choice" | "short_answer" | "true_false";
  options?: string[];
  explanation?: string;
};
export type QuizResult = { scorePercent?: number; feedback: string; passed?: boolean; recommendation?: string };
export type SubmissionResult = { submissionId?: string; feedback: string; scorePercent?: number; status?: string; recommendation?: string };
type ApiQuizQuestion = { id: string; prompt: string; type?: QuizQuestion["type"]; options?: string[]; choices?: string[]; explanation?: string };
type AssignmentPrompt = { title?: string; prompt: string; deliverables?: string[]; rubric?: string[] };

export type LearningRun = {
  id: string;
  provider: "mock" | "codex" | "gemini-cli" | "antigravity-cli";
  research: { topic: string; sources: Source[] };
  // `course` is the richer v2 response. `curriculum` remains supported for existing API responses.
  course?: { title?: string; modules: ApiModule[] };
  curriculum: Array<{ id?: string; week: number; title: string; outcomes: string[]; source_urls: string[]; lessons?: Array<Record<string, unknown>> }>;
  assessment: { quiz: Array<string | ApiQuizQuestion>; quiz_items?: ApiQuizQuestion[]; assignment: string | AssignmentPrompt; project: string };
  sessions: Record<string, string>;
};

type ApiLesson = { id?: string; title?: string; summary?: string; objective?: string; practice?: string; estimated_minutes?: number; estimatedMinutes?: number; outcomes?: string[]; content?: LessonContent[] | string; source_urls?: string[]; sourceUrls?: string[]; completed?: boolean };
type ApiModule = { id?: string; week: number; title: string; outcomes?: string[]; source_urls?: string[]; lessons?: ApiLesson[] };

/** Converts legacy curriculum responses and snake_case v2 API responses into one UI model. */
export function courseModules(run: LearningRun): CourseModule[] {
  const apiModules: ApiModule[] = run.course?.modules ?? run.curriculum;
  return apiModules.map((module, moduleIndex) => {
    const outcomes = module.outcomes ?? [];
    const sourceUrls = module.source_urls ?? [];
    const lessons = (module.lessons?.length ? module.lessons : [{ title: module.title, outcomes, source_urls: sourceUrls }]).map((lesson, lessonIndex) => {
      const lessonOutcomes = lesson.outcomes ?? outcomes;
      return {
        id: lesson.id ?? `module-${moduleIndex + 1}-lesson-${lessonIndex + 1}`,
        title: lesson.title ?? `${module.title}: core concepts`,
        summary: lesson.summary,
        estimatedMinutes: lesson.estimated_minutes ?? lesson.estimatedMinutes ?? 30,
        outcomes: lessonOutcomes,
        content: typeof lesson.content === "string" ? [{ heading: lesson.objective ?? "Study guide", body: lesson.content, type: "concept" as const }, ...(lesson.practice ? [{ heading: "Practice", body: lesson.practice, type: "practice" as const }] : [])] : lesson.content?.length ? lesson.content : [{ heading: "What to focus on", body: "Work through the outcomes below. Use the linked course sources to deepen your understanding, then complete the knowledge check.", bullets: lessonOutcomes, type: "concept" as const }],
        sourceUrls: lesson.source_urls ?? lesson.sourceUrls ?? sourceUrls,
        completed: lesson.completed,
      };
    });
    return { id: module.id ?? `module-${moduleIndex + 1}`, week: module.week, title: module.title, outcomes, lessons };
  });
}

export function quizQuestions(run: LearningRun): QuizQuestion[] {
  if (run.assessment.quiz_items?.length) return run.assessment.quiz_items.map((item) => ({ id: item.id, prompt: item.prompt, type: item.type ?? ((item.options ?? item.choices)?.length ? "multiple_choice" : "short_answer"), options: item.options ?? item.choices, explanation: item.explanation }));
  return run.assessment.quiz.map((item, index) => typeof item === "string" ? ({ id: `quiz-${index + 1}`, prompt: item, type: "short_answer" }) : ({ id: item.id, prompt: item.prompt, type: item.type ?? ((item.options ?? item.choices)?.length ? "multiple_choice" : "short_answer"), options: item.options ?? item.choices }));
}

export function workPrompt(run: LearningRun, kind: "assignment" | "project") {
  if (kind === "project") return run.assessment.project;
  const assignment = run.assessment.assignment;
  if (typeof assignment === "string") return assignment;
  return [assignment.title, assignment.prompt, assignment.deliverables?.length ? `Deliverables: ${assignment.deliverables.join("; ")}` : ""].filter(Boolean).join("\n\n");
}

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
export const saveLessonProgress = (runId: string, lessonId: string, completed: boolean, token: string) => request<{ completed?: boolean }>(`/learning-runs/${runId}/progress`, { method: "PATCH", body: JSON.stringify({ lesson_id: lessonId, completed }) }, token);
export async function submitQuiz(runId: string, quizId: string, answers: Array<{ questionId: string; answer: string }>, token: string): Promise<QuizResult> {
  const data = await request<{ score_percent?: number; scorePercent?: number; feedback?: Array<{ correct?: boolean; explanation?: string }> | string; passed?: boolean; recommendation?: string }>(`/learning-runs/${runId}/quiz-submissions`, { method: "POST", body: JSON.stringify({ quiz_id: quizId, answers: answers.map(({ questionId, answer }) => ({ question_id: questionId, answer })) }) }, token);
  const feedback = Array.isArray(data.feedback) ? data.feedback.map((item, index) => `${item.correct ? "Correct" : `Question ${index + 1}: review needed`}${item.explanation ? ` — ${item.explanation}` : ""}`).join("\n") : data.feedback ?? "Your answers were submitted.";
  return { scorePercent: data.scorePercent ?? data.score_percent, feedback, passed: data.passed, recommendation: data.recommendation };
}
export async function submitWork(runId: string, kind: "assignment" | "project", response: string, token: string): Promise<SubmissionResult> {
  const data = await request<{ id?: string; submission_id?: string; status?: string; score_percent?: number; feedback?: string[] | string; recommendation?: string }>(`/learning-runs/${runId}/submissions`, { method: "POST", body: JSON.stringify({ kind, response }) }, token);
  return { submissionId: data.id ?? data.submission_id, status: data.status, scorePercent: data.score_percent, feedback: Array.isArray(data.feedback) ? data.feedback.join("\n") : data.feedback ?? "Your work was submitted.", recommendation: data.recommendation };
}
