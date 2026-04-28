/**
 * bundle-backend.mjs — copies the Python backend source into the extension
 * so it ships inside the .vsix.
 *
 * Layout inside the packaged extension:
 *   backend/
 *     samwise/          ← src/samwise/**
 *     pyproject.toml    ← root pyproject.toml (for dependency list)
 */

import { cpSync, mkdirSync, rmSync } from "node:fs";
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

// Copy pyproject.toml (pip needs it for dependency resolution)
cpSync(join(repoRoot, "pyproject.toml"), join(backendDest, "pyproject.toml"));

console.log("✓ Backend source bundled into extension/backend/");
