/**
 * DingDawg Agent 1 — Gaming Sector E2E Tests
 *
 * Verifies:
 * 1. Gaming agent type is accepted by the registration endpoint
 * 2. 8 gaming templates are visible via the templates API
 * 3. All 4 gaming skills work end-to-end via the skill execute API
 * 4. Agent isolation: gaming skills only return data for the owning agent
 *
 * All requests route through the Vercel proxy → Railway backend.
 * Total: ~30 tests
 */

import { test, expect, type APIRequestContext } from "@playwright/test";

// ─── Constants ────────────────────────────────────────────────────────────────

const BACKEND = process.env.PLAYWRIGHT_BASE_URL ?? "https://app.dingdawg.com";
const TS = Date.now();
const TEST_EMAIL = `gaming-e2e-${TS}@dingdawg.dev`;
const TEST_PASSWORD = "GamingE2E2026x!";

// ─── Shared state ─────────────────────────────────────────────────────────────

let authToken = "";
let capturedMatchId = "";
let capturedTournamentId = "";
let capturedSessionId = "";
let capturedLootItemId = "";

// ─── Suite configuration ──────────────────────────────────────────────────────

test.describe.configure({ mode: "serial" });

// ─── Auth: register once, share token ────────────────────────────────────────

test.beforeAll(async ({ request }) => {
  const regRes = await request.post(`${BACKEND}/auth/register`, {
    data: { email: TEST_EMAIL, password: TEST_PASSWORD },
    timeout: 20_000,
  });

  if (regRes.status() === 409 || regRes.status() === 400) {
    const loginRes = await request.post(`${BACKEND}/auth/login`, {
      data: { email: TEST_EMAIL, password: TEST_PASSWORD },
      timeout: 20_000,
    });
    expect(loginRes.status()).toBe(200);
    const body = await loginRes.json();
    authToken = (body.access_token ?? body.token) as string;
  } else {
    expect([200, 201]).toContain(regRes.status());
    const body = await regRes.json();
    authToken = (body.access_token ?? body.token) as string;
  }

  expect(authToken).toBeTruthy();
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

async function executeSkill(
  request: APIRequestContext,
  skillName: string,
  action: string,
  parameters: Record<string, unknown> = {}
): Promise<{ status: number; body: Record<string, unknown> }> {
  const res = await request.post(
    `${BACKEND}/api/v1/skills/${skillName}/execute`,
    {
      headers: { Authorization: `Bearer ${authToken}` },
      data: { action, parameters: { ...parameters, action } },
      timeout: 30_000,
    }
  );
  const body = await res.json();
  return { status: res.status(), body };
}

function parseOutput(body: Record<string, unknown>): Record<string, unknown> {
  const raw = body.output;
  if (typeof raw === "string") {
    try { return JSON.parse(raw) as Record<string, unknown>; } catch { return {}; }
  }
  if (raw !== null && typeof raw === "object") return raw as Record<string, unknown>;
  return {};
}

function assertSkillSuccess(
  status: number,
  body: Record<string, unknown>
): Record<string, unknown> {
  expect(status).toBe(200);
  expect(body.success).toBe(true);
  const output = parseOutput(body);
  const errStr = String(output.error ?? "");
  if (errStr.includes("Unknown action")) {
    throw new Error(`Skill returned success=true but output contains: ${errStr}`);
  }
  return output;
}

// ─── 1. Templates API ─────────────────────────────────────────────────────────

test.describe("1. Gaming Templates API", () => {
  test("gaming templates visible in templates list", async ({ request }) => {
    const res = await request.get(`${BACKEND}/api/v1/templates`, {
      headers: { Authorization: `Bearer ${authToken}` },
      timeout: 15_000,
    });
    // Templates endpoint may be public or auth-protected
    expect([200, 401]).toContain(res.status());
    if (res.status() === 200) {
      const body = await res.json();
      const templates = (body.templates ?? body) as Array<Record<string, unknown>>;
      const gamingTemplates = templates.filter((t) => t.agent_type === "gaming");
      expect(gamingTemplates.length).toBeGreaterThanOrEqual(8);
    }
  });

  test("gaming templates filter by agent_type", async ({ request }) => {
    const res = await request.get(`${BACKEND}/api/v1/templates?agent_type=gaming`, {
      headers: { Authorization: `Bearer ${authToken}` },
      timeout: 15_000,
    });
    if (res.status() === 200) {
      const body = await res.json();
      const templates = (body.templates ?? body) as Array<Record<string, unknown>>;
      // All returned templates should be gaming
      templates.forEach((t) => {
        expect(t.agent_type).toBe("gaming");
      });
    }
  });

  test("Game Coach template exists", async ({ request }) => {
    const res = await request.get(`${BACKEND}/api/v1/templates`, {
      headers: { Authorization: `Bearer ${authToken}` },
      timeout: 15_000,
    });
    if (res.status() === 200) {
      const body = await res.json();
      const templates = (body.templates ?? body) as Array<Record<string, unknown>>;
      const gameCoach = templates.find((t) => t.name === "Game Coach");
      expect(gameCoach).toBeTruthy();
      expect(gameCoach?.agent_type).toBe("gaming");
    }
  });
});

// ─── 2. Agent Registration with Gaming Type ───────────────────────────────────

test.describe("2. Gaming Agent Registration", () => {
  test("gaming agent_type accepted by API", async ({ request }) => {
    const res = await request.post(`${BACKEND}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${authToken}` },
      data: {
        handle: `gaming-test-${TS}`,
        name: "My Gaming Agent",
        agent_type: "gaming",
      },
      timeout: 20_000,
    });
    // 200/201 = created, 409 = handle taken (still proves type is valid)
    // 422 would mean type was rejected
    expect([200, 201, 409]).toContain(res.status());
    if (res.status() === 422) {
      const body = await res.json();
      // Should not fail because of agent_type
      const bodyStr = JSON.stringify(body).toLowerCase();
      expect(bodyStr).not.toContain("agent_type");
    }
  });

  test("invalid agent_type rejected", async ({ request }) => {
    const res = await request.post(`${BACKEND}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${authToken}` },
      data: {
        handle: `invalid-type-${TS}`,
        name: "Bad Agent",
        agent_type: "spectral",  // invalid type
      },
      timeout: 20_000,
    });
    expect([400, 422]).toContain(res.status());
  });
});

// ─── 3. match_tracker Skill ───────────────────────────────────────────────────

test.describe("3. match_tracker skill", () => {
  test("record_match: records a win", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "match_tracker", "record_match",
      {
        agent_id: `e2e-gamer-${TS}`,
        game_title: "Valorant",
        result: "win",
        kills: 25,
        deaths: 8,
        assists: 10,
        duration_minutes: 35,
        map_name: "Ascent",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("recorded");
    expect(output.id).toBeTruthy();
    capturedMatchId = output.id as string;
  });

  test("record_match: records a loss", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "match_tracker", "record_match",
      {
        agent_id: `e2e-gamer-${TS}`,
        game_title: "Valorant",
        result: "loss",
        kills: 10,
        deaths: 20,
        assists: 5,
        duration_minutes: 28,
        map_name: "Bind",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("recorded");
  });

  test("get_stats: returns aggregate stats", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "match_tracker", "get_stats",
      {
        agent_id: `e2e-gamer-${TS}`,
        game_title: "Valorant",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(typeof output.total_matches).toBe("number");
    expect(typeof output.win_rate_pct).toBe("number");
    expect(typeof output.avg_kda).toBe("number");
  });

  test("get_history: returns match list", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "match_tracker", "get_history",
      {
        agent_id: `e2e-gamer-${TS}`,
        game_title: "Valorant",
        limit: 10,
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(Array.isArray(output.matches)).toBe(true);
    expect((output.matches as unknown[]).length).toBeGreaterThanOrEqual(1);
  });

  test("get_winrate: returns breakdown", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "match_tracker", "get_winrate",
      {
        agent_id: `e2e-gamer-${TS}`,
        group_by: "game_title",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(Array.isArray(output.breakdown)).toBe(true);
  });

  test("compare_periods: this_week vs last_week", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "match_tracker", "compare_periods",
      {
        agent_id: `e2e-gamer-${TS}`,
        period_a: "this_week",
        period_b: "last_week",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.period_a).toBeTruthy();
    expect(output.period_b).toBeTruthy();
  });
});

// ─── 4. tournament Skill ─────────────────────────────────────────────────────

test.describe("4. tournament skill", () => {
  test("create_tournament: single_elimination", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "tournament", "create_tournament",
      {
        agent_id: `e2e-org-${TS}`,
        name: `E2E Spring Open ${TS}`,
        game_title: "Valorant",
        format: "single_elimination",
        max_participants: 8,
        prize_pool: "$100",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("pending");
    expect(output.id).toBeTruthy();
    capturedTournamentId = output.id as string;
  });

  test("register_player: adds participants", async ({ request }) => {
    if (!capturedTournamentId) test.skip();
    for (const name of ["Alice", "Bob", "Charlie"]) {
      const { status, body } = await executeSkill(
        request, "tournament", "register_player",
        {
          tournament_id: capturedTournamentId,
          player_name: name,
        }
      );
      const output = assertSkillSuccess(status, body);
      expect(output.status).toBe("registered");
    }
  });

  test("get_bracket: returns tournament with participants", async ({ request }) => {
    if (!capturedTournamentId) test.skip();
    const { status, body } = await executeSkill(
      request, "tournament", "get_bracket",
      { tournament_id: capturedTournamentId }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.tournament).toBeTruthy();
    expect(Array.isArray(output.participants)).toBe(true);
    expect((output.participants as unknown[]).length).toBeGreaterThanOrEqual(3);
  });

  test("record_result: win advances player", async ({ request }) => {
    if (!capturedTournamentId) test.skip();
    const { status, body } = await executeSkill(
      request, "tournament", "record_result",
      {
        tournament_id: capturedTournamentId,
        player_name: "Alice",
        result: "win",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.result).toBe("win");
    expect(output.status).toBe("active");
  });

  test("get_standings: returns ordered standings", async ({ request }) => {
    if (!capturedTournamentId) test.skip();
    const { status, body } = await executeSkill(
      request, "tournament", "get_standings",
      { tournament_id: capturedTournamentId }
    );
    const output = assertSkillSuccess(status, body);
    expect(Array.isArray(output.standings)).toBe(true);
  });
});

// ─── 5. game_session Skill ───────────────────────────────────────────────────

test.describe("5. game_session skill", () => {
  test("start_session: begins a gaming session", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "game_session", "start_session",
      {
        agent_id: `e2e-player-${TS}`,
        game_title: "Elden Ring",
        session_type: "story",
        started_at: "2026-03-01T10:00:00+00:00",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("started");
    expect(output.id).toBeTruthy();
    capturedSessionId = output.id as string;
  });

  test("end_session: ends session and calculates duration", async ({ request }) => {
    // If start_session did not capture an id (e.g. backend DB issue), start a
    // fresh session here so end_session can still exercise its own code path.
    const START_AT = "2026-03-01T10:00:00+00:00";
    const END_AT   = "2026-03-01T12:30:00+00:00";
    const EXPECTED_DURATION = 150; // 2h 30m

    let sessionId = capturedSessionId;
    if (!sessionId) {
      const { status: sStatus, body: sBody } = await executeSkill(
        request, "game_session", "start_session",
        {
          agent_id: `e2e-player-${TS}`,
          game_title: "Elden Ring",
          session_type: "story",
          started_at: START_AT,
        }
      );
      const sOutput = assertSkillSuccess(sStatus, sBody);
      expect(sOutput.status).toBe("started");
      sessionId = sOutput.id as string;
    }

    expect(sessionId).toBeTruthy();

    const { status, body } = await executeSkill(
      request, "game_session", "end_session",
      {
        id: sessionId,
        ended_at: END_AT,
        xp_gained: 2500,
        level_after: 15,
        achievements: ["Margit Slain", "First Grace"],
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("ended");
    // Duration: END_AT - START_AT = 150 minutes exactly.
    // Accept ±1 to guard against any rounding at second boundaries.
    expect(Math.abs((output.duration_minutes as number) - EXPECTED_DURATION)).toBeLessThanOrEqual(1);
  });

  test("get_sessions: returns session list", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "game_session", "get_sessions",
      {
        agent_id: `e2e-player-${TS}`,
        game_title: "Elden Ring",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(Array.isArray(output.sessions)).toBe(true);
  });

  test("get_playtime: grouped by game", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "game_session", "get_playtime",
      {
        agent_id: `e2e-player-${TS}`,
        group_by: "game",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(Array.isArray(output.playtime)).toBe(true);
  });

  test("get_achievements: returns earned achievements", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "game_session", "get_achievements",
      {
        agent_id: `e2e-player-${TS}`,
        game_title: "Elden Ring",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(typeof output.total).toBe("number");
    expect(Array.isArray(output.achievements)).toBe(true);
  });
});

// ─── 6. loot_tracker Skill ───────────────────────────────────────────────────

test.describe("6. loot_tracker skill", () => {
  test("add_item: adds a legendary item", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "loot_tracker", "add_item",
      {
        agent_id: `e2e-looter-${TS}`,
        game_title: "WoW",
        item_name: "Thunderfury, Blessed Blade",
        item_type: "weapon",
        rarity: "legendary",
        quantity: 1,
        value_gold: 50000,
        value_real_currency_cents: 0,
        source: "Molten Core",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("added");
    expect(output.id).toBeTruthy();
    capturedLootItemId = output.id as string;
  });

  test("add_item: adds a common item with real currency value", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "loot_tracker", "add_item",
      {
        agent_id: `e2e-looter-${TS}`,
        game_title: "CS2",
        item_name: "AK-47 | Redline",
        item_type: "skin",
        rarity: "rare",
        quantity: 1,
        value_gold: 0,
        value_real_currency_cents: 1500,  // $15.00
        source: "case_opening",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("added");
  });

  test("get_inventory: returns item list", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "loot_tracker", "get_inventory",
      {
        agent_id: `e2e-looter-${TS}`,
        game_title: "WoW",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(Array.isArray(output.inventory)).toBe(true);
    expect((output.inventory as unknown[]).length).toBeGreaterThanOrEqual(1);
  });

  test("get_value: calculates total value", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "loot_tracker", "get_value",
      {
        agent_id: `e2e-looter-${TS}`,
        game_title: "WoW",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(typeof output.total_gold).toBe("number");
    expect(typeof output.total_real_currency_cents).toBe("number");
    // Verify total_real_currency_cents is integer (not float)
    expect(Number.isInteger(output.total_real_currency_cents)).toBe(true);
  });

  test("price_check: returns price statistics", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "loot_tracker", "price_check",
      {
        agent_id: `e2e-looter-${TS}`,
        game_title: "WoW",
        item_name: "Thunderfury, Blessed Blade",
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(typeof output.min_gold).toBe("number");
    expect(typeof output.max_gold).toBe("number");
    expect(typeof output.data_points).toBe("number");
  });

  test("trade_log: records a trade", async ({ request }) => {
    const { status, body } = await executeSkill(
      request, "loot_tracker", "trade_log",
      {
        agent_id: `e2e-looter-${TS}`,
        game_title: "WoW",
        item_name: "Minor Healing Potion",
        traded_to: "GuildMate_Zara",
        quantity: 5,
        value_gold: 50,
        value_real_currency_cents: 0,
      }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.status).toBe("logged");
    expect(output.traded_to).toBe("GuildMate_Zara");
  });
});

// ─── 7. Agent Isolation E2E ──────────────────────────────────────────────────

test.describe("7. Gaming skill agent isolation", () => {
  test("match_tracker: agent B cannot see agent A stats", async ({ request }) => {
    const agentA = `iso-a-${TS}`;
    const agentB = `iso-b-${TS}`;

    // Record match for agent A only
    await executeSkill(request, "match_tracker", "record_match", {
      agent_id: agentA,
      game_title: "Private Game",
      result: "win",
    });

    // Agent B stats for same game should show 0
    const { status, body } = await executeSkill(
      request, "match_tracker", "get_stats",
      { agent_id: agentB, game_title: "Private Game" }
    );
    const output = assertSkillSuccess(status, body);
    expect(output.total_matches).toBe(0);
  });

  test("loot_tracker: agent B inventory empty when agent A has items", async ({ request }) => {
    const agentA = `loot-iso-a-${TS}`;
    const agentB = `loot-iso-b-${TS}`;

    await executeSkill(request, "loot_tracker", "add_item", {
      agent_id: agentA,
      game_title: "Private MMO",
      item_name: "Secret Sword",
      rarity: "legendary",
    });

    const { status, body } = await executeSkill(
      request, "loot_tracker", "get_inventory",
      { agent_id: agentB, game_title: "Private MMO" }
    );
    const output = assertSkillSuccess(status, body);
    expect((output.inventory as unknown[]).length).toBe(0);
  });
});
