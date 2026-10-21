import { ExternalLink } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { LearningRun, ResearchCoverage, Source } from "@/lib/api";

const statusStyle: Record<ResearchCoverage["status"], string> = {
  covered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200",
  partial: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  missing: "bg-muted text-muted-foreground",
};

/** The coverage checklist for a topic, each item with the pages that cover it. */
export function ResearchResults({ run }: { run: LearningRun }) {
  const { research } = run;
  const sourceByUrl = new Map(research.sources.map((source) => [source.url, source]));
  return <section className="grid gap-4" aria-label="Research results">
    <div><h2 className="text-2xl font-bold">{research.topic}</h2><p className="mt-1 text-muted-foreground">What to learn, and the pages that teach each part.</p></div>
    {(research.coverage ?? []).map((item) => {
      const sources = item.supported_by.map((url) => sourceByUrl.get(url)).filter((source): source is Source => Boolean(source));
      return <Card key={item.requirement_id} className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="font-semibold">{item.question}</h3><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyle[item.status]}`}>{item.status}</span></div>
        {sources.length ? <ul className="grid gap-3">{sources.map((source) => <li key={source.url} className="grid gap-1">
          <a href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-primary underline-offset-4 hover:underline">{source.title}<ExternalLink size={14} aria-hidden="true" /></a>
          {source.key_points?.length ? <ul className="list-disc pl-5 text-sm text-muted-foreground">{source.key_points.map((point) => <li key={point}>{point}</li>)}</ul> : null}
        </li>)}</ul> : <p className="text-sm text-muted-foreground">No page found for this yet.</p>}
      </Card>;
    })}
  </section>;
}
