import { forwardRef } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "secondary" | "ghost" };
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "default", type = "button", ...props }, ref) => (
  <button ref={ref} type={type} className={cn("inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-50", variant === "default" && "bg-primary text-primary-foreground hover:opacity-90", variant === "secondary" && "bg-muted text-foreground hover:bg-slate-200 dark:hover:bg-slate-700", variant === "ghost" && "hover:bg-muted", className)} {...props} />
));
Button.displayName = "Button";
