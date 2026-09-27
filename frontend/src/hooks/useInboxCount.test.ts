/**
 * useInboxCount tests.
 *
 * Snapshot basis: frontend/src/hooks/useInboxCount.ts
 * The hook reads through ../api/client and consumes the
 * `inbox-changed` window event and a 60s polling interval.
 */
import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  api: { getInboxCount: vi.fn() },
}));

vi.mock("../context/useAuth", () => {
  const STABLE_USER = { id: "u1" };
  return { useAuth: () => ({ user: STABLE_USER }) };
});

vi.mock("../auth/useCapabilities", () => ({
  useCapabilities: () => ({ can: () => true }),
}));

import { api } from "../api/client";
import { useInboxCount } from "./useInboxCount";

const apiMock = api as unknown as { getInboxCount: ReturnType<typeof vi.fn> };

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  apiMock.getInboxCount.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useInboxCount", () => {
  it("fetches the pending count on mount", async () => {
    apiMock.getInboxCount.mockResolvedValue({ pending: 3 });
    const { result } = renderHook(() => useInboxCount());
    await waitFor(() => expect(result.current.count).toBe(3));
    expect(apiMock.getInboxCount).toHaveBeenCalledTimes(1);
  });

  it("refetches on inbox-changed", async () => {
    apiMock.getInboxCount.mockResolvedValue({ pending: 1 });
    const { result } = renderHook(() => useInboxCount());
    await waitFor(() => expect(result.current.count).toBe(1));

    apiMock.getInboxCount.mockResolvedValue({ pending: 5 });
    act(() => {
      window.dispatchEvent(new Event("inbox-changed"));
    });
    await waitFor(() => expect(result.current.count).toBe(5));
  });

  it("polls on the 60s interval", async () => {
    apiMock.getInboxCount.mockResolvedValue({ pending: 1 });
    renderHook(() => useInboxCount());
    await waitFor(() => expect(apiMock.getInboxCount).toHaveBeenCalled());
    const callsAfterMount = apiMock.getInboxCount.mock.calls.length;

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    await waitFor(() =>
      expect(apiMock.getInboxCount.mock.calls.length).toBeGreaterThan(
        callsAfterMount,
      ),
    );
  });

  it("silently ignores API errors", async () => {
    apiMock.getInboxCount.mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useInboxCount());
    await waitFor(() => expect(apiMock.getInboxCount).toHaveBeenCalled());
    // count stays at 0, no throw.
    expect(result.current.count).toBe(0);
  });
});