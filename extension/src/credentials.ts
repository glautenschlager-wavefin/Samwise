/**
 * Credentials — reads VS Code settings + SecretStorage and produces
 * the SAMWISE_* environment variable map for the backend subprocess.
 */

import * as vscode from "vscode";

/** Keys used in SecretStorage. */
const SECRET_GITHUB_TOKEN = "samwise.githubToken";
const SECRET_JIRA_API_TOKEN = "samwise.jiraApiToken";

/**
 * Build a Record of SAMWISE_* env vars from VS Code configuration
 * and SecretStorage.  Only non-empty values are included.
 */
export async function buildBackendEnv(
  secrets: vscode.SecretStorage,
): Promise<Record<string, string>> {
  const cfg = vscode.workspace.getConfiguration("samwise");
  const env: Record<string, string> = {};

  // --- Secrets ---
  const githubToken = await secrets.get(SECRET_GITHUB_TOKEN);
  if (githubToken) {
    env["SAMWISE_GITHUB_TOKEN"] = githubToken;
  }

  const jiraToken = await secrets.get(SECRET_JIRA_API_TOKEN);
  if (jiraToken) {
    env["SAMWISE_JIRA_API_TOKEN"] = jiraToken;
  }

  // --- Regular settings → env vars ---
  const mapping: Array<[string, string]> = [
    ["github.username", "SAMWISE_GITHUB_USERNAME"],
    ["jira.baseUrl", "SAMWISE_JIRA_BASE_URL"],
    ["jira.email", "SAMWISE_JIRA_EMAIL"],
    ["google.clientSecretPath", "SAMWISE_GOOGLE_CLIENT_SECRET_FILE"],
    ["backend.port", "SAMWISE_PORT"],
    ["backend.pollIntervalSeconds", "SAMWISE_POLL_INTERVAL_SECONDS"],
    ["backend.autoMerge", "SAMWISE_AUTO_MERGE"],
  ];

  for (const [settingKey, envKey] of mapping) {
    const value = cfg.get<string | number | boolean>(settingKey);
    if (value !== undefined && value !== "") {
      env[envKey] = String(value);
    }
  }

  return env;
}

/**
 * Prompt the user for a secret and store it in SecretStorage.
 * Returns true if a value was stored.
 */
export async function promptAndStoreSecret(
  secrets: vscode.SecretStorage,
  key: string,
  prompt: string,
): Promise<boolean> {
  const value = await vscode.window.showInputBox({
    prompt,
    password: true,
    ignoreFocusOut: true,
  });
  if (value) {
    await secrets.store(key, value);
    return true;
  }
  return false;
}

/** Prompt for and store a GitHub personal access token. */
export async function setGithubToken(secrets: vscode.SecretStorage): Promise<boolean> {
  return promptAndStoreSecret(
    secrets,
    SECRET_GITHUB_TOKEN,
    "Enter your GitHub personal access token",
  );
}

/** Prompt for and store a Jira API token. */
export async function setJiraToken(secrets: vscode.SecretStorage): Promise<boolean> {
  return promptAndStoreSecret(
    secrets,
    SECRET_JIRA_API_TOKEN,
    "Enter your Jira API token",
  );
}

/** Check whether essential credentials are configured. */
export async function hasMinimalCredentials(
  secrets: vscode.SecretStorage,
): Promise<boolean> {
  const githubToken = await secrets.get(SECRET_GITHUB_TOKEN);
  return !!githubToken;
}
