import { cn } from "@/lib/utils";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) { return <label className={cn("text-sm font-semibold", className)} {...props} />; }
export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) { return <input className={cn("min-h-11 w-full rounded-xl border bg-transparent px-3 text-base placeholder:text-muted-foreground", className)} {...props} />; }
export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) { return <select className={cn("min-h-11 w-full rounded-xl border bg-transparent px-3 text-base", className)} {...props} />; }
