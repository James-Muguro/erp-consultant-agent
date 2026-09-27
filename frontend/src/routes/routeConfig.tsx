import type { ReactNode } from "react";
import { matchPath } from "react-router-dom";
import type { Permission } from "../auth/capabilities";
import { ProjectListRoute } from "./ProjectListRoute";
import { ChatRoute } from "./ChatRoute";
import { WorkspaceRoute } from "./WorkspaceRoute";
import { SettingsPage } from "../pages/SettingsPage";
import { OrganizationDashboardPage } from "../pages/OrganizationDashboardPage";
import { ErpUserWorkspace } from "../pages/erp/ErpUserWorkspace";
import { RequireArtifactGrant } from "./RequireArtifactGrant";
import { OpportunityListPage } from "../pages/OpportunityListPage";
import { OpportunityWorkspacePage } from "../pages/OpportunityWorkspacePage";
import { CaseStudyPage } from "../pages/CaseStudyPage";

/**
 * Single source of truth for authenticated route metadata.
 *
 * `App.tsx` emits `<Route>` elements from this list; `AppLayout` reads
 * it to decide chrome; `RequireAuth` reads it to enforce access;
 * `Sidebar` reads it to decide which top-level navigation items to
 * show. There is exactly one source of truth — nothing outside this
 * file decides what a route requires.
 *
 * `requiredCapability` is an application-level permission (see
 * src/auth/permissions.py). It is evaluated against the caller's
 * delivered `permissions` set via `useCapabilities().can(...)`.
 *
 * `organizationScoped` marks a route whose access is governed by
 * organization membership rather than by an application permission.
 * RequireAuth reads the `orgId` path parameter and consults
 * `useCapabilities().isInOrganization(orgId)`. Application-role
 * capabilities are not consulted for these routes.
 *
 * Both fields are optional. A route with neither is available to any
 * authenticated user — used for `/` and `/settings`, which the backend
 * also serves without a capability requirement.
 */
export interface RouteConfig {
  path: string;
  element: ReactNode;
  /** True when this route sits inside a project workspace and should
   *  render the ProjectTabs bar via AppLayout. */
  hasWorkspace: boolean;
  /** Application permission required to reach the route. Undefined
   *  means "available to any authenticated user". */
  requiredCapability?: Permission;
  /** True when access is governed by organization membership rather
   *  than by application capability. */
  organizationScoped?: boolean;
}

/**
 * Order matters for `matchRouteConfig`, which returns the first
 * pattern that matches. More-specific patterns precede the more-general
 * ones they would otherwise be shadowed by.
 */
export const ROUTES: RouteConfig[] = [
  // `/` and `/settings` are intentionally ungated. They are shared
  // surfaces every authenticated user can reach; the backend does not
  // require a capability to serve them either.
  {
    path: "/",
    element: <ProjectListRoute />,
    hasWorkspace: false,
  },
  {
    path: "/settings",
    element: <SettingsPage />,
    hasWorkspace: false,
  },

  // Chat is gated on chat:submit. Every application role holds it; an
  // organization-only account (which holds no application role) does
  // not — the backend returns 403 for those callers on /api/chat.
  {
    path: "/chat",
    element: <ChatRoute mode="adhoc" />,
    hasWorkspace: false,
    requiredCapability: "chat:submit",
  },
  {
    path: "/chat/:sessionId",
    element: <ChatRoute mode="adhoc" />,
    hasWorkspace: false,
    requiredCapability: "chat:submit",
  },

  // Case-study view (Business Development). Standalone page rendered inside the
  // app shell but outside ProjectWorkspace. Gated on
  // opportunity:case_study_read (Business Development only), not phase:execute, so
  // the Business Development boundary stays clean. Placed before /p/:sessionId/:tab
  // so the specific pattern matches first.
  {
    path: "/p/:sessionId/case-study",
    element: <CaseStudyPage />,
    hasWorkspace: false,
    requiredCapability: "opportunity:case_study_read",
  },

  // Business Development opportunity surfaces.
  {
    path: "/opportunities",
    element: <OpportunityListPage />,
    hasWorkspace: false,
    requiredCapability: "opportunity:read",
  },
  {
    path: "/opportunities/:opportunityId",
    element: <OpportunityWorkspacePage />,
    hasWorkspace: false,
    requiredCapability: "opportunity:read",
  },
 
  // Workspace routes are gated on phase:execute. That capability is
  // the intersection of Functional Consultant and Developer
  // capabilities and excludes Business Development and ERP User. The backend does
  // not expose a dedicated workspace-entry capability; see the file
  // header in ProjectWorkspace.tsx for the rationale.
  //
  // The ERP User surface does NOT go through this gate. It lives under
  // the separate /erp/p/* prefix (see the ERP route block below), where
  // access is gated by per-artifact grants rather than by an
  // application capability.
  //
  // The more specific /p/:sessionId/chat precedes the generic
  // /p/:sessionId/:tab so first-match logic resolves project chat
  // correctly.
  {
    path: "/p/:sessionId/chat",
    element: <ChatRoute mode="project" />,
    hasWorkspace: true,
    requiredCapability: "phase:execute",
  },
  {
    path: "/p/:sessionId/:tab",
    element: <WorkspaceRoute />,
    hasWorkspace: true,
    requiredCapability: "phase:execute",
  },
  {
    path: "/p/:sessionId",
    element: <WorkspaceRoute />,
    hasWorkspace: true,
    requiredCapability: "phase:execute",
  },

  // ERP User artifact surface. A separate prefix from /p/* because
  // ERP Users do not hold phase:execute and must not see the
  // consultant workspace chrome (ProjectTabs, Issues, Solution
  // decisions, etc.).
  //
  // One route per artifact rather than a single dynamic
  // /erp/p/:sessionId/:artifact pattern, because RequireArtifactGrant
  // takes the required artifact as a static prop. Literal artifact
  // values also let the router distinguish an unknown artifact segment
  // from a known one without the wrapper having to inspect the URL.
  //
  // The bare /erp/p/:sessionId root passes artifact={null}: it is the
  // workspace entry and any active grant is sufficient.
  //
  // More-specific paths precede the bare root so first-match logic
  // resolves the artifact page correctly.
  {
    path: "/erp/p/:sessionId/questionnaire",
    element: (
      <RequireArtifactGrant artifact="requirements_questionnaire">
        <ErpUserWorkspace />
      </RequireArtifactGrant>
    ),
    hasWorkspace: false,
  },
  {
    path: "/erp/p/:sessionId/frd",
    element: (
      <RequireArtifactGrant artifact="frd">
        <ErpUserWorkspace />
      </RequireArtifactGrant>
    ),
    hasWorkspace: false,
  },
  {
    path: "/erp/p/:sessionId/uat-scenarios",
    element: (
      <RequireArtifactGrant artifact="uat_scenarios">
        <ErpUserWorkspace />
      </RequireArtifactGrant>
    ),
    hasWorkspace: false,
  },
  {
    path: "/erp/p/:sessionId/training-materials",
    element: (
      <RequireArtifactGrant artifact="training_materials">
        <ErpUserWorkspace />
      </RequireArtifactGrant>
    ),
    hasWorkspace: false,
  },
  {
    // Support is available to any ERP User with at least one active
    // artifact grant on the project. artifact={null} matches the
    // workspace root semantics: "any active grant is sufficient".
    // The backend re-checks "at least one grant" on the request
    // endpoints themselves (src/api/erp_user_api.py).
    path: "/erp/p/:sessionId/support",
    element: (
      <RequireArtifactGrant artifact={null}>
        <ErpUserWorkspace />
      </RequireArtifactGrant>
    ),
    hasWorkspace: false,
  },
  {
    path: "/erp/p/:sessionId",
    element: (
      <RequireArtifactGrant artifact={null}>
        <ErpUserWorkspace />
      </RequireArtifactGrant>
    ),
    hasWorkspace: false,
  },

  // Organization context. Access is checked against the caller's
  // membership in the org identified by the URL. No application
  // capability is required — an organization-only user without any
  // application role still reaches their organization dashboard.
  {
    path: "/org/:orgId",
    element: <OrganizationDashboardPage />,
    hasWorkspace: false,
    organizationScoped: true,
  },
];

/**
 * Return the route config whose path pattern matches `pathname`, or
 * null for an unmatched path (which the router itself redirects via
 * the `*` catch-all in App.tsx).
 */
export function matchRouteConfig(pathname: string): RouteConfig | null {
  for (const route of ROUTES) {
    if (matchPath(route.path, pathname)) return route;
  }
  return null;
}