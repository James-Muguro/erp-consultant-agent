import { Navigate, useLocation, useParams } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../context/useAuth";
import { useArtifactGrants } from "../hooks/useArtifactGrants";
import { NotAuthorizedState } from "./NotAuthorizedState";

/**
 * Gate for /erp/p/:sessionId/:artifact routes.
 * Requires authenticated user + an active grant for the named artifact
 * OR (for the workspace root) at least one grant so a redirect can pick
 * a default.
 */
export function RequireArtifactGrant({
  artifact,
  children,
}: {
  artifact: string | null; // null = workspace root, any grant is fine
  children: ReactNode;
}) {
  const { user } = useAuth();
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const { grants, loading, error } = useArtifactGrants(sessionId);

  if (!user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ returnTo: location.pathname + location.search }}
      />
    );
  }
  if (!sessionId) {
    return (
      <NotAuthorizedState
        title="Project not available"
        description="This project either does not exist or you do not have access to it."
      />
    );
  }
  if (loading) {
    return <div className="p-6 text-sm text-ink-muted">Loading…</div>;
  }
  if (error || grants.length === 0) {
    return (
      <NotAuthorizedState
        title="Project not available"
        description="This project either does not exist or you do not have access to it."
      />
    );
  }
  if (artifact && !grants.some((g) => g.artifact_type === artifact)) {
    return (
      <NotAuthorizedState
        title="Artifact not available"
        description="You do not have access to this artifact on this project."
      />
    );
  }
  return <>{children}</>;
}