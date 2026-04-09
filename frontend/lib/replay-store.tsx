"use client";

import React, { createContext, useContext, useReducer, useCallback, useEffect, useRef } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface ReplaySession {
  replay_session_id: string;
  strategy_id: number;
  strategy_type?: string;
  symbol: string;
  start_time: string;
  end_time: string;
  speed: number;
  initial_capital: number;
  interval?: string;
  params?: Record<string, any>;
  status: "pending" | "running" | "paused" | "completed" | "failed";
  current_timestamp?: string;
  created_at: string;
  is_saved?: boolean;
}

export interface ReplayStatus {
  replay_session_id: string;
  status: "pending" | "running" | "paused" | "completed" | "failed";
  current_simulated_time: string;
  progress: number;
  pnl: number;
  elapsed_seconds?: number;  // 实际消耗时间(秒)
  equity_curve?: { t: string; v: number }[];
  // 健康状态监控字段
  error_count?: number;      // 回放过程中的错误数量
  warnings?: string[];       // 最近20条警告信息
  bars_processed?: number;   // 已处理的K线数量
  bars_total?: number;       // K线总数量
}

interface ReplayState {
  session: ReplaySession | null;
  status: ReplayStatus | null;
  isPolling: boolean;
  sessionIdFromUrl: string | null;
  // Store the last session ID for persistence across page navigation
  lastSessionId: string | null;
}

type ReplayAction =
  | { type: "SET_SESSION"; payload: ReplaySession }
  | { type: "SET_STATUS"; payload: ReplayStatus }
  | { type: "SET_URL_SESSION_ID"; payload: string | null }
  | { type: "UPDATE_STATUS_ONLY"; payload: Partial<ReplayStatus> }
  | { type: "CLEAR_SESSION" }
  | { type: "SET_POLLING"; payload: boolean }
  | { type: "SET_LAST_SESSION_ID"; payload: string | null }
  | { type: "RESTORE_FROM_STORAGE"; payload: { session: ReplaySession; status: ReplayStatus | null } };

// Storage key for persistence
const STORAGE_KEY = "quantagent_replay_session";

function loadStoredState(): Partial<ReplayState> {
  if (typeof window === "undefined") return {};
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return {
        lastSessionId: parsed.lastSessionId || null,
        session: parsed.session || null,
        status: parsed.status || null,
      };
    }
  } catch (e) {
    console.warn("Failed to load stored replay state:", e);
  }
  return {};
}

function clearStoredState() {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (e) {
    console.warn("Failed to clear stored replay state:", e);
  }
}

function saveStateToStorage(state: ReplayState) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      lastSessionId: state.lastSessionId,
      session: state.session,
      status: state.status,
    }));
  } catch (e) {
    console.warn("Failed to save replay state:", e);
  }
}

const initialState: ReplayState = {
  session: null,
  status: null,
  isPolling: false,
  sessionIdFromUrl: null,
  lastSessionId: null,
};

function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  let newState: ReplayState;
  switch (action.type) {
    case "SET_SESSION":
      newState = { ...state, session: action.payload, lastSessionId: action.payload.replay_session_id };
      break;
    case "SET_STATUS":
      newState = { ...state, status: action.payload };
      break;
    case "SET_URL_SESSION_ID":
      newState = { ...state, sessionIdFromUrl: action.payload };
      break;
    case "UPDATE_STATUS_ONLY":
      newState = {
        ...state,
        status: state.status ? { ...state.status, ...action.payload } : null,
      };
      break;
    case "CLEAR_SESSION":
      newState = { ...state, session: null, status: null, isPolling: false };
      break;
    case "SET_POLLING":
      newState = { ...state, isPolling: action.payload };
      break;
    case "SET_LAST_SESSION_ID":
      newState = { ...state, lastSessionId: action.payload };
      break;
    case "RESTORE_FROM_STORAGE":
      newState = {
        ...state,
        session: action.payload.session,
        status: action.payload.status,
        lastSessionId: action.payload.session.replay_session_id,
        sessionIdFromUrl: action.payload.session.replay_session_id,
      };
      break;
    default:
      return state;
  }
  // Auto-save to localStorage when state changes
  saveStateToStorage(newState);
  return newState;
}

// ─── Context ──────────────────────────────────────────────────────────────────
interface ReplayContextValue {
  state: ReplayState;
  dispatch: React.Dispatch<ReplayAction>;
  // Actions
  setSession: (session: ReplaySession) => void;
  setStatus: (status: ReplayStatus) => void;
  clearSession: () => void;
  setUrlSessionId: (id: string | null) => void;
  updateStatus: (updates: Partial<ReplayStatus>) => void;
  // Polling
  startPolling: (sessionId: string) => void;
  stopPolling: () => void;
  // Session restoration
  restoreSession: (sessionId: string) => Promise<void>;
}

const ReplayContext = createContext<ReplayContextValue | null>(null);

// ─── Provider ─────────────────────────────────────────────────────────────────
export function ReplayProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(replayReducer, initialState);
  const pollTimerRef = useRef<ReturnType<typeof globalThis.setInterval> | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);

  // Restore state from localStorage on mount
  // Always clear old session data so the page starts fresh.
  // Users should explicitly start a new replay or restore from the history list.
  useEffect(() => {
    clearStoredState();
    dispatch({ type: "CLEAR_SESSION" });
  }, []);

  // Start polling when polling state becomes true
  useEffect(() => {
    if (!state.isPolling || !currentSessionIdRef.current) return;
    
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
    }

    pollTimerRef.current = globalThis.setInterval(async () => {
      if (!currentSessionIdRef.current) return;
      
      try {
        const res = await fetch(`/api/v1/replay/${currentSessionIdRef.current}/status`);
        if (res.ok) {
          const data = await res.json();
          // Guard: only update status if response has valid status field
          if (data && typeof data.status === 'string') {
            dispatch({ type: "SET_STATUS", payload: data });

            // Update session status if session exists
            if (data.status === "completed" || data.status === "failed") {
              if (pollTimerRef.current) {
                clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
              }
              dispatch({ type: "SET_POLLING", payload: false });
            }
          }
        }
      } catch (e) {
        console.error("Polling failed", e);
      }
    }, 500);

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [state.isPolling]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    currentSessionIdRef.current = null;
    dispatch({ type: "SET_POLLING", payload: false });
  }, []);

  const startPolling = useCallback((sessionId: string) => {
    currentSessionIdRef.current = sessionId;
    dispatch({ type: "SET_POLLING", payload: true });
  }, []);

  const restoreSession = useCallback(async (sessionId: string) => {
    try {
      // Fetch full session detail
      const sessionRes = await fetch(`/api/v1/replay/${sessionId}`);
      if (!sessionRes.ok) {
        // Session not found or other error - clear invalid stored state
        console.warn(`Session ${sessionId} not found or error (${sessionRes.status}), clearing stored state`);
        clearStoredState();
        // Clear local session state as well
        dispatch({ type: "CLEAR_SESSION" });
        dispatch({ type: "SET_LAST_SESSION_ID", payload: null });
        return;
      }
      const sessionData = await sessionRes.json();

      // Guard: if the API returned an error object instead of session data, bail out
      if (!sessionRes.ok || !sessionData || !sessionData.replay_session_id) {
        console.warn("restoreSession: invalid response, skipping store update");
        return;
      }

      // Build full ReplaySession object
      const fullSession: ReplaySession = {
        replay_session_id: sessionData.replay_session_id,
        strategy_id: sessionData.strategy_id,
        strategy_type: sessionData.strategy_type,
        symbol: sessionData.symbol,
        start_time: sessionData.start_time,
        end_time: sessionData.end_time,
        speed: sessionData.speed,
        initial_capital: sessionData.initial_capital,
        interval: sessionData.params?.interval || "1m",
        params: sessionData.params,
        status: sessionData.status,
        current_timestamp: sessionData.current_timestamp,
        created_at: sessionData.created_at,
        is_saved: sessionData.is_saved,
      };
      dispatch({ type: "SET_SESSION", payload: fullSession });

      // Fetch current status
      const statusRes = await fetch(`/api/v1/replay/${sessionId}/status`);
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        dispatch({ type: "SET_STATUS", payload: statusData });
        
        // Resume polling only if session is paused
        if (statusData.status === "paused") {
          currentSessionIdRef.current = sessionId;
          dispatch({ type: "SET_POLLING", payload: true });
        }
      }
    } catch (err) {
      console.error("Restore session failed", err);
    }
  }, []);

  // ─── Page Unload Protection ────────────────────────────────────────────────────
  // Warn user before leaving page if replay is running
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      // Only warn if there's an active replay session
      if (state.session && (state.session.status === "running" || state.session.status === "paused")) {
        e.preventDefault();
        e.returnValue = "回放正在进行中，离开页面将不会中断后端回放，但前端界面将无法实时更新。确定要离开吗？";
        return e.returnValue;
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [state.session]);

  const setSession = useCallback((session: ReplaySession) => {
    dispatch({ type: "SET_SESSION", payload: session });
  }, []);

  const setStatus = useCallback((status: ReplayStatus) => {
    dispatch({ type: "SET_STATUS", payload: status });
  }, []);

  const clearSession = useCallback(() => {
    stopPolling();
    dispatch({ type: "CLEAR_SESSION" });
  }, [stopPolling]);

  const setUrlSessionId = useCallback((id: string | null) => {
    dispatch({ type: "SET_URL_SESSION_ID", payload: id });
  }, []);

  const updateStatus = useCallback((updates: Partial<ReplayStatus>) => {
    dispatch({ type: "UPDATE_STATUS_ONLY", payload: updates });
  }, []);

  const value: ReplayContextValue = {
    state,
    dispatch,
    setSession,
    setStatus,
    clearSession,
    setUrlSessionId,
    updateStatus,
    startPolling,
    stopPolling,
    restoreSession,
  };

  return (
    <ReplayContext.Provider value={value}>
      {children}
    </ReplayContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────
export function useReplayStore() {
  const context = useContext(ReplayContext);
  if (!context) {
    throw new Error("useReplayStore must be used within a ReplayProvider");
  }
  return context;
}
