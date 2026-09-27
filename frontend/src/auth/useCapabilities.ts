import { useMemo } from "react";
import { useAuth } from "../context/useAuth";
import type {
  OrganizationPrivilege,
  Permission,
  UserRole,
} from "./capabilities";

/**
 * Central capability evaluation hook.
 *
 * Reads the caller's capability context from AuthContext and exposes
 * it as a small, typed interface. The effective permission set and
 * per-organization privileges are computed by the backend and delivered
 * on the /me payload; this hook does not translate roles into
 * permissions itself. That keeps the mapping in exactly one place
 * (src/auth/permissions.py) and prevents the frontend from drifting.
 *
 * Missing fields are treated as empty. A frontend running against a
 * backend that predates the capability fields still works — it simply
 * sees no capabilities until the backend is redeployed.
 */
export interface Capabilities {
  /** Application roles the caller holds, as an opaque set. */
  roles: ReadonlySet<UserRole>;
  /** Effective application permissions the caller has been granted. */
  permissions: ReadonlySet<Permission>;
  /** True when the caller holds the given application permission. */
  can: (permission: Permission) => boolean;
  /** True when the caller is a member of the given organization. */
  isInOrganization: (organizationId: string) => boolean;
  /** True when the caller holds the given privilege in the given org. */
  canInOrganization: (
    organizationId: string,
    privilege: OrganizationPrivilege,
  ) => boolean;
}

export function useCapabilities(): Capabilities {
  const { user } = useAuth();

  return useMemo(() => {
    const roles = new Set<UserRole>((user?.roles ?? []) as UserRole[]);
    const permissions = new Set<Permission>(
      (user?.permissions ?? []) as Permission[],
    );

    const orgPrivileges: Record<string, ReadonlySet<OrganizationPrivilege>> = {};
    for (const [orgId, list] of Object.entries(
      user?.organization_privileges ?? {},
    )) {
      orgPrivileges[orgId] = new Set<OrganizationPrivilege>(
        list as OrganizationPrivilege[],
      );
    }

    return {
      roles,
      permissions,
      can: (permission) => permissions.has(permission),
      isInOrganization: (organizationId) => organizationId in orgPrivileges,
      canInOrganization: (organizationId, privilege) =>
        orgPrivileges[organizationId]?.has(privilege) ?? false,
    };
  }, [user]);
}