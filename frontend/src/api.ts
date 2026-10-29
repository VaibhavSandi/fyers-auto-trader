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

  // historical data (Phase 2)
  getDataStatus: () => request<any[]>("/data/status"),
  syncData: (payload: { symbols?: string[]; timeframe?: string; days?: number }) =>
    request<any>("/data/sync", { method: "POST", body: JSON.stringify(payload) }),

  // backtesting (Phase 3/4/5)
  getStrategies: () => request<any[]>("/backtest/strategies"),
  runBacktest: (payload: any) => request<any>("/backtest/run", { method: "POST", body: JSON.stringify(payload) }),
  listBacktests: () => request<any[]>("/backtest"),
  getBacktest: (id: number) => request<any>(`/backtest/${id}`),
  runWalkForward: (payload: any) =>
    request<any>("/backtest/walk-forward", { method: "POST", body: JSON.stringify(payload) }),

  // ML (Phase 6)
  trainModel: (strategyName: string) =>
    request<any>("/ml/train", { method: "POST", body: JSON.stringify({ strategy_name: strategyName }) }),
  listModels: () => request<any[]>("/ml/models"),

  // self-learning loop (Phase 8)
  diagnose: (strategyName?: string) =>
    request<any>(`/learning/diagnose${strategyName ? `?strategy_name=${strategyName}` : ""}`),
  runExperiment: (payload: any) =>
    request<any>("/learning/experiment", { method: "POST", body: JSON.stringify(payload) }),
  listExperiments: () => request<any[]>("/learning/experiments"),
  listActiveVersions: () => request<any[]>("/learning/active"),
  rollbackStrategy: (strategyName: string, reason: string) =>
    request<any>("/learning/rollback", { method: "POST", body: JSON.stringify({ strategy_name: strategyName, reason }) }),
};
