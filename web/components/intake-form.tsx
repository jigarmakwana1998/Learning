"use client";

import { FormEvent, useState } from "react";
import { LoaderCircle, WandSparkles } from "lucide-react";
import type { TopicIntent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/field";

export function IntakeForm({ onSubmit, pending }: { onSubmit: (intent: TopicIntent) => void; pending: boolean }) {
  const [intent, setIntent] = useState<TopicIntent>({ topic: "", level: "beginner", hoursPerWeek: 5, weeks: 4 });
  const update = <K extends keyof TopicIntent>(key: K, value: TopicIntent[K]) => setIntent((current) => ({ ...current, [key]: value }));
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (intent.topic.trim().length >= 2) onSubmit({ ...intent, topic: intent.topic.trim() }); }

  return <Card id="intake" className="scroll-mt-6">
    <div className="mb-6"><p className="text-sm font-semibold uppercase tracking-wider text-primary">Create a course</p><h1 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">What would you like to learn?</h1><p className="mt-2 max-w-2xl text-muted-foreground">We will research public sources, filter the strongest evidence, and write a complete cited course with quizzes and an assignment.</p></div>
    <form className="grid gap-5" onSubmit={submit}>
      <div className="grid gap-1.5"><Label htmlFor="topic">Topic or goal</Label><Input id="topic" value={intent.topic} onChange={(event) => update("topic", event.target.value)} minLength={2} maxLength={160} placeholder="e.g. Data analysis with Python" required aria-describedby="topic-help" /><p id="topic-help" className="text-sm text-muted-foreground">Be specific about the skill or subject you want to master.</p></div>
      <div className="grid gap-5 sm:grid-cols-3">
        <div className="grid gap-1.5"><Label htmlFor="level">Current level</Label><Select id="level" value={intent.level} onChange={(event) => update("level", event.target.value as TopicIntent["level"])}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></Select></div>
        <div className="grid gap-1.5"><Label htmlFor="hours">Hours each week</Label><Input id="hours" type="number" min={1} max={40} value={intent.hoursPerWeek} onChange={(event) => update("hoursPerWeek", Number(event.target.value))} required /></div>
        <div className="grid gap-1.5"><Label htmlFor="weeks">Course duration in weeks</Label><Input id="weeks" type="number" min={1} max={24} value={intent.weeks} onChange={(event) => update("weeks", Number(event.target.value))} required /></div>
      </div>
      <div><Button type="submit" disabled={pending} className="w-full gap-2 sm:w-auto">{pending ? <><LoaderCircle className="animate-spin" size={18} aria-hidden="true" /> Researching and writing...</> : <><WandSparkles size={18} aria-hidden="true" /> Research and create course</>}</Button>{pending && <p className="mt-3 text-sm text-muted-foreground" role="status">The agent is searching, reading, filtering, and writing your lessons. This can take a few minutes; please keep this tab open.</p>}</div>
    </form>
  </Card>;
}
