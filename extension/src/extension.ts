import * as vscode from "vscode";
import { createChatHandler } from "./chat-handler.js";
import { getStatusBarSummary } from "./mock-data.js";
import { SidebarProvider } from "./sidebar-provider.js";

let statusBarItem: vscode.StatusBarItem;
let refreshInterval: ReturnType<typeof setInterval> | undefined;

export function activate(context: vscode.ExtensionContext): void {
  // --- Sidebar ---
  const sidebarProvider = new SidebarProvider(context.extensionUri);
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
  const chatParticipant = vscode.chat.createChatParticipant("samwise.chat", createChatHandler());
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
      sidebarProvider.refresh();
      void vscode.window.showInformationMessage("Samwise: Activity feed refreshed");
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("samwise.showSummary", () => {
      const s = getStatusBarSummary();
      void vscode.window.showInformationMessage(s.text.replace("$(rocket) ", ""));
    }),
  );

  // --- Periodic Refresh (simulates future backend polling) ---
  refreshInterval = setInterval(
    () => {
      const s = getStatusBarSummary();
      statusBarItem.text = s.text;
      statusBarItem.tooltip = s.tooltip;
      sidebarProvider.refresh();
    },
    60_000, // every 60 seconds
  );
}

export function deactivate(): void {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = undefined;
  }
}
