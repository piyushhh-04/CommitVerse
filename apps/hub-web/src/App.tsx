import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { AppRoutes } from "./app/AppRoutes";
import { AppErrorBoundary } from "./app/AppErrorBoundary";
import { queryClient } from "./app/queryClient";
import { ThemeProvider } from "./theme/ThemeProvider";

function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppErrorBoundary>
            <AppRoutes />
          </AppErrorBoundary>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
