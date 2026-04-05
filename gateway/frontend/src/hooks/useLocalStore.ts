"use client";

/**
 * useLocalStore.ts — React hooks for Privacy-First Local Data (Item 2.7)
 *
 * useLocalStore<T>:
 *   Reactive access to a single key in the encrypted local store.
 *   Returns current value, loading state, error state, and set/remove actions.
 *
 * useSyncStatus:
 *   Reactive view of the SyncEngine status: sync status string, queue size,
 *   last sync timestamp, and a manual syncNow() trigger.
 */

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import { LocalStore } from "@/lib/localStore";
import { SyncEngine } from "@/lib/syncEngine";
import type { StorageTier } from "@/lib/localStore";
import type { SyncStatus, SyncResult } from "@/lib/syncEngine";

// ---------------------------------------------------------------------------
// Module-level singletons
// ---------------------------------------------------------------------------

// A single LocalStore instance shared across all hook users in the same page.
// Re-created only when the module is first imported.
let _sharedStore: LocalStore | null = null;
let _sharedEngine: SyncEngine | null = null;

function getSharedStore(): LocalStore {
  if (!_sharedStore) {
    _sharedStore = new LocalStore();
  }
  return _sharedStore;
}

function getSharedEngine(): SyncEngine {
  if (!_sharedEngine) {
    const store = getSharedStore();
    _sharedEngine = new SyncEngine(store, {
      apiBaseUrl:
        typeof window !== "undefined"
          ? window.location.origin
          : "",
    });
    _sharedEngine.start();
  }
  return _sharedEngine;
}

// ---------------------------------------------------------------------------
// useLocalStore
// ---------------------------------------------------------------------------

export interface UseLocalStoreResult<T> {
  /** Current stored value, or defaultValue/null if not found. */
  value: T | null;
  /** True while the initial async read is in progress. */
  loading: boolean;
  /** Error message if the last operation failed, or null. */
  error: string | null;
  /**
   * Store a new value under the hook's key.
   * @param value - Any JSON-serialisable value.
   * @param tier  - Storage tier (default: 'local').
   */
  set: (value: T, tier?: StorageTier) => Promise<void>;
  /** Delete the value stored under the hook's key. */
  remove: () => Promise<void>;
}

/**
 * Reactive hook for accessing a single key in the encrypted local store.
 *
 * @param key          - The storage key to read/write.
 * @param defaultValue - Value returned when the key is not found.
 */
export function useLocalStore<T = unknown>(
  key: string,
  defaultValue?: T
): UseLocalStoreResult<T> {
  const store = useMemo(() => getSharedStore(), []);

  const [value, setValue] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track whether the component is still mounted to avoid state updates after unmount
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Load the initial value from the store on mount (and when key changes)
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);

      try {
        await store.ready;
        const stored = await store.get<T>(key);

        if (!cancelled && mountedRef.current) {
          if (stored !== null) {
            setValue(stored);
          } else if (defaultValue !== undefined) {
            setValue(defaultValue);
          } else {
            setValue(null);
          }
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled && mountedRef.current) {
          const message =
            err instanceof Error ? err.message : "Failed to read from local store.";
          setError(message);
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [key, store, defaultValue]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Actions ───────────────────────────────────────────────────────────────

  const set = useCallback(
    async (newValue: T, tier: StorageTier = "local"): Promise<void> => {
      setError(null);
      try {
        await store.set(key, newValue, tier);
        if (mountedRef.current) {
          setValue(newValue);
        }

        // For hybrid entries, also enqueue for cloud sync
        if (tier === "hybrid") {
          const engine = getSharedEngine();
          await engine.enqueue({
            id: `${key}-${Date.now()}`,
            key,
            operation: "set",
            data: newValue,
            timestamp: Date.now(),
            retries: 0,
          });
        }
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to write to local store.";
        if (mountedRef.current) {
          setError(message);
        }
        throw err;
      }
    },
    [key, store]
  );

  const remove = useCallback(async (): Promise<void> => {
    setError(null);
    try {
      await store.delete(key);
      if (mountedRef.current) {
        setValue(null);
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to delete from local store.";
      if (mountedRef.current) {
        setError(message);
      }
      throw err;
    }
  }, [key, store]);

  return { value, loading, error, set, remove };
}

// ---------------------------------------------------------------------------
// useSyncStatus
// ---------------------------------------------------------------------------

export interface UseSyncStatusResult {
  /** Current sync engine status. */
  status: SyncStatus;
  /** Number of entries currently queued for cloud sync. */
  queueSize: number;
  /** Timestamp of the last successful sync, or null if never synced. */
  lastSync: Date | null;
  /** Trigger an immediate sync pass. */
  syncNow: () => Promise<void>;
}

/**
 * Reactive hook for monitoring and controlling the SyncEngine.
 *
 * Polls the engine's status and queue size on a short interval so the UI
 * stays up-to-date without requiring direct access to the engine instance.
 */
export function useSyncStatus(): UseSyncStatusResult {
  const engine = useMemo(() => getSharedEngine(), []);

  const [status, setStatus] = useState<SyncStatus>(() =>
    engine.getSyncStatus()
  );
  const [queueSize, setQueueSize] = useState<number>(0);
  const [lastSync, setLastSync] = useState<Date | null>(() =>
    engine.getLastSyncTime()
  );

  // Track mount state
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Subscribe to sync completion events
  useEffect(() => {
    const unsubComplete = engine.onSyncComplete((result: SyncResult) => {
      void result;
      if (!mountedRef.current) return;
      setStatus(engine.getSyncStatus());
      setLastSync(engine.getLastSyncTime());

      // Refresh queue size after sync
      engine.getQueueSize().then((size) => {
        if (mountedRef.current) setQueueSize(size);
      }).catch(() => {
        // Ignore queue size errors
      });
    });

    const unsubError = engine.onSyncError(() => {
      if (!mountedRef.current) return;
      setStatus(engine.getSyncStatus());
    });

    const unsubOnline = engine.onOnlineChange(() => {
      if (!mountedRef.current) return;
      setStatus(engine.getSyncStatus());
    });

    // Initial queue size fetch
    engine.getQueueSize().then((size) => {
      if (mountedRef.current) setQueueSize(size);
    }).catch(() => {
      // Ignore initial queue size errors
    });

    return () => {
      unsubComplete();
      unsubError();
      unsubOnline();
    };
  }, [engine]);

  const syncNow = useCallback(async (): Promise<void> => {
    setStatus("syncing");
    try {
      await engine.syncNow();
    } finally {
      if (mountedRef.current) {
        setStatus(engine.getSyncStatus());
        setLastSync(engine.getLastSyncTime());
        const size = await engine.getQueueSize().catch(() => 0);
        if (mountedRef.current) setQueueSize(size);
      }
    }
  }, [engine]);

  return { status, queueSize, lastSync, syncNow };
}
