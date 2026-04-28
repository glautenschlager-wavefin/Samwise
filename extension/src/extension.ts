import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import { BackendManager } from "./backend-manager.js";
import { createChatHandler } from "./chat-handler.js";
import { buildBackendEnv, hasMinimalCredentials, setGithubToken, setJiraToken } from "./credentials.js";
import { getStatusBarSummary } from "./mock-data.js";
import { SidebarProvider } from "./sidebar-provider.js";

let statusBarItem: vscode.StatusBarItem;
let refreshInterval: ReturnType<typeof setInterval> | undefined;
let backendManager: BackendManager | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const client = new BackendClient();

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
  const summary = getStatusBarSummary();
  statusBarItem.text = summary.text;
  statusBarItem.tooltip = summary.tooltip;
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
      void vscode.window.showInformationMessage("Samwise: Activity feed refreshed");
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.showSummary", async () => {
      const live = await client.fetchStatus();
      const s = live ?? getStatusBarSummary();
      void vscode.window.showInformationMessage(s.text.replace("$(rocket) ", ""));
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
        void vscode.window.showInformationMessage("GitHub token saved. Restart Samwise to apply.");
      }
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.setJiraToken", async () => {
      const stored = await setJiraToken(context.secrets);
      if (stored) {
        void vscode.window.showInformationMessage("Jira API token saved. Restart Samwise to apply.");
      }
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.authenticateGoogle", async () => {
      try {
        const authUrl = await client.startGoogleAuth();
        if (!authUrl) {
          void vscode.window.showErrorMessage("Samwise: Failed to start Google auth.");
          return;
        }

        await vscode.env.openExternal(vscode.Uri.parse(authUrl));
        void vscode.window.showInformationMessage(
          "Samwise: Complete Google sign-in in your browser…",
        );

        // Poll for completion (up to 2 minutes, every 3 seconds)
        for (let i = 0; i < 40; i++) {
          await new Promise((r) => setTimeout(r, 3_000));
          const done = await client.isGoogleAuthenticated();
          if (done) {
            void vscode.window.showInformationMessage(
              "Samwise: Google Calendar connected! Events will appear on the next poll cycle.",
            );
            return;
          }
        }

        void vscode.window.showWarningMessage(
          "Samwise: Google auth timed out. Try running the command again.",
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        void vscode.window.showErrorMessage(`Samwise: Google auth failed — ${msg}`);
      }
    }),
  );

  // --- Periodic Refresh ---
  const updateStatusBar = async (): Promise<void> => {
    const live = await client.fetchStatus();
    const s = live ?? getStatusBarSummary();
    statusBarItem.text = s.text;
    statusBarItem.tooltip = s.tooltip;
    void sidebarProvider.refresh();
  };

  refreshInterval = setInterval(() => void updateStatusBar(), 60_000);

  // --- SSE helper (called once backend is ready) ---
  const connectSse = (): void => {
    client.subscribeEvents((item) => {
      void sidebarProvider.refresh();
      void updateStatusBar();

      if (item.urgency === "high") {
        void vscode.window
          .showWarningMessage(`Samwise: ${item.title}`, "Open Feed")
          .then((choice) => {
            if (choice === "Open Feed") {
              void vscode.commands.executeCommand("samwise.activityFeed.focus");
            }
          });
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

      void vscode.window.showInformationMessage(
        `Samwise backend running on port ${backendManager.port}`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      backendManager?.outputChannel.appendLine(`Startup failed: ${msg}`);

      // Fall back to trying an already-running backend
      statusBarItem.text = "$(warning) Samwise: backend failed";
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
