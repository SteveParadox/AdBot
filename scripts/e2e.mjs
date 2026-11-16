import { createServer } from "node:net";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const temp = mkdtempSync(join(tmpdir(), "adbot-e2e-"));
const python = join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const apiPort = process.env.ADBOT_E2E_API_PORT || "8000";
const frontendPort = process.env.ADBOT_E2E_FRONTEND_PORT || "5173";
const env = {
  ...process.env,
  ADBOT_E2E_BASE_URL: "http://127.0.0.1:" + frontendPort,
  ADBOT_API_PROXY_TARGET: "http://127.0.0.1:" + apiPort,
  ADBOT_API_KEYS: "e2e-local-key-000000000000000000000000",
  ADBOT_CONTENT_ADMIN_KEYS: "e2e-local-key-000000000000000000000000",
  ADBOT_DATABASE_URL: "sqlite:///" + join(temp, "e2e.db").replaceAll("\\", "/"),
  ADBOT_FIXTURE_MODE: "true",
  ADBOT_ARTIFACT_DIR: join(temp, "screenshots"),
  ADBOT_REDIS_URL: "",
  ADBOT_ENVIRONMENT: "development",
  ADBOT_RATE_PER_MINUTE: "10000",
  ADBOT_AUTHORIZED_DOMAINS: "",
  ADBOT_AI_PROVIDER: "local",
  ADBOT_AI_API_KEY: "fixture-only-not-a-live-provider-key",
  ADBOT_AI_FALLBACK_PROVIDER: "disabled",
  ADBOT_AI_MODEL: "fixture-model-not-live-llm",
  ADBOT_AI_BASE_URL: "http://127.0.0.1:8766/v1",
  ADBOT_AGENT_MAX_STEPS: "15",
  ADBOT_AGENT_MAX_TOKENS: "100000",
  ADBOT_USER_AGENT_ROTATABLE_SERVICES: "browser",
  ADBOT_USER_AGENT_FIXED_IDENTITIES: "{}",
  ADBOT_OUTBOUND_PROXY_ENABLED: "false",
  ADBOT_ENFORCE_HTTPS: "false",
  ADBOT_HSTS_ENABLED: "false",
};
const children = [];
let logs = "";
function start(command, args, cwd) {
  const child = spawn(command, args, {
    cwd,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  child.stdout.on("data", (b) => {
    logs = (logs + b).slice(-15000);
  });
  child.stderr.on("data", (b) => {
    logs = (logs + b).slice(-15000);
  });
  return child;
}
async function ready(url) {
  const deadline = Date.now() + Number(process.env.ADBOT_E2E_STARTUP_MS || 20000);
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("Service failed to become ready: " + url);
}
try {
  for (const port of [apiPort, frontendPort, "8765", "8766"]) {
    await new Promise((resolve, reject) => {
      const probe = createServer();
      probe.once("error", () => reject(new Error("E2E port is occupied: " + port)));
      probe.listen(Number(port), "127.0.0.1", () => probe.close(resolve));
    });
  }
  const migration = spawnSync(python, ["-m", "alembic", "upgrade", "head"], {
    cwd: join(root, "backend"),
    env,
    encoding: "utf8",
  });
  if (migration.status !== 0) throw new Error(migration.stderr);
  start(
    python,
    [
      "-m",
      "uvicorn",
      "app.fixture:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8765",
    ],
    join(root, "backend"),
  );
  start(
    python,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", apiPort, "--no-proxy-headers", "--no-server-header", "--no-access-log"],
    join(root, "backend"),
  );
  start(python, ["-m", "app.worker"], join(root, "backend"));
  start(python, ["-m", "app.scheduler"], join(root, "backend"));
  start(
    python,
    [
      "-m",
      "uvicorn",
      "testsupport.model_fixture:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8766",
    ],
    join(root, "backend"),
  );
  start(
    process.execPath,
    [
      join(root, "frontend/node_modules/vite/bin/vite.js"),
      "--host",
      "127.0.0.1",
      "--strictPort",
      "--port", frontendPort,
    ],
    join(root, "frontend"),
  );
  await Promise.all([
    ready("http://127.0.0.1:" + apiPort + "/api/ready"),
    ready("http://127.0.0.1:8765/"),
    ready("http://127.0.0.1:" + frontendPort + "/"),
    ready("http://127.0.0.1:8766/docs"),
  ]);
  const test = spawn(
    process.execPath,
    [join(root, "frontend/node_modules/@playwright/test/cli.js"), "test"],
    { cwd: join(root, "frontend"), env, stdio: "inherit" },
  );
  process.exitCode = await new Promise((resolve) =>
    test.on("exit", (code) => resolve(code ?? 1)),
  );
  if (process.exitCode) console.error(logs);
} catch (error) {
  console.error(error.message, logs);
  process.exitCode = 1;
} finally {
  for (const child of children) child.kill("SIGTERM");
  await Promise.all(
    children.map(
      (child) =>
        new Promise((resolve) => {
          const timer = setTimeout(() => {
            child.kill("SIGKILL");
            resolve();
          }, 5000);
          child.on("exit", () => {
            clearTimeout(timer);
            resolve();
          });
          if (child.exitCode !== null) {
            clearTimeout(timer);
            resolve();
          }
        }),
    ),
  );
}
