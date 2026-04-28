import type { ActivityItem } from "./mock-data.js";

const DEFAULT_BASE_URL = "http://127.0.0.1:9474";

interface StatusResponse {
  text: string;
  tooltip: string;
}

export class BackendClient {
  private _baseUrl: string;
  private _sseAbort: AbortController | null = null;

  constructor(baseUrl?: string) {
    this._baseUrl = baseUrl ?? DEFAULT_BASE_URL;
  }

  /** Update the base URL (e.g. after the backend auto-selects a port). */
  setBaseUrl(url: string): void {
    this._baseUrl = url;
  }

  async fetchActivity(): Promise<ActivityItem[] | null> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/activity`);
      if (!resp.ok) {
        return null;
      }
      const data = (await resp.json()) as Array<{
        id: string;
        category: ActivityItem["category"];
        icon: string;
        title: string;
        detail: string;
        timestamp: string;
      }>;
      return data.map((item) => ({
        ...item,
        timestamp: new Date(item.timestamp),
      }));
    } catch {
      return null;
    }
  }

  async fetchStatus(): Promise<StatusResponse | null> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/status`);
      if (!resp.ok) {
        return null;
      }
      return (await resp.json()) as StatusResponse;
    } catch {
      return null;
    }
  }

  async fetchDeferred(): Promise<ActivityItem[] | null> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/deferred`);
      if (!resp.ok) {
        return null;
      }
      return (await resp.json()) as ActivityItem[];
    } catch {
      return null;
    }
  }

  async flushDeferred(): Promise<ActivityItem[] | null> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/deferred/flush`, { method: "POST" });
      if (!resp.ok) {
        return null;
      }
      return (await resp.json()) as ActivityItem[];
    } catch {
      return null;
    }
  }

  async isHealthy(): Promise<boolean> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/health`);
      return resp.ok;
    } catch {
      return false;
    }
  }

  /** Start Google OAuth flow. Returns the auth URL to open in the browser. */
  async startGoogleAuth(): Promise<string | null> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/auth/google`, {
        method: "POST",
      });
      if (!resp.ok) {
        const body = (await resp.json()) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${resp.status}`);
      }
      const data = (await resp.json()) as { auth_url: string };
      return data.auth_url;
    } catch (err) {
      if (err instanceof Error) {
        throw err;
      }
      return null;
    }
  }

  /** Check whether Google Calendar is authenticated. */
  async isGoogleAuthenticated(): Promise<boolean> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/auth/google/status`);
      if (!resp.ok) {
        return false;
      }
      const data = (await resp.json()) as { authenticated: boolean };
      return data.authenticated;
    } catch {
      return false;
    }
  }

  /**
   * Subscribe to the SSE event stream.  Calls `onEvent` for each pushed item.
   * Automatically reconnects on disconnect (5 s backoff).
   */
  subscribeEvents(onEvent: (item: ActivityItem) => void): void {
    this._sseAbort?.abort();
    const ctrl = new AbortController();
    this._sseAbort = ctrl;

    const connect = async (): Promise<void> => {
      try {
        const resp = await fetch(`${this._baseUrl}/api/events`, { signal: ctrl.signal });
        if (!resp.ok || !resp.body) {
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!ctrl.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });

          // SSE events are separated by double newlines
          const parts = buffer.split("\n\n");
          buffer = parts.pop()!;

          for (const part of parts) {
            const dataLine = part
              .split("\n")
              .find((l) => l.startsWith("data: "));
            if (dataLine) {
              try {
                const item = JSON.parse(dataLine.slice(6)) as ActivityItem;
                onEvent(item);
              } catch {
                // skip malformed events
              }
            }
          }
        }
      } catch {
        // fetch aborted or network error — handled by reconnect below
      }

      // Reconnect unless intentionally stopped
      if (!ctrl.signal.aborted) {
        setTimeout(() => void connect(), 5_000);
      }
    };

    void connect();
  }

  /** Stop the SSE subscription. */
  disposeEvents(): void {
    this._sseAbort?.abort();
    this._sseAbort = null;
  }
}
