import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { createFakeApi } from "@/test-utils/fake-api";
import { SuggestionBox } from "../suggestion-box";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function mount() {
  const api = createFakeApi();
  globalThis.fetch = api.fetchImpl;
  render(<SuggestionBox />);
  return api;
}

describe("SuggestionBox", () => {
  it("anyone can send an idea without signing in", async () => {
    const user = userEvent.setup();
    const api = mount();
    await user.type(screen.getByLabelText("Your idea"), "Compare two date ranges");
    await user.click(screen.getByRole("button", { name: /send suggestion/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(/thanks/i);
    const sent = api.requests.find((r) => r.path === "/api/suggestions");
    expect(sent?.body).toEqual({ text: "Compare two date ranges", website: "" });
    expect(sent?.headers.get("authorization")).toBeNull();
    expect(screen.getByLabelText("Your idea")).toHaveValue("");
  });

  it("needs a few words before it can be sent", async () => {
    const user = userEvent.setup();
    const api = mount();
    const send = screen.getByRole("button", { name: /send suggestion/i });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("Your idea"), "ok");
    expect(send).toBeDisabled();
    expect(api.requests).toHaveLength(0);
  });

  it("shows the server's reason when it refuses", async () => {
    const user = userEvent.setup();
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: "Thanks! That's enough for now." }), { status: 429 });
    render(<SuggestionBox />);
    await user.type(screen.getByLabelText("Your idea"), "One more idea");
    await user.click(screen.getByRole("button", { name: /send suggestion/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("That's enough for now"));
  });

  it("the bot trap is hidden from people and from the accessibility tree", () => {
    mount();
    expect(screen.queryByRole("textbox", { name: /website/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
  });
});
