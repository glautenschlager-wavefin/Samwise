import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import { BackendManager } from "./backend-manager.js";
import { createChatHandler } from "./chat-handler.js";
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
      backendManager = new BackendManager(workspaceFolder);
      context.subscriptions.push(backendManager);

      statusBarItem.text = "$(loading~spin) Samwise: starting...";
      await backendManager.start();

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

  void startBackend();
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
