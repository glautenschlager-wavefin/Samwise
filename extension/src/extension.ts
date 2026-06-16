import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import { BackendManager } from "./backend-manager.js";
import { createChatHandler } from "./chat-handler.js";
import { buildBackendEnv, hasMinimalCredentials, setGithubToken, setJiraToken } from "./credentials.js";
import { EventMonitor } from "./event-monitor.js";

import { SidebarProvider } from "./sidebar-provider.js";

let statusBarItem: vscode.StatusBarItem;
let refreshInterval: ReturnType<typeof setInterval> | undefined;
let backendManager: BackendManager | undefined;

type NotificationLevel = "off" | "errors-only" | "important" | "all";

const notificationLastShownAt = new Map<string, number>();

function getNotificationLevel(): NotificationLevel {
  return vscode.workspace
    .getConfiguration("samwise")
    .get<NotificationLevel>("notifications.level", "important");
}

function shouldShowToast(
  level: NotificationLevel,
  severity: "info" | "warning" | "error",
  important = false,
): boolean {
  if (severity === "error") {
    return level !== "off";
  }

  if (severity === "warning") {
    if (level === "all") {
      return true;
    }
    if (level === "important" && important) {
      return true;
    }
    return false;
  }

  if (level === "all") {
    return true;
  }
  if (level === "important" && important) {
    return true;
  }
  return false;
}

function shouldRateLimit(key: string, throttleMs: number): boolean {
  const now = Date.now();
  const last = notificationLastShownAt.get(key);
  if (typeof last === "number" && now - last < throttleMs) {
    return true;
  }
  notificationLastShownAt.set(key, now);
  return false;
}

export function activate(context: vscode.ExtensionContext): void {
  const client = new BackendClient();
  const notificationChannel = vscode.window.createOutputChannel("Samwise");
  context.subscriptions.push(notificationChannel);

  const logNotification = (severity: "info" | "warning" | "error", message: string): void => {
    notificationChannel.appendLine(`${new Date().toISOString()} [${severity.toUpperCase()}] ${message}`);
  };

  const notifyInfo = (
    message: string,
    options?: { important?: boolean; statusBarMs?: number; throttleKey?: string; throttleMs?: number },
  ): void => {
    const throttleKey = options?.throttleKey;
    const throttleMs = options?.throttleMs ?? 60_000;
    if (throttleKey && shouldRateLimit(throttleKey, throttleMs)) {
      return;
    }

    logNotification("info", message);
    if (options?.statusBarMs) {
      vscode.window.setStatusBarMessage(`Samwise: ${message}`, options.statusBarMs);
    }

    if (shouldShowToast(getNotificationLevel(), "info", options?.important ?? false)) {
      void vscode.window.showInformationMessage(`Samwise: ${message}`);
    }
  };

  const notifyWarning = (
    message: string,
    options?: { important?: boolean; statusBarMs?: number; throttleKey?: string; throttleMs?: number },
  ): void => {
    const throttleKey = options?.throttleKey;
    const throttleMs = options?.throttleMs ?? 60_000;
    if (throttleKey && shouldRateLimit(throttleKey, throttleMs)) {
      return;
    }

    logNotification("warning", message);
    if (options?.statusBarMs) {
      vscode.window.setStatusBarMessage(`Samwise: ${message}`, options.statusBarMs);
    }

    if (shouldShowToast(getNotificationLevel(), "warning", options?.important ?? false)) {
      void vscode.window.showWarningMessage(`Samwise: ${message}`);
    }
  };

  const notifyError = (
    message: string,
    options?: { statusBarMs?: number; throttleKey?: string; throttleMs?: number },
  ): void => {
    const throttleKey = options?.throttleKey;
    const throttleMs = options?.throttleMs ?? 60_000;
    if (throttleKey && shouldRateLimit(throttleKey, throttleMs)) {
      return;
    }

    logNotification("error", message);
    if (options?.statusBarMs) {
      vscode.window.setStatusBarMessage(`Samwise: ${message}`, options.statusBarMs);
    }

    if (shouldShowToast(getNotificationLevel(), "error", true)) {
      void vscode.window.showErrorMessage(`Samwise: ${message}`);
    }
  };

  // --- Sidebar ---
  const sidebarProvider = new SidebarProvider(context.extensionUri, client);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(SidebarProvider.viewId, sidebarProvider),
  );

  // --- Status Bar ---
  statusBarItem = vscode.window.createStatusBarItem(
    "samwise.status",
    vscode.StatusBarAlignment.Right,
    100,
  );
  statusBarItem.text = "$(rocket) Samwise";
  statusBarItem.tooltip = "Samwise — starting…";
  statusBarItem.command = "samwise.openPanel";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // --- Chat Participant ---
  const chatParticipant = vscode.chat.createChatParticipant(
    "samwise.chat",
    createChatHandler(client),
  );
  chatParticipant.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "icon.svg");
  context.subscriptions.push(chatParticipant);

  // --- Commands ---
  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.openPanel", () => {
      void vscode.commands.executeCommand("samwise.activityFeed.focus");
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.refreshFeed", () => {
      void sidebarProvider.refresh();
      notifyInfo("Activity feed refreshed", {
        statusBarMs: 2_500,
        throttleKey: "refresh-feed",
        throttleMs: 5_000,
      });
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.showSummary", async () => {
      const live = await client.fetchStatus();
      if (live) {
        notifyInfo(live.text.replace("$(rocket) ", ""), { important: true, statusBarMs: 6_000 });
      } else {
        notifyWarning("Backend is not running.", { important: true, statusBarMs: 6_000 });
      }
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.showBackendLog", () => {
      backendManager?.outputChannel.show();
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.setGithubToken", async () => {
      const stored = await setGithubToken(context.secrets);
      if (stored) {
        notifyInfo("GitHub token saved. Restart Samwise to apply.", {
          important: true,
          statusBarMs: 8_000,
        });
      }
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.setJiraToken", async () => {
      const stored = await setJiraToken(context.secrets);
      if (stored) {
        notifyInfo("Jira API token saved. Restart Samwise to apply.", {
          important: true,
          statusBarMs: 8_000,
        });
      }
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.authenticateGoogle", async () => {
      try {
        const authUrl = await client.startGoogleAuth();
        if (!authUrl) {
          notifyError("Failed to start Google auth.", { statusBarMs: 8_000 });
          return;
        }

        await vscode.env.openExternal(vscode.Uri.parse(authUrl));
        notifyInfo("Complete Google sign-in in your browser...", {
          important: true,
          statusBarMs: 10_000,
        });

        // Poll for completion (up to 2 minutes, every 3 seconds)
        for (let i = 0; i < 40; i++) {
          await new Promise((r) => setTimeout(r, 3_000));
          const done = await client.isGoogleAuthenticated();
          if (done) {
            notifyInfo("Google Calendar connected. Events will appear on the next poll cycle.", {
              important: true,
              statusBarMs: 8_000,
            });
            return;
          }
        }

        notifyWarning("Google auth timed out. Try running the command again.", {
          important: true,
          statusBarMs: 8_000,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        notifyError(`Google auth failed: ${msg}`, { statusBarMs: 10_000 });
      }
    }),
  );

  // --- Periodic Refresh ---
  const updateStatusBar = async (): Promise<void> => {
    const live = await client.fetchStatus();
    if (live) {
      statusBarItem.text = live.text;
      statusBarItem.tooltip = live.tooltip;
    }
    void sidebarProvider.refresh();
  };

  refreshInterval = setInterval(() => void updateStatusBar(), 60_000);

  // --- SSE helper (called once backend is ready) ---
  const eventMonitor = new EventMonitor(client);
  context.subscriptions.push(eventMonitor);

  const connectSse = (): void => {
    // Start the event monitor to send VS Code events to the backend.
    eventMonitor.activate(context);

    client.subscribeEvents((item) => {
      void sidebarProvider.refresh();
      void updateStatusBar();

      if (item.urgency === "high") {
        const message = item.title;
        logNotification("warning", `High urgency event: ${message}`);

        if (shouldRateLimit(`high-urgency:${message}`, 60_000)) {
          return;
        }

        vscode.window.setStatusBarMessage(`Samwise: ${message}`, 8_000);

        if (shouldShowToast(getNotificationLevel(), "warning", true)) {
          void vscode.window
            .showWarningMessage(`Samwise: ${message}`, "Open Feed")
            .then((choice) => {
              if (choice === "Open Feed") {
                void vscode.commands.executeCommand("samwise.activityFeed.focus");
              }
            });
        }
      }
    });
  };

  // --- Backend Auto-Lifecycle ---
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

  // Try to auto-start the backend if we're in the Samwise workspace.
  // Otherwise, fall back to connecting to an already-running backend.
  const startBackend = async (): Promise<void> => {
    if (!workspaceFolder) {
      // No workspace — just try connecting to an existing backend
      void updateStatusBar();
      connectSse();
      return;
    }

    try {
      backendManager = new BackendManager(
        workspaceFolder,
        context.extensionUri,
        context.globalStorageUri,
      );
      context.subscriptions.push(backendManager);

      statusBarItem.text = "$(loading~spin) Samwise: starting...";

      // Build env vars from VS Code settings + SecretStorage
      const credEnv = await buildBackendEnv(context.secrets);
      await backendManager.start(credEnv);

      client.setBaseUrl(backendManager.baseUrl);
      void updateStatusBar();
      connectSse();

      notifyInfo(`Backend running on port ${backendManager.port}`, {
        statusBarMs: 5_000,
        throttleKey: "backend-started",
        throttleMs: 10_000,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      backendManager?.outputChannel.appendLine(`Startup failed: ${msg}`);

      // Fall back to trying an already-running backend
      statusBarItem.text = "$(warning) Samwise: backend failed";
      logNotification("warning", `Backend failed to start: ${msg}`);
      vscode.window.setStatusBarMessage("Samwise: backend failed to start. See logs for details.", 10_000);

      if (shouldShowToast(getNotificationLevel(), "warning", true)) {
        void vscode.window
          .showWarningMessage(
            `Samwise backend failed to start: ${msg}`,
            "Show Log",
            "Retry",
          )
          .then((choice) => {
            if (choice === "Show Log") {
              backendManager?.outputChannel.show();
            } else if (choice === "Retry") {
              void startBackend();
            }
          });
      }

      // Still try connecting in case user starts it manually
      void updateStatusBar();
      connectSse();
    }
  };

  // --- First-run setup wizard ---
  const maybeShowSetupWizard = async (): Promise<void> => {
    const hasCredentials = await hasMinimalCredentials(context.secrets);
    if (hasCredentials) {
      return;
    }

    const choice = await vscode.window.showInformationMessage(
      "Welcome to Samwise! Set up your GitHub token to get started.",
      "Set GitHub Token",
      "Open Settings",
      "Later",
    );

    if (choice === "Set GitHub Token") {
      await setGithubToken(context.secrets);
    } else if (choice === "Open Settings") {
      void vscode.commands.executeCommand(
        "workbench.action.openSettings",
        "samwise",
      );
    }
  };

  void maybeShowSetupWizard().then(() => startBackend());
}

export async function deactivate(): Promise<void> {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = undefined;
  }
  if (backendManager) {
    await backendManager.stop();
  }
}
