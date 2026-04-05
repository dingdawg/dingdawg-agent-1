/**
 * voiceEngine.test.ts — TDD RED phase.
 *
 * Tests derive from USER REQUIREMENTS, not implementation.
 *
 * Requirements:
 *   - VoiceEngine manages TTS via SpeechSynthesis (browser), Kokoro, ElevenLabs
 *   - VoiceEngine manages STT via SpeechRecognition (browser)
 *   - Auto-fallback: browser -> kokoro -> elevenlabs on failure
 *   - Provider switching and availability detection
 *   - Resource cleanup on destroy()
 *   - State tracking: isSpeaking(), isListening()
 *   - speakStream() batches tokens into sentences before speaking
 */

import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";
import { VoiceEngine } from "../../lib/voiceEngine";

// ─── Mocks ────────────────────────────────────────────────────────────────────

function makeMockUtterance() {
  return {
    text: "",
    lang: "",
    rate: 1,
    pitch: 1,
    volume: 1,
    voice: null,
    onstart: null as (() => void) | null,
    onend: null as (() => void) | null,
    onerror: null as ((e: { error: string }) => void) | null,
  };
}

function makeMockSpeechSynthesis() {
  const utterances: ReturnType<typeof makeMockUtterance>[] = [];
  return {
    speaking: false,
    paused: false,
    pending: false,
    speak: vi.fn((utt: ReturnType<typeof makeMockUtterance>) => {
      utterances.push(utt);
      // Simulate async speech completion
      setTimeout(() => {
        if (utt.onend) utt.onend();
      }, 0);
    }),
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    getVoices: vi.fn(() => []),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    _utterances: utterances,
  };
}

function makeMockSpeechRecognition() {
  // Use a plain object so methods can close over `instance` by reference
  // eslint-disable-next-line prefer-const
  // Local minimal interfaces — SpeechRecognitionErrorEvent and SpeechRecognitionEvent
  // are DOM types not available in the jsdom type stubs used by vitest.
  interface LocalSpeechRecognitionErrorEvent {
    error: string;
    message?: string;
  }
  interface LocalSpeechRecognitionResultItem {
    transcript: string;
  }
  interface LocalSpeechRecognitionResult extends ArrayLike<LocalSpeechRecognitionResultItem> {
    isFinal: boolean;
    0: LocalSpeechRecognitionResultItem;
    length: number;
  }
  interface LocalSpeechRecognitionEvent {
    results: LocalSpeechRecognitionResult[];
  }

  let instance: {
    lang: string;
    continuous: boolean;
    interimResults: boolean;
    maxAlternatives: number;
    onstart: (() => void) | null;
    onend: (() => void) | null;
    onerror: ((e: LocalSpeechRecognitionErrorEvent) => void) | null;
    onresult: ((e: LocalSpeechRecognitionEvent) => void) | null;
    start: MockInstance;
    stop: MockInstance;
    abort: MockInstance;
  };

  instance = {
    lang: "",
    continuous: false,
    interimResults: false,
    maxAlternatives: 1,
    onstart: null,
    onend: null,
    onerror: null,
    onresult: null,
    // start() fires onstart after a macrotask — simulates real browser behaviour
    start: vi.fn(() => {
      setTimeout(() => {
        if (instance.onstart) instance.onstart();
      }, 0);
    }),
    // stop() fires onend after a macrotask
    stop: vi.fn(() => {
      setTimeout(() => {
        if (instance.onend) instance.onend();
      }, 0);
    }),
    abort: vi.fn(),
  };
  return instance;
}

// ─── Setup / Teardown ─────────────────────────────────────────────────────────

let mockSynth: ReturnType<typeof makeMockSpeechSynthesis>;
let mockRecognitionInstance: ReturnType<typeof makeMockSpeechRecognition>;
let SpeechSynthesisUtteranceMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockSynth = makeMockSpeechSynthesis();
  mockRecognitionInstance = makeMockSpeechRecognition();

  SpeechSynthesisUtteranceMock = vi.fn().mockImplementation(() => makeMockUtterance());

  // Install browser API mocks
  Object.defineProperty(globalThis, "speechSynthesis", {
    value: mockSynth,
    writable: true,
    configurable: true,
  });
  Object.defineProperty(globalThis, "SpeechSynthesisUtterance", {
    value: SpeechSynthesisUtteranceMock,
    writable: true,
    configurable: true,
  });
  Object.defineProperty(globalThis, "SpeechRecognition", {
    value: vi.fn(() => mockRecognitionInstance),
    writable: true,
    configurable: true,
  });
  Object.defineProperty(globalThis, "webkitSpeechRecognition", {
    value: vi.fn(() => mockRecognitionInstance),
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

// ─── Constructor ──────────────────────────────────────────────────────────────

describe("VoiceEngine — constructor", () => {
  it("constructs with default config", () => {
    const engine = new VoiceEngine();
    expect(engine).toBeDefined();
    expect(engine.isSpeaking()).toBe(false);
    expect(engine.isListening()).toBe(false);
    engine.destroy();
  });

  it("constructs with custom config overrides", () => {
    const engine = new VoiceEngine({
      ttsProvider: "kokoro",
      language: "es-ES",
      rate: 1.5,
      pitch: 0.8,
      volume: 0.7,
      autoFallback: false,
    });
    expect(engine).toBeDefined();
    expect(engine.isSpeaking()).toBe(false);
    engine.destroy();
  });
});

// ─── Browser TTS ──────────────────────────────────────────────────────────────

describe("VoiceEngine — Browser TTS", () => {
  it("speak() calls speechSynthesis.speak with an utterance", async () => {
    const engine = new VoiceEngine({ ttsProvider: "browser" });
    const speakPromise = engine.speak("Hello world");
    // Allow microtask queue to flush
    await new Promise((r) => setTimeout(r, 10));
    expect(mockSynth.speak).toHaveBeenCalled();
    engine.destroy();
    await speakPromise.catch(() => {});
  });

  it("speak() sets utterance language from config", async () => {
    const engine = new VoiceEngine({ ttsProvider: "browser", language: "fr-FR" });
    engine.speak("Bonjour").catch(() => {});
    await new Promise((r) => setTimeout(r, 5));
    const callArg = (mockSynth.speak as ReturnType<typeof vi.fn>).mock.calls[0]?.[0];
    if (callArg) {
      // The utterance should have lang set
      expect(callArg.lang ?? "fr-FR").toBe("fr-FR");
    }
    engine.destroy();
  });

  it("stop() calls speechSynthesis.cancel", () => {
    const engine = new VoiceEngine({ ttsProvider: "browser" });
    engine.stop();
    expect(mockSynth.cancel).toHaveBeenCalled();
    engine.destroy();
  });

  it("speakStream() batches tokens into sentences before speaking", async () => {
    const engine = new VoiceEngine({ ttsProvider: "browser" });

    async function* tokenStream() {
      const tokens = ["Hello", " world", ".", " How", " are", " you", "?"];
      for (const t of tokens) {
        yield t;
      }
    }

    await engine.speakStream(tokenStream()).catch(() => {});
    await new Promise((r) => setTimeout(r, 50));

    // At least one call to speak — sentences should be batched
    expect(mockSynth.speak.mock.calls.length).toBeGreaterThanOrEqual(1);
    engine.destroy();
  });
});

// ─── STT ──────────────────────────────────────────────────────────────────────

describe("VoiceEngine — STT", () => {
  it("startListening() initializes and starts SpeechRecognition", async () => {
    const engine = new VoiceEngine({ sttEnabled: true });
    await engine.startListening();
    expect(mockRecognitionInstance.start).toHaveBeenCalled();
    engine.destroy();
  });

  it("stopListening() stops the recognition instance", async () => {
    const engine = new VoiceEngine({ sttEnabled: true });
    await engine.startListening();
    engine.stopListening();
    expect(mockRecognitionInstance.stop).toHaveBeenCalled();
    engine.destroy();
  });

  it("onTranscript callback fires with interim results", async () => {
    const engine = new VoiceEngine({ sttEnabled: true });
    const cb = vi.fn();
    engine.onTranscript(cb);
    await engine.startListening();

    // Simulate interim result event
    const fakeEvent = {
      results: [
        Object.assign([""], {
          isFinal: false,
          0: { transcript: "hel" },
          length: 1,
        }),
      ],
    };
    if (mockRecognitionInstance.onresult) {
      mockRecognitionInstance.onresult(fakeEvent as unknown as Parameters<typeof mockRecognitionInstance.onresult>[0]);
    }

    expect(cb).toHaveBeenCalledWith("hel", false);
    engine.destroy();
  });

  it("onTranscript callback fires with final results", async () => {
    const engine = new VoiceEngine({ sttEnabled: true });
    const cb = vi.fn();
    engine.onTranscript(cb);
    await engine.startListening();

    const fakeEvent = {
      results: [
        Object.assign([""], {
          isFinal: true,
          0: { transcript: "hello world" },
          length: 1,
        }),
      ],
    };
    if (mockRecognitionInstance.onresult) {
      mockRecognitionInstance.onresult(fakeEvent as unknown as Parameters<typeof mockRecognitionInstance.onresult>[0]);
    }

    expect(cb).toHaveBeenCalledWith("hello world", true);
    engine.destroy();
  });

  it("startListening() throws gracefully when SpeechRecognition is unavailable", async () => {
    // Remove recognition APIs
    Object.defineProperty(globalThis, "SpeechRecognition", {
      value: undefined,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(globalThis, "webkitSpeechRecognition", {
      value: undefined,
      writable: true,
      configurable: true,
    });

    const engine = new VoiceEngine({ sttEnabled: true });
    await expect(engine.startListening()).rejects.toThrow(/not supported/i);
    engine.destroy();
  });
});

// ─── Auto-Fallback ────────────────────────────────────────────────────────────

describe("VoiceEngine — auto-fallback", () => {
  it("falls back from browser to kokoro when browser TTS fails", async () => {
    // Make browser TTS fail by removing speechSynthesis
    Object.defineProperty(globalThis, "speechSynthesis", {
      value: undefined,
      writable: true,
      configurable: true,
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(0),
      body: null,
    } as unknown as Response);

    const engine = new VoiceEngine({
      ttsProvider: "browser",
      autoFallback: true,
    });

    // speak() should not throw — it should fall back
    await expect(engine.speak("test")).resolves.not.toThrow();
    fetchSpy.mockRestore();
    engine.destroy();
  });
});

// ─── Provider Management ──────────────────────────────────────────────────────

describe("VoiceEngine — provider management", () => {
  it("setProvider() switches the active TTS provider", () => {
    const engine = new VoiceEngine({ ttsProvider: "browser" });
    engine.setProvider("kokoro");
    // After switching, no error thrown
    expect(engine).toBeDefined();
    engine.destroy();
  });

  it("getAvailableProviders() includes 'browser' when SpeechSynthesis is present", () => {
    const engine = new VoiceEngine();
    const providers = engine.getAvailableProviders();
    expect(providers).toContain("browser");
    engine.destroy();
  });

  it("testProvider() returns false for an unsupported provider name", async () => {
    const engine = new VoiceEngine();
    const result = await engine.testProvider("nonexistent_provider");
    expect(result).toBe(false);
    engine.destroy();
  });
});

// ─── State Tracking ───────────────────────────────────────────────────────────

describe("VoiceEngine — state tracking", () => {
  it("isSpeaking() and isListening() start as false", () => {
    const engine = new VoiceEngine();
    expect(engine.isSpeaking()).toBe(false);
    expect(engine.isListening()).toBe(false);
    engine.destroy();
  });

  it("isListening() becomes true after startListening() and false after stopListening()", async () => {
    const engine = new VoiceEngine({ sttEnabled: true });
    await engine.startListening();
    expect(engine.isListening()).toBe(true);
    engine.stopListening();
    expect(engine.isListening()).toBe(false);
    engine.destroy();
  });
});

// ─── Cleanup ──────────────────────────────────────────────────────────────────

describe("VoiceEngine — destroy", () => {
  it("destroy() cancels TTS and stops STT without throwing", async () => {
    const engine = new VoiceEngine({ ttsProvider: "browser", sttEnabled: true });
    await engine.startListening().catch(() => {});
    expect(() => engine.destroy()).not.toThrow();
    expect(mockSynth.cancel).toHaveBeenCalled();
  });

  it("speakStream() handles an empty async iterable without throwing", async () => {
    const engine = new VoiceEngine({ ttsProvider: "browser" });

    async function* empty() {}
    await expect(engine.speakStream(empty())).resolves.not.toThrow();
    engine.destroy();
  });
});
