"use client";

import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { ThemeToggle } from "@/components/app/theme-toggle";
import { Button } from "@/components/ui/button";

const NAV = [
  ["#how", "How it works"],
  ["#features", "Features"],
  ["#reliability", "Reliability"],
  ["#next", "Coming next"],
] as const;

export function SiteHeader() {
  const { isLoaded, isSignedIn } = useAuth();
  return (
    <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-5">
        <Link href="/" className="marked shrink-0 text-base font-semibold tracking-tight">
          SandboxAnalyst
        </Link>
        <nav aria-label="Sections" className="hidden items-center gap-6 md:flex">
          {NAV.map(([href, label]) => (
            <a key={href} href={href} className="text-sm text-muted-foreground hover:text-foreground">
              {label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          {/* nothing until Clerk knows, so the button does not flicker between states */}
          {isLoaded ? (
            isSignedIn ? (
              <UserButton />
            ) : (
              <SignInButton mode="modal">
                <Button variant="ghost" size="sm">
                  Sign in
                </Button>
              </SignInButton>
            )
          ) : null}
          <Button asChild size="sm">
            <Link href="/app">Open the analyst</Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
