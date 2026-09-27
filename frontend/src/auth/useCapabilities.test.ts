import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useCapabilities } from "./useCapabilities";
import { useAuth } from "../context/useAuth";
import type { AuthContextValue } from "../context/auth-context";
import type { User } from "../types";

vi.mock("../context/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: "u-1",
    email: "a@b.com",
    name: null,
    profile_picture_url: null,
    created_at: "2026-01-01T00:00:00Z",
    roles: [],
    organizations: [],
    permissions: [],
    organization_privileges: {},
    ...overrides,
  };
}

function mockAuth(user: User | null): void {
  const value: AuthContextValue = {
    user,
    loading: false,
    verifyOtp: vi.fn(),
    updateAccountSettings: vi.fn(),
    uploadProfilePicture: vi.fn(),
    changePassword: vi.fn(),
    deleteAccount: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
  };
  mockedUseAuth.mockReturnValue(value);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useCapabilities", () => {
  it("returns empty sets when there is no user", () => {
    mockAuth(null);
    const { result } = renderHook(() => useCapabilities());
    expect(result.current.roles.size).toBe(0);
    expect(result.current.permissions.size).toBe(0);
    expect(result.current.can("chat:submit")).toBe(false);
    expect(result.current.isInOrganization("org-1")).toBe(false);
    expect(
      result.current.canInOrganization("org-1", "org:member:manage"),
    ).toBe(false);
  });

  it("exposes the caller's application roles", () => {
    mockAuth(makeUser({ roles: ["developer", "business_development"] }));
    const { result } = renderHook(() => useCapabilities());
    expect(result.current.roles.has("developer")).toBe(true);
    expect(result.current.roles.has("business_development")).toBe(true);
    expect(result.current.roles.has("functional_consultant")).toBe(false);
  });

  it("can() reads only from the delivered permissions set", () => {
    mockAuth(
      makeUser({
        roles: ["developer"],
        permissions: ["chat:submit", "solution:record_actual"],
      }),
    );
    const { result } = renderHook(() => useCapabilities());
    expect(result.current.can("chat:submit")).toBe(true);
    expect(result.current.can("solution:record_actual")).toBe(true);
    expect(result.current.can("project:create")).toBe(false);
  });

  it("does not infer permissions from role strings", () => {
    // The frontend must not translate role strings into permissions
    // itself. Roles list is populated; permissions list is empty. The
    // hook must respect the backend's computed set, not guess.
    mockAuth(
      makeUser({
        roles: ["functional_consultant"],
        permissions: [],
      }),
    );
    const { result } = renderHook(() => useCapabilities());
    expect(result.current.can("project:create")).toBe(false);
    expect(result.current.can("chat:submit")).toBe(false);
  });

  it("isInOrganization reflects membership, not privilege", () => {
    mockAuth(
      makeUser({
        // Member of org-1 but with no privileges inside it.
        organization_privileges: { "org-1": [] },
      }),
    );
    const { result } = renderHook(() => useCapabilities());
    expect(result.current.isInOrganization("org-1")).toBe(true);
    expect(result.current.isInOrganization("org-2")).toBe(false);
  });

  it("canInOrganization reads the per-organization privilege list", () => {
    mockAuth(
      makeUser({
        organization_privileges: {
          "org-1": ["org:member:manage", "org:settings:edit"],
          "org-2": ["org:member:manage"],
        },
      }),
    );
    const { result } = renderHook(() => useCapabilities());
    expect(result.current.canInOrganization("org-1", "org:settings:edit")).toBe(true);
    expect(result.current.canInOrganization("org-2", "org:settings:edit")).toBe(false);
    expect(result.current.canInOrganization("org-2", "org:member:manage")).toBe(true);
    expect(result.current.canInOrganization("org-3", "org:member:manage")).toBe(false);
  });

  it("treats missing permissions/organization_privileges as empty", () => {
    // Defensive: a frontend running against a backend that predates the
    // capability fields must not crash. The fields are typed required
    // but the hook falls back to empty when they are absent at runtime.
    const partial = {
      id: "u",
      email: "a@b.com",
      name: null,
      profile_picture_url: null,
      created_at: "2026-01-01T00:00:00Z",
      roles: ["developer"],
      organizations: [],
    } as unknown as User;
    mockAuth(partial);
    const { result } = renderHook(() => useCapabilities());
    expect(result.current.permissions.size).toBe(0);
    expect(result.current.isInOrganization("org-1")).toBe(false);
    // Roles still read correctly — that field has existed all along.
    expect(result.current.roles.has("developer")).toBe(true);
  });
});