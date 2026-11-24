import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import Docs from "./Docs";
import { matchDocsPath } from "./docsContent";
import { createQueryClient } from "./queryClient";
import "./style.css";
import "./workspace.css";
import "./docs.css";

const client = createQueryClient();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      {matchDocsPath(window.location.pathname) ? <Docs /> : <App />}
    </QueryClientProvider>
  </React.StrictMode>,
);
