import { Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { PlaceholderPage } from "../components/PlaceholderPage";
import { LoginPage } from "../pages/LoginPage";
import LandingPage from "../pages/LandingPage";
import { RegisterPage } from "../pages/RegisterPage";
import { AuthenticatedShell } from "./AuthenticatedShell";

function AuthenticationLayout() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route element={<AuthenticationLayout />}>
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="app" element={<ProtectedRoute />}>
          <Route element={<AuthenticatedShell />}>
            <Route
              index
              element={
                <PlaceholderPage
                  eyebrow="CommitVerse Hub"
                  title="Your workspace"
                  description="Your authenticated dashboard will be built in a later milestone."
                />
              }
            />
            <Route
              path="repositories"
              element={
                <PlaceholderPage
                  eyebrow="Personal repositories"
                  title="Repositories"
                  description="Repository management will be built in a later milestone."
                />
              }
            />
            <Route
              path="repositories/new"
              element={
                <PlaceholderPage
                  eyebrow="Personal repositories"
                  title="New repository"
                  description="Repository creation will be built in a later milestone."
                />
              }
            />
            <Route
              path="repositories/:repositoryId"
              element={
                <PlaceholderPage
                  eyebrow="Personal repositories"
                  title="Repository details"
                  description="Repository details will be built in a later milestone."
                />
              }
            />
            <Route
              path="organizations"
              element={
                <PlaceholderPage
                  eyebrow="Organizations"
                  title="Organizations"
                  description="Organization management will be built in a later milestone."
                />
              }
            />
            <Route
              path="organizations/new"
              element={
                <PlaceholderPage
                  eyebrow="Organizations"
                  title="New organization"
                  description="Organization creation will be built in a later milestone."
                />
              }
            />
            <Route
              path="organizations/:organizationId"
              element={
                <PlaceholderPage
                  eyebrow="Organizations"
                  title="Organization details"
                  description="Organization details will be built in a later milestone."
                />
              }
            />
            <Route
              path="organizations/:organizationId/members"
              element={
                <PlaceholderPage
                  eyebrow="Organization members"
                  title="Membership"
                  description="Organization membership management will be built in a later milestone."
                />
              }
            />
          </Route>
        </Route>
      </Route>
      <Route
        path="*"
        element={
          <PlaceholderPage
            eyebrow="Not found"
            title="Page not found"
            description="The page you requested does not exist."
          />
        }
      />
    </Routes>
  );
}
