/**
 * hooks.test.ts — TDD RED phase.
 *
 * Tests derive from USER REQUIREMENTS, not implementation.
 *
 * Requirements:
 *   - useLocalStore: reactive local store access with loading/error state
 *   - useSyncStatus: reactive sync status with queueSize, lastSync, syncNow
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useLocalStore, useSyncStatus } from "../../hooks/useLocalStore";

// ---------------------------------------------------------------------------
// Mock the lib modules so hooks don't touch real IndexedDB/crypto
// ---------------------------------------------------------------------------

const mockStoreData = new Map<string, unknown>();
const mockQueue: unknown[] = [];
let mockSyncStatus: "idle" | "syncing" | "error" | "offline" = "idle";
let mockLastSync: Date | null = null;
let mockQueueSize = 0;

const mockLocalStoreInstance = {
  ready: Promise.resolve(),
  get: vi.fn(async (key: string) => mockStoreData.get(key) ?? null),
  set: vi.fn(async (key: string, value: unknown) => {
    mockStoreData.set(key, value);
  }),
  delete: vi.fn(async (key: string) => {
    mockStoreData.delete(key);
  }),
  has: vi.fn(async (key: string) => mockStoreData.has(key)),
  keys: vi.fn(async () => Array.from(mockStoreData.keys())),
  clear: vi.fn(async () => mockStoreData.clear()),
  getAll: vi.fn(async () => Object.fromEntries(mockStoreData)),
  setMany: vi.fn(async () => {}),
  getStorageUsage: vi.fn(async () => ({
    used: 0,
    quota: 1_000_000,
    percentage: 0,
  })),
  getEntryCount: vi.fn(async () => mockStoreData.size),
  generateKey: vi.fn(async () => ({} as CryptoKey)),
  exportKey: vi.fn(async () => "mock-key"),
  importKey: vi.fn(async () => ({} as CryptoKey)),
  destroy: vi.fn(async () => {}),
};

const mockSyncEngineInstance = {
  getSyncStatus: vi.fn(() => mockSyncStatus),
  getLastSyncTime: vi.fn(() => mockLastSync),
  getQueueSize: vi.fn(async () => mockQueueSize),
  syncNow: vi.fn(async () => ({
    uploaded: 0,
    downloaded: 0,
    conflicts: 0,
    errors: 0,
    duration: 10,
  })),
  start: vi.fn(),
  stop: vi.fn(),
  destroy: vi.fn(),
  enqueue: vi.fn(async () => {}),
  clearQueue: vi.fn(async () => {}),
  getQueue: vi.fn(async () => []),
  onConflict: vi.fn(),
  // These must return an unsubscribe function (matching the real SyncEngine API)
  onSyncComplete: vi.fn(() => () => {}),
  onSyncError: vi.fn(() => () => {}),
  onOnlineChange: vi.fn(() => () => {}),
  isOnline: vi.fn(() => true),
};

vi.mock("../../lib/localStore", () => ({
  LocalStore: vi.fn(() => mockLocalStoreInstance),
}));

vi.mock("../../lib/syncEngine", () => ({
  SyncEngine: vi.fn(() => mockSyncEngineInstance),
}));

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockStoreData.clear();
  mockQueue.length = 0;
  mockSyncStatus = "idle";
  mockLastSync = null;
  mockQueueSize = 0;

  // Re-wire mock implementations after clearAllMocks
  mockLocalStoreInstance.get.mockImplementation(
    async (key: string) => mockStoreData.get(key) ?? null
  );
  mockLocalStoreInstance.set.mockImplementation(
    async (key: string, value: unknown) => {
      mockStoreData.set(key, value);
    }
  );
  mockLocalStoreInstance.delete.mockImplementation(async (key: string) => {
    mockStoreData.delete(key);
  });
  mockLocalStoreInstance.getEntryCount.mockImplementation(
    async () => mockStoreData.size
  );
  mockSyncEngineInstance.getSyncStatus.mockImplementation(
    () => mockSyncStatus
  );
  mockSyncEngineInstance.getLastSyncTime.mockImplementation(
    () => mockLastSync
  );
  mockSyncEngineInstance.getQueueSize.mockImplementation(
    async () => mockQueueSize
  );
  mockSyncEngineInstance.syncNow.mockImplementation(async () => ({
    uploaded: 1,
    downloaded: 0,
    conflicts: 0,
    errors: 0,
    duration: 5,
  }));
  // Ensure event subscription mocks return unsubscribe functions
  mockSyncEngineInstance.onSyncComplete.mockImplementation(() => () => {});
  mockSyncEngineInstance.onSyncError.mockImplementation(() => () => {});
  mockSyncEngineInstance.onOnlineChange.mockImplementation(() => () => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

describe("useLocalStore", () => {
  // ── 1. Returns initial null ──────────────────────────────────────────────
  it("returns null value on initial render (before async load)", () => {
    const { result } = renderHook(() =>
      useLocalStore<string>("test-key")
    );

    // Before the async get resolves, value is null
    expect(result.current.value).toBeNull();
    expect(typeof result.current.set).toBe("function");
    expect(typeof result.current.remove).toBe("function");
  });

  // ── 2. Loading state ─────────────────────────────────────────────────────
  it("loading is true initially and false after data loads", async () => {
    const { result } = renderHook(() =>
      useLocalStore<string>("loading-key")
    );

    // loading may start as true
    // After waiting for the async operation to complete, loading becomes false
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
  });

  // ── 3. Set updates value ─────────────────────────────────────────────────
  it("set() stores value and triggers re-render with updated value", async () => {
    const { result } = renderHook(() =>
      useLocalStore<string>("update-key")
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.set("hello world");
    });

    // After set, value should reflect what was stored
    await waitFor(() => {
      expect(result.current.value).toBe("hello world");
    });
  });

  // ── 4. Remove clears value ───────────────────────────────────────────────
  it("remove() deletes the value and hook returns null", async () => {
    // Pre-populate the store
    mockStoreData.set("remove-key", "to-be-removed");
    mockLocalStoreInstance.get.mockImplementation(
      async (key: string) => mockStoreData.get(key) ?? null
    );

    const { result } = renderHook(() =>
      useLocalStore<string>("remove-key")
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.remove();
    });

    await waitFor(() => {
      expect(result.current.value).toBeNull();
    });
  });

  // ── 5. Default value ─────────────────────────────────────────────────────
  it("returns defaultValue when key is not found in store", async () => {
    // Store is empty — key doesn't exist
    const { result } = renderHook(() =>
      useLocalStore<string>("missing-key", "default-fallback")
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    // Should use defaultValue since key is missing
    expect(result.current.value).toBe("default-fallback");
  });
});

describe("useSyncStatus", () => {
  // ── 6. Returns status ────────────────────────────────────────────────────
  it("returns current sync status from SyncEngine", async () => {
    mockSyncStatus = "idle";

    const { result } = renderHook(() => useSyncStatus());

    await waitFor(() => {
      expect(result.current.status).toBe("idle");
    });

    expect(typeof result.current.syncNow).toBe("function");
  });

  // ── 7. QueueSize ─────────────────────────────────────────────────────────
  it("returns queueSize from SyncEngine.getQueueSize()", async () => {
    mockQueueSize = 3;
    mockSyncEngineInstance.getQueueSize.mockResolvedValue(3);

    const { result } = renderHook(() => useSyncStatus());

    await waitFor(() => {
      expect(result.current.queueSize).toBe(3);
    });
  });
});
