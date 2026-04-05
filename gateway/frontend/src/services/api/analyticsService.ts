/**
 * Analytics service — wires to the real analytics backend endpoints.
 *
 * Backend endpoints:
 *   GET /api/v1/analytics/dashboard/{agent_id}    — overview KPIs + daily chart
 *   GET /api/v1/analytics/conversations/{agent_id} — conversation list
 *   GET /api/v1/analytics/skills/{agent_id}        — skill usage + success rates
 *   GET /api/v1/analytics/revenue/{agent_id}       — revenue totals + daily
 *
 * Follows the same typing and export pattern as platformService.ts.
 */

import { get } from "./client";

// ─── Response Types ───────────────────────────────────────────────────────────

export interface DashboardAnalytics {
  total_conversations: number;
  total_messages: number;
  avg_messages_per_conversation: number;
  daily_conversations: Array<{ date: string; count: number }>;
  top_hours: Array<{ hour: number; count: number }>;
}

export interface ConversationEntry {
  session_id: string;
  message_count: number;
  duration_seconds: number;
  started_at: string;
}

export interface SkillUsageEntry {
  skill_name: string;
  total_executions: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
}

export interface RevenueData {
  total_revenue_cents: number;
  daily_revenue: Array<{ date: string; amount_cents: number }>;
}

// ─── API Functions ────────────────────────────────────────────────────────────

export async function getDashboardAnalytics(
  agentId: string
): Promise<DashboardAnalytics> {
  return get<DashboardAnalytics>(`/api/v1/analytics/dashboard/${agentId}`);
}

export async function getConversations(
  agentId: string
): Promise<ConversationEntry[]> {
  const data = await get<ConversationEntry[] | { conversations: ConversationEntry[] }>(
    `/api/v1/analytics/conversations/${agentId}`
  );
  if (Array.isArray(data)) return data;
  return data.conversations ?? [];
}

export async function getSkillUsage(
  agentId: string
): Promise<SkillUsageEntry[]> {
  const data = await get<SkillUsageEntry[] | { skills: SkillUsageEntry[] }>(
    `/api/v1/analytics/skills/${agentId}`
  );
  if (Array.isArray(data)) return data;
  return data.skills ?? [];
}

export async function getRevenue(agentId: string): Promise<RevenueData> {
  return get<RevenueData>(`/api/v1/analytics/revenue/${agentId}`);
}
