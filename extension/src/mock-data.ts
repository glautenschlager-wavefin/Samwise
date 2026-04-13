export interface ActivityItem {
  id: string;
  category: "code-shipping" | "comms" | "break" | "sprint";
  icon: string;
  title: string;
  detail: string;
  timestamp: Date;
}

const now = new Date();
function minutesAgo(minutes: number): Date {
  return new Date(now.getTime() - minutes * 60_000);
}

export function getMockActivityItems(): ActivityItem[] {
  return [
    {
      id: "1",
      category: "code-shipping",
      icon: "✅",
      title: "Implemented PROJ-142",
      detail: "PR #87 created — adds rate limiting to payment endpoint",
      timestamp: minutesAgo(5),
    },
    {
      id: "2",
      category: "code-shipping",
      icon: "👀",
      title: "PR #85 approved",
      detail: "@maria approved your refactor of the auth module — ready to merge",
      timestamp: minutesAgo(12),
    },
    {
      id: "3",
      category: "comms",
      icon: "💬",
      title: "Slack from @james",
      detail: "Question about the migration timeline for identity service",
      timestamp: minutesAgo(25),
    },
    {
      id: "4",
      category: "sprint",
      icon: "📋",
      title: "Sprint update",
      detail: "3 in progress, 2 blocked, 4 done — sprint ends Thursday",
      timestamp: minutesAgo(45),
    },
    {
      id: "5",
      category: "break",
      icon: "☕",
      title: "Break reminder",
      detail: "You've been coding for 90 minutes — consider stretching",
      timestamp: minutesAgo(2),
    },
    {
      id: "6",
      category: "code-shipping",
      icon: "🔴",
      title: "CI failure on main",
      detail: "Integration tests failing after merge of PR #84 — flaky test in accounting",
      timestamp: minutesAgo(60),
    },
    {
      id: "7",
      category: "comms",
      icon: "📧",
      title: "Email from product",
      detail: "Q2 roadmap review scheduled for Wednesday 2pm",
      timestamp: minutesAgo(90),
    },
    {
      id: "8",
      category: "code-shipping",
      icon: "🔔",
      title: "Review requested",
      detail: "@carlos wants your review on PR #89 — payroll batch processing",
      timestamp: minutesAgo(35),
    },
  ];
}

export function getMockSprintSummary(): string {
  return [
    "## Sprint 24.3 — ends Thursday",
    "",
    "| Status | Count | Tickets |",
    "|--------|-------|---------|",
    "| ✅ Done | 4 | PROJ-138, PROJ-139, PROJ-140, PROJ-142 |",
    "| 🔄 In Progress | 3 | PROJ-143, PROJ-145, PROJ-147 |",
    "| 🚫 Blocked | 2 | PROJ-141 (waiting on infra), PROJ-146 (needs design) |",
    "| 📋 To Do | 1 | PROJ-148 |",
    "",
    "**Velocity:** 4/10 points completed (40%)",
    "",
    "**Risks:** PROJ-141 has been blocked for 3 days. Consider escalating.",
  ].join("\n");
}

export function getMockStatusSummary(): string {
  return [
    "## Samwise Status",
    "",
    "**Today so far:**",
    "- Implemented 1 ticket (PROJ-142)",
    "- Created 1 PR (#87)",
    "- 1 PR approved and ready to merge (#85)",
    "- 1 review requested from you (#89)",
    "- 1 CI failure needs attention",
    "",
    "**Unread comms:**",
    "- 1 Slack message from @james",
    "- 1 email from product team",
    "",
    "**Next suggested action:** Merge PR #85, then review PR #89",
  ].join("\n");
}

export function getStatusBarSummary(): { text: string; tooltip: string } {
  return {
    text: "$(rocket) Samwise: 4 done, 1 needs attention",
    tooltip: "4 items done today • 1 CI failure • 1 review pending\nClick to open Activity Feed",
  };
}
