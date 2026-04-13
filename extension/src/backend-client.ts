import type { ActivityItem } from "./mock-data.js";

const DEFAULT_BASE_URL = "http://127.0.0.1:9474";

interface StatusResponse {
  text: string;
  tooltip: string;
}

export class BackendClient {
  private readonly _baseUrl: string;

  constructor(baseUrl?: string) {
    this._baseUrl = baseUrl ?? DEFAULT_BASE_URL;
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

  async isHealthy(): Promise<boolean> {
    try {
      const resp = await fetch(`${this._baseUrl}/api/health`);
      return resp.ok;
    } catch {
      return false;
    }
  }
}
