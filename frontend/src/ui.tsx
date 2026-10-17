// shadcn/ui Button pattern, using Radix Slot and class-variance-authority.
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
const button = cva("button", {
  variants: {
    variant: {
      default: "primary",
      outline: "outline",
      destructive: "danger",
      ghost: "ghost",
    },
  },
  defaultVariants: { variant: "default" },
});
export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
}
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, asChild = false, type = "button", ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(button({ variant }), className)}
        type={type}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function Badge({ status }: { status: string }) {
  return <span className={"badge " + status}>{status.replace(/_/g, " ")}</span>;
}
export function Empty({ text }: { text: string }) {
  return <div className="empty">{text}</div>;
}
export function Pager({
  page,
  total,
  setPage,
}: {
  page: number;
  total: number;
  setPage: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>{total} results</span>
      <Button
        variant="outline"
        disabled={page === 0}
        onClick={() => setPage(page - 1)}
      >
        Previous
      </Button>
      <span>Page {page + 1}</span>
      <Button
        variant="outline"
        disabled={(page + 1) * 25 >= total}
        onClick={() => setPage(page + 1)}
      >
        Next
      </Button>
    </div>
  );
}
