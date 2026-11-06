import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ACCESS_CODE, TOKEN, createFakeApi, type FakeApiOptions } from "@/test-utils/fake-api";
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

  it("lets anyone browse the schema in the sidebar", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("tab", { name: /the data/i }));
    expect(await screen.findByText("orders")).toBeInTheDocument();
    expect(screen.getByText(/50,021 rows/)).toBeInTheDocument();
  });

  it("says so when the schema cannot be loaded", async () => {
    const user = userEvent.setup();
    mount({ schemaFails: true });
    await user.click(await screen.findByRole("tab", { name: /the data/i }));
    expect(await screen.findByText(/could not load the schema/i)).toBeInTheDocument();
  });

  it("asking while signed out opens the access dialog and sends nothing yet", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop in march 2025/i }));
    expect(await screen.findByRole("dialog", { name: /enter the access code/i })).toBeInTheDocument();
    expect(chatRequests()).toHaveLength(0);
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

  it("an expired session during a question asks for the code again instead of showing a dead error", async () => {
    const user = userEvent.setup();
    mount({ chatStatus: { status: 401, detail: "Invalid or expired access token." } });
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);
    const dialog = await screen.findByRole("dialog", { name: /enter the access code/i });
    expect(dialog).toHaveTextContent(/your session ended/i);
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

  it("the access token is kept for the tab (sessionStorage) but never in localStorage", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /why did revenue drop/i }));
    await signIn(user);
    await screen.findByTestId("answer");
    expect(window.sessionStorage.getItem("sa.token")).toContain(TOKEN);
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(TOKEN);
  });
});
