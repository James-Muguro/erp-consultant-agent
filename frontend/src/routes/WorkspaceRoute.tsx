import { useParams } from "react-router-dom";
import { ProjectWorkspace } from "../components/workspace/ProjectWorkspace";

/**
 * Thin wrapper that extracts :sessionId from the URL and renders the
 * workspace.
 *
 * The workspace / chat tab bar is rendered by AppLayout, which owns
 * chrome for every authenticated route. This component deliberately
 * does not render it: chrome decisions belong to the route-config
 * source of truth, not to individual route components.
 */
export function WorkspaceRoute() {
  const { sessionId } = useParams<{ sessionId: string }>();
  if (!sessionId) return null;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ProjectWorkspace sessionId={sessionId} />
    </div>
  );
}