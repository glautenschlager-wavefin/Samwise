/**
 * bundle-backend.mjs — copies the Python backend source into the extension
 * so it ships inside the .vsix.
 *
 * Layout inside the packaged extension:
 *   backend/
 *     samwise/           ← src/samwise/**
 *     requirements.txt   ← generated from pyproject.toml dependencies
 */

import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const extRoot = join(__dirname, "..");
const repoRoot = join(extRoot, "..");
const backendDest = join(extRoot, "backend");

// Clean previous bundle
rmSync(backendDest, { recursive: true, force: true });
mkdirSync(backendDest, { recursive: true });

// Copy Python source
cpSync(join(repoRoot, "src", "samwise"), join(backendDest, "samwise"), {
  recursive: true,
  filter: (src) => !src.includes("__pycache__"),
});

// Generate requirements.txt from pyproject.toml [tool.poetry.dependencies]
const toml = readFileSync(join(repoRoot, "pyproject.toml"), "utf-8");
const depsMatch = toml.match(/\[tool\.poetry\.dependencies\]\n([\s\S]*?)(?:\n\[|$)/);
if (!depsMatch) {
  console.error("Could not find [tool.poetry.dependencies] in pyproject.toml");
  process.exit(1);
}

const lines = depsMatch[1].trim().split("\n");
const reqs = [];
for (const line of lines) {
  // Skip python itself
  if (line.startsWith("python")) continue;
  // "fastapi = "^0.115.0""  →  fastapi>=0.115.0
  const simple = line.match(/^(\S+)\s*=\s*"[\^~]?([^"]+)"/);
  if (simple) {
    reqs.push(`${simple[1]}>=${simple[2]}`);
    continue;
  }
  // "uvicorn = { version = "^0.34.0", extras = ["standard"] }"  →  uvicorn[standard]>=0.34.0
  const table = line.match(/^(\S+)\s*=\s*\{.*version\s*=\s*"[\^~]?([^"]+)"(?:.*extras\s*=\s*\[([^\]]+)\])?/);
  if (table) {
    const extras = table[3] ? `[${table[3].replace(/"/g, "").replace(/\s/g, "")}]` : "";
    reqs.push(`${table[1]}${extras}>=${table[2]}`);
  }
}

writeFileSync(join(backendDest, "requirements.txt"), reqs.join("\n") + "\n");
console.log(`✓ Backend source bundled into extension/backend/ (${reqs.length} deps)`);
