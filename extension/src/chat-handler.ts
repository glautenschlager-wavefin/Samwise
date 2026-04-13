import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import { getMockSprintSummary, getMockStatusSummary } from "./mock-data.js";

export function createChatHandler(client: BackendClient): vscode.ChatRequestHandler {
  return async (
    request: vscode.ChatRequest,
    _context: vscode.ChatContext,
    stream: vscode.ChatResponseStream,
    _token: vscode.CancellationToken,
  ): Promise<vscode.ChatResult> => {
    switch (request.command) {
      case "sprint": {
        stream.markdown(getMockSprintSummary());
        break;
      }
      case "status": {
        stream.progress("Fetching live status...");
        const live = await client.fetchActivity();
        if (live && live.length > 0) {
          const lines = ["## Samwise Status (live)", ""];
          for (const item of live.slice(0, 15)) {
            lines.push(`- ${item.icon} **${item.title}** — ${item.detail}`);
          }
          stream.markdown(lines.join("\n"));
        } else {
          stream.markdown(getMockStatusSummary());
        }
        break;
      }
      case "break": {
        stream.markdown(
          "☕ **Break reminder toggled.** I'll nudge you after 90 minutes of continuous coding.",
        );
        break;
      }
      case "help": {
        stream.markdown(
          [
            "## Samwise Commands",
            "",
            "| Command | Description |",
            "|---------|-------------|",
            "| `/sprint` | Show sprint board summary |",
            "| `/status` | Show current activity status |",
            "| `/break` | Toggle break reminder |",
            "| `/help` | Show this help message |",
            "",
            "You can also just type a message and I'll do my best to help.",
          ].join("\n"),
        );
        break;
      }
      default: {
        stream.progress("Thinking...");
        stream.markdown(
          `👍 Got it — "${request.prompt}"\n\nI'll handle that. *(Autonomous actions coming soon — this is a placeholder.)*`,
        );
        break;
      }
    }

    return {};
  };
}
