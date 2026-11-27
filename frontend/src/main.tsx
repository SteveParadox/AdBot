import { count, trafficSnapshot } from "./traffic";
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
const Research = React.lazy(() => import("./Research"));
Object.defineProperty(window, "adbotTraffic", {value: trafficSnapshot});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <React.Profiler id="workspace" onRender={(_id, _phase, duration) => {count("render_commits"); count("render_duration_ms_total", duration);}}>
        {matchDocsPath(window.location.pathname) ? <Docs /> :
          window.location.pathname.replace(/\/$/, "") === "/research" ? <React.Suspense fallback={<main role="status">Loading Web Research…</main>}><Research /></React.Suspense> : <App />}
      </React.Profiler>
    </QueryClientProvider>
  </React.StrictMode>,
);
