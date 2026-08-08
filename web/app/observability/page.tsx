"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, Bot, BrainCircuit, ChevronDown, CircleDollarSign, Clock3, Database, Wrench } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { getMe, getTraceRun, getTraceRuns, type TraceEvent } from "@/lib/api";

const tokenKey = "learning-coach-token";

export default function ObservabilityPage() {
  const [token, setToken] = useState<string>();
  const [selectedRunId, setSelectedRunId] = useState<string>();
  const [openEvent, setOpenEvent] = useState<string>();
  useEffect(() => setToken(sessionStorage.getItem(tokenKey) ?? undefined), []);
  const me = useQuery({ queryKey: ["me", token], queryFn: () => getMe(token!), enabled: Boolean(token), retry: false });
  const runs = useQuery({ queryKey: ["trace-runs", token], queryFn: () => getTraceRuns(token!), enabled: Boolean(token) });
  useEffect(() => { if (!selectedRunId && runs.data?.[0]) setSelectedRunId(runs.data[0].id); }, [runs.data, selectedRunId]);
  const trace = useQuery({ queryKey: ["trace-run", selectedRunId, token], queryFn: () => getTraceRun(selectedRunId!, token!), enabled: Boolean(token && selectedRunId) });

  if (!token) return <SignInRequired />;
  if (me.isLoading) return <main className="grid min-h-screen place-items-center text-muted-foreground">Restoring your workspace…</main>;
  if (!me.data) return <SignInRequired />;
  const signOut = () => { sessionStorage.removeItem(tokenKey); setToken(undefined); };
  return <AppShell user={me.data} onSignOut={signOut}><div className="space-y-7">
    <header className="max-w-3xl"><h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Agent run explorer</h1><p className="mt-3 max-w-2xl text-base leading-7 text-muted-foreground">Follow every agent hand-off, model request, tool invocation, output, token count, latency, and proxy-reported cost in chronological order.</p></header>
    {runs.isLoading && <p className="text-muted-foreground">Loading recorded runs…</p>}
    {runs.data?.length === 0 && <EmptyState />}
    {runs.data && runs.data.length > 0 && <div className="grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="h-fit rounded-xl border bg-card p-2 xl:sticky xl:top-6"><p className="px-3 pb-2 pt-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">Recorded runs</p>{runs.data.map(run => <button key={run.id} onClick={() => { setSelectedRunId(run.id); setOpenEvent(undefined); }} className={`mb-1 w-full rounded-lg p-3 text-left transition ${selectedRunId === run.id ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}><span className="block truncate font-semibold">{run.topic}</span><span className={`mt-1 block text-xs ${selectedRunId === run.id ? "text-primary-foreground/80" : "text-muted-foreground"}`}>{run.harness} · {run.event_count} events</span></button>)}</aside>
      <section>{trace.isLoading && <p className="text-muted-foreground">Loading run trace…</p>}{trace.data && <TraceView trace={trace.data} openEvent={openEvent} onToggle={setOpenEvent} />}</section>
    </div>}
  </div></AppShell>;
}

function TraceView({ trace, openEvent, onToggle }: { trace: Awaited<ReturnType<typeof getTraceRun>>; openEvent?: string; onToggle: (id?: string) => void }) {
  const modelEvents = trace.events.filter(event => event.prompt_tokens != null || event.completion_tokens != null);
  const tokens = modelEvents.reduce((sum, event) => sum + (event.prompt_tokens ?? 0) + (event.completion_tokens ?? 0), 0);
  return <div className="space-y-6"><section className="rounded-xl border bg-card p-5 sm:p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-xl font-bold">{trace.topic}</h2><p className="mt-1 text-sm text-muted-foreground">{trace.harness} harness · LiteLLM gateway · {trace.status} · started {new Date(trace.started_at).toLocaleString()}</p></div><span className={`rounded-full px-3 py-1 text-sm font-bold ${trace.status === "completed" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300" : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"}`}>{trace.status}</span></div><div className="mt-6 grid gap-3 sm:grid-cols-3"><Metric icon={<Activity size={18} />} value={String(trace.events.length)} label="recorded events" /><Metric icon={<Database size={18} />} value={tokens.toLocaleString()} label="tokens" /><Metric icon={<CircleDollarSign size={18} />} value={`$${trace.total_cost_usd.toFixed(5)}`} label="proxy-reported cost" /></div></section>
    <Topology trace={trace} />
    <section className="rounded-xl border bg-card p-5 sm:p-6"><div className="flex items-center justify-between"><div><h2 className="text-xl font-bold">Event timeline</h2><p className="mt-1 text-sm text-muted-foreground">Open any entry to inspect the exact structured boundary data.</p></div><Clock3 className="text-muted-foreground" size={20} /></div><ol className="mt-6 space-y-1">{trace.events.map(event => <EventRow key={event.id} event={event} agent={trace.sessions.find(session => session.id === event.session_id)?.agent_name ?? "Agent"} open={openEvent === event.id} onToggle={() => onToggle(openEvent === event.id ? undefined : event.id)} />)}</ol></section>
  </div>;
}

function Topology({ trace }: { trace: Awaited<ReturnType<typeof getTraceRun>> }) {
  const models = Array.from(new Set(trace.events
    .filter(event => event.event_type === "model")
    .map(event => event.metadata?.model_group ?? event.metadata?.model)
    .filter((model): model is string => typeof model === "string")));
  return <section className="overflow-hidden rounded-xl border bg-card">
    <div className="border-b px-5 py-4 sm:px-6"><h2 className="text-xl font-bold">Run topology</h2><p className="mt-1 text-sm text-muted-foreground">Harness orchestration and the model gateway remain separate, joined layers.</p></div>
    <div className="space-y-7 overflow-x-auto p-5 sm:p-6">
      <div className="flex min-w-[620px] items-stretch gap-3">
        <TopologyNode icon={<Activity size={18} />} title="Learning Coach" detail="orchestrator" />
        <TopologyLink label="starts" />
        <TopologyNode icon={<Bot size={18} />} title={trace.harness} detail="agent harness" />
        <TopologyLink label="calls" />
        <TopologyNode icon={<BrainCircuit size={18} />} title="LiteLLM" detail={models.length ? models.join(", ") : "agent-model alias"} />
      </div>
      <div className="flex min-w-[620px] items-center justify-between gap-3">{trace.sessions.map((session, index) => <div className="contents" key={session.id}><div className="w-48 rounded-xl bg-muted p-4"><div className="flex items-center gap-2 font-bold"><Bot size={18} className="text-primary" />{session.agent_name}</div><p className="mt-2 text-sm text-muted-foreground">{trace.events.filter(event => event.session_id === session.id && event.event_type === "model").length} model calls · {trace.events.filter(event => event.session_id === session.id && event.event_type === "tool").length} tools</p></div>{index < trace.sessions.length - 1 && <div className="h-px flex-1 bg-border"><span className="relative -top-2 left-1/2 text-xs text-muted-foreground">handoff</span></div>}</div>)}</div>
    </div>
  </section>;
}

function TopologyNode({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) { return <div className="min-w-44 flex-1 rounded-xl border bg-background p-4"><div className="flex items-center gap-2 font-bold text-primary">{icon}<span className="text-foreground">{title}</span></div><p className="mt-2 truncate text-sm text-muted-foreground">{detail}</p></div>; }
function TopologyLink({ label }: { label: string }) { return <div className="flex w-16 shrink-0 items-center"><div className="h-px flex-1 bg-border" /><span className="px-2 text-xs text-muted-foreground">{label}</span><div className="h-px flex-1 bg-border" /></div>; }

function EventRow({ event, agent, open, onToggle }: { event: TraceEvent; agent: string; open: boolean; onToggle: () => void }) { const Icon = event.event_type === "tool" ? Wrench : event.event_type === "model" ? BrainCircuit : event.event_type === "harness" ? Bot : Activity; return <li className="border-b last:border-0"><button onClick={onToggle} className="flex w-full items-center gap-3 py-4 text-left"><span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${event.status === "failed" ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300" : event.event_type === "tool" ? "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" : "bg-accent text-primary"}`}><Icon size={17} /></span><span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-x-2"><span className="font-semibold">{event.name}</span><span className="text-sm text-muted-foreground">{agent}</span></span><span className="mt-1 block text-xs text-muted-foreground">{new Date(event.created_at).toLocaleTimeString()} · {event.duration_ms ?? 0}ms{event.prompt_tokens != null ? ` · ${event.prompt_tokens + (event.completion_tokens ?? 0)} tokens` : ""}</span></span><ChevronDown size={18} className={`text-muted-foreground transition ${open ? "rotate-180" : ""}`} /></button>{open && <div className="pb-5 pl-12"><div className="grid gap-3 lg:grid-cols-2">{event.input_payload && <Payload title="Input" value={event.input_payload} />}{event.output_payload && <Payload title="Output" value={event.output_payload} />}{event.metadata && <Payload title="Metadata" value={event.metadata} />}{event.error_message && <Payload title="Error" value={{ message: event.error_message }} />}</div></div>}</li>; }
function Payload({ title, value }: { title: string; value: unknown }) { return <div><p className="mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">{title}</p><pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs leading-5 text-foreground">{JSON.stringify(value, null, 2)}</pre></div>; }
function Metric({ icon, value, label }: { icon: React.ReactNode; value: string; label: string }) { return <div className="rounded-xl bg-muted p-4"><div className="flex items-center gap-2 text-primary">{icon}<span className="text-2xl font-bold text-foreground">{value}</span></div><p className="mt-1 text-sm text-muted-foreground">{label}</p></div>; }
function EmptyState() { return <section className="rounded-xl border border-dashed bg-card p-10 text-center"><Activity className="mx-auto text-primary" size={28} /><h2 className="mt-4 text-xl font-bold">No run traces yet</h2><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">Create a learning run and return here to inspect its model boundaries and tool activity.</p><Link href="/" className="mt-5 inline-flex min-h-11 items-center rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">Create a learning run</Link></section>; }
function SignInRequired() { return <main className="grid min-h-screen place-items-center px-6 text-center"><div><h1 className="text-2xl font-bold">Sign in to inspect agent runs</h1><p className="mt-2 text-muted-foreground">Run traces follow the same access boundary as learning runs.</p><Link href="/" className="mt-5 inline-flex min-h-11 items-center rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">Go to Learning Coach</Link></div></main>; }
