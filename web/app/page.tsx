"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, BookOpenCheck } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { AuthPanel } from "@/components/auth-panel";
import { IntakeForm } from "@/components/intake-form";
import { ResearchResults } from "@/components/research-results";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getMe, getResearchRun, startResearchRun, type TopicIntent } from "@/lib/api";

const tokenKey = "learning-coach-token";

export default function Home() {
  const [token, setToken] = useState<string>();
  const [ready, setReady] = useState(false);
  const [runId, setRunId] = useState<string>();
  useEffect(() => { setToken(sessionStorage.getItem(tokenKey) ?? undefined); setReady(true); }, []);
  const userQuery = useQuery({ queryKey: ["me", token], queryFn: () => getMe(token!), enabled: Boolean(token), retry: false });
  const generation = useMutation({ mutationFn: (intent: TopicIntent) => startResearchRun(intent, token!), onSuccess: ({ id }) => setRunId(id) });
  // Poll while the agent works so coverage and pages appear as they arrive.
  const run = useQuery({ queryKey: ["research-run", runId, token], queryFn: () => getResearchRun(runId!, token!), enabled: Boolean(token && runId), refetchInterval: (query) => (query.state.data?.status === "running" || !query.state.data ? 2000 : false) });

  function signOut() { sessionStorage.removeItem(tokenKey); setToken(undefined); setRunId(undefined); }
  if (!ready) return <main className="grid min-h-screen place-items-center text-muted-foreground" aria-live="polite">Loading Learning Coach...</main>;
  if (!token) return <PublicLanding onAuthenticated={setToken} />;
  if (userQuery.isError) return <PublicLanding error="Your session has expired. Please sign in again." onAuthenticated={setToken} />;
  if (!userQuery.data) return <main className="grid min-h-screen place-items-center text-muted-foreground" aria-live="polite">Restoring your session...</main>;

  return <AppShell user={userQuery.data} onSignOut={signOut}>
    <div className="grid gap-8">
      {generation.error && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{generation.error instanceof Error ? generation.error.message : "We could not research that topic. Please try again."}</p>}
      <IntakeForm onSubmit={generation.mutate} pending={generation.isPending} />
      {run.data?.status === "failed" && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{run.data.error ?? "Research failed. Please try again."}</p>}
      {run.data && <ResearchResults run={run.data} />}
    </div>
  </AppShell>;
}

function PublicLanding({ onAuthenticated, error }: { onAuthenticated: (token: string) => void; error?: string }) {
  return <main className="min-h-screen px-4 py-8 sm:px-6 sm:py-14"><div className="mx-auto grid max-w-6xl items-center gap-10 lg:grid-cols-[1.1fr_0.9fr]">
    <section><p className="inline-flex items-center gap-2 rounded-full bg-accent px-3 py-1 text-sm font-semibold text-primary"><BookOpenCheck size={16} aria-hidden="true" />Evidence-first learning</p><h1 className="mt-5 max-w-3xl text-4xl font-bold tracking-tight sm:text-6xl">A trustworthy path from curiosity to capability.</h1><p className="mt-5 max-w-2xl text-lg leading-8 text-muted-foreground">Enter what you want to learn. The research agent maps what to cover and finds the pages that teach each part, from sources it actually opened and read.</p><div className="mt-8 grid gap-3 sm:grid-cols-3"><Value title="Coverage map" text="A checklist of what the topic involves, sized to your level." /><Value title="Curated pages" text="Each item links to pages that actually teach it." /><Value title="Visible process" text="Inspect every visited page, transcript, and tool call." /></div></section>
    <div>{error && <p role="alert" className="mb-4 flex gap-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"><AlertTriangle className="shrink-0" size={18} aria-hidden="true" />{error}</p>}<AuthPanel onAuthenticated={onAuthenticated} /><p className="mx-auto mt-4 max-w-md text-center text-xs leading-5 text-muted-foreground">Agent-generated content is displayed as text, not executable markup. Always evaluate external sources for your own context.</p></div>
  </div></main>;
}

function Value({ title, text }: { title: string; text: string }) { return <Card className="p-4"><h2 className="font-bold">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{text}</p></Card>; }
