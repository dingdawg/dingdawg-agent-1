"use client";

/**
 * IntegrationConfigModal — per-integration configuration dialog.
 *
 * Renders a different form for each integration type:
 *   - google_calendar: OAuth connect button
 *   - sendgrid: API key + from_email + from_name
 *   - twilio: account_sid + auth_token + from_number
 *   - vapi: api_key + voice_model + first_message
 *   - webhooks: list + add webhook form
 *   - dd_main_bridge: status + bridge info
 *
 * All API calls are delegated back to the parent via callback props so
 * the modal stays pure and the parent holds state.
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { X, AlertTriangle, CheckCircle, Trash2, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  IntegrationStatus,
  WebhookEntry,
  SendGridConfig,
  TwilioConfig,
  VapiConfig,
  WebhookConfig,
} from "@/services/api/integrationService";

// ─── Types ────────────────────────────────────────────────────────────────────

export type ModalIntegration =
  | "google_calendar"
  | "sendgrid"
  | "twilio"
  | "vapi"
  | "webhooks"
  | "dd_main_bridge"
  | "cronofy"
  | "zapier"
  | "stripe";

export interface IntegrationConfigModalProps {
  integration: ModalIntegration;
  status: IntegrationStatus;
  webhooks: WebhookEntry[];
  onClose: () => void;
  onConnectGoogle: () => Promise<void>;
  onConfigureSendGrid: (config: SendGridConfig) => Promise<void>;
  onConfigureTwilio: (config: TwilioConfig) => Promise<void>;
  onConfigureVapi: (config: VapiConfig) => Promise<void>;
  onDisconnect: (integration: ModalIntegration) => Promise<void>;
  onTestIntegration: (integration: "sendgrid" | "twilio") => Promise<void>;
  onAddWebhook: (config: WebhookConfig) => Promise<void>;
  onDeleteWebhook: (webhookId: string) => Promise<void>;
}

// ─── Shared sub-components ───────────────────────────────────────────────────

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-xs font-medium text-[var(--color-muted)] mb-1.5">
      {children}
    </label>
  );
}

function AlertBanner({
  type,
  message,
  onDismiss,
}: {
  type: "success" | "error";
  message: string;
  onDismiss?: () => void;
}) {
  const isSuccess = type === "success";
  return (
    <div
      className={cn(
        "flex items-start gap-2 p-3 rounded-xl text-sm mb-4",
        isSuccess
          ? "bg-green-500/10 border border-green-500/20 text-green-400"
          : "bg-red-500/10 border border-red-500/20 text-red-400"
      )}
    >
      {isSuccess ? (
        <CheckCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
      ) : (
        <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
      )}
      <span className="flex-1">{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} className="text-xs underline opacity-70 hover:opacity-100 flex-shrink-0">
          dismiss
        </button>
      )}
    </div>
  );
}

function DisconnectButton({
  onDisconnect,
  disabled,
}: {
  onDisconnect: () => void;
  disabled?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <div className="flex items-center gap-2 mt-3">
        <Button
          variant="destructive"
          size="sm"
          onClick={onDisconnect}
          disabled={disabled}
        >
          Confirm Disconnect
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setConfirming(false)}
        >
          Cancel
        </Button>
      </div>
    );
  }
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => setConfirming(true)}
      disabled={disabled}
      className="text-red-400 border-red-500/20 hover:bg-red-500/10 mt-3"
    >
      Disconnect
    </Button>
  );
}

// ─── Google Calendar Panel ────────────────────────────────────────────────────

function GoogleCalendarPanel({
  status,
  onConnect,
  onDisconnect,
}: {
  status: IntegrationStatus["google_calendar"];
  onConnect: () => Promise<void>;
  onDisconnect: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const handleConnect = useCallback(async () => {
    setBusy(true);
    setFeedback(null);
    try {
      await onConnect();
      setFeedback({ type: "success", msg: "Redirecting to Google sign-in..." });
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [onConnect]);

  const handleDisconnect = useCallback(async () => {
    setBusy(true);
    setFeedback(null);
    try {
      await onDisconnect();
      setFeedback({ type: "success", msg: "Google Calendar disconnected." });
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [onDisconnect]);

  return (
    <div>
      {feedback && (
        <AlertBanner
          type={feedback.type}
          message={feedback.msg}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {/* Status indicator */}
      <div className="flex items-center gap-2 mb-4">
        <span
          className={cn(
            "h-2.5 w-2.5 rounded-full",
            status.connected ? "bg-green-400" : "bg-white/20"
          )}
        />
        <span className="text-sm text-[var(--foreground)]">
          {status.connected ? "Connected" : "Not connected"}
        </span>
        {status.email && (
          <span className="text-xs text-[var(--color-muted)]">({status.email})</span>
        )}
      </div>

      <p className="text-xs text-[var(--color-muted)] mb-4 leading-relaxed">
        Connect your Google Calendar to let your agent schedule appointments,
        check availability, and send invites automatically.
      </p>

      {status.connected ? (
        <>
          {status.email && (
            <div className="glass-panel p-3 mb-3">
              <p className="text-xs text-[var(--color-muted)]">Connected account</p>
              <p className="text-sm font-medium text-[var(--foreground)] mt-0.5">{status.email}</p>
            </div>
          )}
          <DisconnectButton onDisconnect={handleDisconnect} disabled={busy} />
        </>
      ) : (
        <Button
          variant="gold"
          onClick={handleConnect}
          isLoading={busy}
          className="w-full"
        >
          <span>Connect with Google</span>
        </Button>
      )}
    </div>
  );
}

// ─── SendGrid Panel ───────────────────────────────────────────────────────────

function SendGridPanel({
  status,
  onSave,
  onTest,
  onDisconnect,
}: {
  status: IntegrationStatus["sendgrid"];
  onSave: (config: SendGridConfig) => Promise<void>;
  onTest: () => Promise<void>;
  onDisconnect: () => Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [fromEmail, setFromEmail] = useState(status.from_email ?? "");
  const [fromName, setFromName] = useState(status.from_name ?? "");
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const handleSave = useCallback(async () => {
    if (!apiKey || !fromEmail) return;
    setBusy(true);
    setFeedback(null);
    try {
      await onSave({ api_key: apiKey, from_email: fromEmail, from_name: fromName });
      setFeedback({ type: "success", msg: "SendGrid configured successfully." });
      setApiKey("");
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [apiKey, fromEmail, fromName, onSave]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setFeedback(null);
    try {
      await onTest();
      setFeedback({ type: "success", msg: "Test email sent successfully." });
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setTesting(false);
    }
  }, [onTest]);

  const handleDisconnect = useCallback(async () => {
    setBusy(true);
    try {
      await onDisconnect();
      setFeedback({ type: "success", msg: "SendGrid disconnected." });
      setFromEmail("");
      setFromName("");
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [onDisconnect]);

  return (
    <div>
      {feedback && (
        <AlertBanner
          type={feedback.type}
          message={feedback.msg}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {status.connected && (
        <div className="glass-panel p-3 mb-4">
          <p className="text-xs text-[var(--color-muted)]">Currently sending from</p>
          <p className="text-sm font-medium text-[var(--foreground)] mt-0.5">
            {status.from_name
              ? `${status.from_name} <${status.from_email}>`
              : status.from_email}
          </p>
        </div>
      )}

      <div className="space-y-3 mb-4">
        <div>
          <FieldLabel>API Key {status.connected && "(leave blank to keep current)"}</FieldLabel>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="SG.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            autoComplete="off"
          />
        </div>
        <div>
          <FieldLabel>From Email</FieldLabel>
          <Input
            type="email"
            value={fromEmail}
            onChange={(e) => setFromEmail(e.target.value)}
            placeholder="hello@yourbusiness.com"
          />
        </div>
        <div>
          <FieldLabel>From Name</FieldLabel>
          <Input
            value={fromName}
            onChange={(e) => setFromName(e.target.value)}
            placeholder="Your Business Name"
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="gold"
          onClick={handleSave}
          isLoading={busy}
          disabled={(!apiKey && !status.connected) || !fromEmail}
          className="flex-1"
        >
          Save
        </Button>
        {status.connected && (
          <Button
            variant="outline"
            onClick={handleTest}
            isLoading={testing}
            disabled={busy}
          >
            Test
          </Button>
        )}
      </div>

      {status.connected && (
        <DisconnectButton onDisconnect={handleDisconnect} disabled={busy || testing} />
      )}
    </div>
  );
}

// ─── Twilio Panel ─────────────────────────────────────────────────────────────

function TwilioPanel({
  status,
  onSave,
  onTest,
  onDisconnect,
}: {
  status: IntegrationStatus["twilio"];
  onSave: (config: TwilioConfig) => Promise<void>;
  onTest: () => Promise<void>;
  onDisconnect: () => Promise<void>;
}) {
  const [accountSid, setAccountSid] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [fromNumber, setFromNumber] = useState(status.from_number ?? "");
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const handleSave = useCallback(async () => {
    if (!accountSid || !authToken || !fromNumber) return;
    setBusy(true);
    setFeedback(null);
    try {
      await onSave({ account_sid: accountSid, auth_token: authToken, from_number: fromNumber });
      setFeedback({ type: "success", msg: "Twilio configured successfully." });
      setAccountSid("");
      setAuthToken("");
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [accountSid, authToken, fromNumber, onSave]);

  const handleTest = useCallback(async () => {
    setTesting(true);
    setFeedback(null);
    try {
      await onTest();
      setFeedback({ type: "success", msg: "Test SMS sent successfully." });
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setTesting(false);
    }
  }, [onTest]);

  const handleDisconnect = useCallback(async () => {
    setBusy(true);
    try {
      await onDisconnect();
      setFeedback({ type: "success", msg: "Twilio disconnected." });
      setFromNumber("");
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [onDisconnect]);

  return (
    <div>
      {feedback && (
        <AlertBanner
          type={feedback.type}
          message={feedback.msg}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {status.connected && (
        <div className="glass-panel p-3 mb-4">
          <p className="text-xs text-[var(--color-muted)]">Sending from</p>
          <p className="text-sm font-medium text-[var(--foreground)] mt-0.5">
            {status.from_number}
          </p>
          {status.account_sid_hint && (
            <p className="text-xs text-[var(--color-muted)]">
              Account ...{status.account_sid_hint}
            </p>
          )}
        </div>
      )}

      <div className="space-y-3 mb-4">
        <div>
          <FieldLabel>Account SID</FieldLabel>
          <Input
            value={accountSid}
            onChange={(e) => setAccountSid(e.target.value)}
            placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            autoComplete="off"
          />
        </div>
        <div>
          <FieldLabel>Auth Token</FieldLabel>
          <Input
            type="password"
            value={authToken}
            onChange={(e) => setAuthToken(e.target.value)}
            placeholder="Your auth token"
            autoComplete="off"
          />
        </div>
        <div>
          <FieldLabel>From Number</FieldLabel>
          <Input
            value={fromNumber}
            onChange={(e) => setFromNumber(e.target.value)}
            placeholder="+15551234567"
          />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="gold"
          onClick={handleSave}
          isLoading={busy}
          disabled={!accountSid || !authToken || !fromNumber}
          className="flex-1"
        >
          Save
        </Button>
        {status.connected && (
          <Button
            variant="outline"
            onClick={handleTest}
            isLoading={testing}
            disabled={busy}
          >
            Test
          </Button>
        )}
      </div>

      {status.connected && (
        <DisconnectButton onDisconnect={handleDisconnect} disabled={busy || testing} />
      )}
    </div>
  );
}

// ─── Vapi Panel ───────────────────────────────────────────────────────────────

const VOICE_MODELS = [
  { value: "elevenlabs", label: "ElevenLabs (Realistic)" },
  { value: "browser", label: "Browser TTS (Free)" },
  { value: "custom", label: "Custom / BYO Model" },
] as const;

function VapiPanel({
  status,
  onSave,
  onDisconnect,
}: {
  status: IntegrationStatus["vapi"];
  onSave: (config: VapiConfig) => Promise<void>;
  onDisconnect: () => Promise<void>;
}) {
  const [apiKey, setApiKey] = useState("");
  const [voiceModel, setVoiceModel] = useState<VapiConfig["voice_model"]>(
    (status.voice_model as VapiConfig["voice_model"]) ?? "browser"
  );
  const [firstMessage, setFirstMessage] = useState(status.first_message ?? "");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const handleSave = useCallback(async () => {
    setBusy(true);
    setFeedback(null);
    try {
      await onSave({ api_key: apiKey, voice_model: voiceModel, first_message: firstMessage });
      setFeedback({ type: "success", msg: "Vapi configured successfully." });
      setApiKey("");
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [apiKey, voiceModel, firstMessage, onSave]);

  const handleDisconnect = useCallback(async () => {
    setBusy(true);
    try {
      await onDisconnect();
      setFeedback({ type: "success", msg: "Vapi disconnected." });
      setFirstMessage("");
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [onDisconnect]);

  return (
    <div>
      {feedback && (
        <AlertBanner
          type={feedback.type}
          message={feedback.msg}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {status.connected && (
        <div className="glass-panel p-3 mb-4">
          <p className="text-xs text-[var(--color-muted)]">Voice model</p>
          <p className="text-sm font-medium text-[var(--foreground)] mt-0.5 capitalize">
            {status.voice_model ?? "Browser TTS"}
          </p>
        </div>
      )}

      <div className="space-y-3 mb-4">
        <div>
          <FieldLabel>Vapi API Key {status.connected && "(leave blank to keep current)"}</FieldLabel>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="vapi_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            autoComplete="off"
          />
        </div>
        <div>
          <FieldLabel>Voice Model</FieldLabel>
          <select
            value={voiceModel}
            onChange={(e) => setVoiceModel(e.target.value as VapiConfig["voice_model"])}
            className={cn(
              "flex h-10 w-full rounded-md px-3 py-2 text-sm",
              "bg-white/5 border border-[var(--stroke2)] text-[var(--foreground)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]"
            )}
          >
            {VOICE_MODELS.map((m) => (
              <option key={m.value} value={m.value} className="bg-[var(--ink-900)]">
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <FieldLabel>First Message (agent greeting)</FieldLabel>
          <Input
            value={firstMessage}
            onChange={(e) => setFirstMessage(e.target.value)}
            placeholder="Hi! How can I help you today?"
            maxLength={200}
          />
        </div>
      </div>

      <Button
        variant="gold"
        onClick={handleSave}
        isLoading={busy}
        disabled={!apiKey && !status.connected}
        className="w-full"
      >
        Save
      </Button>

      {status.connected && (
        <DisconnectButton onDisconnect={handleDisconnect} disabled={busy} />
      )}
    </div>
  );
}

// ─── Webhooks Panel ───────────────────────────────────────────────────────────

const WEBHOOK_EVENTS = [
  "message.received",
  "conversation.started",
  "conversation.ended",
  "task.created",
  "task.completed",
  "payment.received",
];

function WebhooksPanel({
  webhooks,
  onAdd,
  onDelete,
}: {
  webhooks: WebhookEntry[];
  onAdd: (config: WebhookConfig) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<string[]>(["message.received"]);
  const [authType, setAuthType] = useState<WebhookConfig["auth_type"]>("none");
  const [authValue, setAuthValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const toggleEvent = (event: string) => {
    setSelectedEvents((prev) =>
      prev.includes(event)
        ? prev.filter((e) => e !== event)
        : [...prev, event]
    );
  };

  const handleAdd = useCallback(async () => {
    if (!url || selectedEvents.length === 0) return;
    setBusy(true);
    setFeedback(null);
    try {
      await onAdd({
        url,
        events: selectedEvents,
        auth_type: authType,
        auth_value: authValue || undefined,
      });
      setFeedback({ type: "success", msg: "Webhook added successfully." });
      setUrl("");
      setSelectedEvents(["message.received"]);
      setAuthType("none");
      setAuthValue("");
      setShowForm(false);
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [url, selectedEvents, authType, authValue, onAdd]);

  const handleDelete = useCallback(
    async (id: string) => {
      setDeletingId(id);
      try {
        await onDelete(id);
      } catch (err) {
        setFeedback({ type: "error", msg: (err as Error).message });
      } finally {
        setDeletingId(null);
      }
    },
    [onDelete]
  );

  return (
    <div>
      {feedback && (
        <AlertBanner
          type={feedback.type}
          message={feedback.msg}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {/* Existing webhooks list */}
      {webhooks.length === 0 ? (
        <p className="text-sm text-[var(--color-muted)] py-2 mb-4">
          No webhooks configured yet.
        </p>
      ) : (
        <div className="space-y-2 mb-4">
          {webhooks.map((wh) => (
            <div
              key={wh.id}
              className="glass-panel p-3 flex items-start gap-3"
            >
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-[var(--foreground)] truncate">
                  {wh.url}
                </p>
                <p className="text-[10px] text-[var(--color-muted)] mt-0.5">
                  {wh.events.join(", ")}
                </p>
                <div className="flex items-center gap-1.5 mt-1">
                  <span
                    className={cn(
                      "text-[10px] px-1.5 py-0.5 rounded-full",
                      wh.active
                        ? "bg-green-400/10 text-green-400"
                        : "bg-white/5 text-[var(--color-muted)]"
                    )}
                  >
                    {wh.active ? "Active" : "Inactive"}
                  </span>
                  {wh.auth_type !== "none" && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-400/10 text-blue-400 capitalize">
                      {wh.auth_type}
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleDelete(wh.id)}
                disabled={deletingId === wh.id}
                className="text-[var(--color-muted)] hover:text-red-400 transition-colors p-1 flex-shrink-0 disabled:opacity-50"
                aria-label="Delete webhook"
              >
                {deletingId === wh.id ? (
                  <span className="spinner h-3.5 w-3.5" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add webhook form toggle */}
      {!showForm ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowForm(true)}
          className="w-full"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Webhook
        </Button>
      ) : (
        <div className="glass-panel p-4 space-y-3">
          <h4 className="text-xs font-semibold text-[var(--foreground)]">New Webhook</h4>

          <div>
            <FieldLabel>Endpoint URL</FieldLabel>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://yourapp.com/webhook"
              type="url"
            />
          </div>

          <div>
            <FieldLabel>Events</FieldLabel>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {WEBHOOK_EVENTS.map((event) => (
                <button
                  key={event}
                  onClick={() => toggleEvent(event)}
                  className={cn(
                    "text-[10px] px-2 py-1 rounded-full border transition-colors",
                    selectedEvents.includes(event)
                      ? "bg-[var(--gold-500)]/10 border-[var(--gold-500)]/30 text-[var(--gold-500)]"
                      : "bg-white/5 border-white/10 text-[var(--color-muted)] hover:border-white/20"
                  )}
                >
                  {event}
                </button>
              ))}
            </div>
          </div>

          <div>
            <FieldLabel>Auth Type</FieldLabel>
            <select
              value={authType}
              onChange={(e) => setAuthType(e.target.value as WebhookConfig["auth_type"])}
              className={cn(
                "flex h-10 w-full rounded-md px-3 py-2 text-sm",
                "bg-white/5 border border-[var(--stroke2)] text-[var(--foreground)]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)]"
              )}
            >
              <option value="none" className="bg-[var(--ink-900)]">None</option>
              <option value="bearer" className="bg-[var(--ink-900)]">Bearer Token</option>
              <option value="basic" className="bg-[var(--ink-900)]">Basic Auth</option>
            </select>
          </div>

          {authType !== "none" && (
            <div>
              <FieldLabel>
                {authType === "bearer" ? "Bearer Token" : "Password"}
              </FieldLabel>
              <Input
                type="password"
                value={authValue}
                onChange={(e) => setAuthValue(e.target.value)}
                placeholder={authType === "bearer" ? "Token value" : "Basic auth password"}
              />
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            <Button
              variant="gold"
              size="sm"
              onClick={handleAdd}
              isLoading={busy}
              disabled={!url || selectedEvents.length === 0}
              className="flex-1"
            >
              Add
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowForm(false)}
              disabled={busy}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── DD Main Bridge Panel ─────────────────────────────────────────────────────

function DdMainBridgePanel({
  status,
  onDisconnect,
}: {
  status: IntegrationStatus["dd_main_bridge"];
  onDisconnect: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const handleDisconnect = useCallback(async () => {
    setBusy(true);
    try {
      await onDisconnect();
      setFeedback({ type: "success", msg: "DD Main bridge disconnected." });
    } catch (err) {
      setFeedback({ type: "error", msg: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }, [onDisconnect]);

  return (
    <div>
      {feedback && (
        <AlertBanner
          type={feedback.type}
          message={feedback.msg}
          onDismiss={() => setFeedback(null)}
        />
      )}

      <div className="flex items-center gap-2 mb-4">
        <span
          className={cn(
            "h-2.5 w-2.5 rounded-full",
            status.connected ? "bg-green-400" : "bg-white/20"
          )}
        />
        <span className="text-sm text-[var(--foreground)]">
          {status.connected ? "Connected to DingDawg Main" : "Not connected"}
        </span>
      </div>

      <p className="text-xs text-[var(--color-muted)] mb-4 leading-relaxed">
        The DingDawg Main Bridge connects your agent to the DingDawg Command Center,
        enabling multi-location management, shared customers, and centralized billing.
      </p>

      {status.connected ? (
        <>
          {status.bridge_url && (
            <div className="glass-panel p-3 mb-3">
              <p className="text-xs text-[var(--color-muted)]">Bridge endpoint</p>
              <p className="text-sm font-mono text-[var(--foreground)] mt-0.5 truncate">
                {status.bridge_url}
              </p>
              {status.last_ping && (
                <p className="text-xs text-[var(--color-muted)] mt-1">
                  Last ping: {new Date(status.last_ping).toLocaleString()}
                </p>
              )}
            </div>
          )}
          <DisconnectButton onDisconnect={handleDisconnect} disabled={busy} />
        </>
      ) : (
        <div className="glass-panel p-4 text-center">
          <p className="text-sm text-[var(--color-muted)] mb-2">
            Contact your DingDawg administrator to obtain a bridge connection token.
          </p>
          <a
            href="https://dingdawg.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-[var(--gold-500)] hover:underline"
          >
            Learn more about DingDawg Main →
          </a>
        </div>
      )}
    </div>
  );
}

// ─── Modal labels ─────────────────────────────────────────────────────────────

const MODAL_TITLES: Record<ModalIntegration, string> = {
  google_calendar: "Google Calendar",
  sendgrid: "Email Notifications",
  twilio: "Text Messages (SMS)",
  vapi: "Phone Calls & Voicemail",
  webhooks: "Connect Other Apps",
  dd_main_bridge: "Multi-Location Management",
  cronofy: "All Calendars (Cronofy)",
  zapier: "Zapier (8,000+ Apps)",
  stripe: "Collect Payments",
};

const MODAL_ICONS: Record<ModalIntegration, string> = {
  google_calendar: "📅",
  sendgrid: "✉️",
  twilio: "💬",
  vapi: "📞",
  webhooks: "🔗",
  dd_main_bridge: "🏪",
  cronofy: "🗓️",
  zapier: "⚡",
  stripe: "💳",
};

// ─── Main Modal ───────────────────────────────────────────────────────────────

export function IntegrationConfigModal({
  integration,
  status,
  webhooks,
  onClose,
  onConnectGoogle,
  onConfigureSendGrid,
  onConfigureTwilio,
  onConfigureVapi,
  onDisconnect,
  onTestIntegration,
  onAddWebhook,
  onDeleteWebhook,
}: IntegrationConfigModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Close on overlay click
  const handleOverlayClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target === overlayRef.current) onClose();
    },
    [onClose]
  );

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={handleOverlayClick}
    >
      <div
        className={cn(
          "w-full sm:max-w-md max-h-[90dvh] overflow-y-auto",
          "glass-panel rounded-2xl shadow-2xl",
          "card-enter"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--stroke)]">
          <div className="flex items-center gap-3">
            <span className="text-xl">{MODAL_ICONS[integration]}</span>
            <h2 className="text-base font-heading font-semibold text-[var(--foreground)]">
              {MODAL_TITLES[integration]}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--color-muted)] hover:text-[var(--foreground)] hover:bg-white/5 transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5">
          {integration === "google_calendar" && (
            <GoogleCalendarPanel
              status={status.google_calendar}
              onConnect={onConnectGoogle}
              onDisconnect={() => onDisconnect("google_calendar")}
            />
          )}
          {integration === "sendgrid" && (
            <SendGridPanel
              status={status.sendgrid}
              onSave={onConfigureSendGrid}
              onTest={() => onTestIntegration("sendgrid")}
              onDisconnect={() => onDisconnect("sendgrid")}
            />
          )}
          {integration === "twilio" && (
            <TwilioPanel
              status={status.twilio}
              onSave={onConfigureTwilio}
              onTest={() => onTestIntegration("twilio")}
              onDisconnect={() => onDisconnect("twilio")}
            />
          )}
          {integration === "vapi" && (
            <VapiPanel
              status={status.vapi}
              onSave={onConfigureVapi}
              onDisconnect={() => onDisconnect("vapi")}
            />
          )}
          {integration === "webhooks" && (
            <WebhooksPanel
              webhooks={webhooks}
              onAdd={onAddWebhook}
              onDelete={onDeleteWebhook}
            />
          )}
          {integration === "dd_main_bridge" && (
            <DdMainBridgePanel
              status={status.dd_main_bridge}
              onDisconnect={() => onDisconnect("dd_main_bridge")}
            />
          )}
        </div>
      </div>
    </div>
  );
}
