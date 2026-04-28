/**
 * BackendManager — spawns, monitors, and shuts down the Python backend.
 *
 * Lifecycle:
 *   1. Detect Python 3.12+
 *   2. Ensure a venv exists (packaged mode) or use Poetry (dev mode)
 *   3. Spawn the backend process
 *   4. Parse `SAMWISE_PORT=<port>` from stdout to discover the bound port
 *   5. Poll /api/health until the backend is ready
 *   6. Pipe all output to a VS Code Output Channel
 *   7. On dispose, SIGTERM → grace period → SIGKILL
 */

import { existsSync } from "node:fs";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import * as vscode from "vscode";

/** Minimum Python version required. */
const MIN_PYTHON_MAJOR = 3;
const MIN_PYTHON_MINOR = 12;

/** How long (ms) to wait for the backend to report its port. */
const PORT_TIMEOUT_MS = 15_000;

/** Health-check: max attempts and base delay. */
const HEALTH_MAX_ATTEMPTS = 20;
const HEALTH_BASE_DELAY_MS = 300;

/** Grace period before SIGKILL on shutdown. */
const SHUTDOWN_GRACE_MS = 4_000;

export class BackendManager implements vscode.Disposable {
  private _process: ChildProcess | null = null;
  private _port: number | null = null;
  private _outputChannel: vscode.OutputChannel;
  private _disposed = false;

  /** Path to the bundled backend/ dir (exists only in packaged .vsix mode). */
  private readonly _bundledBackendDir: string;

  /** Whether we're running from a packaged .vsix (vs. dev mode with Poetry). */
  private readonly _isPackaged: boolean;

  /** Directory for the auto-managed venv (inside globalStorageUri). */
  private readonly _venvDir: string;

  constructor(
    private readonly _workspaceRoot: string,
    extensionUri: vscode.Uri,
    globalStorageUri: vscode.Uri,
  ) {
    this._outputChannel = vscode.window.createOutputChannel("Samwise Backend");
    this._bundledBackendDir = join(extensionUri.fsPath, "backend");
    this._isPackaged = existsSync(this._bundledBackendDir);
    this._venvDir = join(globalStorageUri.fsPath, "venv");
  }

  /** The port the backend is listening on (null until ready). */
  get port(): number | null {
    return this._port;
  }

  get baseUrl(): string {
    return `http://127.0.0.1:${this._port ?? 9474}`;
  }

  get outputChannel(): vscode.OutputChannel {
    return this._outputChannel;
  }

  // -----------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------

  /**
   * Start the backend.  Resolves when /api/health returns 200.
   * Throws on Python-not-found, spawn failure, or timeout.
   */
  async start(env?: Record<string, string>): Promise<void> {
    await this._ensurePython();
    if (this._isPackaged) {
      await this._ensureVenv();
    }
    this._port = await this._spawnAndWaitForPort(env);
    this._outputChannel.appendLine(`Backend bound to port ${this._port}`);
    await this._waitForHealthy();
    this._outputChannel.appendLine("Backend is healthy — ready to go.");
  }

  /** Gracefully stop the backend process. */
  async stop(): Promise<void> {
    const proc = this._process;
    if (!proc || proc.exitCode !== null) {
      return;
    }

    this._outputChannel.appendLine("Stopping backend...");

    return new Promise<void>((resolve) => {
      const killTimer = setTimeout(() => {
        proc.kill("SIGKILL");
      }, SHUTDOWN_GRACE_MS);

      proc.once("exit", () => {
        clearTimeout(killTimer);
        resolve();
      });

      proc.kill("SIGTERM");
    });
  }

  dispose(): void {
    if (this._disposed) {
      return;
    }
    this._disposed = true;
    const proc = this._process;
    if (proc && proc.exitCode === null) {
      proc.kill("SIGTERM");
      setTimeout(() => {
        if (proc.exitCode === null) {
          proc.kill("SIGKILL");
        }
      }, SHUTDOWN_GRACE_MS);
    }
    this._outputChannel.dispose();
  }

  // -----------------------------------------------------------------
  // Python detection
  // -----------------------------------------------------------------

  private async _ensurePython(): Promise<void> {
    const version = await this._getPythonVersion();
    if (!version) {
      const action = await vscode.window.showErrorMessage(
        "Samwise requires Python 3.12+ but it was not found on your PATH.",
        "Install Python",
      );
      if (action === "Install Python") {
        void vscode.env.openExternal(vscode.Uri.parse("https://www.python.org/downloads/"));
      }
      throw new Error("Python 3.12+ not found");
    }

    const [major, minor] = version;
    if (major < MIN_PYTHON_MAJOR || (major === MIN_PYTHON_MAJOR && minor < MIN_PYTHON_MINOR)) {
      const action = await vscode.window.showErrorMessage(
        `Samwise requires Python 3.12+ but found ${major}.${minor}.`,
        "Install Python",
      );
      if (action === "Install Python") {
        void vscode.env.openExternal(vscode.Uri.parse("https://www.python.org/downloads/"));
      }
      throw new Error(`Python ${major}.${minor} is too old (need 3.12+)`);
    }

    this._outputChannel.appendLine(`Found Python ${major}.${minor}`);
  }

  private _getPythonVersion(): Promise<[number, number] | null> {
    return new Promise((resolve) => {
      const proc = spawn("python3", ["--version"], { stdio: ["ignore", "pipe", "pipe"] });
      let out = "";
      proc.stdout.on("data", (d: Buffer) => {
        out += d.toString();
      });
      proc.on("error", () => resolve(null));
      proc.on("exit", (code) => {
        if (code !== 0) {
          resolve(null);
          return;
        }
        // "Python 3.12.5"
        const match = out.match(/Python (\d+)\.(\d+)/);
        if (match) {
          resolve([parseInt(match[1], 10), parseInt(match[2], 10)]);
        } else {
          resolve(null);
        }
      });
    });
  }

  // -----------------------------------------------------------------
  // Spawn + port discovery
  // -----------------------------------------------------------------

  private _spawnAndWaitForPort(env?: Record<string, string>): Promise<number> {
    return new Promise<number>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error("Timed out waiting for backend to report its port"));
      }, PORT_TIMEOUT_MS);

      let proc: ChildProcess;

      if (this._isPackaged) {
        // Packaged mode: run from the venv with bundled source on PYTHONPATH
        const venvPython = join(this._venvDir, "bin", "python3");
        proc = spawn(venvPython, ["-m", "samwise.server"], {
          cwd: this._bundledBackendDir,
          env: {
            ...process.env,
            ...env,
            PYTHONPATH: this._bundledBackendDir,
          },
          stdio: ["ignore", "pipe", "pipe"],
        });
      } else {
        // Dev mode: use Poetry
        proc = spawn("poetry", ["run", "samwise"], {
          cwd: this._workspaceRoot,
          env: { ...process.env, ...env },
          stdio: ["ignore", "pipe", "pipe"],
        });
      }

      this._process = proc;
      let portFound = false;

      proc.stdout!.on("data", (data: Buffer) => {
        const text = data.toString();
        this._outputChannel.append(text);

        if (!portFound) {
          const match = text.match(/SAMWISE_PORT=(\d+)/);
          if (match) {
            portFound = true;
            clearTimeout(timer);
            resolve(parseInt(match[1], 10));
          }
        }
      });

      proc.stderr!.on("data", (data: Buffer) => {
        this._outputChannel.append(data.toString());
      });

      proc.on("error", (err) => {
        clearTimeout(timer);
        reject(new Error(`Failed to spawn backend: ${err.message}`));
      });

      proc.on("exit", (code) => {
        if (!portFound) {
          clearTimeout(timer);
          reject(new Error(`Backend exited with code ${code} before reporting port`));
        } else {
          this._outputChannel.appendLine(`Backend exited with code ${code}`);
        }
      });
    });
  }

  // -----------------------------------------------------------------
  // Venv provisioning (packaged mode only)
  // -----------------------------------------------------------------

  private async _ensureVenv(): Promise<void> {
    const venvPython = join(this._venvDir, "bin", "python3");

    if (existsSync(venvPython)) {
      this._outputChannel.appendLine("Venv exists — checking dependencies...");
      await this._pipInstall();
      return;
    }

    this._outputChannel.appendLine("Creating venv...");
    await this._runCommand("python3", ["-m", "venv", this._venvDir]);
    this._outputChannel.appendLine("Installing dependencies...");
    await this._pipInstall();
  }

  private async _pipInstall(): Promise<void> {
    const venvPip = join(this._venvDir, "bin", "pip");
    // Install the project from the bundled backend directory (contains pyproject.toml).
    // --quiet to reduce noise; errors still surface on stderr.
    await this._runCommand(venvPip, ["install", "--quiet", this._bundledBackendDir]);
  }

  /**
   * Run a command and pipe output to the output channel.
   * Rejects if the process exits non-zero.
   */
  private _runCommand(cmd: string, args: string[]): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const proc = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
      proc.stdout.on("data", (d: Buffer) => this._outputChannel.append(d.toString()));
      proc.stderr.on("data", (d: Buffer) => this._outputChannel.append(d.toString()));
      proc.on("error", (err) => reject(new Error(`Failed to run ${cmd}: ${err.message}`)));
      proc.on("exit", (code) => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(`${cmd} exited with code ${code}`));
        }
      });
    });
  }

  // -----------------------------------------------------------------
  // Health check with retry
  // -----------------------------------------------------------------

  private async _waitForHealthy(): Promise<void> {
    for (let attempt = 0; attempt < HEALTH_MAX_ATTEMPTS; attempt++) {
      try {
        const resp = await fetch(`${this.baseUrl}/api/health`);
        if (resp.ok) {
          return;
        }
      } catch {
        // not ready yet
      }
      const delay = HEALTH_BASE_DELAY_MS * Math.min(2 ** attempt, 16);
      await new Promise((r) => setTimeout(r, delay));
    }
    throw new Error("Backend failed to become healthy");
  }
}
