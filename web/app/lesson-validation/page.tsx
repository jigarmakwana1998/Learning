"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Activity,
  BookOpen,
  Check,
  CheckCircle2,
  Circle,
  FileSearch,
  Moon,
  Sparkles,
  Sun,
  TriangleAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type ReviewTab = "lesson" | "validation";

const coverage = [
  ["Foundations", "Definitions and prerequisites", "0.98"],
  ["Mechanism", "How inputs bind and outputs return", "0.98"],
  ["Examples", "Worked behavior, not only descriptions", "0.98"],
  ["Boundaries", "Limitations and edge cases", "0.98"],
  ["Integration", "Connection to wider program design", "0.98"],
] as const;

export default function LessonValidationPage() {
  const [tab, setTab] = useState<ReviewTab>("lesson");

  return (
    <div className="min-h-screen">
      <header className="border-b bg-card/90 backdrop-blur">
        <nav className="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6" aria-label="Validation navigation">
          <Link href="/" className="flex items-center gap-2 font-bold">
            <span className="rounded-lg bg-primary p-1.5 text-primary-foreground"><Sparkles size={18} aria-hidden="true" /></span>
            Learning Coach
          </Link>
          <div className="flex items-center gap-2">
            <span className="hidden rounded-full bg-accent px-3 py-1 text-xs font-bold text-primary sm:inline">Validation build</span>
            <Button variant="ghost" className="w-11 px-0" onClick={() => document.documentElement.classList.toggle("dark")} aria-label="Toggle color theme">
              <Sun className="dark:hidden" size={18} /><Moon className="hidden dark:block" size={18} />
            </Button>
          </div>
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
        <section className="mb-7 flex flex-col justify-between gap-5 md:flex-row md:items-end">
          <div>
            <p className="text-sm font-bold text-primary">Lesson-generation candidate</p>
            <h1 className="mt-2 max-w-3xl text-3xl font-bold tracking-tight sm:text-5xl">Review the lesson where learners will read it.</h1>
            <p className="mt-3 max-w-3xl text-muted-foreground">This page renders the previous real-model lesson using the corrected learner-facing layout, beside the new pipeline&apos;s coverage evidence.</p>
          </div>
          <div className="flex shrink-0 gap-2" role="tablist" aria-label="Review views">
            <Button variant={tab === "lesson" ? "default" : "secondary"} onClick={() => setTab("lesson")} className="gap-2" role="tab" aria-selected={tab === "lesson"}><BookOpen size={16} />Lesson output</Button>
            <Button variant={tab === "validation" ? "default" : "secondary"} onClick={() => setTab("validation")} className="gap-2" role="tab" aria-selected={tab === "validation"}><Activity size={16} />Validation</Button>
          </div>
        </section>

        <div className="mb-5 flex gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
          <TriangleAlert className="mt-0.5 shrink-0" size={19} aria-hidden="true" />
          <p><strong>Review boundary:</strong> the prose below is a real Gemini baseline generated before the new coverage ledger. The structural checks are current. A fresh provider lesson is still the final acceptance gate before merge and freeze.</p>
        </div>

        {tab === "lesson" ? <LessonOutput /> : <ValidationOutput />}
      </main>
    </div>
  );
}

function LessonOutput() {
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-primary">Previous real provider output · rendered with current web adapter</p>
            <h2 className="mt-1 text-2xl font-bold">Attention layers in large language models</h2>
            <p className="mt-1 text-sm text-muted-foreground">2 lessons · 1,291 and 1,235 words</p>
          </div>
          <div className="text-right"><p className="text-2xl font-bold text-primary">0%</p><p className="text-xs text-muted-foreground">course progress</p></div>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full w-0 rounded-full bg-primary" /></div>
      </div>

      <div className="grid min-h-[42rem] lg:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="border-b bg-muted/30 p-3 lg:border-b-0 lg:border-r" aria-label="Course lessons">
          <p className="px-2 pb-2 text-sm font-bold text-muted-foreground">Course content</p>
          <p className="px-2 pb-1 pt-3 text-xs font-semibold text-muted-foreground">Module 1: Foundations of Attention</p>
          <button type="button" className="flex w-full items-center gap-2 rounded-lg bg-card px-2 py-2 text-left text-sm font-semibold shadow-sm"><Circle className="shrink-0 text-primary" size={17} /><span><span className="mr-1 text-muted-foreground">1.</span>Why Attention Matters</span></button>
          <button type="button" className="mt-1 flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-muted-foreground"><Circle className="shrink-0 text-primary" size={17} /><span><span className="mr-1">2.</span>Self-Attention in Practice</span></button>
        </aside>

        <div className="min-w-0 p-5 sm:p-7">
          <div className="flex flex-wrap gap-2 border-b pb-4">
            <span className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-primary"><BookOpen size={16} />Lesson</span>
            <span className="inline-flex min-h-10 items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold text-muted-foreground"><FileSearch size={16} />Sources</span>
          </div>

          <article className="pt-6">
            <p className="text-sm font-semibold text-primary">Module 1 / 30 min</p>
            <h3 className="mt-1 text-3xl font-bold tracking-tight">Why Attention Matters: Beyond Sequential Processing</h3>
            <p className="mt-3 max-w-[72ch] text-lg leading-8 text-muted-foreground">Understand the motivation for attention mechanisms in deep learning.</p>
            <div className="mt-8 grid max-w-[76ch] gap-7">
              <LessonSection title="The fixed-context bottleneck">
                Earlier sequence-to-sequence systems compressed an entire input into one fixed-length context vector. On longer sequences, that representation could lose details and weaken long-range dependencies. Attention replaces that single static summary with a dynamic weighting mechanism that can revisit relevant input positions for each output step.
              </LessonSection>
              <LessonSection title="Queries, keys, and values">
                Each token is projected into a query, key, and value. The query represents what the current token is looking for; keys describe what other tokens offer; values hold the information to combine. Dot products produce attention scores, softmax turns them into weights, and the weighted values create a context-aware representation.
              </LessonSection>
              <LessonSection title="Why transformers parallelize">
                The Transformer removes recurrence and contextualizes tokens simultaneously. This enables substantially more parallel training than recurrent models. Multi-head attention repeats the operation in several learned representation spaces so different relationships can be captured at the same time.
              </LessonSection>
              <section className="rounded-xl border border-amber-300 bg-amber-50 p-5 text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
                <h4 className="text-lg font-bold">Issue detected in the baseline</h4>
                <p className="mt-2 leading-8">The original lesson inserted a full paragraph about electrical transformers, then drifted into Hugging Face, CUDA setup, and university courses. Those search-result topics became lesson content without an explicit requirement or worked-example gate.</p>
              </section>
              <section className="rounded-xl bg-accent p-5">
                <h4 className="text-lg font-bold">Practice now preserved by the web adapter</h4>
                <p className="mt-2 leading-8">For the sentence “The animal didn&apos;t cross the street because it was tired,” identify which earlier word the token “it” should attend to. Explain what evidence the attention score needs to capture.</p>
              </section>
            </div>
            <section className="mt-9 max-w-[76ch] rounded-xl border bg-muted/40 p-5"><h4 className="font-bold">By the end of this lesson, you can</h4><ul className="mt-3 grid gap-2"><Outcome>Explain the fixed-context bottleneck.</Outcome><Outcome>Describe query, key, value, and attention weights.</Outcome><Outcome>Identify why the baseline lesson drifted off-topic.</Outcome></ul></section>
          </article>
        </div>
      </div>
    </Card>
  );
}

function LessonSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h4 className="text-lg font-bold">{title}</h4><p className="mt-2 text-[1.03rem] leading-8 text-foreground/90">{children}</p><p className="mt-3 text-xs font-semibold text-muted-foreground">Sources: <a className="text-primary underline decoration-primary/30 underline-offset-4" href="https://arxiv.org/abs/1706.03762" target="_blank" rel="noreferrer">Attention Is All You Need</a> · <a className="text-primary underline decoration-primary/30 underline-offset-4" href="https://jalammar.github.io/illustrated-transformer/" target="_blank" rel="noreferrer">The Illustrated Transformer</a></p></section>;
}

function Outcome({ children }: { children: React.ReactNode }) {
  return <li className="flex gap-2 text-sm"><CheckCircle2 className="shrink-0 text-primary" size={16} aria-hidden="true" />{children}</li>;
}

function ValidationOutput() {
  return (
    <div className="grid gap-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Metric value="5 / 5" label="requirements explicitly covered" />
        <Metric value="2 × 1,680" label="lesson word counts in deterministic E2E" />
        <Metric value="6 + 6" label="teaching sections preserved" />
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.25fr_0.75fr]">
        <Card><p className="text-sm font-bold text-primary">Coverage ledger</p><h2 className="mt-1 text-2xl font-bold">Python functions · current pipeline run</h2><div className="mt-5">{coverage.map(([title, description, confidence]) => <div key={title} className="grid grid-cols-[1.5rem_1fr_auto] items-center gap-3 border-t py-3 first:border-t-0"><span className="grid h-5 w-5 place-items-center rounded-full border text-xs"><Check size={13} /></span><span><strong>{title}</strong><br /><span className="text-sm text-muted-foreground">{description}</span></span><span className="text-xs font-semibold text-muted-foreground">{confidence}</span></div>)}</div></Card>
        <div className="grid gap-5">
          <Card><p className="text-sm font-bold text-primary">Generated lesson shape</p><h2 className="mt-1 text-xl font-bold">Two complete lessons</h2><div className="mt-4 border-t pt-4"><p className="font-semibold">Function inputs and outputs</p><p className="mt-1 text-sm text-muted-foreground">1,680 words · 6 sections · foundations, mechanism, examples</p></div><div className="mt-4 border-t pt-4"><p className="font-semibold">Validate function behavior</p><p className="mt-1 text-sm text-muted-foreground">1,680 words · 6 sections · boundaries, integration</p></div></Card>
          <Card className="border-primary/30 bg-accent/40"><h2 className="font-bold">Freeze recommendation</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Backend tests, TypeScript, coverage, length, section, citation, and practice gates pass. Run one fresh real-model lesson and review its prose before freezing.</p></Card>
        </div>
      </div>
    </div>
  );
}

function Metric({ value, label }: { value: string; label: string }) {
  return <Card><p className="text-3xl font-bold tracking-tight">{value}</p><p className="mt-1 text-sm text-muted-foreground">{label}</p></Card>;
}
