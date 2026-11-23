import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import Docs from "./Docs";
import { matchDocsPath } from "./docsContent";
import { ApiError } from "./api";
import "./style.css";
import "./workspace.css";
import "./docs.css";

const client = new QueryClient({
  defaultOptions: { queries: {
    refetchInterval: 30000,
    staleTime: 15000,
    refetchOnWindowFocus: false,
    retry: (attempt, error) => attempt < 1 && (!(error instanceof ApiError) || error.status >= 500),
  } },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      {matchDocsPath(window.location.pathname) ? <Docs /> : <App />}
    </QueryClientProvider>
  </React.StrictMode>,
);
