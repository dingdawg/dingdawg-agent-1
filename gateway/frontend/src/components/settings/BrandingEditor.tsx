"use client";

/**
 * BrandingEditor — Agent branding & visual identity tab.
 *
 * Stores into branding_json:
 *   { primary_color, avatar_url, business_name, widget_greeting }
 */

import { useState, useEffect } from "react";
import { Save, Palette, User, MessageSquare, Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface BrandingConfig {
  primary_color: string;
  avatar_url: string;
  business_name: string;
  widget_greeting: string;
}

interface BrandingEditorProps {
  initialConfig: Partial<BrandingConfig>;
  agentName: string;
  agentHandle: string;
  onSave: (config: BrandingConfig) => Promise<void>;
  saving: boolean;
}

// ─── Preset Colors ────────────────────────────────────────────────────────────

const PRESET_COLORS = [
  { value: "#F6B400", label: "Gold" },
  { value: "#3B82F6", label: "Blue" },
  { value: "#10B981", label: "Green" },
  { value: "#8B5CF6", label: "Purple" },
  { value: "#EF4444", label: "Red" },
  { value: "#F97316", label: "Orange" },
];

// ─── Avatar Preview ────────────────────────────────────────────────────────────

function AvatarPreview({
  url,
  name,
  color,
}: {
  url: string;
  name: string;
  color: string;
}) {
  const initials = name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={name}
        className="h-16 w-16 rounded-full object-cover border-2"
        style={{ borderColor: color }}
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = "none";
        }}
      />
    );
  }

  return (
    <div
      className="h-16 w-16 rounded-full flex items-center justify-center text-lg font-bold text-white border-2"
      style={{ background: color, borderColor: color }}
    >
      {initials || <User className="h-6 w-6" />}
    </div>
  );
}

// ─── Widget Preview ────────────────────────────────────────────────────────────

function WidgetPreview({
  agentName,
  greeting,
  color,
  avatarUrl,
}: {
  agentName: string;
  greeting: string;
  color: string;
  avatarUrl: string;
}) {
  const initials = agentName
    .split(" ")
    .map((w) => w[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="rounded-xl border border-[var(--stroke2)] bg-white/[0.03] p-3 max-w-xs">
      <div className="flex items-center gap-2.5 mb-2.5 pb-2.5 border-b border-[var(--stroke)]">
        <div
          className="h-7 w-7 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0 overflow-hidden"
          style={{ background: color }}
        >
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatarUrl}
              alt={agentName}
              className="h-full w-full object-cover"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            initials || "AI"
          )}
        </div>
        <span className="text-xs font-semibold text-[var(--foreground)]">
          {agentName || "Your Agent"}
        </span>
        <span className="ml-auto h-1.5 w-1.5 rounded-full bg-green-400 flex-shrink-0" />
      </div>
      <div
        className="rounded-lg rounded-tl-none px-3 py-2 text-xs text-white max-w-[80%] leading-relaxed"
        style={{ background: color }}
      >
        {greeting || "Hi! How can I help you today?"}
      </div>
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function BrandingEditor({
  initialConfig,
  agentName,
  agentHandle,
  onSave,
  saving,
}: BrandingEditorProps) {
  const [primaryColor, setPrimaryColor] = useState(
    initialConfig.primary_color ?? "#F6B400"
  );
  const [avatarUrl, setAvatarUrl] = useState(initialConfig.avatar_url ?? "");
  const [businessName, setBusinessName] = useState(
    initialConfig.business_name ?? ""
  );
  const [widgetGreeting, setWidgetGreeting] = useState(
    initialConfig.widget_greeting ?? ""
  );
  const [customColor, setCustomColor] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    const orig = initialConfig;
    const changed =
      primaryColor !== (orig.primary_color ?? "#F6B400") ||
      avatarUrl !== (orig.avatar_url ?? "") ||
      businessName !== (orig.business_name ?? "") ||
      widgetGreeting !== (orig.widget_greeting ?? "");
    setDirty(changed);
  }, [primaryColor, avatarUrl, businessName, widgetGreeting, initialConfig]);

  const handleCustomColorChange = (val: string) => {
    setCustomColor(val);
    // Validate hex — only apply if valid
    if (/^#[0-9A-Fa-f]{6}$/.test(val)) {
      setPrimaryColor(val);
    }
  };

  const handleSave = async () => {
    await onSave({
      primary_color: primaryColor,
      avatar_url: avatarUrl,
      business_name: businessName,
      widget_greeting: widgetGreeting,
    });
    setDirty(false);
  };

  return (
    <div className="space-y-5">
      {/* Unsaved indicator */}
      {dirty && (
        <div className="px-3 py-2 rounded-lg bg-[var(--gold-500)]/10 border border-[var(--gold-500)]/20 text-[var(--gold-500)] text-xs font-medium">
          Unsaved changes
        </div>
      )}

      {/* Live widget preview */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-3">
          Widget Preview
        </h3>
        <WidgetPreview
          agentName={businessName || agentName}
          greeting={widgetGreeting}
          color={primaryColor}
          avatarUrl={avatarUrl}
        />
        <p className="text-xs text-[var(--color-muted)] mt-2">
          @{agentHandle} · Updates as you edit
        </p>
      </div>

      {/* Brand Color */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1 flex items-center gap-2">
          <Palette className="h-4 w-4 text-[var(--gold-500)]" />
          Brand Color
        </h3>
        <p className="text-xs text-[var(--color-muted)] mb-3">
          Used in your chat widget and public profile
        </p>

        {/* Preset swatches */}
        <div className="flex flex-wrap gap-2 mb-3">
          {PRESET_COLORS.map((c) => (
            <button
              key={c.value}
              onClick={() => {
                setPrimaryColor(c.value);
                setCustomColor("");
              }}
              title={c.label}
              className={`h-8 w-8 rounded-full border-2 transition-all hover:scale-110 ${
                primaryColor === c.value
                  ? "border-white scale-110 shadow-lg"
                  : "border-transparent"
              }`}
              style={{ background: c.value }}
              aria-label={`${c.label} color`}
            />
          ))}
        </div>

        {/* Custom hex */}
        <div className="flex items-center gap-2">
          <div
            className="h-8 w-8 rounded-md border border-[var(--stroke2)] flex-shrink-0"
            style={{ background: primaryColor }}
          />
          <Input
            value={customColor || primaryColor}
            onChange={(e) => handleCustomColorChange(e.target.value)}
            placeholder="#F6B400"
            maxLength={7}
            className="font-mono text-xs w-32"
          />
          <span className="text-xs text-[var(--color-muted)]">
            Custom hex color
          </span>
        </div>
      </div>

      {/* Avatar */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1 flex items-center gap-2">
          <User className="h-4 w-4 text-[var(--gold-500)]" />
          Agent Avatar
        </h3>
        <p className="text-xs text-[var(--color-muted)] mb-3">
          Enter a public image URL for your agent&apos;s profile picture
        </p>

        <div className="flex items-center gap-4">
          <AvatarPreview
            url={avatarUrl}
            name={businessName || agentName}
            color={primaryColor}
          />
          <div className="flex-1">
            <Input
              value={avatarUrl}
              onChange={(e) => setAvatarUrl(e.target.value)}
              placeholder="https://example.com/avatar.png"
              type="url"
            />
            <p className="text-xs text-[var(--color-muted)] mt-1.5">
              Must be a public URL. Recommended: 256×256px, square
            </p>
          </div>
        </div>
      </div>

      {/* Business Name */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1 flex items-center gap-2">
          <Building2 className="h-4 w-4 text-[var(--gold-500)]" />
          Display Name
        </h3>
        <p className="text-xs text-[var(--color-muted)] mb-3">
          Business or brand name shown in your widget header
        </p>
        <Input
          value={businessName}
          onChange={(e) => setBusinessName(e.target.value)}
          placeholder={agentName || "My Business"}
          maxLength={60}
        />
        <p className="text-xs text-[var(--color-muted)] mt-1.5">
          Leave blank to use your agent name: &quot;{agentName}&quot;
        </p>
      </div>

      {/* Widget Greeting */}
      <div className="glass-panel p-5">
        <h3 className="text-sm font-semibold text-[var(--foreground)] mb-1 flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-[var(--gold-500)]" />
          Widget Greeting
        </h3>
        <p className="text-xs text-[var(--color-muted)] mb-3">
          First message your agent sends when a visitor opens the chat
        </p>
        <textarea
          value={widgetGreeting}
          onChange={(e) => setWidgetGreeting(e.target.value)}
          placeholder="Hi! I'm here to help. What can I do for you today?"
          rows={3}
          maxLength={280}
          className="w-full rounded-md px-3 py-2.5 text-sm bg-white/5 border border-[var(--stroke2)] text-[var(--foreground)] placeholder:text-[var(--color-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--gold-500)] resize-none leading-relaxed"
        />
        <p className="text-xs text-[var(--color-muted)] mt-1.5">
          {widgetGreeting.length}/280 characters
        </p>
      </div>

      {/* Save */}
      <Button
        variant="gold"
        onClick={handleSave}
        isLoading={saving}
        disabled={!dirty}
        className="w-full"
      >
        <Save className="h-4 w-4" />
        Save Branding
      </Button>
    </div>
  );
}
