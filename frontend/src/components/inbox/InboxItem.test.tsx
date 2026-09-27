/**
 * InboxItem component tests.
 *
 * Snapshot basis: frontend/src/components/inbox/InboxItem.tsx as seen.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { InboxItemRow } from "./InboxItem";
import type { InboxItem } from "../../types";

function makeItem(overrides: Partial<InboxItem> = {}): InboxItem {
  return {
    id: "i1",
    source_type: "bid_won",
    source_id: "src1",
    session_id: "s1",
    organization_id: null,
    status: "pending",
    created_at: new Date().toISOString(),
    resolved_at: null,
    resolved_by_user_id: null,
    title: "Hello",
    subtitle: "World",
    context_url: "/p/s1",
    ...overrides,
  };
}

function renderItem(item: InboxItem, onResolve?: (id: string) => void, busy = false) {
  return render(
    <MemoryRouter>
      <ul>
        <InboxItemRow item={item} onResolve={onResolve} busy={busy} />
      </ul>
    </MemoryRouter>,
  );
}

describe("InboxItemRow", () => {
  it("renders title and subtitle", () => {
    renderItem(makeItem({ title: "T", subtitle: "Sub" }));
    expect(screen.getByText("T")).toBeInTheDocument();
    expect(screen.getByText("Sub")).toBeInTheDocument();
  });

  it("renders the source-type pill label", () => {
    renderItem(makeItem({ source_type: "bid_won" }));
    expect(screen.getByText("Bid won")).toBeInTheDocument();
  });

  it("wraps body in a link when context_url is present", () => {
    renderItem(makeItem({ context_url: "/p/s1" }));
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/p/s1");
  });

  it("does not render a link when context_url is null", () => {
    renderItem(makeItem({ context_url: null }));
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders the resolve button on pending items when a handler is provided", async () => {
    const onResolve = vi.fn();
    renderItem(makeItem(), onResolve);
    await userEvent.click(screen.getByRole("button", { name: /resolve/i }));
    expect(onResolve).toHaveBeenCalledWith("i1");
  });

  it("does not render the resolve button on resolved items", () => {
    renderItem(makeItem({ status: "resolved", resolved_at: new Date().toISOString() }));
    expect(screen.queryByRole("button", { name: /resolve/i })).toBeNull();
  });

  it("disables the resolve button while busy", () => {
    renderItem(makeItem(), vi.fn(), true);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});