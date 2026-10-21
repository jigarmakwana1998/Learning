import { ExternalLink, LoaderCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { CoverageItem, ResearchRun } from "@/lib/api";

const statusStyle: Record<CoverageItem["status"], string> = {
  covered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  partial: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  missing: "bg-muted text-muted-foreground",
};

/** The coverage checklist for a topic, each item with the pages that cover it, filled in as the agent works. */
export function ResearchResults({ run }: { run: ResearchRun }) {
  const running = run.status === "running";
  return <section className="grid gap-4" aria-label="Research results" aria-busy={running}>
    <div>
      <h2 className="text-2xl font-bold">{run.topic}</h2>
      <p className="mt-1 text-muted-foreground">What to learn, and the pages that teach each part.</p>
      {running && <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground" role="status"><LoaderCircle className="shrink-0 animate-spin" size={16} aria-hidden="true" /><span className="truncate">{run.activity ?? "Planning what to cover..."}</span></p>}
    </div>
    {run.coverage.map((item) => {
      const pages = run.pages.filter((page) => page.covers.includes(item.id));
      return <Card key={item.id} className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="font-semibold">{item.question}</h3><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyle[item.status]}`}>{item.status}</span></div>
        {pages.length ? <ul className="grid gap-3">{pages.map((page) => <li key={page.url} className="grid gap-1">
          <a href={page.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline">{page.title}<ExternalLink size={14} aria-hidden="true" /></a>
          <p className="text-sm">{page.why}</p>
          <ul className="list-disc pl-5 text-sm text-muted-foreground">{page.key_points.map((point) => <li key={point}>{point}</li>)}</ul>
        </li>)}</ul> : <p className="text-sm text-muted-foreground">{running ? "Looking for pages..." : "No page found for this."}</p>}
      </Card>;
    })}
  </section>;
}
