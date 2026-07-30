import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/utils";

// Standard shadcn-style Button. NOTE: we use @radix-ui/react-slot for asChild
// (delegating render). Listed in package.json transitively via lucide-react
// but we may need to add it explicitly when the import resolves; for now
// the import name is here so refactors find it.

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-accent text-accent-fg hover:bg-accent-hover",
        secondary:
          "bg-surface-2 text-fg hover:bg-surface-3 border border-border",
        ghost: "text-fg hover:bg-surface-2",
        outline:
          "border border-border-strong bg-transparent text-fg hover:bg-surface-2",
        danger:
          "bg-danger text-white hover:bg-danger/90",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-10 px-6 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size }), className)}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

// The component and its variant helper ship together on purpose — that is
// the shadcn/ui layout, and splitting them means every consumer imports
// from two files. The cost is coarser hot-reload for this one file.
// eslint-disable-next-line react-refresh/only-export-components
export { buttonVariants };
