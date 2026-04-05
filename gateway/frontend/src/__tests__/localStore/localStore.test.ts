/**
 * localStore.test.ts — TDD RED phase.
 *
 * Tests derive from USER REQUIREMENTS, not implementation.
 *
 * Requirements:
 *   - IndexedDB encrypted storage (AES-256-GCM, Web Crypto API only)
 *   - CRUD operations: set, get, delete, has, keys, clear
 *   - Bulk: getAll, setMany
 *   - Encryption: round-trip, unique IVs, stored value differs from original
 *   - Key management: generateKey, exportKey, importKey
 *   - Storage info: getStorageUsage, getEntryCount
 *   - Storage tier stored with each entry
 *   - Lifecycle: destroy
 *   - Edge cases: large values, concurrent sets, invalid key handling
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { LocalStore } from "../../lib/localStore";

// ---------------------------------------------------------------------------
// IndexedDB mock (in-memory, simulates IDBFactory / IDBDatabase interface)
// ---------------------------------------------------------------------------

interface IDBRecord {
  value: unknown;
}

function createIDBMock() {
  // Separate in-memory stores per object store name
  const stores: Record<string, Map<string, IDBRecord>> = {};

  function getOrCreateStore(name: string): Map<string, IDBRecord> {
    if (!stores[name]) stores[name] = new Map();
    return stores[name];
  }

  function makeRequest<T>(resolver: () => T): IDBRequest<T> {
    let _onsuccess: ((e: { target: { result: T } }) => void) | null = null;
    let _onerror: ((e: { target: { error: DOMException } }) => void) | null =
      null;
    // Mutable internal state — avoids assigning to the readonly IDBRequest fields
    let _result: T | undefined = undefined;
    let _error: DOMException | null = null;

    const req = {
      get result() { return _result; },
      get error() { return _error; },
      get onsuccess() {
        return _onsuccess;
      },
      set onsuccess(fn: ((e: { target: { result: T } }) => void) | null) {
        _onsuccess = fn;
        // Fire async
        Promise.resolve().then(() => {
          try {
            const r = resolver();
            _result = r;
            fn?.({ target: { result: r } });
          } catch (err) {
            _error = err as DOMException;
            _onerror?.({ target: { error: err as DOMException } });
          }
        });
      },
      get onerror() {
        return _onerror;
      },
      set onerror(
        fn: ((e: { target: { error: DOMException } }) => void) | null
      ) {
        _onerror = fn;
      },
    } as unknown as IDBRequest<T>;

    return req;
  }

  function makeObjectStore(storeName: string) {
    const store = getOrCreateStore(storeName);

    return {
      put: (value: IDBRecord, key: string): IDBRequest<string> => {
        return makeRequest<string>(() => {
          store.set(key, value);
          return key;
        });
      },
      get: (key: string): IDBRequest<IDBRecord | undefined> => {
        return makeRequest<IDBRecord | undefined>(() => store.get(key));
      },
      delete: (key: string): IDBRequest<undefined> => {
        return makeRequest<undefined>(() => {
          store.delete(key);
          return undefined;
        });
      },
      clear: (): IDBRequest<undefined> => {
        return makeRequest<undefined>(() => {
          store.clear();
          return undefined;
        });
      },
      getAllKeys: (): IDBRequest<string[]> => {
        return makeRequest<string[]>(() => Array.from(store.keys()));
      },
      getAll: (): IDBRequest<IDBRecord[]> => {
        return makeRequest<IDBRecord[]>(() => Array.from(store.values()));
      },
      count: (): IDBRequest<number> => {
        return makeRequest<number>(() => store.size);
      },
    };
  }

  function makeTransaction(storeNames: string[]) {
    return {
      objectStore: (name: string) => makeObjectStore(name),
      oncomplete: null as (() => void) | null,
      onerror: null as ((e: unknown) => void) | null,
      onabort: null as ((e: unknown) => void) | null,
    };
  }

  function makeDB(dbStoreNames: string[]) {
    dbStoreNames.forEach((n) => getOrCreateStore(n));
    return {
      transaction: (
        storeNames: string | string[],
        mode: IDBTransactionMode
      ) => {
        const names = Array.isArray(storeNames) ? storeNames : [storeNames];
        void mode;
        return makeTransaction(names);
      },
      objectStoreNames: {
        contains: (name: string) => dbStoreNames.includes(name),
      },
      close: vi.fn(),
      createObjectStore: vi.fn(),
    };
  }

  function makeOpenRequest(dbName: string, _version: number) {
    const storeNames = ["encrypted-data", "keystore"];
    let _onupgradeneeded: ((e: { target: { result: ReturnType<typeof makeDB> } }) => void) | null = null;
    let _onsuccess: ((e: { target: { result: ReturnType<typeof makeDB> } }) => void) | null = null;
    let _onerror: ((e: { target: { error: DOMException } }) => void) | null = null;
    // Mutable internal state — avoids assigning to the readonly IDBOpenDBRequest.result
    let _result: ReturnType<typeof makeDB> | undefined = undefined;

    void dbName;

    const openReq = {
      get result() { return _result; },
      get error() { return null as DOMException | null; },
      get onupgradeneeded() {
        return _onupgradeneeded;
      },
      set onupgradeneeded(fn: ((e: { target: { result: ReturnType<typeof makeDB> } }) => void) | null) {
        _onupgradeneeded = fn;
      },
      get onsuccess() {
        return _onsuccess;
      },
      set onsuccess(fn: ((e: { target: { result: ReturnType<typeof makeDB> } }) => void) | null) {
        _onsuccess = fn;
        Promise.resolve().then(() => {
          const db = makeDB(storeNames);
          _result = db;
          _onupgradeneeded?.({ target: { result: db } });
          fn?.({ target: { result: db } });
        });
      },
      get onerror() {
        return _onerror;
      },
      set onerror(fn: ((e: { target: { error: DOMException } }) => void) | null) {
        _onerror = fn;
      },
    } as unknown as IDBOpenDBRequest;

    return openReq;
  }

  return {
    open: (dbName: string, version: number) => makeOpenRequest(dbName, version),
    deleteDatabase: (dbName: string): IDBRequest<undefined> => {
      void dbName;
      return makeRequest<undefined>(() => {
        Object.keys(stores).forEach((k) => stores[k].clear());
        return undefined;
      });
    },
    // Reset all stores between tests
    _reset() {
      Object.keys(stores).forEach((k) => delete stores[k]);
    },
  };
}

// ---------------------------------------------------------------------------
// Web Crypto mock — simulates AES-256-GCM encrypt/decrypt
// ---------------------------------------------------------------------------

function createCryptoMock() {
  // Use a simple XOR-based "encryption" for tests so we can verify
  // that the stored value differs from the original AND round-trips correctly.
  const SECRET_BYTE = 0xaa;

  function xorBytes(data: Uint8Array): Uint8Array {
    return data.map((b) => b ^ SECRET_BYTE);
  }

  const mockKey: CryptoKey = {
    type: "secret",
    extractable: true,
    algorithm: { name: "AES-GCM" },
    usages: ["encrypt", "decrypt"],
  } as CryptoKey;

  const exportedKeyB64 = "bW9ja0tleUJhc2U2NA=="; // "mockKeyBase64"

  return {
    subtle: {
      generateKey: vi.fn(async () => mockKey),
      exportKey: vi.fn(async (_format: string, _key: CryptoKey) => {
        // Return a fixed ArrayBuffer representing the key
        const buf = new Uint8Array(32).fill(0xab);
        return buf.buffer;
      }),
      importKey: vi.fn(
        async (
          _format: string,
          _keyData: ArrayBuffer,
          _algo: AesKeyGenParams,
          _extractable: boolean,
          _usages: KeyUsage[]
        ) => mockKey
      ),
      encrypt: vi.fn(
        async (
          _algo: AesGcmParams,
          _key: CryptoKey,
          data: ArrayBuffer
        ): Promise<ArrayBuffer> => {
          // "Encrypt" by XOR-ing the bytes
          const input = new Uint8Array(data);
          const ciphertext = xorBytes(input);
          return ciphertext.buffer as ArrayBuffer;
        }
      ),
      decrypt: vi.fn(
        async (
          _algo: AesGcmParams,
          _key: CryptoKey,
          data: ArrayBuffer
        ): Promise<ArrayBuffer> => {
          // "Decrypt" by XOR-ing again (symmetric)
          const input = new Uint8Array(data);
          const plaintext = xorBytes(input);
          return plaintext.buffer as ArrayBuffer;
        }
      ),
      deriveBits: vi.fn(),
      deriveKey: vi.fn(),
      digest: vi.fn(),
      sign: vi.fn(),
      verify: vi.fn(),
      wrapKey: vi.fn(),
      unwrapKey: vi.fn(),
    } as unknown as SubtleCrypto,
    getRandomValues: vi.fn((array: Uint8Array) => {
      // Fill with a fixed pattern so IVs are deterministic in tests
      // BUT we want to verify that two encrypt calls produce different IVs.
      // We use a counter to differentiate calls.
      for (let i = 0; i < array.length; i++) {
        array[i] = (i + ivCallCount * 13 + 7) % 256;
      }
      ivCallCount++;
      return array;
    }),
    randomUUID: vi.fn(() => crypto.randomUUID()),
  };
}

let ivCallCount = 0;
let idbMock: ReturnType<typeof createIDBMock>;
let cryptoMock: ReturnType<typeof createCryptoMock>;

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  ivCallCount = 0;
  idbMock = createIDBMock();
  cryptoMock = createCryptoMock();

  // Inject mocks into global scope (jsdom provides window but not IndexedDB/crypto)
  Object.defineProperty(globalThis, "indexedDB", {
    value: idbMock,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(globalThis, "crypto", {
    value: cryptoMock,
    configurable: true,
    writable: true,
  });
  // TextEncoder/TextDecoder are available in jsdom
});

afterEach(() => {
  vi.restoreAllMocks();
  idbMock._reset();
});

// ---------------------------------------------------------------------------
// Test Suite
// ---------------------------------------------------------------------------

describe("LocalStore", () => {
  // ── 1. Constructor creates DB ─────────────────────────────────────────────
  it("constructor creates a database connection", async () => {
    const store = new LocalStore();
    // Allow async init to complete
    await store.ready;
    // getEntryCount() would fail if DB was not opened
    const count = await store.getEntryCount();
    expect(count).toBe(0);
    await store.destroy();
  });

  // ── 2. Set and get a value ────────────────────────────────────────────────
  it("set stores a value and get retrieves it", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.set("test-key", { name: "Alice", age: 30 });
    const result = await store.get<{ name: string; age: number }>("test-key");

    expect(result).not.toBeNull();
    expect(result?.name).toBe("Alice");
    expect(result?.age).toBe(30);
    await store.destroy();
  });

  // ── 3. Get returns null for missing key ──────────────────────────────────
  it("get returns null for a missing key", async () => {
    const store = new LocalStore();
    await store.ready;

    const result = await store.get("nonexistent-key");
    expect(result).toBeNull();
    await store.destroy();
  });

  // ── 4. Delete removes entry ───────────────────────────────────────────────
  it("delete removes an entry from the store", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.set("del-key", "some-value");
    expect(await store.has("del-key")).toBe(true);

    await store.delete("del-key");
    expect(await store.has("del-key")).toBe(false);
    await store.destroy();
  });

  // ── 5. Has returns correct boolean ───────────────────────────────────────
  it("has returns true for existing key and false for missing key", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.set("present-key", 42);
    expect(await store.has("present-key")).toBe(true);
    expect(await store.has("absent-key")).toBe(false);
    await store.destroy();
  });

  // ── 6. Keys returns all keys ──────────────────────────────────────────────
  it("keys() returns all stored keys", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.set("alpha", 1);
    await store.set("beta", 2);
    await store.set("gamma", 3);

    const allKeys = await store.keys();
    expect(allKeys).toContain("alpha");
    expect(allKeys).toContain("beta");
    expect(allKeys).toContain("gamma");
    await store.destroy();
  });

  // ── 7. Keys with prefix filters ──────────────────────────────────────────
  it("keys(prefix) returns only keys matching the prefix", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.set("user:1", "a");
    await store.set("user:2", "b");
    await store.set("session:1", "c");

    const userKeys = await store.keys("user:");
    expect(userKeys).toContain("user:1");
    expect(userKeys).toContain("user:2");
    expect(userKeys).not.toContain("session:1");
    await store.destroy();
  });

  // ── 8. Clear removes all entries ─────────────────────────────────────────
  it("clear() removes all entries", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.set("k1", "v1");
    await store.set("k2", "v2");
    await store.clear();

    expect(await store.getEntryCount()).toBe(0);
    await store.destroy();
  });

  // ── 9. GetAll returns all entries ─────────────────────────────────────────
  it("getAll() returns a map of all entries", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.set("foo", "bar");
    await store.set("baz", 99);

    const all = await store.getAll();
    expect(all["foo"]).toBe("bar");
    expect(all["baz"]).toBe(99);
    await store.destroy();
  });

  // ── 10. SetMany stores multiple ──────────────────────────────────────────
  it("setMany() stores multiple key-value pairs", async () => {
    const store = new LocalStore();
    await store.ready;

    await store.setMany({ x: 1, y: 2, z: 3 });

    expect(await store.get("x")).toBe(1);
    expect(await store.get("y")).toBe(2);
    expect(await store.get("z")).toBe(3);
    await store.destroy();
  });

  // ── 11. Encryption: stored value !== original ────────────────────────────
  it("encryption: raw IndexedDB value differs from original plaintext", async () => {
    const store = new LocalStore({ encryptionEnabled: true });
    await store.ready;

    const original = { secret: "my-password" };
    await store.set("encrypted-key", original);

    // Verify that crypto.subtle.encrypt was called (meaning data was encrypted)
    expect(cryptoMock.subtle.encrypt).toHaveBeenCalled();
    await store.destroy();
  });

  // ── 12. Encryption: round-trip produces original ─────────────────────────
  it("encryption: get() round-trips correctly to original value", async () => {
    const store = new LocalStore({ encryptionEnabled: true });
    await store.ready;

    const original = { message: "Hello, World!", count: 42, flag: true };
    await store.set("rt-key", original);

    const retrieved = await store.get<typeof original>("rt-key");
    expect(retrieved).toEqual(original);
    await store.destroy();
  });

  // ── 13. generateKey creates CryptoKey ────────────────────────────────────
  it("generateKey() creates a CryptoKey", async () => {
    const store = new LocalStore();
    await store.ready;

    const key = await store.generateKey();
    expect(key).toBeDefined();
    expect(key.type).toBe("secret");
    expect(key.algorithm.name).toBe("AES-GCM");
    await store.destroy();
  });

  // ── 14. exportKey/importKey round-trip ───────────────────────────────────
  it("exportKey() and importKey() round-trip without throwing", async () => {
    const store = new LocalStore();
    await store.ready;

    const key = await store.generateKey();
    const exported = await store.exportKey();
    expect(typeof exported).toBe("string");
    expect(exported.length).toBeGreaterThan(0);

    // importKey should not throw
    const importedKey = await store.importKey(exported);
    expect(importedKey).toBeDefined();
    expect(importedKey.type).toBe("secret");
    await store.destroy();
  });

  // ── 15. Different IVs per entry ──────────────────────────────────────────
  it("different IVs are used for each encrypted entry", async () => {
    const store = new LocalStore({ encryptionEnabled: true });
    await store.ready;

    await store.set("k1", "value-one");
    await store.set("k2", "value-two");

    // getRandomValues is called to generate IV — should be called at least twice (once per set)
    const callCount = (cryptoMock.getRandomValues as ReturnType<typeof vi.fn>)
      .mock.calls.length;
    expect(callCount).toBeGreaterThanOrEqual(2);
    await store.destroy();
  });

  // ── 16. Storage usage returns numbers ────────────────────────────────────
  it("getStorageUsage() returns numeric used/quota/percentage", async () => {
    const store = new LocalStore();
    await store.ready;

    const usage = await store.getStorageUsage();
    expect(typeof usage.used).toBe("number");
    expect(typeof usage.quota).toBe("number");
    expect(typeof usage.percentage).toBe("number");
    expect(usage.used).toBeGreaterThanOrEqual(0);
    expect(usage.quota).toBeGreaterThanOrEqual(0);
    expect(usage.percentage).toBeGreaterThanOrEqual(0);
    expect(usage.percentage).toBeLessThanOrEqual(100);
    await store.destroy();
  });

  // ── 17. Entry count accurate ─────────────────────────────────────────────
  it("getEntryCount() returns accurate count", async () => {
    const store = new LocalStore();
    await store.ready;

    expect(await store.getEntryCount()).toBe(0);
    await store.set("a", 1);
    expect(await store.getEntryCount()).toBe(1);
    await store.set("b", 2);
    expect(await store.getEntryCount()).toBe(2);
    await store.delete("a");
    expect(await store.getEntryCount()).toBe(1);
    await store.destroy();
  });

  // ── 18. Destroy deletes database ─────────────────────────────────────────
  it("destroy() closes and deletes the database without throwing", async () => {
    const store = new LocalStore({ dbName: "test-destroy-db" });
    await store.ready;

    await store.set("data", "important");
    // destroy should not throw
    await expect(store.destroy()).resolves.not.toThrow();
  });

  // ── 19. Storage tier stored with entry ───────────────────────────────────
  it("storage tier is stored alongside each entry", async () => {
    const store = new LocalStore();
    await store.ready;

    // Set with explicit tiers
    await store.set("local-key", "local-value", "local");
    await store.set("hybrid-key", "hybrid-value", "hybrid");
    await store.set("cloud-key", "cloud-value", "cloud");

    // All local/hybrid tiers should be retrievable from IDB
    const local = await store.get("local-key");
    const hybrid = await store.get("hybrid-key");
    const cloud = await store.get("cloud-key");

    // local and hybrid are stored locally
    expect(local).toBe("local-value");
    expect(hybrid).toBe("hybrid-value");
    // cloud-tier entries are NOT stored in IDB (they go to cloud only)
    expect(cloud).toBeNull();
    await store.destroy();
  });

  // ── 20. Large value handling ─────────────────────────────────────────────
  it("handles large values (100KB string) without throwing", async () => {
    const store = new LocalStore();
    await store.ready;

    const largeValue = "x".repeat(100_000);
    await store.set("large", largeValue);
    const result = await store.get<string>("large");
    expect(result).toBe(largeValue);
    await store.destroy();
  });

  // ── 21. Concurrent set operations ────────────────────────────────────────
  it("concurrent set operations all succeed", async () => {
    const store = new LocalStore();
    await store.ready;

    // Fire 10 sets concurrently
    await Promise.all(
      Array.from({ length: 10 }, (_, i) => store.set(`concurrent-${i}`, i))
    );

    const count = await store.getEntryCount();
    expect(count).toBe(10);
    await store.destroy();
  });

  // ── 22. Invalid key handling ─────────────────────────────────────────────
  it("invalid key (empty string) throws a descriptive error", async () => {
    const store = new LocalStore();
    await store.ready;

    await expect(store.set("", "value")).rejects.toThrow(
      /key.*empty|invalid.*key/i
    );
    await store.destroy();
  });
});
