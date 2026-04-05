/**
 * Payment service — usage tracking, payment intents, and subscriptions.
 *
 * Backend endpoints (all require auth):
 *   POST /api/v1/payments/create-intent              — create Stripe payment intent
 *   GET  /api/v1/payments/usage                      — get current usage stats (message-level)
 *   GET  /api/v1/payments/usage/{agent_id}           — get skill action usage for an agent
 *   GET  /api/v1/payments/usage/{agent_id}/history   — get monthly usage history for an agent
 *   POST /api/v1/payments/subscribe                  — subscribe to a plan
 */

import { get, post } from "./client";

export interface UsageInfo {
  messages_used: number;
  messages_limit: number;
  messages_remaining: number;
  plan: "free" | "pay_per_use" | "unlimited";
  cost_per_message_cents: number;
}

export interface PaymentIntentResponse {
  client_secret: string;
  amount: number;
  currency: string;
}

export interface SkillUsageSummary {
  total_actions: number;
  free_actions: number;
  billed_actions: number;
  total_amount_cents: number;
  remaining_free: number;
  plan: string;
  year_month: string;
  actions_included: number;
}

export interface SubscriptionResponse {
  plan: string;
  status: string;
  created_at: string;
}

/**
 * Get current usage stats for the authenticated user (message-level).
 */
export async function getUsage(): Promise<UsageInfo> {
  try {
    return await get<UsageInfo>("/api/v1/payments/usage");
  } catch {
    // Return default free tier if endpoint not available
    return {
      messages_used: 0,
      messages_limit: 5,
      messages_remaining: 5,
      plan: "free",
      cost_per_message_cents: 100,
    };
  }
}

/**
 * Create a payment intent for additional messages.
 */
export async function createPaymentIntent(
  sessionId: string
): Promise<PaymentIntentResponse> {
  return post<PaymentIntentResponse>("/api/v1/payments/create-intent", {
    session_id: sessionId,
  });
}

/**
 * Get skill action usage for the current month for a specific agent.
 * Returns total_actions, free_actions, billed_actions, remaining_free,
 * total_amount_cents, plan, year_month, and actions_included.
 */
export async function getSkillUsage(
  agentId: string
): Promise<SkillUsageSummary> {
  return get<SkillUsageSummary>(`/api/v1/payments/usage/${agentId}`);
}

/**
 * Get month-by-month skill usage history for a specific agent.
 */
export async function getSkillUsageHistory(
  agentId: string
): Promise<SkillUsageSummary[]> {
  return get<SkillUsageSummary[]>(`/api/v1/payments/usage/${agentId}/history`);
}

/**
 * Subscribe the authenticated user to a billing plan.
 * agentId: the agent to subscribe
 * plan: "free" | "starter" | "pro" | "enterprise"
 *
 * NOTE: For paid plans (starter/pro/enterprise), use createCheckoutSession
 * instead. This endpoint only handles the free plan downgrade.
 */
export async function subscribeToPlan(
  agentId: string,
  plan: string
): Promise<SubscriptionResponse> {
  return post<SubscriptionResponse>("/api/v1/payments/subscribe", {
    agent_id: agentId,
    plan,
  });
}

// ---------------------------------------------------------------------------
// Stripe Checkout — hosted payment page
// ---------------------------------------------------------------------------

export interface CheckoutSessionRequest {
  plan: string;
  agent_id: string;
  success_url?: string;
  cancel_url?: string;
}

export interface CheckoutSessionResponse {
  checkout_url: string;
  session_id: string;
}

/**
 * Create a Stripe Checkout Session for a paid plan subscription.
 *
 * Returns a checkout_url — redirect window.location.href to it.
 * Stripe handles card collection, 3D Secure, receipts, and retries.
 *
 * On completion, Stripe redirects to /billing?success=true&session_id=...
 * On cancel, Stripe redirects to /billing?canceled=true
 */
export async function createCheckoutSession(
  agentId: string,
  plan: string,
): Promise<CheckoutSessionResponse> {
  return post<CheckoutSessionResponse>(
    "/api/v1/payments/create-checkout-session",
    { agent_id: agentId, plan }
  );
}

// ---------------------------------------------------------------------------
// Billing portal
// ---------------------------------------------------------------------------

export interface BillingPortalResponse {
  portal_url: string;
}

/**
 * Create a Stripe Customer Portal session.
 * Redirects to the Stripe-hosted portal where the user can manage
 * their subscription, update payment methods, or cancel.
 */
export async function createBillingPortalSession(
  agentId?: string
): Promise<BillingPortalResponse> {
  const params = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
  return get<BillingPortalResponse>(`/api/v1/payments/billing-portal${params}`);
}

// ---------------------------------------------------------------------------
// Subscription status
// ---------------------------------------------------------------------------

export interface SubscriptionStatusResponse {
  plan: string;
  stripe_status: string;
  stripe_subscription_id: string;
  stripe_customer_id: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  is_active: boolean;
}

/**
 * Fetch current subscription status live from Stripe.
 * Requires agent_id.
 */
export async function getSubscriptionStatus(
  agentId: string
): Promise<SubscriptionStatusResponse> {
  return get<SubscriptionStatusResponse>(
    `/api/v1/payments/status?agent_id=${encodeURIComponent(agentId)}`
  );
}
