import { Component, type ErrorInfo, type ReactNode } from "react";

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("CommitVerse could not render this page.", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="repository-page repository-error-boundary" role="alert">
          <p className="eyebrow">CommitVerse / Unexpected error</p>
          <h1>We could not render this page.</h1>
          <p>Your session and saved work are unchanged. Reload the page to try again.</p>
          <button
            className="repository-primary-action"
            type="button"
            onClick={() => window.location.reload()}
          >
            Reload page
          </button>
        </main>
      );
    }

    return this.props.children;
  }
}
