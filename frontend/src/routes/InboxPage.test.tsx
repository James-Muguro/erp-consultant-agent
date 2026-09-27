/**
 * InboxPage tests.
 *
 * Snapshot basis: frontend/src/routes/InboxPage.tsx.
 *
 * The API client is mocked per test. No global fetch mocking is
 * introduced; the component reads exclusively through ../api/client.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InboxPage } from "./InboxPage";
import type { InboxItem } from "../types";

vi.mock("../api/client", () => ({
  api: {
    getInbox: vi.fn(),
    getInboxHistory: vi.fn(),
    getInboxCount: vi.fn(),
    resolveInboxItem: vi.fn(),
  },
}));

vi.mock("../hooks/useInboxCount", () => ({
  useInboxCount: () => ({ count: 0, refresh: vi.fn() }),
}));

import { api } from "../api/client";

const apiMock = api as unknown as {
  getInbox: ReturnType<typeof vi.fn>;
  getInboxHistory: ReturnType<typeof vi.fn>;
  getInboxCount: ReturnType<typeof vi.fn>;
  resolveInboxItem: ReturnType<typeof vi.fn>;
};

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
    title: "T",
    subtitle: "S",
    context_url: "/p/s1",
    ...overrides,
  };
}

beforeEach(() => {
  apiMock.getInbox.mockReset();
  apiMock.getInboxHistory.mockReset();
  apiMock.getInboxCount.mockReset();
  apiMock.resolveInboxItem.mockReset();
  apiMock.getInboxCount.mockResolvedValue({ pending: 0 });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderPage() {
  return render(
    <MemoryRouter>
      <InboxPage />
    </MemoryRouter>,
  );
}

describe("InboxPage", () => {
  it("shows empty state when the pending list is empty", async () => {
    apiMock.getInbox.mockResolvedValue({ items: [] });
    renderPage();
    expect(await screen.findByText("Nothing pending.")).toBeInTheDocument();
  });

  it("renders pending items", async () => {
    apiMock.getInbox.mockResolvedValue({ items: [makeItem({ title: "First" })] });
    renderPage();
    expect(await screen.findByText("First")).toBeInTheDocument();
  });

  it("renders history items when the history tab is selected", async () => {
    apiMock.getInbox.mockResolvedValue({ items: [] });
    apiMock.getInboxHistory.mockResolvedValue({
      items: [makeItem({ id: "h1", status: "resolved", title: "Resolved A", resolved_at: new Date().toISOString() })],
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /history/i }));
    expect(await screen.findByText("Resolved A")).toBeInTheDocument();
  });

  it("shows error banner with retry on API failure", async () => {
    apiMock.getInbox.mockRejectedValueOnce(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/);
  });

  it("resolves an item and refreshes the list", async () => {
    apiMock.getInbox
      .mockResolvedValueOnce({ items: [makeItem({ title: "Actionable" })] })
      .mockResolvedValueOnce({ items: [] });
    apiMock.resolveInboxItem.mockResolvedValue({ resolved: true });

    renderPage();
    await screen.findByText("Actionable");
    await userEvent.click(screen.getByRole("button", { name: /resolve/i }));

    await waitFor(() => {
      expect(apiMock.resolveInboxItem).toHaveBeenCalledWith("i1");
    });
    expect(await screen.findByText("Nothing pending.")).toBeInTheDocument();
  });
});