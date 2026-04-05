"use client";

/**
 * MfaSetupPanel — MFA management section for the settings page.
 *
 * States:
 *  - MFA disabled:   show setup button → QR code + code entry → backup codes display
 *  - MFA enabled:    show status (backup codes remaining, phone registered) + disable button
 *
 * Requirements:
 *  - TOTP via any TOTP app (Google Authenticator, Authy, 1Password, etc.)
 *  - SMS OTP via registered phone number (optional add-on)
 *  - Backup codes displayed once after setup
 */

import { useEffect, useState, useCallback } from "react";
import { QRCodeSVG } from "qrcode.react";
import {
  getMfaStatus,
  mfaSetupStart,
  mfaVerifySetup,
  mfaDisable,
  mfaRegisterPhone,
  type MfaStatusResponse,
} from "@/services/api/authService";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ShieldCheck,
  ShieldOff,
  Smartphone,
  Copy,
  CheckCircle,
  AlertTriangle,
} from "lucide-react";

type SetupStep = "idle" | "qr" | "verify" | "backup-codes" | "done";
type PanelMode = "loading" | "enabled" | "disabled" | "setup";

export function MfaSetupPanel() {
  const [status, setStatus] = useState<MfaStatusResponse | null>(null);
  const [mode, setMode] = useState<PanelMode>("loading");
  const [step, setStep] = useState<SetupStep>("idle");

  // Setup flow state
  const [pendingSecret, setPendingSecret] = useState("");
  const [otpauthUri, setOtpauthUri] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [copiedAll, setCopiedAll] = useState(false);

  // Disable flow state
  const [showDisable, setShowDisable] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableTotpCode, setDisableTotpCode] = useState("");

  // Phone registration state
  const [showPhone, setShowPhone] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [phoneSaved, setPhoneSaved] = useState(false);

  // Loading / error state
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getMfaStatus();
      setStatus(s);
      setMode(s.mfa_enabled ? "enabled" : "disabled");
    } catch {
      setMode("disabled"); // fail open — assume disabled
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  // --- Setup flow ---

  const handleStartSetup = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await mfaSetupStart();
      setPendingSecret(res.secret);
      setOtpauthUri(res.otpauth_uri);
      setStep("qr");
      setMode("setup");
    } catch (err: unknown) {
      setError(extractDetail(err, "Failed to start MFA setup"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerifySetup = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      const res = await mfaVerifySetup(pendingSecret, totpCode);
      setBackupCodes(res.backup_codes);
      setStep("backup-codes");
    } catch (err: unknown) {
      setError(extractDetail(err, "Invalid code. Try again."));
      setTotpCode("");
    } finally {
      setIsLoading(false);
    }
  };

  const handleFinishSetup = async () => {
    setStep("done");
    await loadStatus();
  };

  // --- Disable flow ---

  const handleDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      await mfaDisable(disablePassword, disableTotpCode);
      setSuccess("MFA has been disabled.");
      setShowDisable(false);
      setDisablePassword("");
      setDisableTotpCode("");
      await loadStatus();
    } catch (err: unknown) {
      setError(extractDetail(err, "Failed to disable MFA"));
    } finally {
      setIsLoading(false);
    }
  };

  // --- Phone registration ---

  const handleSavePhone = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      await mfaRegisterPhone(phoneNumber);
      setPhoneSaved(true);
      setShowPhone(false);
      await loadStatus();
    } catch (err: unknown) {
      setError(extractDetail(err, "Failed to save phone number"));
    } finally {
      setIsLoading(false);
    }
  };

  // --- Helpers ---

  const handleCopyAll = () => {
    navigator.clipboard.writeText(backupCodes.join("\n"));
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2000);
  };

  if (mode === "loading") {
    return (
      <div className="flex items-center gap-2 py-6 text-[var(--color-muted)] text-sm">
        <div className="w-4 h-4 border-2 border-[var(--gold-400)] border-t-transparent rounded-full animate-spin" />
        Loading MFA status...
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-[var(--stroke)] bg-[var(--surface)] p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div
          className={[
            "w-10 h-10 rounded-xl flex items-center justify-center",
            status?.mfa_enabled
              ? "bg-green-500/10"
              : "bg-[var(--gold-500)]/10",
          ].join(" ")}
        >
          {status?.mfa_enabled ? (
            <ShieldCheck className="h-5 w-5 text-green-400" />
          ) : (
            <ShieldOff className="h-5 w-5 text-[var(--gold-500)]" />
          )}
        </div>
        <div>
          <h3 className="font-semibold text-[var(--foreground)]">
            Two-Factor Authentication
          </h3>
          <p className="text-xs text-[var(--color-muted)]">
            {status?.mfa_enabled
              ? "Your account is protected with 2FA"
              : "Add an extra layer of security to your account"}
          </p>
        </div>
        {status?.mfa_enabled && (
          <span className="ml-auto text-xs font-semibold text-green-400 bg-green-500/10 px-2.5 py-1 rounded-full">
            Enabled
          </span>
        )}
      </div>

      {/* Feedback messages */}
      {error && (
        <div className="flex items-start gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl p-3">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="flex items-start gap-2 text-sm text-green-400 bg-green-500/10 border border-green-500/20 rounded-xl p-3">
          <CheckCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{success}</span>
        </div>
      )}

      {/* ---- DISABLED STATE ---- */}
      {mode === "disabled" && step === "idle" && (
        <div className="space-y-3">
          <p className="text-sm text-[var(--color-muted)]">
            Enable 2FA using an authenticator app (Google Authenticator, Authy, 1Password, etc.)
            to protect your account from unauthorized access.
          </p>
          <Button
            variant="gold"
            onClick={handleStartSetup}
            isLoading={isLoading}
            className="w-full sm:w-auto"
          >
            Set Up Two-Factor Authentication
          </Button>
        </div>
      )}

      {/* ---- SETUP STEP: QR CODE ---- */}
      {(mode === "setup" || mode === "disabled") && step === "qr" && (
        <div className="space-y-4">
          <div>
            <p className="text-sm text-[var(--color-muted)] mb-3">
              1. Open your authenticator app and scan this QR code (or enter the secret manually).
            </p>
            {/* QR code rendered client-side — secret NEVER leaves the browser */}
            <div className="flex justify-center mb-3">
              <div className="rounded-xl border border-[var(--stroke)] bg-white p-2 inline-block">
                <QRCodeSVG
                  value={otpauthUri}
                  size={200}
                  bgColor="#ffffff"
                  fgColor="#000000"
                  level="M"
                />
              </div>
            </div>
            <p className="text-xs text-[var(--color-muted)] text-center mb-1">
              Can&apos;t scan? Enter this secret manually:
            </p>
            <div className="flex items-center gap-2 bg-[var(--surface-alt,#111)] rounded-lg px-3 py-2 font-mono text-xs text-[var(--foreground)] break-all">
              <span className="flex-1">{pendingSecret}</span>
              <button
                type="button"
                onClick={() => navigator.clipboard.writeText(pendingSecret)}
                className="shrink-0 text-[var(--color-muted)] hover:text-[var(--foreground)]"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <form onSubmit={handleVerifySetup} className="space-y-3">
            <div>
              <label className="block text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-2">
                2. Enter the 6-digit code from your app
              </label>
              <Input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                placeholder="000000"
                autoComplete="one-time-code"
                className="text-center text-2xl tracking-[0.5em] font-mono"
              />
            </div>
            <div className="flex gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => { setStep("idle"); setMode("disabled"); }}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="gold"
                isLoading={isLoading}
                disabled={totpCode.length !== 6}
                className="flex-1"
              >
                Activate 2FA
              </Button>
            </div>
          </form>
        </div>
      )}

      {/* ---- SETUP STEP: BACKUP CODES ---- */}
      {step === "backup-codes" && (
        <div className="space-y-4">
          <div className="flex items-start gap-2 text-sm text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-xl p-3">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>
              <strong>Save these backup codes now.</strong> They won&apos;t be shown again.
              Each code can only be used once.
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {backupCodes.map((code) => (
              <div
                key={code}
                className="font-mono text-sm bg-[var(--surface-alt,#111)] rounded-lg px-3 py-2 text-center text-[var(--foreground)] tracking-widest"
              >
                {code}
              </div>
            ))}
          </div>

          <Button
            type="button"
            variant="outline"
            onClick={handleCopyAll}
            className="w-full"
          >
            {copiedAll ? (
              <><CheckCircle className="h-4 w-4 mr-2 text-green-400" />Copied!</>
            ) : (
              <><Copy className="h-4 w-4 mr-2" />Copy All Codes</>
            )}
          </Button>

          <Button
            type="button"
            variant="gold"
            onClick={handleFinishSetup}
            className="w-full"
          >
            I&apos;ve saved my backup codes
          </Button>
        </div>
      )}

      {/* ---- ENABLED STATE ---- */}
      {mode === "enabled" && step !== "backup-codes" && (
        <div className="space-y-4">
          {/* Status summary */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-[var(--surface-alt,#111)] p-3 text-center">
              <p className="text-xs text-[var(--color-muted)] mb-1">Backup Codes Left</p>
              <p className="text-xl font-bold text-[var(--foreground)]">
                {status?.backup_codes_remaining ?? "—"}
              </p>
            </div>
            <div className="rounded-xl bg-[var(--surface-alt,#111)] p-3 text-center">
              <p className="text-xs text-[var(--color-muted)] mb-1">SMS OTP</p>
              <p className="text-sm font-semibold text-[var(--foreground)]">
                {status?.has_phone ? "Registered" : "Not set"}
              </p>
            </div>
          </div>

          {/* Phone registration */}
          {!status?.has_phone && !showPhone && (
            <button
              type="button"
              className="flex items-center gap-2 text-sm text-[var(--gold-500)] hover:underline"
              onClick={() => setShowPhone(true)}
            >
              <Smartphone className="h-4 w-4" />
              Add phone number for SMS backup
            </button>
          )}

          {showPhone && (
            <form onSubmit={handleSavePhone} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-[var(--color-muted)] uppercase tracking-wider mb-2">
                  Phone Number (E.164 format)
                </label>
                <Input
                  type="tel"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  placeholder="+12125551234"
                  autoComplete="tel"
                />
              </div>
              <div className="flex gap-3">
                <Button type="button" variant="outline" onClick={() => setShowPhone(false)} className="flex-1">
                  Cancel
                </Button>
                <Button type="submit" variant="gold" isLoading={isLoading} className="flex-1">
                  Save Number
                </Button>
              </div>
            </form>
          )}

          {phoneSaved && (
            <p className="text-sm text-green-400">Phone number saved successfully.</p>
          )}

          {/* Disable MFA */}
          {!showDisable ? (
            <button
              type="button"
              className="flex items-center gap-2 text-sm text-red-400 hover:underline"
              onClick={() => setShowDisable(true)}
            >
              <ShieldOff className="h-4 w-4" />
              Disable Two-Factor Authentication
            </button>
          ) : (
            <form onSubmit={handleDisable} className="space-y-3 border border-red-500/20 rounded-xl p-4 bg-red-500/5">
              <p className="text-sm font-semibold text-red-400">Disable 2FA</p>
              <p className="text-xs text-[var(--color-muted)]">
                Enter your password and a TOTP code to confirm.
              </p>
              <Input
                type="password"
                value={disablePassword}
                onChange={(e) => setDisablePassword(e.target.value)}
                placeholder="Your password"
                autoComplete="current-password"
              />
              <Input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={disableTotpCode}
                onChange={(e) => setDisableTotpCode(e.target.value.replace(/\D/g, ""))}
                placeholder="6-digit TOTP code"
                autoComplete="one-time-code"
                className="font-mono tracking-widest text-center"
              />
              <div className="flex gap-3">
                <Button type="button" variant="outline" onClick={() => setShowDisable(false)} className="flex-1">
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="destructive"
                  isLoading={isLoading}
                  disabled={!disablePassword || disableTotpCode.length !== 6}
                  className="flex-1"
                >
                  Disable 2FA
                </Button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractDetail(err: unknown, fallback: string): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? fallback
  );
}
