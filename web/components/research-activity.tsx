"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Card } from "@/components/ui/card";
import { getResearchActivity } from "@/lib/api";

export function ResearchActivity({ runId, token, running, active }: { runId: string; token: string; running: boolean; active: boolean }) {
  const activity = useQuery({ queryKey: ["research-activity", runId, token], queryFn: () => getResearchActivity(runId, token), enabled: active, refetchInterval: active && running ? 5000 : false });
  const { refetch } = activity;
  useEffect(() => { if (active && !running) refetch(); }, [active, running, refetch]);
  return <section aria-label="Research activity" className="grid gap-4">
    <h2 className="text-2xl font-bold">Research activity</h2>
    {activity.isLoading && <p>Loading activity...</p>}
    {activity.isError && <p role="alert">Could not load activity. <button className="underline" onClick={() => activity.refetch()}>Try again</button></p>}
    {activity.data?.sessions.map((session) => <Card key={session.id} className="grid gap-3">
      <h3 className="font-semibold">{session.agent_name} · {session.status}</h3>
      {session.activity.length === 0 && <p className="text-muted-foreground">No browser activity saved yet.</p>}
      {session.activity.map((item, index) => <details key={index} className="border-t pt-3">
        <summary className="cursor-pointer font-medium">{item.tool === "browser_search" ? `Search: ${String(item.input.query ?? "Query unavailable")}` : "Pages read"}</summary>
        {((item.output.results ?? item.output.pages ?? []) as Array<Record<string, unknown>>).map((page, i) => <div key={i} className="mt-3 grid gap-1 text-sm">
          {typeof page.url === "string" && page.url.startsWith("https://") ? <a className="text-primary underline" href={page.url} target="_blank" rel="noopener noreferrer">{String(page.title || page.url)}</a> : <span>{String(page.title || page.requested_url || "Page unavailable")}</span>}
          {typeof page.content === "string" && <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 font-sans">{page.content}</pre>}
        </div>)}
      </details>)}
      {session.output != null && <details><summary className="cursor-pointer font-medium">Agent output</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-sm">{JSON.stringify(session.output, null, 2)}</pre></details>}
    </Card>)}
  </section>;
}
