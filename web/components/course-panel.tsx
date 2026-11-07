"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, LoaderCircle, NotebookPen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { buildCourse, getCourse, getCourseVersions, type Course, type Sentence } from "@/lib/api";

/** A link that opens the source page scrolled to the quoted text (a URL text fragment). */
function quoteLink(url: string, quote: string) {
  return `${url.split("#")[0]}#:~:text=${encodeURIComponent(quote).replace(/-/g, "%2D")}`;
}

/** Build course versions from a finished research run and read the selected one. */
export function CoursePanel({ researchRunId, token }: { researchRunId: string; token: string }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string>();
  const versions = useQuery({ queryKey: ["course-versions", researchRunId, token], queryFn: () => getCourseVersions(researchRunId, token), refetchInterval: (query) => (query.state.data?.some((v) => v.status === "running") ? 2000 : false) });
  const courseId = selected ?? versions.data?.[0]?.id;
  // Poll while the agent writes so sections appear as they arrive.
  const course = useQuery({ queryKey: ["course", courseId, token], queryFn: () => getCourse(courseId!, token), enabled: Boolean(courseId), refetchInterval: (query) => (query.state.data?.status === "running" || !query.state.data ? 2000 : false) });
  const build = useMutation({ mutationFn: () => buildCourse(researchRunId, token), onSuccess: ({ id }) => { setSelected(id); queryClient.invalidateQueries({ queryKey: ["course-versions", researchRunId] }); } });
  const building = build.isPending || versions.data?.some((v) => v.status === "running");

  return <section className="grid gap-4" aria-label="Course">
    <Card className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-2xl font-bold">Course</h2><p className="text-muted-foreground">Chapters written from these pages; every fact links to the text it comes from.</p></div>
        <Button onClick={() => build.mutate()} disabled={building} className="gap-2"><NotebookPen size={18} aria-hidden="true" />{versions.data?.length ? "Build new version" : "Build course"}</Button>
      </div>
      {build.error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{build.error instanceof Error ? build.error.message : "The course could not be started."}</p>}
      {Boolean(versions.data?.length) && <div className="flex flex-wrap gap-2" role="group" aria-label="Course versions">
        {versions.data!.map((v) => <Button key={v.id} variant={v.id === courseId ? "default" : "secondary"} onClick={() => setSelected(v.id)} aria-pressed={v.id === courseId}>
          v{v.version} · {v.status} · {new Date(v.created_at).toLocaleString()}
        </Button>)}
      </div>}
    </Card>
    {course.data && <CourseBody course={course.data} />}
  </section>;
}

function CourseBody({ course }: { course: Course }) {
  const running = course.status === "running";
  const sourceNumber = (passage: string) => Number(passage.slice(1).split(".")[0]);
  const source = (passage: string) => course.sources.find((item) => item.id === passage.split(".")[0]);
  return <div className="grid gap-4" aria-busy={running}>
    {running && <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status"><LoaderCircle className="shrink-0 animate-spin" size={16} aria-hidden="true" /><span className="truncate">{course.activity ?? "Reading the sources..."}</span></p>}
    {course.status === "failed" && <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{course.error ?? "The course could not be built."}</p>}
    {course.chapters.map((chapter, c) => <Card key={chapter.id} className="grid gap-4">
      <h3 className="text-xl font-bold">Chapter {c + 1}: {chapter.title}</h3>
      {chapter.sections.map((section) => {
        const paragraphs = course.sections[section.id];
        return <article key={section.id} className="grid gap-2">
          <h4 className="font-semibold">{section.title}</h4>
          {paragraphs ? paragraphs.map((paragraph, p) => <Paragraph key={p} sentences={paragraph} sourceNumber={sourceNumber} source={source} />)
            : <p className="text-sm text-muted-foreground">{running ? "Writing..." : "Not written."}</p>}
        </article>;
      })}
    </Card>)}
    {course.gaps.length > 0 && <Card><h3 className="font-semibold">Not covered by the sources</h3><ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">{course.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></Card>}
    {course.sources.length > 0 && <Card><h3 className="font-semibold">Sources</h3><ol className="mt-2 list-decimal pl-5 text-sm">{course.sources.map((item) => <li key={item.id}><a href={item.url} target="_blank" rel="noopener noreferrer" className="text-primary underline-offset-4 hover:underline">{item.title}</a></li>)}</ol></Card>}
  </div>;
}

function Paragraph({ sentences, sourceNumber, source }: { sentences: Sentence[]; sourceNumber: (passage: string) => number; source: (passage: string) => Course["sources"][number] | undefined }) {
  const warnings = sentences.filter((s) => s.warning);
  return <div>
    <p className="leading-7">{sentences.map((sentence, i) => {
      const text = <>{sentence.text}{sentence.cites.map((cite, k) => {
        const page = source(cite.passage);
        return page ? <sup key={k}><a href={quoteLink(page.url, cite.quote)} target="_blank" rel="noopener noreferrer" title={`"${cite.quote}" (${page.title})`} className="text-primary hover:underline">[{sourceNumber(cite.passage)}]</a></sup> : null;
      })}</>;
      return <span key={i}>{sentence.warning ? <mark className="rounded bg-amber-100 px-0.5 text-inherit dark:bg-amber-900/60" title={sentence.warning}>{text}</mark> : text} </span>;
    })}</p>
    {warnings.length > 0 && <ul className="mt-1 grid gap-0.5 text-xs text-amber-800 dark:text-amber-300">{warnings.map((s, i) => <li key={i} className="flex gap-1"><AlertTriangle className="mt-0.5 shrink-0" size={12} aria-hidden="true" /><span>{s.warning} <span className="text-muted-foreground">({s.text})</span></span></li>)}</ul>}
  </div>;
}
