"use client";

/**
 * MfaChallengeModal — shown after a successful password login when MFA is required.
 *
 * Tabs:
 *   1. Authenticator App (TOTP)
 *   2. SMS Code (if phone is registered)
 *   3. Backup Code
 *
 * On success: calls onSuccess(accessToken, userId, email) so the parent
 * page can store the token and redirect.
 */

import { useState } from "react";
import {
  mfaChallenge,
  mfaSendSms,
} from "@/services/api/authService";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ShieldCheck, MessageSquare, Key } from "lucide-react";

type TabType = "totp" | "sms" | "backup";

interface Props {
  challengeToken: string;
  userId: string;
  email: string;
  onSuccess: (accessToken: string, userId: string, email: string) => void;
  onCancel: () => void;
}

export function MfaChallengeModal({
  challengeToken,
  userId,
  email,
  onSuccess,
  onCancel,
}: Props) {
  const [tab, setTab] = useState<TabType>("totp");
  const [code, setCode] = useState("");
  const [rememberDevice, setRememberDevice] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [smsSent, setSmsSent] = useState(false);
  const [smsSending, setSmsSending] = useState(false);

  const handleSendSms = async () => {
    setSmsSending(true);
    setError(null);
    try {
      await mfaSendSms(challengeToken);
      setSmsSent(true);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to send SMS. Please try another method.";
      setError(detail);
    } finally {
      setSmsSending(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;

    setIsLoading(true);
    setError(null);
    try {
      const res = await mfaChallenge({
        challenge_token: challengeToken,
        code: code.trim(),
        code_type: tab,
        remember_device: rememberDevice,
      });
      onSuccess(res.access_token, res.user_id, res.email);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Invalid code. Please try again.";
      setError(detail);
      setCode("");
    } finally {
      setIsLoading(false);
    }
  };

  const tabs: { id: TabType; label: string; icon: React.ReactNode }[] = [
    { id: "totp", label: "Authenticator", icon: <ShieldCheck className="h-4 w-4" /> },
    { id: "sms", label: "SMS Code", icon: <MessageSquare className="h-4 w-4" /> },
    { id: "backup", label: "Backup Code", icon: <Key className="h-4 w-4" /> },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
      <div className="w-full max-w-md rounded-2xl bg-[var(--surface)] border border-[var(--stroke)] shadow-2xl p-8">
        {/* Header */}
        <div className="flex flex-col items-center gap-2 mb-6">
          <div className="w-12 h-12 rounded-full bg-[var(--gold-500)]/10 flex items-center justify-center">
            <ShieldCheck className="h-6 w-6 text-[var(--gold-500)]" />
          </div>
          <h2 className="text-xl font-bold text-[var(--foreground)] font-heading">
            Two-Factor Authentication
          </h2>
          <p className="text-sm text-[var(--color-muted)] text-center">
            Signing in as <span className="font-medium text-[var(--foreground)]">{email}</span>
          </p>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 p-1 rounded-xl bg-[var(--surface-alt,#1a1a2e)] mb-6">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => { setTab(t.id); setCode(""); setError(null); setSmsSent(false); }}
              className={[
                "flex-1 flex items-center justify-center gap-1.5 py-2 px-2 rounded-lg text-xs font-semibold transition-all",
                tab === t.id
                  ? "bg-[var(--gold-500)] text-black"
                  : "text-[var(--color-muted)] hover:text-[var(--foreground)]",
              ].join(" ")}
            >
              {t.icon}
              <span className="hidden sm:inline">{t.label}</span>
            </button>
          ))}
        </div>

        {/* Tab content */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {/* TOTP */}
          {tab === "totp" && (
            <div>
              <p className="text-sm text-[var(--color-muted)] mb-3">
                Enter the 6-digit code from your authenticator app (Google Authenticator, Authy, etc.).
              </p>
              <Input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                placeholder="000000"
                autoComplete="one-time-code"
                autoFocus
                className="text-center text-2xl tracking-[0.5em] font-mono"
              />
            </div>
          )}

          {/* SMS */}
          {tab === "sms" && (
            <div>
              {!smsSent ? (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-[var(--color-muted)]">
                    Send a 6-digit code to your registered phone number.
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleSendSms}
                    isLoading={smsSending}
                  >
                    Send SMS Code
                  </Button>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-[var(--color-muted)] mb-3">
                    Code sent! Enter it below (expires in 10 minutes).{" "}
                    <button
                      type="button"
                      className="text-[var(--gold-500)] underline text-xs"
                      onClick={handleSendSms}
                    >
                      Resend
                    </button>
                  </p>
                  <Input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    placeholder="000000"
                    autoComplete="one-time-code"
                    autoFocus
                    className="text-center text-2xl tracking-[0.5em] font-mono"
                  />
                </div>
              )}
            </div>
          )}

          {/* Backup */}
          {tab === "backup" && (
            <div>
              <p className="text-sm text-[var(--color-muted)] mb-3">
                Enter one of your 8-character backup codes. Each code can only be used once.
              </p>
              <Input
                type="text"
                inputMode="text"
                maxLength={8}
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="ABCD1234"
                autoComplete="off"
                autoFocus
                className="text-center text-xl tracking-[0.4em] font-mono uppercase"
              />
            </div>
          )}

          {/* Error */}
          {error && (
            <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
              {error}
            </p>
          )}

          {/* Remember device */}
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={rememberDevice}
              onChange={(e) => setRememberDevice(e.target.checked)}
              className="rounded border-[var(--stroke)] accent-[var(--gold-500)]"
            />
            <span className="text-sm text-[var(--color-muted)]">
              Remember this device for 30 days
            </span>
          </label>

          {/* Actions */}
          <div className="flex gap-3 mt-2">
            <Button type="button" variant="outline" onClick={onCancel} className="flex-1">
              Cancel
            </Button>
            <Button
              type="submit"
              variant="gold"
              isLoading={isLoading}
              className="flex-1"
              disabled={
                (tab === "sms" && !smsSent) ||
                code.length === 0
              }
            >
              Verify
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
