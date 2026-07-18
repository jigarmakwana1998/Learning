"use client";

import { FormEvent, useState } from "react";
import { KeyRound } from "lucide-react";
import { login, register } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/field";

export function AuthPanel({ onAuthenticated }: { onAuthenticated: (token: string) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(undefined);
    setPending(true);
    try {
      const result = await (mode === "login" ? login(email, password) : register(email, password));
      sessionStorage.setItem("learning-coach-token", result.access_token);
      onAuthenticated(result.access_token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Authentication failed. Please try again.");
    } finally { setPending(false); }
  }

  return <Card className="mx-auto w-full max-w-md">
    <div className="mb-5 flex items-center gap-3"><span className="rounded-xl bg-accent p-2 text-primary"><KeyRound aria-hidden="true" /></span><div><h2 className="text-xl font-bold">Start your learning path</h2><p className="text-sm text-muted-foreground">Save your outline and pick up where you left off.</p></div></div>
    <form className="grid gap-4" onSubmit={submit}>
      <div className="grid gap-1.5"><Label htmlFor="email">Email</Label><Input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></div>
      <div className="grid gap-1.5"><Label htmlFor="password">Password</Label><Input id="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required /></div>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{error}</p>}
      <Button type="submit" disabled={pending}>{pending ? "Checking your account…" : mode === "login" ? "Sign in" : "Create account"}</Button>
    </form>
    <button type="button" className="mt-4 w-full text-sm font-semibold text-primary underline-offset-4 hover:underline" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(undefined); }}>
      {mode === "login" ? "Need an account? Create one" : "Already have an account? Sign in"}
    </button>
  </Card>;
}
