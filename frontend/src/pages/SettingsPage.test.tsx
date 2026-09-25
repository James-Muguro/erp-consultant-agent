import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { SettingsPage } from "./SettingsPage";
import { AuthContext, type AuthContextValue } from "../context/auth-context";
import { ConfirmProvider } from "../context/ConfirmContext";
import type { User } from "../types";

const SAMPLE_USER: User = {
  id: "u-1",
  email: "a@b.com",
  name: "Alice",
  profile_picture_url: null,
  created_at: "2026-01-01T00:00:00Z",
  roles: ["developer"],
  organizations: [],
};

function makeContext(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    user: SAMPLE_USER,
    loading: false,
    verifyOtp: vi.fn(),
    updateAccountSettings: vi.fn(),
    uploadProfilePicture: vi.fn(),
    changePassword: vi.fn(),
    deleteAccount: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    ...overrides,
  };
}

function renderSettings(ctx: AuthContextValue) {
  return render(
    <AuthContext.Provider value={ctx}>
      <ConfirmProvider>
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>
      </ConfirmProvider>
    </AuthContext.Provider>,
  );
}

beforeEach(() => {
  globalThis.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPage — Sessions section", () => {
  it("renders the sign-out-all button", () => {
    renderSettings(makeContext());
    expect(screen.getByRole("button", { name: /sign out of all devices/i })).toBeInTheDocument();
  });

  it("opens the confirmation dialog and does NOT call logoutAll on cancel", async () => {
    const logoutAll = vi.fn();
    const user = userEvent.setup();
    renderSettings(makeContext({ logoutAll }));

    await user.click(screen.getByRole("button", { name: /sign out of all devices/i }));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
    expect(logoutAll).not.toHaveBeenCalled();
  });

  it("calls logoutAll when confirmed", async () => {
    const logoutAll = vi.fn().mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    renderSettings(makeContext({ logoutAll }));

    await user.click(screen.getByRole("button", { name: /sign out of all devices/i }));
    await user.click(screen.getByRole("button", { name: /sign out everywhere/i }));

    await waitFor(() => expect(logoutAll).toHaveBeenCalledTimes(1));
  });
});