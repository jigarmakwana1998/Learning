"use client";

import { LogOut, Moon, Sparkles, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { User } from "@/lib/api";

export function AppShell({ user, onSignOut, children }: { user: User; onSignOut: () => void; children: React.ReactNode }) {
  const toggleTheme = () => document.documentElement.classList.toggle("dark");
  return <div className="min-h-screen">
    <header className="border-b bg-card/90 backdrop-blur"><nav className="mx-auto flex min-h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6" aria-label="Main navigation">
      <a href="#intake" className="flex items-center gap-2 font-bold"><span className="rounded-lg bg-primary p-1.5 text-primary-foreground"><Sparkles size={18} aria-hidden="true" /></span>Learning Coach</a>
      <div className="flex items-center gap-1 sm:gap-2"><span className="hidden text-sm text-muted-foreground sm:inline">{user.email}</span><Button variant="ghost" className="w-11 px-0" onClick={toggleTheme} aria-label="Toggle color theme"><Sun className="dark:hidden" size={18} /><Moon className="hidden dark:block" size={18} /></Button><Button variant="ghost" className="gap-2" onClick={onSignOut}><LogOut size={16} aria-hidden="true" /><span className="hidden sm:inline">Sign out</span></Button></div>
    </nav></header>
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">{children}</main>
  </div>;
}
