import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..", "..");
const repoRoot = path.resolve(frontendDir, "..");
const backendDir = path.resolve(repoRoot, "backend");
const runtimeRoot = path.resolve(os.tmpdir(), "novel-system-runtime-ops-e2e");
const databasePath = path.resolve(runtimeRoot, "novel-system-e2e.sqlite");
const vectorStoreDir = path.resolve(runtimeRoot, "vector-store");

rmSync(runtimeRoot, { recursive: true, force: true });
mkdirSync(vectorStoreDir, { recursive: true });

const backendEnv = {
  ...process.env,
  PYTHONPATH: path.resolve(backendDir, "src"),
  NOVEL_SYSTEM_DATABASE_URL: `sqlite:///${databasePath.replace(/\\/g, "/")}`,
  NOVEL_SYSTEM_CHROMA_DIR: vectorStoreDir,
  NOVEL_SYSTEM_VECTOR_BACKEND: "memory",
};

const seedResult = spawnSync(
  "python",
  [
    "-c",
    [
      "from novel_system.db.base import Base",
      "from novel_system.db.session import engine, reset_engine",
      "from novel_system.tools.seed_demo import seed_demo",
      "reset_engine()",
      "Base.metadata.create_all(bind=engine())",
      'seed_demo(fixture="all_e2e")',
    ].join("; "),
  ],
  {
    cwd: backendDir,
    env: backendEnv,
    stdio: "inherit",
  },
);

if (seedResult.status !== 0) {
  process.exit(seedResult.status ?? 1);
}

const server = spawn(
  "python",
  [
    "-m",
    "uvicorn",
    "novel_system.api.app:create_app",
    "--factory",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
  ],
  {
    cwd: backendDir,
    env: backendEnv,
    stdio: "inherit",
  },
);

const shutdown = (signal) => {
  if (!server.killed) {
    server.kill(signal);
  }
};

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

server.on("exit", (code) => {
  process.exit(code ?? 0);
});
