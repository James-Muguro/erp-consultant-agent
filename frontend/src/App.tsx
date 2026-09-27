import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./context/useAuth";
import { LoginPage } from "./pages/LoginPage";
import { MfaPage } from "./pages/MfaPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { RequireAuth } from "./routes/RequireAuth";
import { AppLayout } from "./routes/AppLayout";
import { ROUTES } from "./routes/routeConfig";

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
      {/* Public authentication routes. Any of these redirects to the
          authenticated home if the user is already signed in. */}
      <Route
        path="/login"
        element={user ? <Navigate to="/" replace /> : <LoginPage />}
      />
      <Route
        path="/mfa"
        element={user ? <Navigate to="/" replace /> : <MfaPage />}
      />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />

      {/* Authenticated routes. Route definitions come from
          routeConfig.tsx, which is also the source of truth consulted
          by AppLayout (chrome) and RequireAuth (access). */}
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        {ROUTES.map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}