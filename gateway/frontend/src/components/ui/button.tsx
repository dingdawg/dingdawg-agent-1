"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl",
    "text-sm font-medium transition-all duration-200 cursor-pointer",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]",
    "disabled:pointer-events-none disabled:opacity-50",
    "hover:brightness-110 active:brightness-95",
  ],
  {
    variants: {
      variant: {
        default:
          "bg-[var(--gold-500)] text-[var(--ink-950)] shadow hover:bg-[var(--gold-600)] hover:shadow-[0_0_20px_rgba(246,180,0,0.25)]",
        outline:
          "border border-[var(--stroke2)] bg-transparent text-[var(--foreground)] hover:bg-white/5 hover:border-white/20",
        ghost:
          "text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5",
        gold:
          "w-full bg-[var(--gold-500)] text-[#07111c] font-semibold shadow-lg hover:bg-[var(--gold-600)] hover:shadow-[0_0_24px_rgba(246,180,0,0.30)]",
        destructive:
          "bg-red-600 text-white shadow-sm hover:bg-red-700",
      },
      size: {
        sm: "h-8 rounded-lg px-3 text-xs",
        default: "h-10 px-6 py-2",
        lg: "h-12 rounded-xl px-8 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  isLoading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, isLoading, disabled, children, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          children
        )}
      </button>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
