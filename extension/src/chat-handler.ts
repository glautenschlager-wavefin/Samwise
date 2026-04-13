import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import type { ActivityItem } from "./mock-data.js";
import { getMockSprintSummary, getMockStatusSummary } from "./mock-data.js";

const SAMWISE_SYSTEM_PROMPT = `You are Samwise, a faithful coding assistant. You help your developer stay on top of their work — PRs, reviews, CI failures, sprint progress, and communications.

Your personality: loyal, proactive, quietly competent. You speak concisely and focus on what matters. You reference specific PRs, tickets, and people when you have that context. You suggest concrete next actions.

When the user asks you to do something (implement a ticket, fix a bug, run a command), you should:
1. Explain what you plan to do
2. Suggest the specific terminal commands or code changes needed
3. Ask for confirmation if the action is destructive or irreversible

You have access to the user's current activity feed, which shows their open PRs, review requests, CI status, and notifications. Use this context to give informed, specific answers.`;

function formatActivityContext(items: ActivityItem[]): string {
  if (items.length === 0) {
    return "No activity data available — the backend may not be running.";
  }
  const lines = items.slice(0, 20).map(
    (i) => `- [${i.category}] ${i.icon} ${i.title}: ${i.detail}`,
  );
  return `Current activity feed (${items.length} items):\n${lines.join("\n")}`;
}

async function selectModel(
  token: vscode.CancellationToken,
): Promise<vscode.LanguageModelChat | undefined> {
  const models = await vscode.lm.selectChatModels({
    vendor: "copilot",
  });
  if (models.length === 0) {
    return undefined;
  }
  // Prefer GPT-4o class, fall back to whatever is available
  return models.find((m) => m.family.includes("gpt-4")) ?? models[0];
}

async function streamLmResponse(
  model: vscode.LanguageModelChat,
  messages: vscode.LanguageModelChatMessage[],
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken,
): Promise<void> {
  const response = await model.sendRequest(messages, {}, token);
  for await (const chunk of response.text) {
    stream.markdown(chunk);
  }
}

export function createChatHandler(client: BackendClient): vscode.ChatRequestHandler {
  return async (
    request: vscode.ChatRequest,
    context: vscode.ChatContext,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
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
            "| `/do` | Execute a task (e.g., `/do merge PR #85`) |",
            "| `/help` | Show this help message |",
            "",
            "You can also just type a message and I'll reason about it with full context.",
          ].join("\n"),
        );
        break;
      }
      case "do": {
        stream.progress("Planning task...");

        const model = await selectModel(token);
        if (!model) {
          stream.markdown(
            "I need access to a Copilot language model to execute tasks. Make sure Copilot is active.",
          );
          break;
        }

        const activityItems = (await client.fetchActivity()) ?? [];
        const activityContext = formatActivityContext(activityItems);

        const messages = [
          vscode.LanguageModelChatMessage.User(
            `${SAMWISE_SYSTEM_PROMPT}\n\n${activityContext}\n\nThe user wants you to perform the following task. Break it down into concrete steps, specifying exact terminal commands or code changes. Be specific — use real file paths, branch names, and PR numbers from the context when available.\n\nTask: ${request.prompt}`,
          ),
        ];

        // Include recent chat history for continuity
        for (const turn of context.history) {
          if (turn instanceof vscode.ChatRequestTurn) {
            messages.push(vscode.LanguageModelChatMessage.User(turn.prompt));
          } else if (turn instanceof vscode.ChatResponseTurn) {
            const text = turn.response
              .map((r) => (r instanceof vscode.ChatResponseMarkdownPart ? r.value.value : ""))
              .join("");
            if (text) {
              messages.push(vscode.LanguageModelChatMessage.Assistant(text));
            }
          }
        }

        await streamLmResponse(model, messages, stream, token);

        stream.button({
          command: "workbench.action.terminal.new",
          title: "Open Terminal",
        });
        break;
      }
      default: {
        // Free-text: use the LLM with Samwise's context
        stream.progress("Thinking...");

        const model = await selectModel(token);
        if (!model) {
          // Graceful fallback when no model is available
          stream.markdown(
            `Got it — "${request.prompt}"\n\nI need access to a Copilot language model to give you a smart answer. Make sure Copilot is active. In the meantime, try \`/status\` or \`/sprint\` for data I can show directly.`,
          );
          break;
        }

        const activityItems = (await client.fetchActivity()) ?? [];
        const activityContext = formatActivityContext(activityItems);

        const messages: vscode.LanguageModelChatMessage[] = [
          vscode.LanguageModelChatMessage.User(
            `${SAMWISE_SYSTEM_PROMPT}\n\n${activityContext}`,
          ),
        ];

        // Replay chat history for continuity
        for (const turn of context.history) {
          if (turn instanceof vscode.ChatRequestTurn) {
            messages.push(vscode.LanguageModelChatMessage.User(turn.prompt));
          } else if (turn instanceof vscode.ChatResponseTurn) {
            const text = turn.response
              .map((r) => (r instanceof vscode.ChatResponseMarkdownPart ? r.value.value : ""))
              .join("");
            if (text) {
              messages.push(vscode.LanguageModelChatMessage.Assistant(text));
            }
          }
        }

        // Current user message
        messages.push(vscode.LanguageModelChatMessage.User(request.prompt));

        await streamLmResponse(model, messages, stream, token);
        break;
      }
    }

    return {};
  };
}
