import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { useAuth } from "../context/useAuth";
import { useCapabilities } from "../auth/useCapabilities";
import type { Capabilities } from "../auth/useCapabilities";
import type { User } from "../types";

vi.mock("../context/useAuth", () => ({ useAuth: vi.fn() }));
vi.mock("../auth/useCapabilities", () => ({ useCapabilities: vi.fn() }));

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseCapabilities = vi.mocked(useCapabilities);

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: "u-1",
    email: "a@b.com",
    name: "Alice",
    profile_picture_url: null,
    created_at: "2026-01-01T00:00:00Z",
    roles: ["developer"],
    organizations: [],
    permissions: [],
    organization_privileges: {},
    ...overrides,
  };
}

function makeCapabilities(overrides: Partial<Capabilities> = {}): Capabilities {
  return {
    roles: new Set(),
    permissions: new Set(),
    can: () => false,
    isInOrganization: () => false,
    canInOrganization: () => false,
    ...overrides,
  };
}

const noop = () => {};
const baseProps = {
  projects: [],
  activeSessionId: null,
    activeOrganizationId: null as string | null,
  onSelect: noop,
  onSelectOrganization: noop,
  onNewChat: noop,
  onNewProject: noop,
  onRename: noop,
  onArchive: noop,
  onDelete: noop,
  onOpenSettings: noop,
  showArchived: false,
  onToggleArchived: noop,
  isOpen: true,
  onClose: noop,
};

function renderSidebar(extra: Partial<typeof baseProps> = {}) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Sidebar {...baseProps} {...extra} />
    </MemoryRouter>,
  );
}

function mockAuth(user: User | null) {
  mockedUseAuth.mockReturnValue({
    user,
    loading: false,
    verifyOtp: vi.fn(),
    updateAccountSettings: vi.fn(),
    uploadProfilePicture: vi.fn(),
    changePassword: vi.fn(),
    deleteAccount: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Sidebar capability filtering", () => {
  it("hides 'New project' for a user without project:create", () => {
    mockAuth(makeUser());
    mockedUseCapabilities.mockReturnValue(
      makeCapabilities({ can: (p) => p === "chat:submit" }),
    );
    renderSidebar();
    expect(screen.getByRole("button", { name: /new chat/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /new project/i }),
    ).not.toBeInTheDocument();
  });

  it("shows 'New project' for a user with project:create", () => {
    mockAuth(makeUser());
    mockedUseCapabilities.mockReturnValue(
      makeCapabilities({
        can: (p) => p === "chat:submit" || p === "project:create",
      }),
    );
    renderSidebar();
    expect(
      screen.getByRole("button", { name: /new project/i }),
    ).toBeInTheDocument();
  });

  it("hides 'New chat' when the user lacks chat:submit", () => {
    // Organization-only user: no application roles → no permissions.
    mockAuth(
      makeUser({
        roles: [],
        organizations: [{ id: "org_1", name: "Acme", role: "owner" }],
      }),
    );
    mockedUseCapabilities.mockReturnValue(makeCapabilities());
    renderSidebar();
    expect(
      screen.queryByRole("button", { name: /new chat/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /new project/i }),
    ).not.toBeInTheDocument();
  });

  it("renders the Organizations section when the user has memberships", () => {
    mockAuth(
      makeUser({
        organizations: [
          { id: "org_1", name: "Acme", role: "owner" },
          { id: "org_2", name: "Beta", role: "member" },
        ],
      }),
    );
    mockedUseCapabilities.mockReturnValue(makeCapabilities());
    renderSidebar();
    expect(screen.getByText(/organizations/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /acme/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /beta/i })).toBeInTheDocument();
  });

  it("does not render the Organizations section without memberships", () => {
    mockAuth(makeUser({ organizations: [] }));
    mockedUseCapabilities.mockReturnValue(
      makeCapabilities({ can: () => true }),
    );
    renderSidebar();
    expect(screen.queryByText(/^organizations$/i)).not.toBeInTheDocument();
  });

  it("highlights the active organization", () => {
    mockAuth(
      makeUser({
        organizations: [{ id: "org_1", name: "Acme", role: "owner" }],
      }),
    );
    mockedUseCapabilities.mockReturnValue(makeCapabilities());
    renderSidebar({ activeOrganizationId: "org_1" });
    const btn = screen.getByRole("button", { name: /acme/i });
    expect(btn.className).toContain("bg-accent-soft");
  });
});