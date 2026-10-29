const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ? JSON.stringify(body.detail) : detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  // setup
  getProfiles: () => request<Record<string, string>>("/setup/profiles"),
  getDefaults: (capital: number, riskProfile: string) =>
    request(`/setup/defaults?capital=${capital}&risk_profile=${riskProfile}`),
  getSettings: () => request<any>("/setup/settings"),
  saveSettings: (payload: any) =>
    request<any>("/setup/settings", { method: "POST", body: JSON.stringify(payload) }),

  // auth
  getLoginUrl: () => request<{ login_url: string }>("/auth/fyers/login-url"),
  getBrokerStatus: () => request<any>("/auth/fyers/status"),
  disconnectBroker: () => request<any>("/auth/fyers/disconnect", { method: "POST" }),

  // trading control
  recoveryCheck: () => request<any>("/trading/recovery-check"),
  startAutoTrading: () => request<any>("/trading/start", { method: "POST" }),
  stopAutoTrading: () => request<any>("/trading/stop", { method: "POST" }),

  // emergency
  activateKillSwitch: () => request<any>("/emergency/kill-switch/activate", { method: "POST" }),
  deactivateKillSwitch: () => request<any>("/emergency/kill-switch/deactivate", { method: "POST" }),
  closeAllPositions: () => request<any>("/emergency/close-all-positions", { method: "POST" }),

  // dashboard
  getDashboard: () => request<any>("/dashboard"),

  // journal
  getTrades: (date?: string) => request<any[]>(`/journal/trades${date ? `?date=${date}` : ""}`),
  getAnalytics: () => request<any>("/journal/analytics"),
  getSignals: () => request<any[]>("/journal/signals"),
  getEngineActivity: () => request<any[]>("/journal/engine-activity"),
  getRiskEvents: () => request<any[]>("/journal/risk-events"),
  getSystemEvents: () => request<any[]>("/journal/system-events"),

  // diagnostics
  getDiagnostics: () => request<any>("/diagnostics"),
};
