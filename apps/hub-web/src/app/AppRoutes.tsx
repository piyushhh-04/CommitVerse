import { Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { PlaceholderPage } from "../components/PlaceholderPage";
import { LoginPage } from "../pages/LoginPage";
import LandingPage from "../pages/LandingPage";
import { RegisterPage } from "../pages/RegisterPage";
import { NewRepositoryPage } from "../pages/NewRepositoryPage";
import { RepositoriesPage } from "../pages/RepositoriesPage";
import { RepositoryDetailRoute } from "../pages/RepositoryDetailPage";
import { OrganizationsPage } from "../pages/OrganizationsPage";
import { NewOrganizationPage } from "../pages/NewOrganizationPage";
import { OrganizationDetailPage } from "../pages/OrganizationDetailPage";
import { OrganizationRepositoriesPage } from "../pages/OrganizationRepositoriesPage";
import { NewOrganizationRepositoryPage } from "../pages/NewOrganizationRepositoryPage";
import { OrganizationRepositoryDetailPage } from "../pages/OrganizationRepositoryDetailPage";
import { ProfileSettingsPage } from "../pages/ProfileSettingsPage";
import { InvitationAcceptancePage } from "../pages/InvitationAcceptancePage";
import { AuthenticatedShell } from "./AuthenticatedShell";
import { WorkspaceDashboardPage } from "../pages/WorkspaceDashboardPage";
import {
  AuthenticatedRepositoryBrowserPage,
  PublicRepositoryPage,
} from "../pages/RepositoryBrowserPage";
import { RepositoryInvitationAcceptancePage } from "../pages/RepositoryInvitationAcceptancePage";

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
      <Route path="browse/:repositoryId" element={<PublicRepositoryPage />} />
      <Route element={<AuthenticationLayout />}>
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterPage />} />
        <Route path="app" element={<ProtectedRoute />}>
          <Route element={<AuthenticatedShell />}>
            <Route index element={<WorkspaceDashboardPage />} />
            <Route path="settings/profile" element={<ProfileSettingsPage />} />
            <Route path="invitations/accept" element={<InvitationAcceptancePage />} />
            <Route
              path="repositories/invitations/accept"
              element={<RepositoryInvitationAcceptancePage />}
            />
            <Route
              path="repository-browser/:repositoryId"
              element={<AuthenticatedRepositoryBrowserPage />}
            />
            <Route path="repositories" element={<RepositoriesPage />} />
            <Route path="repositories/new" element={<NewRepositoryPage />} />
            <Route path="repositories/:repositoryId" element={<RepositoryDetailRoute />} />
            <Route path="organizations" element={<OrganizationsPage />} />
            <Route path="organizations/new" element={<NewOrganizationPage />} />
            <Route path="organizations/:organizationId" element={<OrganizationDetailPage />} />
            <Route
              path="organizations/:organizationId/members"
              element={<OrganizationDetailPage />}
            />
            <Route
              path="organizations/:organizationId/repositories"
              element={<OrganizationRepositoriesPage />}
            />
            <Route
              path="organizations/:organizationId/repositories/new"
              element={<NewOrganizationRepositoryPage />}
            />
            <Route
              path="organizations/:organizationId/repositories/:repositoryId"
              element={<OrganizationRepositoryDetailPage />}
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
