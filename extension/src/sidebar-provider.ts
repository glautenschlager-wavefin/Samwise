import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import { ActivityItem, getMockActivityItems } from "./mock-data.js";

export class SidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewId = "samwise.activityFeed";
  private _view?: vscode.WebviewView;

  constructor(
    private readonly _extensionUri: vscode.Uri,
    private readonly _client: BackendClient,
  ) {}

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    void this.refresh();
  }

  public async refresh(): Promise<void> {
    if (!this._view) {
      return;
    }
    const liveItems = await this._client.fetchActivity();
    const items = liveItems ?? getMockActivityItems();
    this._view.webview.html = this._getHtml(items);
  }

  private _getHtml(items: ActivityItem[]): string {
    const itemsHtml = items
      .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
      .map((item) => {
        const age = this._formatAge(item.timestamp);
        const categoryClass = item.category;
        return `
        <div class="activity-item ${categoryClass}">
          <div class="item-header">
            <span class="icon">${item.icon}</span>
            <span class="title">${this._escapeHtml(item.title)}</span>
            <span class="time">${age}</span>
          </div>
          <div class="detail">${this._escapeHtml(item.detail)}</div>
        </div>`;
      })
      .join("\n");

    return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
  <style>
    body {
      margin: 0;
      padding: 0;
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
    }

    .feed {
      padding: 8px;
    }

    .activity-item {
      padding: 10px;
      margin-bottom: 6px;
      border-radius: 4px;
      background: var(--vscode-editor-background);
      border-left: 3px solid var(--vscode-textLink-foreground);
    }

    .activity-item.break {
      border-left-color: var(--vscode-charts-orange);
    }

    .activity-item.comms {
      border-left-color: var(--vscode-charts-purple);
    }

    .activity-item.sprint {
      border-left-color: var(--vscode-charts-blue);
    }

    .activity-item.code-shipping {
      border-left-color: var(--vscode-charts-green);
    }

    .item-header {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 4px;
    }

    .icon {
      font-size: 14px;
      flex-shrink: 0;
    }

    .title {
      font-weight: 600;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .time {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      flex-shrink: 0;
    }

    .detail {
      font-size: 12px;
      color: var(--vscode-descriptionForeground);
      line-height: 1.4;
      padding-left: 22px;
    }

    .empty {
      text-align: center;
      padding: 24px 12px;
      color: var(--vscode-descriptionForeground);
    }
  </style>
</head>
<body>
  <div class="feed">
    ${items.length > 0 ? itemsHtml : '<div class="empty">No activity yet. Samwise is watching...</div>'}
  </div>
</body>
</html>`;
  }

  private _formatAge(timestamp: Date): string {
    const diffMs = Date.now() - timestamp.getTime();
    const minutes = Math.floor(diffMs / 60_000);
    if (minutes < 1) {
      return "just now";
    }
    if (minutes < 60) {
      return `${minutes}m ago`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
      return `${hours}h ago`;
    }
    return `${Math.floor(hours / 24)}d ago`;
  }

  private _escapeHtml(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}
