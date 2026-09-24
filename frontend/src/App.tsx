import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/useAuth";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RequireAuth } from "./routes/RequireAuth";
import { AppLayout } from "./routes/AppLayout";
import { ProjectListRoute } from "./routes/ProjectListRoute";
import { ChatRoute } from "./routes/ChatRoute";
import { WorkspaceRoute } from "./routes/WorkspaceRoute";

export default function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper text-sm text-ink-faint">
        Loading…
      </div>
    );
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <Navigate to="/" replace /> : <LoginPage />}
      />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<ProjectListRoute />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/chat" element={<ChatRoute mode="adhoc" />} />
        <Route path="/chat/:sessionId" element={<ChatRoute mode="adhoc" />} />
        <Route path="/p/:sessionId" element={<WorkspaceRoute />} />
        <Route path="/p/:sessionId/:tab" element={<WorkspaceRoute />} />
        <Route path="/p/:sessionId/chat" element={<ChatRoute mode="project" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}