import { useParams } from "react-router-dom";
import { ProjectWorkspace } from "../components/workspace/ProjectWorkspace";
import { ProjectTabs } from "./ProjectTabs";

/**
 * Thin wrapper that extracts :sessionId from the URL and renders the
 * workspace. The tab is read inside ProjectWorkspace from its own URL
 * segment, so this route does not need to know about tabs.
 */
export function WorkspaceRoute() {
  const { sessionId } = useParams<{ sessionId: string }>();
  if (!sessionId) return null;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ProjectTabs sessionId={sessionId} />
      <ProjectWorkspace sessionId={sessionId} />
    </div>
  );
}