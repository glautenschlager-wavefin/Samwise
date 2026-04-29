/**
 * EventMonitor — listens to VS Code workspace events and posts them
 * to the Samwise backend to trigger targeted pipeline runs.
 *
 * Events: git push/commit/branch switch, terminal task completion.
 */

import * as vscode from "vscode";
import type { BackendClient } from "./backend-client.js";

interface GitExtensionAPI {
  getAPI(version: 1): GitAPI;
}

interface GitAPI {
  repositories: GitRepository[];
  onDidOpenRepository: vscode.Event<GitRepository>;
}

interface GitRepository {
  rootUri: vscode.Uri;
  state: {
    HEAD: { name?: string; commit?: string } | undefined;
    onDidChange: vscode.Event<void>;
  };
}

export class EventMonitor implements vscode.Disposable {
  private readonly _disposables: vscode.Disposable[] = [];
  private readonly _client: BackendClient;
  private _lastBranch = new Map<string, string>();
  private _lastCommit = new Map<string, string>();

  constructor(client: BackendClient) {
    this._client = client;
  }

  /** Start listening to workspace events. */
  activate(context: vscode.ExtensionContext): void {
    // --- Git events ---
    const gitExt = vscode.extensions.getExtension<GitExtensionAPI>(
      "vscode.git",
    );
    if (gitExt?.isActive) {
      this._watchGit(gitExt.exports.getAPI(1));
    } else if (gitExt) {
      gitExt.activate().then((ext) => this._watchGit(ext.getAPI(1)));
    }

    // --- Terminal task completion ---
    this._disposables.push(
      vscode.tasks.onDidEndTaskProcess((e) => {
        const name =
          e.execution.task.name || e.execution.task.definition.type || "";
        const folder = e.execution.task.scope;
        const ws =
          folder && typeof folder === "object" && "uri" in folder
            ? (folder as vscode.WorkspaceFolder).uri.fsPath
            : "";
        this._client.postEvent({
          type: "task_complete",
          workspace: ws,
          detail: `${name} exited ${e.exitCode}`,
        });
      }),
    );
  }

  private _watchGit(git: GitAPI): void {
    for (const repo of git.repositories) {
      this._watchRepo(repo);
    }
    this._disposables.push(
      git.onDidOpenRepository((repo) => this._watchRepo(repo)),
    );
  }

  private _watchRepo(repo: GitRepository): void {
    const root = repo.rootUri.fsPath;

    // Seed initial state so we can detect changes.
    if (repo.state.HEAD?.name) {
      this._lastBranch.set(root, repo.state.HEAD.name);
    }
    if (repo.state.HEAD?.commit) {
      this._lastCommit.set(root, repo.state.HEAD.commit);
    }

    this._disposables.push(
      repo.state.onDidChange(() => {
        const head = repo.state.HEAD;
        if (!head) {
          return;
        }

        const prevBranch = this._lastBranch.get(root);
        const prevCommit = this._lastCommit.get(root);

        // Branch switch
        if (head.name && head.name !== prevBranch) {
          this._lastBranch.set(root, head.name);
          this._client.postEvent({
            type: "branch_switch",
            workspace: root,
            branch: head.name,
            detail: `${prevBranch ?? "?"} → ${head.name}`,
          });
        }

        // New commit (push or local commit)
        if (head.commit && head.commit !== prevCommit) {
          this._lastCommit.set(root, head.commit);
          this._client.postEvent({
            type: "git_commit",
            workspace: root,
            branch: head.name ?? "",
            detail: head.commit.slice(0, 8),
          });
        }
      }),
    );
  }

  dispose(): void {
    for (const d of this._disposables) {
      d.dispose();
    }
    this._disposables.length = 0;
  }
}
