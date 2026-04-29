import * as vscode from "vscode";
import { BackendClient } from "./backend-client.js";
import type { ProjectSummary, GitHubIssue } from "./backend-client.js";
import type { ActivityItem } from "./mock-data.js";


const SAMWISE_SYSTEM_PROMPT = `You are Samwise, a faithful coding assistant. You help your developer stay on top of their work — PRs, reviews, CI failures, sprint progress, calendar events, communications, and side projects.

Your personality: loyal, proactive, quietly competent. You speak concisely and focus on what matters. You reference specific PRs, tickets, meetings, and people when you have that context. You suggest concrete next actions.

When the user asks about meetings or their calendar, look for items with category "calendar" in the activity feed. If there are none, tell them there are no upcoming meetings in the next 2 hours (the polling window). Do NOT say you don't have calendar access — you do.

When the user asks about their side projects, look for items with category "project" in the activity feed. You can also use the project tools to create, close, list, and label GitHub issues on tracked repos.

When the user asks about shipping readiness, PRs, or code health, look for SLA violations (sla_violation metadata), workspace checks (sensor_type=workspace metadata), and CI failures in the activity feed. Flag items that need attention before code can ship.

When the user asks you to create an issue, extract the repo (owner/name), title, and optional body/labels. Format your response to confirm what was created with the issue number and link.

When the user asks you to close an issue, confirm the repo and issue number, then close it.

When the user asks you to do something (implement a ticket, fix a bug, run a command), you should:
1. Explain what you plan to do
2. Suggest the specific terminal commands or code changes needed
3. Ask for confirmation if the action is destructive or irreversible

You have access to the user's current activity feed, which shows their open PRs, review requests, CI status, sprint board, upcoming calendar events (next 2 hours), and side-project health. Use this context to give informed, specific answers.`;

function formatActivityContext(items: ActivityItem[]): string {
  if (items.length === 0) {
    return "No activity data available — the backend may not be running.";
  }
  const lines = items.slice(0, 20).map(
    (i) => `- [${i.category}] ${i.icon} ${i.title}: ${i.detail}`,
  );
  return `Current activity feed (${items.length} items):\n${lines.join("\n")}`;
}

function formatProjectContext(projects: ProjectSummary[]): string {
  if (projects.length === 0) {
    return "No side projects configured.";
  }
  const lines = projects.map((p) => {
    const status = p.stale ? "STALE" : "active";
    const pushInfo = p.last_push
      ? `last push ${p.idle_days}d ago`
      : "never pushed";
    return `- ${p.repo}: ${status}, ${pushInfo}, ${p.open_issues} open issues`;
  });
  return `Tracked side projects:\n${lines.join("\n")}`;
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
        stream.progress("Fetching sprint board...");
        const live = await client.fetchActivity();
        const sprintItems = live?.filter((i) => i.category === "sprint");
        if (sprintItems && sprintItems.length > 0) {
          const lines = ["## 📋 Sprint Board (live)", ""];
          for (const item of sprintItems) {
            lines.push(`- ${item.icon} **${item.title}** — ${item.detail}`);
          }
          stream.markdown(lines.join("\n"));
        } else if (live && live.length > 0) {
          // Backend is up but no sprint items — show what we have
          stream.markdown(
            "No sprint items found in the activity feed. Is the Jira sensor configured?\n\n" +
            "Set `SAMWISE_JIRA_BASE_URL`, `SAMWISE_JIRA_EMAIL`, and `SAMWISE_JIRA_API_TOKEN` in your `.env` file and restart the backend.",
          );
        } else {
          stream.markdown(
            "Can't reach the backend. Check the Samwise Backend log for errors.",
          );
        }
        break;
      }
      case "calendar": {
        stream.progress("Checking calendar...");
        const calLive = await client.fetchActivity();
        const calItems = calLive?.filter((i) => i.category === "calendar");
        if (calItems && calItems.length > 0) {
          const lines = ["## 📅 Upcoming Meetings", ""];
          for (const item of calItems) {
            lines.push(`- ${item.icon} **${item.title}** — ${item.detail}`);
          }
          stream.markdown(lines.join("\n"));
        } else if (calLive && calLive.length > 0) {
          stream.markdown(
            "No meetings in the next 2 hours. You're in the clear! 🎉",
          );
        } else {
          stream.markdown(
            "Can't reach the backend. Make sure the server is running (`make serve`).",
          );
        }
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
          stream.markdown(
            "Can't reach the backend. Check the Samwise Backend log for errors.",
          );
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
            "| `/calendar` | Show upcoming meetings (next 2h) |",
            "| `/status` | Show current activity status |",
            "| `/projects` | Show side-project health dashboard |",
            "| `/shipping` | Show code shipping readiness |",
            "| `/break` | Toggle break reminder |",
            "| `/do` | Execute a task (e.g., `/do merge PR #85`) |",
            "| `/help` | Show this help message |",
            "",
            "**Project management via chat:**",
            "- `create issue on owner/repo: title` — create a GitHub issue",
            "- `close issue owner/repo#123` — close an issue",
            "- `list issues on owner/repo` — list open issues",
            "",
            "You can also just type a message and I'll reason about it with full context.",
          ].join("\n"),
        );
        break;
      }
      case "projects": {
        stream.progress("Fetching project health...");
        const projects = await client.fetchProjects();
        if (projects && projects.length > 0) {
          const lines = ["## 🔨 Side Projects", ""];
          for (const p of projects) {
            const health = p.stale ? "🧊 STALE" : "🟢 Active";
            const pushInfo = p.last_push
              ? `last push ${p.idle_days}d ago`
              : "never pushed";
            lines.push(
              `### ${p.repo} — ${health}`,
              `${pushInfo} · ${p.open_issues} open issue${p.open_issues !== 1 ? "s" : ""}`,
              "",
            );
          }
          lines.push(
            "---",
            "*Create issues:* `create issue on owner/repo: title`",
            "*List issues:* `list issues on owner/repo`",
          );
          stream.markdown(lines.join("\n"));
        } else if (projects) {
          stream.markdown(
            "No projects configured. Add repos to `samwise.projects.repos` in VS Code settings.",
          );
        } else {
          stream.markdown(
            "Can't reach the backend. Check the Samwise Backend log for errors.",
          );
        }
        break;
      }
      case "shipping": {
        stream.progress("Checking shipping readiness...");
        const live = await client.fetchActivity();
        if (!live || live.length === 0) {
          stream.markdown(
            "Can't reach the backend. Check the Samwise Backend log for errors.",
          );
          break;
        }

        // SLA violations
        const slaItems = live.filter(
          (i) => i.category === "code-shipping" && (i as any).metadata?.sla_violation,
        );
        // Workspace checks
        const wsItems = live.filter(
          (i) => i.category === "code-shipping" && (i as any).metadata?.sensor_type === "workspace",
        );
        // CI failures
        const ciItems = live.filter(
          (i) => i.category === "code-shipping" && i.icon === "🔴",
        );

        const sections: string[] = ["## 🚢 Shipping Readiness", ""];

        if (slaItems.length === 0 && wsItems.length === 0 && ciItems.length === 0) {
          sections.push("All clear — no SLA violations, workspace issues, or CI failures. Ship it! 🎉");
        } else {
          if (ciItems.length > 0) {
            sections.push("### 🔴 CI Failures");
            for (const item of ciItems) {
              sections.push(`- ${item.icon} **${item.title}** — ${item.detail}`);
            }
            sections.push("");
          }
          if (slaItems.length > 0) {
            sections.push("### 📊 PR SLA Violations");
            for (const item of slaItems) {
              sections.push(`- ${item.icon} **${item.title}** — ${item.detail}`);
            }
            sections.push("");
          }
          if (wsItems.length > 0) {
            sections.push("### 🔧 Workspace Checks");
            for (const item of wsItems) {
              sections.push(`- ${item.icon} **${item.title}** — ${item.detail}`);
            }
            sections.push("");
          }
        }

        stream.markdown(sections.join("\n"));
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

        // Fetch project context for the LLM
        const projectSummaries = (await client.fetchProjects()) ?? [];
        const projectContext = formatProjectContext(projectSummaries);

        const messages: vscode.LanguageModelChatMessage[] = [
          vscode.LanguageModelChatMessage.User(
            `${SAMWISE_SYSTEM_PROMPT}\n\n${activityContext}\n\n${projectContext}`,
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
