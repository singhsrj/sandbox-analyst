/**
 * Stand-in for react-resizable-panels in tests. jsdom gives every element a zero-size box, so the
 * real library treats every click as a drag on a divider and keeps focus from reaching inputs.
 * The layout itself is checked in a real browser (e2e/smoke.mjs).
 */
import type { ReactNode } from "react";

type Props = { children?: ReactNode; className?: string; id?: string };

export function Group({ children, className, id }: Props) {
  return (
    <div data-testid={id ? `panel-group-${id}` : undefined} className={className}>
      {children}
    </div>
  );
}

export function Panel({ children, id }: Props) {
  return <div data-testid={id ? `panel-${id}` : undefined}>{children}</div>;
}

export function Separator() {
  return <div role="separator" aria-orientation="vertical" />;
}
