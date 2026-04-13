import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import { createChatHandler } from "./chat-handler.js";
import { getStatusBarSummary } from "./mock-data.js";
import { SidebarProvider } from "./sidebar-provider.js";

let statusBarItem: vscode.StatusBarItem;
let refreshInterval: ReturnType<typeof setInterval> | undefined;

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

  // --- Periodic Refresh ---
  const updateStatusBar = async (): Promise<void> => {
    const live = await client.fetchStatus();
    const s = live ?? getStatusBarSummary();
    statusBarItem.text = s.text;
    statusBarItem.tooltip = s.tooltip;
    void sidebarProvider.refresh();
  };

  refreshInterval = setInterval(() => void updateStatusBar(), 60_000);

  // Also try to connect immediately
  void updateStatusBar();

  // --- SSE: real-time notifications from the backend ---
  client.subscribeEvents((item) => {
    // Refresh sidebar whenever something new arrives
    void sidebarProvider.refresh();
    void updateStatusBar();

    // Show a VS Code notification for high-urgency items
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
}

export function deactivate(): void {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = undefined;
  }
}
