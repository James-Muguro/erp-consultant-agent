import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./RequireAuth";
import { useAuth } from "../context/useAuth";
import { useCapabilities } from "../auth/useCapabilities";
import type { Capabilities } from "../auth/useCapabilities";
import type { User } from "../types";

vi.mock("../context/useAuth", () => ({ useAuth: vi.fn() }));
vi.mock("../auth/useCapabilities", () => ({ useCapabilities: vi.fn() }));

const mockedUseAuth = vi.mocked(useAuth);
const mockedUseCapabilities = vi.mocked(useCapabilities);

function makeUser(): User {
  return {
    id: "u-1",
    email: "a@b.com",
    name: null,
    profile_picture_url: null,
    created_at: "2026-01-01T00:00:00Z",
    roles: ["developer"],
    organizations: [],
    permissions: [],
    organization_privileges: {},
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

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<div data-testid="login">Login</div>} />
        <Route path="/" element={<div data-testid="home">Home</div>} />
        <Route
          element={
            <RequireAuth>
              <div data-testid="protected">Protected</div>
            </RequireAuth>
          }
        >
          <Route path="/chat" element={null} />
          <Route path="/p/:sessionId" element={null} />
          <Route path="/org/:orgId" element={null} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("RequireAuth", () => {
  it("redirects unauthenticated users to /login", () => {
    mockedUseAuth.mockReturnValue({
      user: null,
      loading: false,
      verifyOtp: vi.fn(),
      updateAccountSettings: vi.fn(),
      uploadProfilePicture: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
    mockedUseCapabilities.mockReturnValue(makeCapabilities());

    renderAt("/chat");
    expect(screen.getByTestId("login")).toBeInTheDocument();
  });

  it("renders the route when the capability is held", () => {
    mockedUseAuth.mockReturnValue({
      user: makeUser(),
      loading: false,
      verifyOtp: vi.fn(),
      updateAccountSettings: vi.fn(),
      uploadProfilePicture: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
    mockedUseCapabilities.mockReturnValue(
      makeCapabilities({ can: (p) => p === "chat:submit" }),
    );

    renderAt("/chat");
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  it("renders NotAuthorizedState when the capability is missing", () => {
    mockedUseAuth.mockReturnValue({
      user: makeUser(),
      loading: false,
      verifyOtp: vi.fn(),
      updateAccountSettings: vi.fn(),
      uploadProfilePicture: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
    mockedUseCapabilities.mockReturnValue(makeCapabilities());

    renderAt("/chat");
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
    expect(
      screen.getByText(/you don't have access to this section/i),
    ).toBeInTheDocument();
  });

  it("gates workspace routes on phase:execute", () => {
    mockedUseAuth.mockReturnValue({
      user: makeUser(),
      loading: false,
      verifyOtp: vi.fn(),
      updateAccountSettings: vi.fn(),
      uploadProfilePicture: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
    // User holds chat:submit but NOT phase:execute.
    mockedUseCapabilities.mockReturnValue(
      makeCapabilities({ can: (p) => p === "chat:submit" }),
    );

    renderAt("/p/prj_abc");
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
    expect(
      screen.getByText(/you don't have access to this section/i),
    ).toBeInTheDocument();
  });

  it("requires organization membership for organization-scoped routes", () => {
    mockedUseAuth.mockReturnValue({
      user: makeUser(),
      loading: false,
      verifyOtp: vi.fn(),
      updateAccountSettings: vi.fn(),
      uploadProfilePicture: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
    mockedUseCapabilities.mockReturnValue(
      makeCapabilities({ isInOrganization: () => false }),
    );

    renderAt("/org/org_1");
    expect(
      screen.getByText(/organization not available/i),
    ).toBeInTheDocument();
  });

  it("permits organization-scoped routes when membership exists", () => {
    mockedUseAuth.mockReturnValue({
      user: makeUser(),
      loading: false,
      verifyOtp: vi.fn(),
      updateAccountSettings: vi.fn(),
      uploadProfilePicture: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
    mockedUseCapabilities.mockReturnValue(
      makeCapabilities({ isInOrganization: (id) => id === "org_1" }),
    );

    renderAt("/org/org_1");
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  it("lets ungated routes through for any authenticated user", () => {
    mockedUseAuth.mockReturnValue({
      user: makeUser(),
      loading: false,
      verifyOtp: vi.fn(),
      updateAccountSettings: vi.fn(),
      uploadProfilePicture: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
    mockedUseCapabilities.mockReturnValue(makeCapabilities());

    // No route in the test tree matches "/", so we redirect to the
    // "/" element directly.
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            element={
              <RequireAuth>
                <div data-testid="protected">Protected</div>
              </RequireAuth>
            }
          >
            <Route path="/" element={null} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });
});