import {
  BoxIcon,
  CalendarRangeIcon,
  DatabaseIcon,
  FileSearchIcon,
  HandIcon,
  HistoryIcon,
  MessageCircleQuestionIcon,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { SiteHeader } from "@/components/landing/site-header";
import { SuggestionBox } from "@/components/landing/suggestion-box";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "SandboxAnalyst: ask your data, check the answer",
};

const REPO = "https://github.com/singhsrj/sandbox-analyst";
const RECORDED_RUN = "/app?replay=march-2025-revenue-drop";

const STEPS = [
  ["Plan", "The agent writes a visible to-do list for your question."],
  ["Explore", "It reads the schema to find the right tables and columns."],
  ["Query", "Read-only SQL, checked before it runs. Only a summary reaches the model."],
  ["Analyse", "pandas and matplotlib run in an isolated sandbox."],
  ["Report", "Findings, charts, the SQL and the assumptions, ready to download."],
] as const;

const FEATURES = [
  {
    icon: FileSearchIcon,
    title: "Every number shows its working",
    body: "The report carries the exact SQL, the Python, the charts and the assumptions. Each step streams live while it runs.",
  },
  {
    icon: DatabaseIcon,
    title: "The database can't be changed",
    body: "Two independent defences: a validator that allows one SELECT on approved tables, and a database role that can only read. Either alone stops a write.",
  },
  {
    icon: BoxIcon,
    title: "Model-written code runs in a sandbox",
    body: "A throwaway VM with no network and no secrets. Only the query result goes in, never the database credentials.",
  },
  {
    icon: HandIcon,
    title: "Risky queries wait for you",
    body: "Large or unfiltered queries pause until you approve, edit or reject them. The pause survives a reload.",
  },
  {
    icon: MessageCircleQuestionIcon,
    title: "It asks instead of guessing",
    body: "When a question names a value that isn't in the data, it asks “did you mean…?” rather than inventing an answer.",
  },
  {
    icon: HistoryIcon,
    title: "Your history, on any device",
    body: "Sign in to keep your conversations, charts and reports. Each account sees only its own.",
  },
] as const;

const STATS = [
  ["80", "golden questions across 13 categories, from simple sums to write attempts"],
  ["22", "of those answers double-checked by a second, independently written query"],
  ["80 / 80", "questions reviewed by a person, with every answer scored by code, not by a model"],
  ["0 of 6", "prompt-injection runs compromised (a small sample; see the security notes)"],
] as const;

const CHECKS = [
  ["Answers come from the database", "Every expected answer is the result of a reference SQL query, never a model's opinion."],
  ["Scored by code", "Numbers within tolerance, the right item named first, refusals when the data can't answer, and no write ever attempted."],
  ["The explanation is checked too", "A judge compares the story with the real data and flags claims like “all regions dropped” when one rose."],
  ["Attacks are part of the test", "Write attempts, unanswerable questions and planted prompt injections are in the set on purpose."],
] as const;

export default function LandingPage() {
  return (
    <div className="min-h-full">
      <SiteHeader />
      <main>
        <Hero />
        <HowItWorks />
        <Features />
        <Reliability />
        <ComingNext />
        <Suggest />
      </main>
      <Footer />
    </div>
  );
}

function Section({
  id,
  title,
  lead,
  children,
}: {
  id: string;
  title: string;
  lead?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-14 border-t">
      <div className="mx-auto max-w-6xl px-5 py-16 md:py-24">
        <h2 id={`${id}-title`} className="text-2xl font-semibold tracking-tight text-balance md:text-3xl">
          {title}
        </h2>
        {lead ? <p className="mt-3 max-w-[58ch] leading-7 text-muted-foreground">{lead}</p> : null}
        <div className="mt-10">{children}</div>
      </div>
    </section>
  );
}

function Hero() {
  return (
    <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 py-16 md:py-24 lg:grid-cols-[1.1fr_1fr]">
      <div className="min-w-0">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">AI data analyst</p>
        <h1 className="mt-3 max-w-[18ch] text-4xl font-semibold tracking-tight text-balance md:text-5xl">
          Ask your data a question. Get a report you can check.
        </h1>
        <p className="mt-5 max-w-[52ch] leading-7 text-muted-foreground">
          SandboxAnalyst writes read-only SQL, runs its analysis in an isolated sandbox, and shows
          the query, the code and the assumptions behind every number.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild size="lg">
            <Link href="/app">Open the analyst</Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href={RECORDED_RUN}>Watch a recorded run</Link>
          </Button>
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          Recorded runs and the data are open to everyone. Live questions need an account and an
          access code.
        </p>
      </div>
      <TrailPreview />
    </section>
  );
}

/** A real run, abridged: the March 2025 revenue drop, with the numbers from the database. */
function TrailPreview() {
  const steps: { state: "done" | "running"; label: string; detail?: string }[] = [
    { state: "done", label: "Plan: find the drop, then the regions behind it" },
    { state: "done", label: "Read the schema: orders, regions" },
    {
      state: "done",
      label: "Query: revenue by region, Feb vs Mar 2025",
      detail: "SELECT region_name, sum(total_amount) … WHERE status = 'delivered'",
    },
    { state: "done", label: "Analyse in the sandbox: chart saved" },
    { state: "running", label: "Writing the report" },
  ];
  return (
    <figure className="min-w-0 rounded-sm border bg-card p-5" aria-label="Example of an analysis in progress">
      <p className="text-sm font-medium">Why did revenue drop in March 2025?</p>
      <ol className="trail mt-4">
        {steps.map((step) => (
          <li key={step.label} className="relative pb-3">
            <span className="trail-node" data-state={step.state} aria-hidden="true" />
            <span className="sr-only">{step.state === "done" ? "Done: " : "In progress: "}</span>
            <span className="text-sm">{step.label}</span>
            {step.detail ? (
              <code className="mt-1 block truncate rounded-sm bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                {step.detail}
              </code>
            ) : null}
          </li>
        ))}
      </ol>
      <figcaption className="mt-2 border-t pt-4 text-sm leading-6">
        <span className="marked font-medium">South fell 83%</span> ($154,498 → $26,790) from 3 March;
        North, East and West grew.
      </figcaption>
    </figure>
  );
}

function HowItWorks() {
  return (
    <Section
      id="how"
      title="What it is"
      lead="An analyst agent for a business database. You ask in plain English; it plans the work, runs it safely, and hands back a report whose every step you can inspect."
    >
      <ol className="grid border-t sm:grid-cols-2 lg:grid-cols-5">
        {STEPS.map(([name, body], i) => (
          <li key={name} className="border-b py-5 sm:pr-6 lg:border-b-0">
            <span className="font-mono text-xs text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
            <h3 className="mt-2 text-sm font-semibold">{name}</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{body}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

function Features() {
  return (
    <Section
      id="features"
      title="Built so you can trust the numbers"
      lead="Text-to-SQL chatbots are easy to build and hard to trust. These are the parts that make the difference."
    >
      <ul className="grid gap-px overflow-hidden rounded-sm border bg-border sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <li key={title} className="bg-card p-5">
            <Icon className="size-5" aria-hidden="true" />
            <h3 className="mt-3 text-sm font-semibold">{title}</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{body}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Reliability() {
  return (
    <Section
      id="reliability"
      title="Measured, not claimed"
      lead="Every change to the agent is tested against a fixed set of questions whose right answers come from the database itself. Here is what that suite holds, and what it found."
    >
      <dl className="grid gap-px overflow-hidden rounded-sm border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {STATS.map(([value, label], i) => (
          <div key={label} className="bg-card p-5">
            <dt className="sr-only">{label}</dt>
            <dd>
              <span className={`text-3xl font-semibold tracking-tight tabular-nums ${i === 2 ? "marked" : ""}`}>
                {value}
              </span>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{label}</p>
            </dd>
          </div>
        ))}
      </dl>

      <h3 className="mt-12 text-sm font-semibold">How the evaluation suite works</h3>
      <ol className="mt-4 grid gap-x-10 border-t sm:grid-cols-2">
        {CHECKS.map(([title, body], i) => (
          <li key={title} className="flex gap-4 border-b py-4">
            <span className="font-mono text-xs leading-6 text-muted-foreground">{i + 1}</span>
            <div>
              <p className="text-sm font-medium">{title}</p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">{body}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-6 max-w-[70ch] text-sm leading-6 text-muted-foreground">
        All 80 questions are written and reviewed; running the agent on the full set is next. The
        known limits, including one confidently
        wrong answer, are written down rather than hidden.{" "}
        <a href={`${REPO}/tree/main/evals`} className="text-foreground underline underline-offset-2">
          Read the evaluation suite
        </a>{" "}
        or the{" "}
        <a href={`${REPO}/blob/main/SECURITY.md`} className="text-foreground underline underline-offset-2">
          security notes
        </a>
        .
      </p>
    </Section>
  );
}

function ComingNext() {
  return (
    <Section id="next" title="Coming next">
      <article className="grid gap-6 rounded-sm border bg-card p-6 md:grid-cols-[auto_1fr]">
        <CalendarRangeIcon className="size-6" aria-hidden="true" />
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">Detailed analysis over any time span</h3>
            <span className="rounded-sm border px-1.5 py-0.5 text-xs text-muted-foreground">Planned</span>
          </div>
          <p className="mt-2 max-w-[62ch] text-sm leading-6 text-muted-foreground">
            Pick a date range and get a full analysis across it, not just a single answer: trends
            over the whole history, one period against another, and seasonality, with the same
            checkable SQL and charts as every report today.
          </p>
          <ul className="mt-4 grid gap-1.5 text-sm sm:grid-cols-3">
            <li>Any range, from a week to all time</li>
            <li>Period-over-period comparisons</li>
            <li>Trends and seasonality, explained</li>
          </ul>
        </div>
      </article>
    </Section>
  );
}

function Suggest() {
  return (
    <Section
      id="suggest"
      title="What else should it do?"
      lead="Tell us what's missing. Anyone can write here, and the next features are picked from what people ask for."
    >
      <div className="max-w-2xl">
        <SuggestionBox />
      </div>
    </Section>
  );
}

function Footer() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>
          <span className="marked font-semibold text-foreground">SandboxAnalyst</span> · synthetic
          e-commerce data, real safeguards
        </span>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-2">
          <a href={REPO} className="hover:text-foreground">
            GitHub
          </a>
          <a href={`${REPO}/blob/main/SECURITY.md`} className="hover:text-foreground">
            Security
          </a>
          <a href={`${REPO}/blob/main/docs/decisions.md`} className="hover:text-foreground">
            Design decisions
          </a>
          <Link href={RECORDED_RUN} className="hover:text-foreground">
            Recorded run
          </Link>
        </nav>
      </div>
    </footer>
  );
}
