import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACCESS_CODE,
  TOKEN,
  approvalApproved,
  approvalPaused,
  approvalRejected,
  createFakeApi,
  type FakeApiOptions,
} from "@/test-utils/fake-api";
import { clerk } from "@/test-utils/clerk-mock";
import { Workspace } from "../workspace";

vi.mock("@/components/ai-elements/code-block", () => ({
  CodeBlock: ({ code, language }: { code: string; language: string }) => (
    <pre data-testid={`code-${language}`}>{code}</pre>
  ),
}));

const realFetch = globalThis.fetch;
let api: ReturnType<typeof createFakeApi>;

function mount(options: FakeApiOptions = {}) {
  api = createFakeApi(options);
  globalThis.fetch = api.fetchImpl; // the API helpers (login, schema, threads) use global fetch
  URL.createObjectURL = vi.fn(() => "blob:fake");
  URL.revokeObjectURL = vi.fn();
  return render(<Workspace fetchImpl={api.fetchImpl} />);
}

const chatRequests = () => api.requests.filter((r) => r.path === "/api/chat");

async function signIn(user: ReturnType<typeof userEvent.setup>, code = ACCESS_CODE) {
  await user.type(await screen.findByLabelText("Access code", { selector: "input" }), code);
  await user.click(screen.getByRole("button", { name: /unlock live questions/i }));
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});
afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("Workspace", () => {
  it("shows the example questions from the API without asking for a code", async () => {
    mount();
    expect(await screen.findByRole("heading", { name: /ask a question about the shop/i })).toBeInTheDocument();
    const examples = within(await screen.findByRole("list", { name: /example questions/i }));
    await waitFor(() => expect(examples.getByText(/why did revenue drop in march 2025/i)).toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.requests.some((r) => r.path === "/api/chat")).toBe(false);
  });

  it("opens the data profile beside the chat and closes it with the cross", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /data profile/i }));
    const panel = await screen.findByRole("region", { name: /data profile/i });
    const inPanel = within(panel);
    expect(await inPanel.findByText(/orders from a synthetic shop/i)).toBeInTheDocument();
    expect(inPanel.getByText(/written by openai\.gpt-oss-120b/i)).toBeInTheDocument();
    expect(inPanel.getByRole("img", { name: /entity relationship diagram: 2 tables, 1 joins/i })).toBeInTheDocument();
    // The chat stays usable next to it.
    expect(screen.getByRole("heading", { name: /ask a question about the shop/i })).toBeInTheDocument();
    await user.click(inPanel.getByRole("button", { name: /close data profile/i }));
    expect(screen.queryByRole("region", { name: /data profile/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /data profile/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("shows one table's details at a time and never shows personal data", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /data profile/i }));
    const panel = within(await screen.findByRole("region", { name: /data profile/i }));
    // Starts on the biggest table.
    expect(await panel.findByRole("table", { name: /columns of orders/i })).toBeInTheDocument();
    expect(panel.getByRole("table", { name: /outliers per numeric column of orders/i })).toHaveTextContent("2,985 (5.97%)");
    await user.click(panel.getByRole("button", { name: "customers" }));
    const columns = panel.getByRole("table", { name: /columns of customers/i });
    expect(within(columns).getByText("hidden")).toBeInTheDocument();
    expect(panel.getAllByText(/personal data: values are hidden/i)).toHaveLength(1);
  });

  it("says so when the data profile cannot be loaded", async () => {
    const user = userEvent.setup();
    mount({ profileFails: true });
    await user.click(await screen.findByRole("button", { name: /data profile/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/down|could not/i);
  });

  it("asking while signed out opens sign-in, then the access dialog, and sends nothing yet", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop in march 2025/i }));
    expect(clerk.openSignIn).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("dialog", { name: /enter the access code/i })).toBeInTheDocument();
    expect(chatRequests()).toHaveLength(0);
  });

  it("closing sign-in without signing in sends nothing and asks for no code", async () => {
    const user = userEvent.setup();
    clerk.autoSignIn = false;
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    expect(clerk.openSignIn).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: /access code/i })).not.toBeInTheDocument();
    expect(chatRequests()).toHaveLength(0);
  });

  it("an account that already has live access asks straight away", async () => {
    const user = userEvent.setup();
    clerk.signIn();
    mount({ liveAccess: true });
    await waitFor(() => expect(api.requests.some((r) => r.path === "/api/me")).toBe(true));
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await waitFor(() => expect(chatRequests()).toHaveLength(1));
    expect(chatRequests()[0].headers.get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(clerk.openSignIn).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("the sidebar offers sign-in when signed out and the code when it is still needed", async () => {
    const user = userEvent.setup();
    mount();
    const sidebar = within(await screen.findByRole("navigation", { name: /workspace/i }));
    await user.click(sidebar.getAllByRole("button", { name: /sign in/i })[0]);
    expect(clerk.openSignIn).toHaveBeenCalledTimes(1);
    await user.click(await screen.findByRole("button", { name: /enter access code/i }));
    expect(await screen.findByRole("dialog", { name: /enter the access code/i })).toBeInTheDocument();
  });

  it("history belongs to the account: signing out clears it from the screen", async () => {
    const user = userEvent.setup();
    clerk.signIn();
    mount({
      liveAccess: true,
      threads: [{ thread_id: "thread-0001", title: "Old question", created_at: "", updated_at: "" }],
    });
    expect(await screen.findByText("Old question")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /account/i }));
    await waitFor(() => expect(screen.queryByText("Old question")).not.toBeInTheDocument());
    expect(await screen.findByText(/to keep your questions/i)).toBeInTheDocument();
  });

  it("a wrong code shows a clear error and does not send the question", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user, "wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent(/isn't right/i);
    expect(chatRequests()).toHaveLength(0);
  });

  it("after the right code the waiting question is sent with the bearer token and only the newest message", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);

    await waitFor(() => expect(chatRequests()).toHaveLength(1));
    const [request] = chatRequests();
    expect(request.headers.get("authorization")).toBe(`Bearer ${TOKEN}`);
    const body = request.body as { id: string; messages: { role: string; parts: { text: string }[] }[]; trigger: string };
    expect(body.id).toMatch(/^[A-Za-z0-9_-]{8,64}$/); // the thread id the server validates
    expect(body.messages).toHaveLength(1); // history stays on the server
    expect(body.messages[0].role).toBe("user");
    expect(body.messages[0].parts[0].text).toMatch(/why did revenue drop/i);
    expect(body.trigger).toBe("submit-message");

    // the streamed run renders as a trail plus an answer
    expect(await screen.findByTestId("answer")).toHaveTextContent(/cancelled/i);
    expect(screen.getByRole("list", { name: /steps the analyst took/i })).toBeInTheDocument();
  });

  it("the question stays visible as the heading of its answer", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);
    expect(await screen.findByRole("heading", { level: 2, name: /why did revenue drop/i })).toBeInTheDocument();
  });

  it("shows the files of the answer in the files area and fetches them with the token", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);
    await screen.findByTestId("answer");

    const artifactCalls = () => api.requests.filter((r) => /\/artifacts\//.test(r.path));
    await user.click(await screen.findByRole("button", { name: /files \(1\)/i })); // small screens open the dialog
    await waitFor(() => expect(artifactCalls().length).toBeGreaterThan(0));
    expect(artifactCalls()[0].headers.get("authorization")).toBe(`Bearer ${TOKEN}`);
    expect(await screen.findByRole("link", { name: /download chart\.png/i })).toBeInTheDocument();
  });

  it("an expired sign-in during a question opens sign-in again instead of showing a dead error", async () => {
    const user = userEvent.setup();
    mount({ chatStatus: { status: 401, detail: "Your sign-in has expired. Sign in again." } });
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);
    await waitFor(() => expect(clerk.openSignIn).toHaveBeenCalledTimes(2)); // first sign-in, then again
  });

  it("other server errors are shown plainly with a way to dismiss them", async () => {
    const user = userEvent.setup();
    mount({ chatStatus: { status: 429, detail: "The server is busy. Try again shortly." } });
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The server is busy. Try again shortly.");
    await user.click(within(alert).getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByText(/server is busy/i)).not.toBeInTheDocument();
  });

  describe("human approval", () => {
    async function askAndPause(user: ReturnType<typeof userEvent.setup>, resume = approvalApproved) {
      mount({ chatSequence: [approvalPaused, resume] });
      await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
      await signIn(user);
      return within(await screen.findByRole("region", { name: /approval needed/i }));
    }

    it("a flagged query waits for approval and the composer is locked meanwhile", async () => {
      const user = userEvent.setup();
      const card = await askAndPause(user);
      expect(card.getByText(/raw rows of analytics\.orders/i)).toBeInTheDocument();
      expect(screen.getByLabelText("Your question")).toBeDisabled();
      expect(screen.getByText(/paused: a query above is waiting/i)).toBeInTheDocument();
      expect(chatRequests()).toHaveLength(1);
    });

    it("approving resumes the run with only the decision, then shows the answer", async () => {
      const user = userEvent.setup();
      const card = await askAndPause(user);
      await user.click(card.getByRole("button", { name: /run query/i }));

      await waitFor(() => expect(chatRequests()).toHaveLength(2));
      const body = chatRequests()[1].body as Record<string, unknown>;
      expect(body.approvals).toEqual([{ id: "approval-1", approved: true }]);
      expect(body.messages).toEqual([{ role: "assistant", parts: [] }]); // no client history

      expect(await screen.findByTestId("answer")).toHaveTextContent("Done.");
      expect(screen.queryByRole("region", { name: /approval needed/i })).not.toBeInTheDocument();
      expect(screen.getByText(/you approved this query/i)).toBeInTheDocument();
      expect(screen.getByLabelText("Your question")).not.toBeDisabled();
    });

    it("an edited query is sent with the approval", async () => {
      const user = userEvent.setup();
      const card = await askAndPause(user);
      await user.click(card.getByRole("button", { name: /edit sql/i }));
      const editor = card.getByLabelText(/edit the sql/i);
      await user.clear(editor);
      await user.type(editor, "SELECT * FROM analytics.orders LIMIT 100");
      await user.click(card.getByRole("button", { name: /run edited query/i }));

      await waitFor(() => expect(chatRequests()).toHaveLength(2));
      expect((chatRequests()[1].body as Record<string, unknown>).approvals).toEqual([
        { id: "approval-1", approved: true, edited_query: "SELECT * FROM analytics.orders LIMIT 100" },
      ]);
    });

    it("rejecting sends the reason and shows the query as not run", async () => {
      const user = userEvent.setup();
      const card = await askAndPause(user, approvalRejected);
      await user.click(card.getByRole("button", { name: /^reject$/i }));
      await user.type(card.getByLabelText(/why\?/i), "Too big");
      await user.click(card.getByRole("button", { name: /reject query/i }));

      await waitFor(() => expect(chatRequests()).toHaveLength(2));
      expect((chatRequests()[1].body as Record<string, unknown>).approvals).toEqual([
        { id: "approval-1", approved: false, reason: "Too big" },
      ]);
      expect(await screen.findByText(/query not run/i)).toBeInTheDocument();
      expect(screen.getByText(/you rejected this query: “too big”/i)).toBeInTheDocument();
    });

    it("strict mode is sent with the next question", async () => {
      const user = userEvent.setup();
      mount();
      await user.click(await screen.findByRole("checkbox", { name: /ask me before every query/i }));
      await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
      await signIn(user);
      await waitFor(() => expect(chatRequests()).toHaveLength(1));
      expect((chatRequests()[0].body as Record<string, unknown>).approval_mode).toBe("strict");
    });

    it("the browser's timezone is sent with each question", async () => {
      const user = userEvent.setup();
      mount();
      await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
      await signIn(user);
      await waitFor(() => expect(chatRequests()).toHaveLength(1));
      expect((chatRequests()[0].body as Record<string, unknown>).timezone).toBe(
        Intl.DateTimeFormat().resolvedOptions().timeZone,
      );
    });
  });

  describe("replay mode", () => {
    it("visitors without a code can watch a recorded run, read-only", async () => {
      const user = userEvent.setup();
      mount({ replays: true });
      const list = within(await screen.findByRole("list", { name: /recorded runs/i }));
      await user.click(list.getByRole("button", { name: /cancelled in 2025/i }));

      const banner = await screen.findByTestId("replay-banner");
      expect(banner).toHaveTextContent(/recorded run/i);
      expect(banner).toHaveTextContent("1,086 matches the database");
      expect(await screen.findByTestId("answer")).toHaveTextContent(/cancelled/i);
      expect(screen.queryByLabelText("Your question")).not.toBeInTheDocument(); // no composer
      expect(screen.queryByRole("dialog", { name: /access code/i })).not.toBeInTheDocument();
      expect(window.location.search).toBe("?replay=cancelled-orders");
      expect(chatRequests()).toHaveLength(0);
    });

    it("a recorded run opens even if Clerk never loads", async () => {
      clerk.setLoaded(false);
      window.history.replaceState(null, "", "/app?replay=cancelled-orders");
      mount({ replays: true });
      expect(await screen.findByTestId("replay-banner")).toHaveTextContent(/recorded run/i);
      expect(await screen.findByTestId("answer")).toHaveTextContent(/cancelled/i);
    });

    it("a recorded run's files load without a token", async () => {
      const user = userEvent.setup();
      mount({ replays: true });
      await user.click(await screen.findByRole("button", { name: /cancelled in 2025/i }));
      await screen.findByTestId("answer");
      await user.click(await screen.findByRole("button", { name: /files \(1\)/i }));
      await waitFor(() =>
        expect(api.requests.some((r) => r.path === "/api/replays/cancelled-orders/files/chart.png")).toBe(true),
      );
      const fileRequest = api.requests.find((r) => r.path.startsWith("/api/replays/cancelled-orders/files/"));
      expect(fileRequest?.headers.get("authorization")).toBeNull();
    });

    it("leaving a recorded run starts a fresh question", async () => {
      const user = userEvent.setup();
      mount({ replays: true });
      await user.click(await screen.findByRole("button", { name: /cancelled in 2025/i }));
      await user.click(await screen.findByRole("button", { name: /ask your own question/i }));
      expect(await screen.findByLabelText("Your question")).toBeInTheDocument();
      expect(screen.queryByTestId("replay-banner")).not.toBeInTheDocument();
    });

    it("the list is hidden when there are no recorded runs", async () => {
      mount();
      await screen.findByRole("list", { name: /example questions/i });
      expect(screen.queryByRole("list", { name: /recorded runs/i })).not.toBeInTheDocument();
    });
  });

  it("the session token is never written to browser storage (Clerk keeps the session)", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);
    await screen.findByTestId("answer");
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(TOKEN);
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(TOKEN);
  });
});
