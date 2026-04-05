/**
 * Platform service — agents, templates, tasks, and handles.
 *
 * Backend endpoints:
 *   POST   /api/v1/agents                         — create agent (auth)
 *   GET    /api/v1/agents                         — list user's agents (auth)
 *   GET    /api/v1/agents/{id}                    — get agent detail (auth)
 *   PATCH  /api/v1/agents/{id}                    — update agent (auth)
 *   DELETE /api/v1/agents/{id}                    — delete agent (auth)
 *   GET    /api/v1/handles/check?handle=xxx       — check availability (public)
 *   GET    /api/v1/templates                      — list templates (public)
 *   GET    /api/v1/templates/{id}                 — get template detail (public)
 *   POST   /api/v1/tasks                          — create task (auth)
 *   GET    /api/v1/tasks                          — list tasks (auth)
 *   GET    /api/v1/tasks/{id}                     — get task detail (auth)
 *   PATCH  /api/v1/tasks/{id}                     — update task (auth)
 *   DELETE /api/v1/tasks/{id}                     — cancel task (auth)
 *   GET    /api/v1/tasks/usage/{agent_id}         — current usage (auth)
 *   GET    /api/v1/tasks/usage/{agent_id}/history — usage history (auth)
 */

import { get, post, del } from "./client";
import apiClient from "./client";

// ─── Response Types ───────────────────────────────────────────────────────────

export interface AgentResponse {
  id: string;
  user_id: string;
  handle: string;
  name: string;
  agent_type: "personal" | "business";
  industry_type?: string;
  template_id?: string;
  status: "active" | "suspended" | "archived";
  subscription_tier: string;
  created_at: string;
  updated_at: string;
}

/** Derived helper — maps backend status to simple boolean */
export function isAgentActive(agent: AgentResponse): boolean {
  return agent.status === "active";
}

export interface TemplateResponse {
  id: string;
  name: string;
  description: string;
  agent_type: "personal" | "business";
  industry?: string;
  icon?: string;
  capabilities: string[];
  created_at: string;
}

export interface TaskResponse {
  id: string;
  agent_id: string;
  user_id: string;
  task_type: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "cancelled" | "failed";
  delegated_to?: string;
  result_json?: string;
  tokens_used: number;
  cost_cents: number;
  created_at: string;
  completed_at?: string;
}

export interface TaskUsageResponse {
  agent_id: string;
  period_start: string;
  period_end: string;
  tasks_completed: number;
  tasks_total: number;
  tasks_failed: number;
}

export interface HandleCheckResponse {
  available: boolean;
  handle: string;
}

// ─── Create/Update Payloads ───────────────────────────────────────────────────

export interface CreateAgentPayload {
  handle: string;
  name: string;
  agent_type: "personal" | "business";
  industry_type?: string;
  template_id?: string;
}

export interface UpdateAgentPayload {
  name?: string;
  industry_type?: string;
  status?: "active" | "suspended";
}

export interface CreateTaskPayload {
  agent_id: string;
  task_type: string;
  description: string;
}

export interface UpdateTaskPayload {
  status?: TaskResponse["status"];
  result?: string;
}

export interface ListTasksParams {
  status?: TaskResponse["status"];
  agent_id?: string;
}

// ─── Agent API ────────────────────────────────────────────────────────────────

export async function createAgent(
  data: CreateAgentPayload
): Promise<AgentResponse> {
  return post<AgentResponse>("/api/v1/agents", data);
}

export async function listAgents(): Promise<AgentResponse[]> {
  const data = await get<AgentResponse[] | { agents: AgentResponse[] }>(
    "/api/v1/agents"
  );
  if (Array.isArray(data)) return data;
  return data.agents ?? [];
}

export async function getAgent(id: string): Promise<AgentResponse> {
  return get<AgentResponse>(`/api/v1/agents/${id}`);
}

export async function updateAgent(
  id: string,
  data: UpdateAgentPayload
): Promise<AgentResponse> {
  const res = await apiClient.patch<AgentResponse>(`/api/v1/agents/${id}`, data);
  return res.data;
}

export async function deleteAgent(id: string): Promise<void> {
  await del(`/api/v1/agents/${id}`);
}

// ─── Handle API ───────────────────────────────────────────────────────────────

export async function checkHandle(handle: string): Promise<HandleCheckResponse> {
  return get<HandleCheckResponse>(
    `/api/v1/agents/handle/${encodeURIComponent(handle)}/check`
  );
}

// ─── Template API ─────────────────────────────────────────────────────────────

export async function listTemplates(): Promise<TemplateResponse[]> {
  const data = await get<TemplateResponse[] | { templates: TemplateResponse[] }>(
    "/api/v1/templates"
  );
  if (Array.isArray(data)) return data;
  return data.templates ?? [];
}

export async function getTemplate(id: string): Promise<TemplateResponse> {
  return get<TemplateResponse>(`/api/v1/templates/${id}`);
}

// ─── Task API ─────────────────────────────────────────────────────────────────

export async function createTask(
  data: CreateTaskPayload
): Promise<TaskResponse> {
  return post<TaskResponse>("/api/v1/tasks", data);
}

export async function listTasks(
  params?: ListTasksParams
): Promise<TaskResponse[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.agent_id) query.set("agent_id", params.agent_id);
  const qs = query.toString() ? `?${query.toString()}` : "";
  const data = await get<TaskResponse[] | { tasks: TaskResponse[] }>(
    `/api/v1/tasks${qs}`
  );
  if (Array.isArray(data)) return data;
  return data.tasks ?? [];
}

export async function getTask(id: string): Promise<TaskResponse> {
  return get<TaskResponse>(`/api/v1/tasks/${id}`);
}

export async function updateTask(
  id: string,
  data: UpdateTaskPayload
): Promise<TaskResponse> {
  const res = await apiClient.patch<TaskResponse>(`/api/v1/tasks/${id}`, data);
  return res.data;
}

export async function cancelTask(id: string): Promise<void> {
  await del(`/api/v1/tasks/${id}`);
}

export async function getUsage(agentId: string): Promise<TaskUsageResponse> {
  return get<TaskUsageResponse>(`/api/v1/tasks/usage/${agentId}`);
}

export async function getUsageHistory(
  agentId: string
): Promise<TaskUsageResponse[]> {
  const data = await get<TaskUsageResponse[] | { history: TaskUsageResponse[] }>(
    `/api/v1/tasks/usage/${agentId}/history`
  );
  if (Array.isArray(data)) return data;
  return data.history ?? [];
}
