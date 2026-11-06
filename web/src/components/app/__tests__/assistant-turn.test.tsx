import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { chunksToMessage } from "@/lib/replay";
import { approvalPaused, realRun, toolErrorRun } from "@/test-utils/fake-api";
import { AssistantTurn, organize } from "../assistant-turn";

// Syntax highlighting (shiki) is not what these tests are about, and it is slow in jsdom.
vi.mock("@/components/ai-elements/code-block", () => ({
  CodeBlock: ({ code, language }: { code: string; language: string }) => (
    <pre data-testid={`code-${language}`}>{code}</pre>
  ),
}));

async function messageFrom(chunks: Array<Record<string, unknown>>) {
  const message = await chunksToMessage(chunks);
  if (!message) throw new Error("no message");
  return message;
}

describe("organize", () => {
  it("separates the trail from the final answer and collects data parts", async () => {
    const { trail, answer, todos, artifacts, run } = organize(await messageFrom(realRun));
    expect(trail.some((item) => item.kind === "plan")).toBe(true);
    expect(trail.some((item) => item.kind === "tool" && item.name === "run_sql")).toBe(true);
    expect(trail.every((item) => !(item.kind === "tool" && item.name === "write_todos"))).toBe(true);
    expect(answer).toMatch(/cancelled/i);
    expect(todos.length).toBeGreaterThan(0);
    expect(artifacts[0].name).toBe("chart.png");
    expect(run?.status).toBe("ok");
  });
});

describe("AssistantTurn approvals", () => {
  it("the approval card is visible even when the step first rendered as running (found live)", async () => {
    const paused = await messageFrom(approvalPaused);
    const running = {
      ...paused,
      parts: paused.parts.map((p) =>
        "approval" in p ? ({ ...p, state: "input-available", approval: undefined } as typeof p) : p,
      ),
    };
    const props = { streaming: true, selected: false, onShowFiles: () => {} };
    const { rerender } = render(<AssistantTurn message={running} {...props} />);
    expect(screen.queryByRole("region", { name: /approval needed/i })).not.toBeInTheDocument();
    rerender(<AssistantTurn message={paused} {...props} streaming={false} />);
    expect(screen.getByRole("region", { name: /approval needed/i })).toBeVisible();
  });
});

describe("AssistantTurn", () => {
  it("shows the plan, a query step with its SQL and result preview, and the answer", async () => {
    const user = userEvent.setup();
    render(<AssistantTurn message={await messageFrom(realRun)} streaming={false} selected={false} onShowFiles={() => {}} />);

    const trail = screen.getByRole("list", { name: /steps the analyst took/i });
    expect(within(trail).getByTestId("step-plan")).toBeInTheDocument();

    const sqlStep = within(trail).getByTestId("step-sql");
    expect(sqlStep).toHaveTextContent(/\d+ rows?/); // "N row(s)" in the step summary
    await user.click(within(sqlStep).getByRole("button"));
    expect(within(sqlStep).getByTestId("code-sql").textContent).toMatch(/select/i);
    expect(within(sqlStep).getByRole("table")).toBeInTheDocument(); // the parsed result preview

    expect(screen.getByTestId("answer")).toHaveTextContent(/cancelled/i);
  });

  it("every finished step is announced as done and none as running", async () => {
    render(<AssistantTurn message={await messageFrom(realRun)} streaming={false} selected={false} onShowFiles={() => {}} />);
    const steps = screen.getAllByRole("listitem").filter((li) => li.getAttribute("data-state"));
    expect(steps.length).toBeGreaterThan(3);
    expect(steps.every((li) => li.getAttribute("data-state") === "done")).toBe(true);
  });

  it("footer shows time, queries and model, and links the trace safely", async () => {
    const message = await messageFrom(realRun);
    // give the fixture run a trace link so we can check the anchor attributes
    for (const part of message.parts) if (part.type === "data-run") part.data.trace_url = "https://trace.example/t/1";
    render(<AssistantTurn message={message} streaming={false} selected={false} onShowFiles={() => {}} />);
    const link = screen.getByRole("link", { name: /view trace/i });
    expect(link).toHaveAttribute("href", "https://trace.example/t/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("offers a Files button when the answer produced files", async () => {
    const user = userEvent.setup();
    const onShowFiles = vi.fn();
    render(<AssistantTurn message={await messageFrom(realRun)} streaming={false} selected={false} onShowFiles={onShowFiles} />);
    await user.click(screen.getByRole("button", { name: /files \(1\)/i }));
    expect(onShowFiles).toHaveBeenCalledOnce();
  });

  it("marks a failed tool step as failed and opens it so the problem is visible", async () => {
    render(<AssistantTurn message={await messageFrom(toolErrorRun)} streaming={false} selected={false} onShowFiles={() => {}} />);
    const failed = screen.getAllByRole("listitem").find((li) => li.getAttribute("data-state") === "error");
    expect(failed).toBeDefined();
    expect(failed).toHaveTextContent(/failed/i);
    expect(failed).toHaveTextContent(/boom/);
  });

  it("while streaming with nothing yet it says what is happening", async () => {
    render(
      <AssistantTurn
        message={{ id: "a1", role: "assistant", parts: [] }}
        streaming
        selected={false}
        onShowFiles={() => {}}
      />,
    );
    expect(screen.getByText(/planning the work/i)).toBeInTheDocument();
  });

  it("explains why a run stopped early", async () => {
    const message = await messageFrom(realRun);
    for (const part of message.parts) if (part.type === "data-run") part.data.status = "budget_exceeded";
    render(<AssistantTurn message={message} streaming={false} selected={false} onShowFiles={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent(/token budget/i);
  });
});
