"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BookOpenCheck, Clock3, Menu, Plus, X } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { AuthPanel } from "@/components/auth-panel";
import { CoursePanel } from "@/components/course-panel";
import { IntakeForm } from "@/components/intake-form";
import { ResearchResults } from "@/components/research-results";
import { ResearchActivity } from "@/components/research-activity";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getMe, getResearchRun, getResearchRuns, startResearchRun, type TopicIntent } from "@/lib/api";

const tokenKey = "learning-coach-token";
const runKey = "learning-coach-run";

export default function Home() {
  const [token, setToken] = useState<string>();
  const [ready, setReady] = useState(false);
  const [runId, setRunId] = useState<string>();
  const [tab, setTab] = useState<"research" | "course" | "explorer">("research");
  const [historyOpen, setHistoryOpen] = useState(false);
  const queryClient = useQueryClient();
  useEffect(() => { setToken(sessionStorage.getItem(tokenKey) ?? undefined); setRunId(sessionStorage.getItem(runKey) ?? undefined); setReady(true); }, []);
  useEffect(() => { if (ready) { if (runId) sessionStorage.setItem(runKey, runId); else sessionStorage.removeItem(runKey); } }, [ready, runId]);
  useEffect(() => {
    if (!historyOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    document.querySelector<HTMLElement>("#research-history button")?.focus();
    return () => previous?.focus();
  }, [historyOpen]);
  const userQuery = useQuery({ queryKey: ["me", token], queryFn: () => getMe(token!), enabled: Boolean(token), retry: false });
  const history = useQuery({ queryKey: ["research-runs", token], queryFn: () => getResearchRuns(token!), enabled: Boolean(token && userQuery.data) });
  const generation = useMutation({ mutationFn: (intent: TopicIntent) => startResearchRun(intent, token!), onSuccess: ({ id }) => { setRunId(id); setTab("research"); queryClient.invalidateQueries({ queryKey: ["research-runs", token] }); } });
  // Poll while the agent works so coverage and pages appear as they arrive.
  const run = useQuery({ queryKey: ["research-run", runId, token], queryFn: () => getResearchRun(runId!, token!), enabled: Boolean(token && runId), refetchInterval: (query) => (query.state.data?.status === "running" || !query.state.data ? 2000 : false) });

  function signOut() { sessionStorage.removeItem(tokenKey); sessionStorage.removeItem(runKey); setToken(undefined); setRunId(undefined); queryClient.clear(); }
  if (!ready) return <main className="grid min-h-screen place-items-center text-muted-foreground" aria-live="polite">Loading Learning Coach...</main>;
  if (!token) return <PublicLanding onAuthenticated={setToken} />;
  if (userQuery.isError) return <PublicLanding error="Your session has expired. Please sign in again." onAuthenticated={setToken} />;
  if (!userQuery.data) return <main className="grid min-h-screen place-items-center text-muted-foreground" aria-live="polite">Restoring your session...</main>;

  const tabs = ["research", "course", "explorer"] as const;
  return <AppShell user={userQuery.data} onSignOut={signOut}>
    <div className="mb-4 lg:hidden"><Button variant="secondary" className="gap-2" onClick={() => setHistoryOpen(!historyOpen)} aria-expanded={historyOpen} aria-controls="research-history"><Menu size={17} aria-hidden="true" />History</Button></div>
    <div className="grid items-start gap-6 lg:grid-cols-[250px_minmax(0,1fr)] lg:gap-8">
      {historyOpen && <div aria-hidden="true" className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setHistoryOpen(false)} />}
      <aside id="research-history" aria-label="Research history" role={historyOpen ? "dialog" : undefined} aria-modal={historyOpen || undefined} onKeyDown={(event) => {
        if (!historyOpen) return;
        if (event.key === "Escape") { event.preventDefault(); setHistoryOpen(false); }
        if (event.key === "Tab") {
          const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")).filter((button) => button.getClientRects().length > 0);
          if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1)?.focus(); }
          else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0]?.focus(); }
        }
      }} className={`${historyOpen ? "block" : "hidden"} fixed inset-y-0 left-0 z-50 w-[min(85vw,300px)] overflow-y-auto border-r bg-card p-4 shadow-xl lg:sticky lg:top-6 lg:z-auto lg:block lg:w-auto lg:rounded-xl lg:border lg:p-3 lg:shadow-none`}>
        <div className="mb-4 flex items-center justify-between lg:hidden"><span className="font-bold">History</span><Button variant="ghost" className="w-11 px-0" onClick={() => setHistoryOpen(false)} aria-label="Close history"><X size={18} /></Button></div>
        <Button className="w-full gap-2" onClick={() => { setRunId(undefined); setTab("research"); setHistoryOpen(false); generation.reset(); }}><Plus size={17} aria-hidden="true" />New research</Button>
        <div className="flex items-center gap-2 px-2 pb-2 pt-6 text-sm font-semibold text-muted-foreground"><Clock3 size={16} aria-hidden="true" />History</div>
        {history.isLoading ? <p className="px-2 text-sm text-muted-foreground">Loading history...</p> : history.isError ? <p role="alert" className="px-2 text-sm">Could not load history. <button className="underline" onClick={() => history.refetch()}>Try again</button></p> : history.data?.length ? <ul className="max-h-[55vh] space-y-1 overflow-y-auto">{history.data.map((item) => <li key={item.id}><button type="button" onClick={() => { setRunId(item.id); setTab("research"); setHistoryOpen(false); }} aria-current={runId === item.id ? "true" : undefined} className={`w-full rounded-lg px-3 py-3 text-left transition-colors ${runId === item.id ? "bg-primary/10 text-primary" : "hover:bg-muted"}`}><span className="block truncate text-sm font-semibold">{item.topic}</span><span className="mt-1 block text-xs text-muted-foreground">{item.status} · {new Date(item.created_at).toLocaleDateString()}</span></button></li>)}</ul> : <p className="px-2 text-sm leading-6 text-muted-foreground">Your research sessions will appear here.</p>}
      </aside>
      <div className="min-w-0">
        {generation.error && <p role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{generation.error instanceof Error ? generation.error.message : "We could not research that topic. Please try again."}</p>}
        {!runId && <IntakeForm onSubmit={generation.mutate} pending={generation.isPending} />}
        {runId && run.isLoading && <p role="status" className="text-muted-foreground">Loading your research...</p>}
        {runId && run.isError && <p role="alert">Could not update this session. <button className="underline" onClick={() => run.refetch()}>Try again</button></p>}
        {run.data && <div className="grid gap-6">
          <header><p className="text-sm font-medium text-muted-foreground">Research session · {run.data.status}</p><h1 className="mt-2 break-words text-3xl font-bold tracking-tight">{run.data.topic}</h1></header>
          <div role="tablist" aria-label="Research session views" className="flex gap-1 border-b" onKeyDown={(event) => { const index = tabs.indexOf(tab); const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : -1; if (next >= 0) { event.preventDefault(); setTab(tabs[next]); document.getElementById(`session-tab-${tabs[next]}`)?.focus(); } }}>
            {tabs.map((name) => <button key={name} id={`session-tab-${name}`} role="tab" type="button" aria-selected={tab === name} aria-controls={`session-panel-${name}`} tabIndex={tab === name ? 0 : -1} onClick={() => setTab(name)} className={`min-h-11 border-b-2 px-4 text-sm font-semibold capitalize transition-colors ${tab === name ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{name}</button>)}
          </div>
          {run.data.status === "failed" && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{run.data.error ?? "Research failed. Please try again."}</p>}
          <div id="session-panel-research" role="tabpanel" aria-labelledby="session-tab-research" hidden={tab !== "research"}><ResearchResults run={run.data} /></div>
          <div id="session-panel-course" role="tabpanel" aria-labelledby="session-tab-course" hidden={tab !== "course"}>{run.data.status === "completed" ? <CoursePanel key={run.data.id} researchRunId={run.data.id} token={token} /> : <p className="text-muted-foreground">Your course can be built once research is complete.</p>}</div>
          <div id="session-panel-explorer" role="tabpanel" aria-labelledby="session-tab-explorer" hidden={tab !== "explorer"}><div className="grid gap-6"><Link href={`/observability?run=${encodeURIComponent(run.data.id)}`} className="w-fit text-sm font-semibold text-primary underline-offset-4 hover:underline">Open detailed run explorer →</Link><ResearchActivity runId={run.data.id} token={token} running={run.data.status === "running"} active={tab === "explorer"} /></div></div>
        </div>}
      </div>
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
