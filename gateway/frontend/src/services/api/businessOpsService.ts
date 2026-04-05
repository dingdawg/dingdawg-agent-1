/**
 * Business Ops service — 6 capability engines, 24 endpoints.
 *
 * Backend endpoints (all require auth, prefix: /api/v1/business-ops):
 *
 * Cap 1 — Proactive Ops:
 *   POST  /pulse                          — morning pulse for a business
 *   POST  /triggers/check                 — evaluate enabled trigger monitors
 *   GET   /intelligence/weekly?business_id — 7-day aggregate intelligence report
 *
 * Cap 2 — Payments:
 *   POST  /payments/link                  — generate a Stripe payment link
 *   POST  /payments/record                — record a payment via Stripe event
 *   POST  /payments/refund                — issue a refund
 *   GET   /revenue/forecast?business_id&days — project revenue over N days
 *
 * Cap 3 — Conversations:
 *   POST  /conversations/inbound          — record inbound message / find thread
 *   POST  /conversations/reply            — insert outbound reply
 *   POST  /conversations/smart-reply      — suggest a smart reply (never auto-sends)
 *   GET   /conversations/missed?hours_threshold — detect unanswered threads
 *
 * Cap 4 — Client Intelligence:
 *   GET   /clients/{client_id}/intelligence — composite client profile
 *   POST  /clients/segment                  — run segmentation for a business
 *   GET   /clients/{client_id}/rebook       — predictive rebook suggestion
 *   GET   /clients/dashboard?business_id    — business-level client dashboard
 *
 * Cap 5 — Staff Ops:
 *   POST  /staff/assign                   — assign staff to appointment
 *   PUT   /staff/{staff_id}/schedule      — upsert a weekly schedule entry
 *   GET   /staff/{staff_id}/schedule      — retrieve weekly schedule
 *   GET   /staff/utilization?business_id&period_days — utilisation report
 *
 * Cap 6 — Marketing:
 *   POST  /campaigns                      — create a campaign (status: draft)
 *   POST  /campaigns/{campaign_id}/send   — execute a campaign
 *   POST  /offers/{offer_id}/redeem       — redeem an offer
 *   GET   /campaigns/analytics?business_id&days — campaign analytics
 */

import { get, post, put } from "./client";

// ---------------------------------------------------------------------------
// Shared / generic
// ---------------------------------------------------------------------------

/** Generic engine response envelope returned by most business-ops endpoints. */
export interface OpsResult {
  ok?: boolean;
  err?: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Capability 1 — Proactive Ops
// ---------------------------------------------------------------------------

export interface MorningPulseRequest {
  business_id: string;
}

export interface CheckTriggersRequest {
  business_id: string;
}

export interface WeeklyIntelligenceResponse {
  business_id: string;
  period_days: number;
  [key: string]: unknown;
}

/**
 * Run the morning pulse for a business: appointments, payments, messages.
 * Maps to: POST /api/v1/business-ops/pulse
 */
export async function getMorningPulse(agentId: string): Promise<OpsResult> {
  return post<OpsResult>("/api/v1/business-ops/pulse", {
    business_id: agentId,
  });
}

/**
 * Evaluate all enabled trigger monitors for a business.
 * Maps to: POST /api/v1/business-ops/triggers/check
 */
export async function checkTriggers(agentId: string): Promise<OpsResult> {
  return post<OpsResult>("/api/v1/business-ops/triggers/check", {
    business_id: agentId,
  });
}

/**
 * Return the 7-day aggregate intelligence report for a business.
 * Maps to: GET /api/v1/business-ops/intelligence/weekly?business_id=...
 */
export async function getWeeklyIntelligence(
  agentId: string
): Promise<WeeklyIntelligenceResponse> {
  return get<WeeklyIntelligenceResponse>(
    `/api/v1/business-ops/intelligence/weekly?business_id=${encodeURIComponent(agentId)}`
  );
}

// ---------------------------------------------------------------------------
// Capability 2 — Payments
// ---------------------------------------------------------------------------

export interface CreatePaymentLinkParams {
  client_id: string;
  appointment_id: string;
  amount_cents: number;
}

export interface CreatePaymentLinkResponse {
  ok?: boolean;
  link_id?: string;
  url?: string;
  [key: string]: unknown;
}

export interface RecordPaymentParams {
  link_id: string;
  stripe_event: Record<string, unknown>;
}

export interface ProcessRefundParams {
  payment_id: string;
  amount_cents: number;
  reason: string;
}

export interface RevenueForecastResponse {
  business_id: string;
  days: number;
  forecast?: unknown;
  [key: string]: unknown;
}

/**
 * Generate a hosted Stripe payment link for a client appointment.
 * Maps to: POST /api/v1/business-ops/payments/link
 */
export async function createPaymentLink(
  _agentId: string,
  params: CreatePaymentLinkParams
): Promise<CreatePaymentLinkResponse> {
  return post<CreatePaymentLinkResponse>(
    "/api/v1/business-ops/payments/link",
    params
  );
}

/**
 * Record a payment against an existing payment link via a Stripe event.
 * Maps to: POST /api/v1/business-ops/payments/record
 */
export async function recordPayment(
  _agentId: string,
  params: RecordPaymentParams
): Promise<OpsResult> {
  return post<OpsResult>("/api/v1/business-ops/payments/record", params);
}

/**
 * Issue a refund against a prior payment.
 * Maps to: POST /api/v1/business-ops/payments/refund
 */
export async function processRefund(
  _agentId: string,
  params: ProcessRefundParams
): Promise<OpsResult> {
  return post<OpsResult>("/api/v1/business-ops/payments/refund", params);
}

/**
 * Project revenue over the next N days for a business.
 * Maps to: GET /api/v1/business-ops/revenue/forecast?business_id=...&days=...
 */
export async function getRevenueForecast(
  agentId: string,
  days = 30
): Promise<RevenueForecastResponse> {
  return get<RevenueForecastResponse>(
    `/api/v1/business-ops/revenue/forecast?business_id=${encodeURIComponent(agentId)}&days=${days}`
  );
}

// ---------------------------------------------------------------------------
// Capability 3 — Conversations
// ---------------------------------------------------------------------------

export interface HandleInboundParams {
  client_id: string;
  channel: string;
  content: string;
}

export interface HandleInboundResponse {
  ok?: boolean;
  thread_id?: string;
  [key: string]: unknown;
}

export interface GetSmartReplyParams {
  thread_id: string;
  inbound_content: string;
}

export interface SmartReplyResponse {
  ok?: boolean;
  suggestion?: string;
  [key: string]: unknown;
}

export interface SendReplyParams {
  thread_id: string;
  content: string;
}

export interface MissedConversationsResponse {
  threads?: unknown[];
  [key: string]: unknown;
}

/**
 * Record an inbound message and find or create its conversation thread.
 * Maps to: POST /api/v1/business-ops/conversations/inbound
 */
export async function handleInbound(
  _agentId: string,
  params: HandleInboundParams
): Promise<HandleInboundResponse> {
  return post<HandleInboundResponse>(
    "/api/v1/business-ops/conversations/inbound",
    params
  );
}

/**
 * Suggest a smart reply for the given inbound content (never auto-sends).
 * Maps to: POST /api/v1/business-ops/conversations/smart-reply
 */
export async function getSmartReply(
  _agentId: string,
  params: GetSmartReplyParams
): Promise<SmartReplyResponse> {
  return post<SmartReplyResponse>(
    "/api/v1/business-ops/conversations/smart-reply",
    params
  );
}

/**
 * Insert an outbound reply into a conversation thread.
 * Maps to: POST /api/v1/business-ops/conversations/reply
 */
export async function sendReply(
  _agentId: string,
  params: SendReplyParams
): Promise<OpsResult> {
  return post<OpsResult>("/api/v1/business-ops/conversations/reply", params);
}

/**
 * Detect conversation threads that have not received a reply within the threshold.
 * Maps to: GET /api/v1/business-ops/conversations/missed?hours_threshold=...
 */
export async function getMissedConversations(
  _agentId: string,
  hoursThreshold = 24
): Promise<MissedConversationsResponse> {
  return get<MissedConversationsResponse>(
    `/api/v1/business-ops/conversations/missed?hours_threshold=${hoursThreshold}`
  );
}

// ---------------------------------------------------------------------------
// Capability 4 — Client Intelligence
// ---------------------------------------------------------------------------

export interface ClientIntelligenceResponse {
  client_id: string;
  [key: string]: unknown;
}

export interface ClientSegmentsResponse {
  business_id?: string;
  segments?: unknown[];
  [key: string]: unknown;
}

export interface RebookResponse {
  client_id?: string;
  suggestion?: string;
  [key: string]: unknown;
}

export interface ClientDashboardResponse {
  business_id?: string;
  [key: string]: unknown;
}

/**
 * Retrieve composite intelligence profile for a client.
 * Maps to: GET /api/v1/business-ops/clients/{client_id}/intelligence
 */
export async function getClientIntelligence(
  _agentId: string,
  clientId: string
): Promise<ClientIntelligenceResponse> {
  return get<ClientIntelligenceResponse>(
    `/api/v1/business-ops/clients/${encodeURIComponent(clientId)}/intelligence`
  );
}

/**
 * Run segmentation across all clients for a business.
 * Maps to: POST /api/v1/business-ops/clients/segment
 */
export async function getClientSegments(
  agentId: string
): Promise<ClientSegmentsResponse> {
  return post<ClientSegmentsResponse>("/api/v1/business-ops/clients/segment", {
    business_id: agentId,
  });
}

/**
 * Generate a predictive rebook suggestion for a client.
 * Maps to: GET /api/v1/business-ops/clients/{client_id}/rebook
 */
export async function triggerRebook(
  _agentId: string,
  clientId: string
): Promise<RebookResponse> {
  return get<RebookResponse>(
    `/api/v1/business-ops/clients/${encodeURIComponent(clientId)}/rebook`
  );
}

/**
 * Return the business-level client intelligence dashboard.
 * Maps to: GET /api/v1/business-ops/clients/dashboard?business_id=...
 */
export async function getClientDashboard(
  agentId: string
): Promise<ClientDashboardResponse> {
  return get<ClientDashboardResponse>(
    `/api/v1/business-ops/clients/dashboard?business_id=${encodeURIComponent(agentId)}`
  );
}

// ---------------------------------------------------------------------------
// Capability 5 — Staff Ops
// ---------------------------------------------------------------------------

export interface AssignStaffParams {
  staff_id: string;
  appointment_id: string;
}

export interface StaffScheduleParams {
  day_of_week: number;
  start_time: string;
  end_time: string;
}

export interface StaffScheduleResponse {
  staff_id?: string;
  schedule?: unknown[];
  [key: string]: unknown;
}

export interface UtilizationReportResponse {
  business_id?: string;
  period_days?: number;
  staff?: unknown[];
  [key: string]: unknown;
}

/**
 * Assign a staff member to an appointment.
 * Maps to: POST /api/v1/business-ops/staff/assign
 */
export async function assignStaff(
  _agentId: string,
  params: AssignStaffParams
): Promise<OpsResult> {
  return post<OpsResult>("/api/v1/business-ops/staff/assign", params);
}

/**
 * Retrieve the weekly schedule for a staff member.
 * Maps to: GET /api/v1/business-ops/staff/{staff_id}/schedule
 */
export async function getStaffSchedule(
  _agentId: string,
  staffId: string
): Promise<StaffScheduleResponse> {
  return get<StaffScheduleResponse>(
    `/api/v1/business-ops/staff/${encodeURIComponent(staffId)}/schedule`
  );
}

/**
 * Upsert a weekly schedule entry for a staff member.
 * Maps to: PUT /api/v1/business-ops/staff/{staff_id}/schedule
 */
export async function setStaffSchedule(
  _agentId: string,
  staffId: string,
  params: StaffScheduleParams
): Promise<OpsResult> {
  return put<OpsResult>(
    `/api/v1/business-ops/staff/${encodeURIComponent(staffId)}/schedule`,
    params
  );
}

/**
 * Return resource utilisation report for all staff over a rolling period.
 * Maps to: GET /api/v1/business-ops/staff/utilization?business_id=...&period_days=...
 */
export async function getUtilizationReport(
  agentId: string,
  periodDays = 7
): Promise<UtilizationReportResponse> {
  return get<UtilizationReportResponse>(
    `/api/v1/business-ops/staff/utilization?business_id=${encodeURIComponent(agentId)}&period_days=${periodDays}`
  );
}

// ---------------------------------------------------------------------------
// Capability 6 — Marketing
// ---------------------------------------------------------------------------

export interface CreateCampaignParams {
  name: string;
  segment_filter_json: string;
  channel: string;
  template: string;
}

export interface CreateCampaignResponse {
  ok?: boolean;
  campaign_id?: string;
  [key: string]: unknown;
}

export interface SendCampaignResponse {
  ok?: boolean;
  sent_count?: number;
  [key: string]: unknown;
}

export interface RedeemOfferParams {
  [key: string]: unknown;
}

export interface CampaignAnalyticsResponse {
  business_id?: string;
  days?: number;
  campaigns?: unknown[];
  offers?: unknown[];
  [key: string]: unknown;
}

/**
 * Insert a new marketing campaign record with status 'draft'.
 * Maps to: POST /api/v1/business-ops/campaigns
 */
export async function createCampaign(
  _agentId: string,
  params: CreateCampaignParams
): Promise<CreateCampaignResponse> {
  return post<CreateCampaignResponse>("/api/v1/business-ops/campaigns", params);
}

/**
 * Execute a campaign: resolve segment, render messages, mark sent.
 * Maps to: POST /api/v1/business-ops/campaigns/{campaign_id}/send
 */
export async function sendCampaign(
  _agentId: string,
  campaignId: string
): Promise<SendCampaignResponse> {
  return post<SendCampaignResponse>(
    `/api/v1/business-ops/campaigns/${encodeURIComponent(campaignId)}/send`
  );
}

/**
 * Mark an offer as redeemed and record the redemption timestamp.
 * Maps to: POST /api/v1/business-ops/offers/{offer_id}/redeem
 */
export async function redeemOffer(
  _agentId: string,
  offerId: string,
  _params?: RedeemOfferParams
): Promise<OpsResult> {
  return post<OpsResult>(
    `/api/v1/business-ops/offers/${encodeURIComponent(offerId)}/redeem`
  );
}

/**
 * Compute campaign and offer analytics over a rolling window.
 * Maps to: GET /api/v1/business-ops/campaigns/analytics?business_id=...&days=...
 */
export async function getCampaignAnalytics(
  agentId: string,
  days = 30
): Promise<CampaignAnalyticsResponse> {
  return get<CampaignAnalyticsResponse>(
    `/api/v1/business-ops/campaigns/analytics?business_id=${encodeURIComponent(agentId)}&days=${days}`
  );
}
