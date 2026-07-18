import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLElement>) { return <section className={cn("rounded-xl border bg-card p-5 shadow-sm", className)} {...props} />; }
