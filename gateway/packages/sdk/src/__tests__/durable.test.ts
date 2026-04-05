/**
 * DurableDingDawgClient — unit tests for DDAG v1 TypeScript SDK
 */

import { jest, describe, it, expect, beforeEach } from "@jest/globals";
import { DurableDingDawgClient, AgentFSMState } from "../durable.js";
import { DingDawgApiError } from "../client.js";

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function makeFetch(body: unknown, ok = true, status = 200) {
  return jest.fn(async () => ({
    ok,
    status,
    headers: { get: () => "application/json" },
    json: async () => body,
  })) as unknown as typeof fetch;
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const DURABLE_RESPONSE = {
  reply: "Compliance report generated.",
  session_id: "sess-ddag-001",
  timestamp: "2026-04-05T12:00:00Z",
  checkpoint_cid: "ipfs:QmTestCID123",
  step_index: 3,
  verified: true,
  fsm_state: "done",
  proof_cid: "ipfs:QmProof456",
};

const SOUL_RESPONSE = {
  soul_id: "soul-001",
  agent_id: "acme-support",
  soul_cid: "ipfs:QmSoul789",
  mission: "Govern AI reliably.",
  learned_prefs: { preferred_model: "gpt-5.4" },
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-05T12:00:00Z",
};

const CHECKPOINT_RESPONSE = {
  session_id: "sess-ddag-001",
  step_index: 3,
  state_cid: "ipfs:QmCheckpoint321",
  fsm_state: "checkpointed",
  created_at: "2026-04-05T12:00:00Z",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DurableDingDawgClient — construction", () => {
  it("extends DingDawgClient — all namespaces present", () => {
    const client = new DurableDingDawgClient({ apiKey: "dd_test_key" });
    expect(typeof client.agent.sendMessage).toBe("function");
    expect(typeof client.billing.currentMonth).toBe("function");
    expect(typeof client.invokeWithCheckpoint).toBe("function");
    expect(typeof client.resume).toBe("function");
    expect(typeof client.getSoul).toBe("function");
    expect(typeof client.getCheckpoint).toBe("function");
  });

  it("throws TypeError on empty apiKey", () => {
    expect(() => new DurableDingDawgClient({ apiKey: "" })).toThrow(TypeError);
  });
});

describe("DurableDingDawgClient — invokeWithCheckpoint", () => {
  it("returns DurableResponse with checkpoint_cid and fsm_state", async () => {
    global.fetch = makeFetch(DURABLE_RESPONSE);
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    const result = await client.invokeWithCheckpoint("acme-support", {
      message: "Run compliance report",
      userId: "user_123",
    });
    expect(result.reply).toBe("Compliance report generated.");
    expect(result.checkpoint_cid).toBe("ipfs:QmTestCID123");
    expect(result.step_index).toBe(3);
    expect(result.verified).toBe(true);
    expect(result.fsm_state).toBe(AgentFSMState.Done);
    expect(result.proof_cid).toBe("ipfs:QmProof456");
  });

  it("sends to correct durable invoke endpoint", async () => {
    const mock = makeFetch(DURABLE_RESPONSE);
    global.fetch = mock;
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    await client.invokeWithCheckpoint("acme-support", { message: "Hello" });
    const [url] = (mock as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v2/agents/acme-support/durable/invoke");
  });

  it("sends Idempotency-Key header when idempotency_key is set", async () => {
    const mock = makeFetch(DURABLE_RESPONSE);
    global.fetch = mock;
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    await client.invokeWithCheckpoint("acme-support", {
      message: "Hello",
      idempotency_key: "my-idem-key-001",
    });
    const [, init] = (mock as jest.Mock).mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBe("my-idem-key-001");
  });

  it("includes resume_cid in payload when provided", async () => {
    const mock = makeFetch(DURABLE_RESPONSE);
    global.fetch = mock;
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    await client.invokeWithCheckpoint("acme-support", {
      message: "Continue task",
      resume_cid: "ipfs:QmPriorCID",
    });
    const [, init] = (mock as jest.Mock).mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.resume_cid).toBe("ipfs:QmPriorCID");
  });

  it("throws DingDawgApiError on 500 response", async () => {
    global.fetch = makeFetch({ detail: "server error" }, false, 500);
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    await expect(
      client.invokeWithCheckpoint("acme-support", { message: "fail" })
    ).rejects.toBeInstanceOf(DingDawgApiError);
  });
});

describe("DurableDingDawgClient — resume", () => {
  it("calls resume endpoint with checkpoint_cid in body", async () => {
    const mock = makeFetch({ ...DURABLE_RESPONSE, fsm_state: "running" });
    global.fetch = mock;
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    const result = await client.resume("acme-support", "ipfs:QmPriorCID");
    const [url, init] = (mock as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v2/agents/acme-support/durable/resume");
    const body = JSON.parse(init.body as string);
    expect(body.checkpoint_cid).toBe("ipfs:QmPriorCID");
    expect(result.fsm_state).toBe(AgentFSMState.Running);
  });
});

describe("DurableDingDawgClient — getSoul", () => {
  it("returns AgentSoul with all fields", async () => {
    global.fetch = makeFetch(SOUL_RESPONSE);
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    const soul = await client.getSoul("acme-support");
    expect(soul.soul_id).toBe("soul-001");
    expect(soul.soul_cid).toBe("ipfs:QmSoul789");
    expect(soul.mission).toBe("Govern AI reliably.");
    expect(soul.learned_prefs["preferred_model"]).toBe("gpt-5.4");
  });

  it("calls correct soul endpoint", async () => {
    const mock = makeFetch(SOUL_RESPONSE);
    global.fetch = mock;
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    await client.getSoul("acme-support");
    const [url] = (mock as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v2/agents/acme-support/soul");
  });
});

describe("DurableDingDawgClient — getCheckpoint", () => {
  it("returns CheckpointState when found", async () => {
    global.fetch = makeFetch(CHECKPOINT_RESPONSE);
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    const ckpt = await client.getCheckpoint("acme-support", "sess-ddag-001");
    expect(ckpt).not.toBeNull();
    expect(ckpt!.state_cid).toBe("ipfs:QmCheckpoint321");
    expect(ckpt!.fsm_state).toBe(AgentFSMState.Checkpointed);
    expect(ckpt!.step_index).toBe(3);
  });

  it("returns null on 404", async () => {
    global.fetch = makeFetch({ detail: "Not found" }, false, 404);
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    const ckpt = await client.getCheckpoint("acme-support", "unknown-session");
    expect(ckpt).toBeNull();
  });

  it("rethrows non-404 errors", async () => {
    global.fetch = makeFetch({ detail: "server error" }, false, 500);
    const client = new DurableDingDawgClient({ apiKey: "dd_test" });
    await expect(
      client.getCheckpoint("acme-support", "sess-001")
    ).rejects.toBeInstanceOf(DingDawgApiError);
  });
});

describe("AgentFSMState enum", () => {
  it("has all 10 states", () => {
    const states = Object.values(AgentFSMState);
    expect(states).toContain("idle");
    expect(states).toContain("running");
    expect(states).toContain("tool_pending");
    expect(states).toContain("verifying");
    expect(states).toContain("committing");
    expect(states).toContain("remediating");
    expect(states).toContain("checkpointed");
    expect(states).toContain("resuming");
    expect(states).toContain("done");
    expect(states).toContain("failed");
    expect(states).toHaveLength(10);
  });
});
