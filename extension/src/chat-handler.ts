import * as vscode from "vscode";
import { getMockSprintSummary, getMockStatusSummary } from "./mock-data.js";

export function createChatHandler(): vscode.ChatRequestHandler {
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
        stream.markdown(getMockStatusSummary());
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
