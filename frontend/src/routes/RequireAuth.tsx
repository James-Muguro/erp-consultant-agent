import { Navigate, useLocation, useParams } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../context/useAuth";
import { useCapabilities } from "../auth/useCapabilities";
import { matchRouteConfig } from "./routeConfig";
import { NotAuthorizedState } from "./NotAuthorizedState";

/**
 * Gate for authenticated routes.
 *
 * Two independent checks, in order:
 *
 *   1. Authentication. Unauthenticated users are redirected to /login
 *      with the attempted path preserved. This behaviour is unchanged
 *      from the pre-Phase-2.2 version.
 *
 *   2. Authorization. The route's declared requirements are read from
 *      `routeConfig`, which is the same source of truth consumed by
 *      AppLayout (chrome) and Sidebar (navigation visibility). A route
 *      either declares an application capability (`requiredCapability`)
 *      or is organization-scoped (`organizationScoped`); the two are
 *      mutually exclusive.
 *
 * A failing authorization check renders a full-screen NotAuthorizedState
 * instead of the shell. The user was trying to reach a page they cannot
 * use; collapsing the chrome is the correct signal. The recovery link
 * returns them to `/`, which is ungated.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const capabilities = useCapabilities();
  const location = useLocation();
  const params = useParams<{ orgId?: string }>();

  if (!user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ returnTo: location.pathname + location.search }}
      />
    );
  }

  const routeConfig = matchRouteConfig(location.pathname);

  if (routeConfig?.organizationScoped) {
    const orgId = params.orgId;
    if (!orgId || !capabilities.isInOrganization(orgId)) {
      return (
        <NotAuthorizedState
          title="Organization not available"
          description="You are not a member of this organization, or it no longer exists."
        />
      );
    }
  } else if (
    routeConfig?.requiredCapability &&
    !capabilities.can(routeConfig.requiredCapability)
  ) {
    return (
      <NotAuthorizedState
        title="You don't have access to this section"
        description="Your account doesn't have the permissions required to view this page."
      />
    );
  }

  return <>{children}</>;
}