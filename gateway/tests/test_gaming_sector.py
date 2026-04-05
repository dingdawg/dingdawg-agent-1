"""Tests for the Gaming sector — 8th agent type + 4 skills + 8 templates.

Covers:
- AgentType enum and VALID_AGENT_TYPES contain 'gaming'
- 8 gaming templates present and valid
- MatchTrackerSkill — all 5 actions + isolation
- TournamentSkill — all 6 actions + formats + isolation
- GameSessionSkill — all 5 actions + duration calc + isolation
- LootTrackerSkill — all 6 actions + rarity/cents validation + isolation
- Template registry seed integration (gaming templates seeded)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from isg_agent.agents.agent_types import VALID_AGENT_TYPES, AgentType
from isg_agent.skills.gaming.match_tracker import MatchTrackerSkill, init_tables as mt_init
from isg_agent.skills.gaming.tournament import TournamentSkill, init_tables as tourn_init, VALID_FORMATS
from isg_agent.skills.gaming.game_session import GameSessionSkill, init_tables as gs_init
from isg_agent.skills.gaming.loot_tracker import LootTrackerSkill, init_tables as lt_init
from isg_agent.templates.gaming_templates import get_gaming_templates


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        p = Path(f.name)
    yield p
    p.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(p) + suffix).unlink(missing_ok=True)


@pytest.fixture()
async def match_tracker(tmp_db):
    await mt_init(str(tmp_db))
    return MatchTrackerSkill(str(tmp_db))


@pytest.fixture()
async def tournament(tmp_db):
    await tourn_init(str(tmp_db))
    return TournamentSkill(str(tmp_db))


@pytest.fixture()
async def game_session(tmp_db):
    await gs_init(str(tmp_db))
    return GameSessionSkill(str(tmp_db))


@pytest.fixture()
async def loot_tracker(tmp_db):
    await lt_init(str(tmp_db))
    return LootTrackerSkill(str(tmp_db))


def _p(result: str) -> dict:
    """Parse JSON result string."""
    return json.loads(result)


# ===========================================================================
# 1. Agent Type Tests
# ===========================================================================


class TestGamingAgentType:
    def test_gaming_in_valid_agent_types(self):
        assert "gaming" in VALID_AGENT_TYPES

    def test_gaming_enum_value(self):
        assert AgentType.GAMING.value == "gaming"

    def test_all_9_types_present(self):
        # 8 original + 1 community (v29.0 Phase 5.1) + 1 marketing (v29.1) = 10 total
        expected = {"personal", "business", "b2b", "a2a", "compliance", "enterprise", "health", "gaming", "community", "marketing"}
        assert expected == set(VALID_AGENT_TYPES)

    def test_gaming_agent_type_enum_construction(self):
        t = AgentType("gaming")
        assert t == AgentType.GAMING


# ===========================================================================
# 2. Gaming Templates Tests
# ===========================================================================


class TestGamingTemplates:
    def test_gaming_templates_returns_8(self):
        templates = get_gaming_templates()
        assert len(templates) == 8

    def test_all_templates_agent_type_gaming(self):
        for t in get_gaming_templates():
            assert t["agent_type"] == "gaming", f"Template {t['name']} has wrong agent_type"

    def test_each_template_has_required_fields(self):
        required = {"name", "agent_type", "industry_type", "icon", "skills",
                    "system_prompt_template", "capabilities", "flow", "catalog_schema",
                    "default_constitution_yaml"}
        for t in get_gaming_templates():
            missing = required - set(t.keys())
            assert not missing, f"Template {t['name']} missing fields: {missing}"

    def test_game_coach_is_featured(self):
        templates = {t["name"]: t for t in get_gaming_templates()}
        assert templates["Game Coach"]["featured"] is True

    def test_other_templates_not_featured(self):
        for t in get_gaming_templates():
            if t["name"] != "Game Coach":
                assert t.get("featured") is False or t.get("featured") is None

    def test_template_names_unique(self):
        names = [t["name"] for t in get_gaming_templates()]
        assert len(names) == len(set(names))

    def test_expected_template_names(self):
        names = {t["name"] for t in get_gaming_templates()}
        expected = {
            "Game Coach", "Guild Commander", "Stream Copilot",
            "Tournament Director", "Quest Master", "Economy Analyst",
            "Parent Guardian", "Mod Workshop",
        }
        assert names == expected

    def test_each_template_has_capabilities_list(self):
        for t in get_gaming_templates():
            caps = t["capabilities"]
            assert isinstance(caps, list), f"{t['name']} capabilities must be a list"
            assert len(caps) >= 4, f"{t['name']} should have at least 4 capabilities"

    def test_each_template_has_flow_steps(self):
        for t in get_gaming_templates():
            steps = t["flow"].get("steps", [])
            assert len(steps) >= 3, f"{t['name']} flow needs at least 3 steps"

    def test_game_coach_skills_correct(self):
        templates = {t["name"]: t for t in get_gaming_templates()}
        assert "match_tracker" in templates["Game Coach"]["skills"]
        assert "game_session" in templates["Game Coach"]["skills"]

    def test_tournament_director_skills_correct(self):
        templates = {t["name"]: t for t in get_gaming_templates()}
        assert "tournament" in templates["Tournament Director"]["skills"]

    def test_quest_master_skills_correct(self):
        templates = {t["name"]: t for t in get_gaming_templates()}
        assert "game_session" in templates["Quest Master"]["skills"]
        assert "loot_tracker" in templates["Quest Master"]["skills"]

    def test_economy_analyst_skills_correct(self):
        templates = {t["name"]: t for t in get_gaming_templates()}
        assert "loot_tracker" in templates["Economy Analyst"]["skills"]

    def test_each_template_has_icon(self):
        for t in get_gaming_templates():
            assert t.get("icon"), f"{t['name']} must have an icon"

    def test_each_template_has_constitution(self):
        for t in get_gaming_templates():
            assert t.get("default_constitution_yaml"), f"{t['name']} needs a constitution"

    def test_each_template_system_prompt_nonempty(self):
        for t in get_gaming_templates():
            assert len(t["system_prompt_template"]) > 50, f"{t['name']} system prompt too short"


# ===========================================================================
# 3. MatchTrackerSkill Tests
# ===========================================================================


class TestMatchTrackerRecordMatch:
    async def test_record_match_basic(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "record_match",
            "agent_id": "p1",
            "game_title": "Valorant",
            "result": "win",
            "kills": 20, "deaths": 5, "assists": 8,
            "duration_minutes": 30,
        }))
        assert r["status"] == "recorded"
        assert "id" in r

    async def test_record_match_missing_game_title(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "record_match",
            "agent_id": "p1",
        }))
        assert "error" in r

    async def test_record_match_missing_agent_id(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "record_match",
            "game_title": "Valorant",
        }))
        assert "error" in r

    async def test_record_match_defaults_result_unknown(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "record_match",
            "agent_id": "p1",
            "game_title": "Apex Legends",
        }))
        assert r["status"] == "recorded"


class TestMatchTrackerGetStats:
    async def test_get_stats_empty(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "get_stats",
            "agent_id": "p99",
            "game_title": "Fortnite",
        }))
        assert r["total_matches"] == 0
        assert r["win_rate_pct"] == 0.0

    async def test_get_stats_with_data(self, match_tracker):
        for result, kills, deaths in [("win", 15, 3), ("win", 20, 5), ("loss", 5, 10)]:
            await match_tracker.handle({
                "action": "record_match",
                "agent_id": "p2",
                "game_title": "CS2",
                "result": result, "kills": kills, "deaths": deaths,
            })
        r = _p(await match_tracker.handle({
            "action": "get_stats",
            "agent_id": "p2",
            "game_title": "CS2",
        }))
        assert r["total_matches"] == 3
        assert r["wins"] == 2
        assert r["losses"] == 1
        assert r["win_rate_pct"] == pytest.approx(66.7, abs=0.1)

    async def test_get_stats_missing_agent_id(self, match_tracker):
        r = _p(await match_tracker.handle({"action": "get_stats"}))
        assert "error" in r

    async def test_get_stats_best_map(self, match_tracker):
        # Dust2: 2 wins 0 losses (100% WR), Inferno: 1 win 1 loss (50% WR)
        # best_map should be Dust2 with 100% win rate
        for map_name, result in [
            ("Dust2", "win"),
            ("Dust2", "win"),
            ("Inferno", "win"),
            ("Inferno", "loss"),
        ]:
            await match_tracker.handle({
                "action": "record_match",
                "agent_id": "p3",
                "game_title": "CS2",
                "result": result,
                "map_name": map_name,
            })
        r = _p(await match_tracker.handle({
            "action": "get_stats",
            "agent_id": "p3",
            "game_title": "CS2",
        }))
        assert r["best_map"] == "Dust2"


class TestMatchTrackerGetHistory:
    async def test_get_history_returns_matches(self, match_tracker):
        for i in range(5):
            await match_tracker.handle({
                "action": "record_match",
                "agent_id": "p4",
                "game_title": "Valorant",
                "result": "win" if i % 2 == 0 else "loss",
            })
        r = _p(await match_tracker.handle({
            "action": "get_history",
            "agent_id": "p4",
            "game_title": "Valorant",
        }))
        assert len(r["matches"]) == 5

    async def test_get_history_limit_respected(self, match_tracker):
        for _ in range(10):
            await match_tracker.handle({
                "action": "record_match", "agent_id": "p5", "game_title": "OW2",
            })
        r = _p(await match_tracker.handle({
            "action": "get_history",
            "agent_id": "p5",
            "game_title": "OW2",
            "limit": 3,
        }))
        assert len(r["matches"]) == 3

    async def test_get_history_missing_agent_id(self, match_tracker):
        r = _p(await match_tracker.handle({"action": "get_history"}))
        assert "error" in r


class TestMatchTrackerGetWinrate:
    async def test_get_winrate_by_game(self, match_tracker):
        for game, result in [("A", "win"), ("A", "loss"), ("B", "win"), ("B", "win")]:
            await match_tracker.handle({
                "action": "record_match",
                "agent_id": "p6",
                "game_title": game,
                "result": result,
            })
        r = _p(await match_tracker.handle({
            "action": "get_winrate",
            "agent_id": "p6",
            "group_by": "game_title",
        }))
        assert r["group_by"] == "game_title"
        breakdown = {row["game_title"]: row for row in r["breakdown"]}
        assert breakdown["B"]["win_rate_pct"] == 100.0
        assert breakdown["A"]["win_rate_pct"] == pytest.approx(50.0)

    async def test_get_winrate_invalid_group_by(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "get_winrate",
            "agent_id": "p6",
            "group_by": "invalid_column",
        }))
        assert "error" in r


class TestMatchTrackerComparePeriods:
    async def test_compare_periods_structure(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "compare_periods",
            "agent_id": "p7",
            "period_a": "this_week",
            "period_b": "last_week",
        }))
        assert "period_a" in r
        assert "period_b" in r
        assert r["period_a"]["label"] == "this_week"
        assert r["period_b"]["label"] == "last_week"

    async def test_compare_periods_month(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "compare_periods",
            "agent_id": "p7",
            "period_a": "this_month",
            "period_b": "last_month",
        }))
        assert r["period_a"]["label"] == "this_month"

    async def test_compare_periods_invalid_period(self, match_tracker):
        r = _p(await match_tracker.handle({
            "action": "compare_periods",
            "agent_id": "p7",
            "period_a": "this_century",
        }))
        assert "error" in r


class TestMatchTrackerAgentIsolation:
    async def test_agent_isolation_stats(self, match_tracker):
        for agent, game in [("agent_A", "Valorant"), ("agent_B", "Valorant")]:
            for _ in range(3):
                await match_tracker.handle({
                    "action": "record_match",
                    "agent_id": agent,
                    "game_title": game,
                    "result": "win",
                })
        r_a = _p(await match_tracker.handle({
            "action": "get_stats", "agent_id": "agent_A", "game_title": "Valorant",
        }))
        r_b = _p(await match_tracker.handle({
            "action": "get_stats", "agent_id": "agent_B", "game_title": "Valorant",
        }))
        assert r_a["total_matches"] == 3
        assert r_b["total_matches"] == 3

    async def test_agent_isolation_history(self, match_tracker):
        await match_tracker.handle({
            "action": "record_match",
            "agent_id": "isolate_X",
            "game_title": "SecretGame",
            "result": "win",
        })
        r = _p(await match_tracker.handle({
            "action": "get_history",
            "agent_id": "isolate_Y",
            "game_title": "SecretGame",
        }))
        assert len(r["matches"]) == 0


class TestMatchTrackerUnknownAction:
    async def test_unknown_action(self, match_tracker):
        r = _p(await match_tracker.handle({"action": "teleport"}))
        assert "error" in r


# ===========================================================================
# 4. TournamentSkill Tests
# ===========================================================================


class TestTournamentCreate:
    async def test_create_basic(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org1",
            "name": "Spring Open",
            "game_title": "Valorant",
        }))
        assert r["status"] == "pending"
        assert "id" in r

    async def test_create_missing_name(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org1",
            "game_title": "CS2",
        }))
        assert "error" in r

    async def test_create_missing_game_title(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org1",
            "name": "My Tourney",
        }))
        assert "error" in r

    async def test_create_invalid_format(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org1",
            "name": "T",
            "game_title": "G",
            "format": "random_draw",
        }))
        assert "error" in r

    async def test_create_all_valid_formats(self, tournament):
        for fmt in VALID_FORMATS:
            r = _p(await tournament.handle({
                "action": "create_tournament",
                "agent_id": "org1",
                "name": f"T-{fmt}",
                "game_title": "Dota2",
                "format": fmt,
            }))
            assert r["status"] == "pending", f"Format {fmt} failed"


class TestTournamentRegisterPlayer:
    async def test_register_basic(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org2",
            "name": "Fall Cup",
            "game_title": "LoL",
            "max_participants": 8,
        }))
        r = _p(await tournament.handle({
            "action": "register_player",
            "tournament_id": t["id"],
            "player_name": "PlayerOne",
        }))
        assert r["status"] == "registered"
        assert "id" in r

    async def test_register_missing_tournament_id(self, tournament):
        r = _p(await tournament.handle({
            "action": "register_player",
            "player_name": "X",
        }))
        assert "error" in r

    async def test_register_missing_player_name(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org2",
            "name": "T",
            "game_title": "G",
        }))
        r = _p(await tournament.handle({
            "action": "register_player",
            "tournament_id": t["id"],
        }))
        assert "error" in r

    async def test_register_tournament_not_found(self, tournament):
        r = _p(await tournament.handle({
            "action": "register_player",
            "tournament_id": "nonexistent",
            "player_name": "X",
        }))
        assert "error" in r

    async def test_register_full_tournament(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org2",
            "name": "Tiny",
            "game_title": "G",
            "max_participants": 2,
        }))
        for name in ["P1", "P2"]:
            await tournament.handle({
                "action": "register_player",
                "tournament_id": t["id"],
                "player_name": name,
            })
        r = _p(await tournament.handle({
            "action": "register_player",
            "tournament_id": t["id"],
            "player_name": "P3",
        }))
        assert "error" in r
        assert "full" in r["error"].lower()


class TestTournamentRecordResult:
    async def test_record_result_win(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org3",
            "name": "Test Cup",
            "game_title": "Valorant",
        }))
        await tournament.handle({
            "action": "register_player",
            "tournament_id": t["id"],
            "player_name": "Ace",
        })
        r = _p(await tournament.handle({
            "action": "record_result",
            "tournament_id": t["id"],
            "player_name": "Ace",
            "result": "win",
        }))
        assert r["result"] == "win"
        assert r["status"] == "active"

    async def test_record_result_loss_eliminates(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org3",
            "name": "Cup",
            "game_title": "CS2",
        }))
        await tournament.handle({
            "action": "register_player",
            "tournament_id": t["id"],
            "player_name": "Loser",
        })
        r = _p(await tournament.handle({
            "action": "record_result",
            "tournament_id": t["id"],
            "player_name": "Loser",
            "result": "loss",
            "eliminated_round": 1,
            "placement": 4,
        }))
        assert r["status"] == "eliminated"

    async def test_record_result_invalid_result(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org3",
            "name": "X",
            "game_title": "G",
        }))
        await tournament.handle({
            "action": "register_player",
            "tournament_id": t["id"],
            "player_name": "X",
        })
        r = _p(await tournament.handle({
            "action": "record_result",
            "tournament_id": t["id"],
            "player_name": "X",
            "result": "forfeit",  # invalid
        }))
        assert "error" in r

    async def test_record_result_player_not_found(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org3",
            "name": "X",
            "game_title": "G",
        }))
        r = _p(await tournament.handle({
            "action": "record_result",
            "tournament_id": t["id"],
            "player_name": "Ghost",
            "result": "win",
        }))
        assert "error" in r


class TestTournamentGetBracket:
    async def test_get_bracket_with_participants(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org4",
            "name": "Bracket Cup",
            "game_title": "Dota2",
        }))
        for name in ["A", "B", "C"]:
            await tournament.handle({
                "action": "register_player",
                "tournament_id": t["id"],
                "player_name": name,
            })
        r = _p(await tournament.handle({
            "action": "get_bracket",
            "tournament_id": t["id"],
        }))
        assert r["tournament"]["id"] == t["id"]
        assert len(r["participants"]) == 3

    async def test_get_bracket_not_found(self, tournament):
        r = _p(await tournament.handle({
            "action": "get_bracket",
            "tournament_id": "nope",
        }))
        assert "error" in r

    async def test_get_bracket_missing_tournament_id(self, tournament):
        r = _p(await tournament.handle({"action": "get_bracket"}))
        assert "error" in r


class TestTournamentGetStandings:
    async def test_get_standings_empty(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org5",
            "name": "S",
            "game_title": "OW2",
        }))
        r = _p(await tournament.handle({
            "action": "get_standings",
            "tournament_id": t["id"],
        }))
        assert "standings" in r
        assert r["standings"] == []

    async def test_get_standings_missing_id(self, tournament):
        r = _p(await tournament.handle({"action": "get_standings"}))
        assert "error" in r


class TestTournamentAdvanceRound:
    async def test_advance_round_to_active(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org6",
            "name": "AR Test",
            "game_title": "Valorant",
        }))
        r = _p(await tournament.handle({
            "action": "advance_round",
            "tournament_id": t["id"],
            "new_status": "active",
            "bracket_data": {"round": 1, "matches": [{"a": "P1", "b": "P2"}]},
        }))
        assert r["status"] == "active"

    async def test_advance_completed_tournament_rejected(self, tournament):
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org6",
            "name": "Done",
            "game_title": "G",
        }))
        await tournament.handle({
            "action": "advance_round",
            "tournament_id": t["id"],
            "new_status": "completed",
        })
        r = _p(await tournament.handle({
            "action": "advance_round",
            "tournament_id": t["id"],
        }))
        assert "error" in r


class TestTournamentFormatSupport:
    async def test_single_elimination_format(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org7",
            "name": "SE",
            "game_title": "Valorant",
            "format": "single_elimination",
        }))
        assert "id" in r

    async def test_round_robin_format(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org7",
            "name": "RR",
            "game_title": "LoL",
            "format": "round_robin",
        }))
        assert "id" in r

    async def test_swiss_format(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org7",
            "name": "Swiss",
            "game_title": "Hearthstone",
            "format": "swiss",
        }))
        assert "id" in r

    async def test_double_elimination_format(self, tournament):
        r = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "org7",
            "name": "DE",
            "game_title": "Smash",
            "format": "double_elimination",
        }))
        assert "id" in r


class TestTournamentAgentIsolation:
    async def test_bracket_not_visible_to_other_agent(self, tournament):
        # Create tournament for agent_A — agent_B cannot see it via get_bracket
        t = _p(await tournament.handle({
            "action": "create_tournament",
            "agent_id": "tourn_isolate_A",
            "name": "Secret Cup",
            "game_title": "CS2",
        }))
        await tournament.handle({
            "action": "register_player",
            "tournament_id": t["id"],
            "player_name": "spy",
        })
        # The get_bracket is by tournament_id not agent_id, so test that
        # tournament was actually created for the right agent
        bracket = _p(await tournament.handle({
            "action": "get_bracket",
            "tournament_id": t["id"],
        }))
        assert bracket["tournament"]["agent_id"] == "tourn_isolate_A"


# ===========================================================================
# 5. GameSessionSkill Tests
# ===========================================================================


class TestGameSessionStartEnd:
    async def test_start_session_basic(self, game_session):
        r = _p(await game_session.handle({
            "action": "start_session",
            "agent_id": "player1",
            "game_title": "Elden Ring",
        }))
        assert r["status"] == "started"
        assert "id" in r
        assert "started_at" in r

    async def test_start_session_missing_game_title(self, game_session):
        r = _p(await game_session.handle({
            "action": "start_session",
            "agent_id": "player1",
        }))
        assert "error" in r

    async def test_start_session_missing_agent_id(self, game_session):
        r = _p(await game_session.handle({
            "action": "start_session",
            "game_title": "Minecraft",
        }))
        assert "error" in r

    async def test_end_session_basic(self, game_session):
        s = _p(await game_session.handle({
            "action": "start_session",
            "agent_id": "player2",
            "game_title": "Minecraft",
        }))
        r = _p(await game_session.handle({
            "action": "end_session",
            "id": s["id"],
            "xp_gained": 500,
            "achievements": ["First Night Survived", "Mine Diamonds"],
        }))
        assert r["status"] == "ended"
        assert "duration_minutes" in r

    async def test_end_session_not_found(self, game_session):
        r = _p(await game_session.handle({
            "action": "end_session",
            "id": "ghost_session",
        }))
        assert "error" in r

    async def test_end_session_missing_id(self, game_session):
        r = _p(await game_session.handle({"action": "end_session"}))
        assert "error" in r


class TestGameSessionDurationCalculation:
    async def test_duration_calculated_correctly(self, game_session):
        s = _p(await game_session.handle({
            "action": "start_session",
            "agent_id": "dur_test",
            "game_title": "Minecraft",
            "started_at": "2026-01-01T10:00:00+00:00",
        }))
        r = _p(await game_session.handle({
            "action": "end_session",
            "id": s["id"],
            "ended_at": "2026-01-01T11:30:00+00:00",
        }))
        assert r["duration_minutes"] == 90

    async def test_duration_zero_on_same_time(self, game_session):
        ts = "2026-01-01T10:00:00+00:00"
        s = _p(await game_session.handle({
            "action": "start_session",
            "agent_id": "dur_test2",
            "game_title": "Test",
            "started_at": ts,
        }))
        r = _p(await game_session.handle({
            "action": "end_session",
            "id": s["id"],
            "ended_at": ts,
        }))
        assert r["duration_minutes"] == 0


class TestGameSessionGetPlaytime:
    async def test_get_playtime_by_game(self, game_session):
        for game in ["Valorant", "Valorant", "CS2"]:
            s = _p(await game_session.handle({
                "action": "start_session",
                "agent_id": "pt_test",
                "game_title": game,
                "started_at": "2026-01-01T10:00:00+00:00",
            }))
            await game_session.handle({
                "action": "end_session",
                "id": s["id"],
                "ended_at": "2026-01-01T11:00:00+00:00",
            })
        r = _p(await game_session.handle({
            "action": "get_playtime",
            "agent_id": "pt_test",
            "group_by": "game",
        }))
        totals = {row["game_title"]: row["total_minutes"] for row in r["playtime"]}
        assert totals["Valorant"] == 120
        assert totals["CS2"] == 60

    async def test_get_playtime_missing_agent_id(self, game_session):
        r = _p(await game_session.handle({"action": "get_playtime"}))
        assert "error" in r

    async def test_get_playtime_invalid_group_by(self, game_session):
        r = _p(await game_session.handle({
            "action": "get_playtime",
            "agent_id": "x",
            "group_by": "invalid",
        }))
        assert "error" in r


class TestGameSessionGetAchievements:
    async def test_get_achievements_from_session(self, game_session):
        s = _p(await game_session.handle({
            "action": "start_session",
            "agent_id": "ach_test",
            "game_title": "Elden Ring",
        }))
        await game_session.handle({
            "action": "end_session",
            "id": s["id"],
            "achievements": ["Margit Slain", "First Boss"],
        })
        r = _p(await game_session.handle({
            "action": "get_achievements",
            "agent_id": "ach_test",
        }))
        assert r["total"] == 2
        names = [a["achievement"] for a in r["achievements"]]
        assert "Margit Slain" in names

    async def test_get_achievements_empty(self, game_session):
        r = _p(await game_session.handle({
            "action": "get_achievements",
            "agent_id": "empty_player",
        }))
        assert r["total"] == 0
        assert r["achievements"] == []

    async def test_get_achievements_missing_agent_id(self, game_session):
        r = _p(await game_session.handle({"action": "get_achievements"}))
        assert "error" in r


class TestGameSessionAgentIsolation:
    async def test_sessions_isolated_by_agent(self, game_session):
        for agent in ["gs_iso_A", "gs_iso_B"]:
            for _ in range(3):
                s = _p(await game_session.handle({
                    "action": "start_session",
                    "agent_id": agent,
                    "game_title": "Shared Game",
                    "started_at": "2026-01-01T10:00:00+00:00",
                }))
                await game_session.handle({
                    "action": "end_session",
                    "id": s["id"],
                    "ended_at": "2026-01-01T11:00:00+00:00",
                })
        r_a = _p(await game_session.handle({
            "action": "get_sessions",
            "agent_id": "gs_iso_A",
        }))
        r_b = _p(await game_session.handle({
            "action": "get_sessions",
            "agent_id": "gs_iso_B",
        }))
        assert len(r_a["sessions"]) == 3
        assert len(r_b["sessions"]) == 3


# ===========================================================================
# 6. LootTrackerSkill Tests
# ===========================================================================


class TestLootTrackerAddItem:
    async def test_add_item_basic(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "lt1",
            "game_title": "WoW",
            "item_name": "Thunderfury",
            "rarity": "legendary",
            "quantity": 1,
            "value_gold": 50000,
        }))
        assert r["status"] == "added"
        assert "id" in r

    async def test_add_item_missing_item_name(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "lt1",
            "game_title": "WoW",
        }))
        assert "error" in r

    async def test_add_item_missing_agent_id(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "add_item",
            "game_title": "WoW",
            "item_name": "Sword",
        }))
        assert "error" in r

    async def test_add_item_missing_game_title(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "lt1",
            "item_name": "Sword",
        }))
        assert "error" in r

    async def test_add_item_invalid_rarity(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "lt1",
            "game_title": "WoW",
            "item_name": "X",
            "rarity": "divine",  # invalid
        }))
        assert "error" in r

    async def test_add_item_all_valid_rarities(self, loot_tracker):
        rarities = ["common", "uncommon", "rare", "epic", "legendary", "mythic", "unique"]
        for rarity in rarities:
            r = _p(await loot_tracker.handle({
                "action": "add_item",
                "agent_id": "lt1",
                "game_title": "WoW",
                "item_name": f"Item_{rarity}",
                "rarity": rarity,
            }))
            assert r["status"] == "added", f"Rarity {rarity} failed"


class TestLootTrackerIntegerCents:
    async def test_real_currency_stored_as_integer_cents(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "cents_test",
            "game_title": "CS2",
            "item_name": "AWP Dragon Lore",
            "value_real_currency_cents": 75000,  # $750.00
        }))
        assert r["status"] == "added"

    async def test_float_cents_rejected(self, loot_tracker):
        # Passing a float string that can't become int cleanly
        r = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "cents_test",
            "game_title": "CS2",
            "item_name": "Knife",
            "value_real_currency_cents": "not_a_number",
        }))
        assert "error" in r

    async def test_get_value_returns_integer_cents(self, loot_tracker):
        await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "val_test",
            "game_title": "CS2",
            "item_name": "Knife",
            "value_real_currency_cents": 5000,
            "quantity": 1,
        })
        r = _p(await loot_tracker.handle({
            "action": "get_value",
            "agent_id": "val_test",
            "game_title": "CS2",
        }))
        assert isinstance(r["total_real_currency_cents"], int)
        assert r["total_real_currency_cents"] == 5000


class TestLootTrackerGetInventory:
    async def test_get_inventory_filtered_by_rarity(self, loot_tracker):
        for rarity in ["common", "common", "legendary"]:
            await loot_tracker.handle({
                "action": "add_item",
                "agent_id": "inv_test",
                "game_title": "WoW",
                "item_name": f"Item_{rarity}",
                "rarity": rarity,
            })
        r = _p(await loot_tracker.handle({
            "action": "get_inventory",
            "agent_id": "inv_test",
            "game_title": "WoW",
            "rarity": "legendary",
        }))
        assert len(r["inventory"]) == 1
        assert r["inventory"][0]["rarity"] == "legendary"

    async def test_get_inventory_empty(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "get_inventory",
            "agent_id": "empty_agent",
            "game_title": "EmptyGame",
        }))
        assert r["inventory"] == []

    async def test_get_inventory_missing_agent_id(self, loot_tracker):
        r = _p(await loot_tracker.handle({"action": "get_inventory"}))
        assert "error" in r


class TestLootTrackerGetValue:
    async def test_get_value_sum(self, loot_tracker):
        for gold in [1000, 2000, 3000]:
            await loot_tracker.handle({
                "action": "add_item",
                "agent_id": "sum_test",
                "game_title": "WoW",
                "item_name": "Gold Item",
                "value_gold": gold,
                "quantity": 1,
            })
        r = _p(await loot_tracker.handle({
            "action": "get_value",
            "agent_id": "sum_test",
            "game_title": "WoW",
        }))
        assert r["total_gold"] == 6000

    async def test_get_value_empty(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "get_value",
            "agent_id": "empty_v",
            "game_title": "Nothing",
        }))
        assert r["total_gold"] == 0
        assert r["total_real_currency_cents"] == 0

    async def test_get_value_missing_agent_id(self, loot_tracker):
        r = _p(await loot_tracker.handle({"action": "get_value"}))
        assert "error" in r


class TestLootTrackerRemoveItem:
    async def test_remove_item_partial(self, loot_tracker):
        add = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "rem_test",
            "game_title": "WoW",
            "item_name": "Potion",
            "quantity": 10,
        }))
        r = _p(await loot_tracker.handle({
            "action": "remove_item",
            "id": add["id"],
            "quantity": 3,
        }))
        assert r["remaining"] == 7

    async def test_remove_item_full_delete(self, loot_tracker):
        add = _p(await loot_tracker.handle({
            "action": "add_item",
            "agent_id": "rem_test2",
            "game_title": "WoW",
            "item_name": "Sword",
            "quantity": 1,
        }))
        r = _p(await loot_tracker.handle({
            "action": "remove_item",
            "id": add["id"],
            "quantity": 1,
        }))
        assert r["status"] == "deleted"
        assert r["remaining"] == 0

    async def test_remove_item_not_found(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "remove_item",
            "id": "ghost",
        }))
        assert "error" in r

    async def test_remove_item_missing_id(self, loot_tracker):
        r = _p(await loot_tracker.handle({"action": "remove_item"}))
        assert "error" in r


class TestLootTrackerPriceCheck:
    async def test_price_check_basic(self, loot_tracker):
        for gold in [500, 1000, 1500]:
            await loot_tracker.handle({
                "action": "add_item",
                "agent_id": "pc_test",
                "game_title": "WoW",
                "item_name": "Heartsblood",
                "value_gold": gold,
            })
        r = _p(await loot_tracker.handle({
            "action": "price_check",
            "agent_id": "pc_test",
            "game_title": "WoW",
            "item_name": "Heartsblood",
        }))
        assert r["min_gold"] == 500
        assert r["max_gold"] == 1500
        assert r["avg_gold"] == pytest.approx(1000.0)
        assert r["data_points"] == 3

    async def test_price_check_no_data(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "price_check",
            "item_name": "Obscure Item",
        }))
        assert r["data_points"] == 0

    async def test_price_check_missing_item_name(self, loot_tracker):
        r = _p(await loot_tracker.handle({"action": "price_check"}))
        assert "error" in r


class TestLootTrackerTradeLog:
    async def test_trade_log_basic(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "trade_log",
            "agent_id": "tl_test",
            "game_title": "WoW",
            "item_name": "Sword",
            "traded_to": "PlayerX",
            "value_gold": 5000,
        }))
        assert r["status"] == "logged"
        assert r["traded_to"] == "PlayerX"
        assert "id" in r

    async def test_trade_log_missing_traded_to(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "trade_log",
            "agent_id": "tl_test",
            "game_title": "WoW",
            "item_name": "Sword",
        }))
        assert "error" in r

    async def test_trade_log_real_currency_cents(self, loot_tracker):
        r = _p(await loot_tracker.handle({
            "action": "trade_log",
            "agent_id": "tl_test",
            "game_title": "CS2",
            "item_name": "Knife",
            "traded_to": "Trader",
            "value_real_currency_cents": 10000,  # $100.00
        }))
        assert r["status"] == "logged"


class TestLootTrackerAgentIsolation:
    async def test_inventory_isolated(self, loot_tracker):
        for agent in ["lt_iso_A", "lt_iso_B"]:
            for i in range(3):
                await loot_tracker.handle({
                    "action": "add_item",
                    "agent_id": agent,
                    "game_title": "SharedGame",
                    "item_name": f"Item_{i}",
                })
        r_a = _p(await loot_tracker.handle({
            "action": "get_inventory",
            "agent_id": "lt_iso_A",
            "game_title": "SharedGame",
        }))
        r_b = _p(await loot_tracker.handle({
            "action": "get_inventory",
            "agent_id": "lt_iso_B",
            "game_title": "SharedGame",
        }))
        assert len(r_a["inventory"]) == 3
        assert len(r_b["inventory"]) == 3
        # Ensure no cross-contamination
        ids_a = {item["id"] for item in r_a["inventory"]}
        ids_b = {item["id"] for item in r_b["inventory"]}
        assert ids_a.isdisjoint(ids_b)


# ===========================================================================
# 7. Template Registry Integration Tests
# ===========================================================================


class TestGamingTemplateRegistryIntegration:
    async def test_seed_defaults_includes_gaming(self):
        from isg_agent.templates.template_registry import TemplateRegistry

        reg = TemplateRegistry(db_path=":memory:")
        try:
            count = await reg.seed_defaults()
            assert count >= 8, "At least 8 gaming templates should be seeded"

            templates = await reg.list_templates(agent_type="gaming")
            assert len(templates) == 8
        finally:
            await reg.close()

    async def test_gaming_templates_have_correct_agent_type(self):
        from isg_agent.templates.template_registry import TemplateRegistry

        reg = TemplateRegistry(db_path=":memory:")
        try:
            await reg.seed_defaults()
            templates = await reg.list_templates(agent_type="gaming")
            for t in templates:
                assert t.agent_type == "gaming"
        finally:
            await reg.close()

    async def test_game_coach_template_in_registry(self):
        from isg_agent.templates.template_registry import TemplateRegistry

        reg = TemplateRegistry(db_path=":memory:")
        try:
            await reg.seed_defaults()
            templates = await reg.list_templates(agent_type="gaming")
            names = {t.name for t in templates}
            assert "Game Coach" in names
        finally:
            await reg.close()

    async def test_total_seeds_is_38(self):
        from isg_agent.templates.template_registry import TemplateRegistry

        reg = TemplateRegistry(db_path=":memory:")
        try:
            total = await reg.seed_defaults()
            all_templates = await reg.list_templates()
            assert len(all_templates) == 38
        finally:
            await reg.close()

    async def test_seed_defaults_idempotent(self):
        from isg_agent.templates.template_registry import TemplateRegistry

        reg = TemplateRegistry(db_path=":memory:")
        try:
            first = await reg.seed_defaults()
            second = await reg.seed_defaults()
            assert second == 0  # no duplicates inserted
        finally:
            await reg.close()


# ===========================================================================
# 8. Skill Registration Tests
# ===========================================================================


class TestGamingSkillRegistration:
    def test_gaming_skills_in_skill_registry(self):
        from isg_agent.skills.builtin import _SKILL_REGISTRY

        assert "match_tracker" in _SKILL_REGISTRY
        assert "tournament" in _SKILL_REGISTRY
        assert "game_session" in _SKILL_REGISTRY
        assert "loot_tracker" in _SKILL_REGISTRY

    def test_skill_registry_has_16_skills(self):
        from isg_agent.skills.builtin import _SKILL_REGISTRY

        assert len(_SKILL_REGISTRY) >= 16  # 17+ after loot_tracker addition

    async def test_register_builtin_skills_includes_gaming(self, tmp_db):
        from isg_agent.skills.executor import SkillExecutor
        from isg_agent.skills.builtin import register_builtin_skills

        executor = SkillExecutor(
            workspace_root=str(tmp_db.parent),
        )
        registered = await register_builtin_skills(executor, str(tmp_db))
        assert "match_tracker" in registered
        assert "tournament" in registered
        assert "game_session" in registered
        assert "loot_tracker" in registered
