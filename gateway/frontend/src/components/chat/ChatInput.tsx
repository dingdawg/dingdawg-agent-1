"use client";

/**
 * Chat input with attachment support.
 * Enter to send, Shift+Enter for newline.
 * + button opens attachment menu (Claude/WhatsApp pattern).
 * Drag-and-drop + clipboard paste for files/images.
 *
 * UI LOCK: flex-1 w-full min-w-0 text-base — SACRED classes on textarea.
 *
 * Attachment pattern (researched from Claude, ChatGPT, WhatsApp, iMessage):
 * - [+] button LEFT of textarea
 * - Tap → action sheet with: Camera, Photos, Files, Location
 * - Preview strip ABOVE input bar for selected media
 * - Drag-and-drop on desktop
 * - Clipboard paste for images
 */

import { useState, useRef, useCallback, useEffect } from "react";
import {
  Send,
  Plus,
  X,
  Camera,
  Image as ImageIcon,
  FileText,
  MapPin,
  File,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ChatAttachment {
  id: string;
  file: File;
  type: "image" | "video" | "document";
  previewUrl?: string;
  name: string;
  size: number;
}

interface ChatInputProps {
  onSend: (message: string, attachments?: ChatAttachment[]) => void;
  disabled?: boolean;
  placeholder?: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function generateId(): string {
  return `att_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
}

function getFileType(file: File): "image" | "video" | "document" {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  return "document";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25MB
const MAX_ATTACHMENTS = 10;
const ACCEPTED_IMAGE = "image/jpeg,image/png,image/gif,image/webp,image/heic";
const ACCEPTED_VIDEO = "video/mp4,video/quicktime,video/webm";
const ACCEPTED_DOC = ".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.rtf,.ppt,.pptx";

// ─── Attachment Menu Options ─────────────────────────────────────────────────

interface MenuOption {
  id: string;
  label: string;
  icon: typeof Camera;
  accept: string;
  capture?: "environment" | "user";
}

const MENU_OPTIONS: MenuOption[] = [
  {
    id: "camera",
    label: "Camera",
    icon: Camera,
    accept: "image/*",
    capture: "environment",
  },
  {
    id: "photos",
    label: "Photos & Videos",
    icon: ImageIcon,
    accept: `${ACCEPTED_IMAGE},${ACCEPTED_VIDEO}`,
  },
  {
    id: "files",
    label: "Files & Documents",
    icon: FileText,
    accept: `${ACCEPTED_IMAGE},${ACCEPTED_VIDEO},${ACCEPTED_DOC}`,
  },
];

// ─── Component ───────────────────────────────────────────────────────────────

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Type a message...",
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const activeAcceptRef = useRef<string>("");
  const activeCaptureRef = useRef<string | undefined>(undefined);

  // ── Send ──────────────────────────────────────────────────────────────────

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    const hasContent = trimmed || attachments.length > 0;
    if (!hasContent || disabled) return;
    if (navigator.vibrate) navigator.vibrate(10);

    onSend(trimmed, attachments.length > 0 ? attachments : undefined);
    setValue("");
    setAttachments([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, attachments, disabled, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else if (e.key === "Escape") {
      e.preventDefault();
      textareaRef.current?.blur();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  // ── File handling ─────────────────────────────────────────────────────────

  const processFiles = useCallback((files: FileList | File[]) => {
    const fileArray = Array.from(files);

    setAttachments((prev) => {
      const remaining = MAX_ATTACHMENTS - prev.length;
      const toAdd = fileArray.slice(0, remaining);

      const newAttachments: ChatAttachment[] = toAdd
        .filter((f) => f.size <= MAX_FILE_SIZE)
        .map((file) => {
          const type = getFileType(file);
          const previewUrl =
            type === "image" ? URL.createObjectURL(file) : undefined;
          return {
            id: generateId(),
            file,
            type,
            previewUrl,
            name: file.name,
            size: file.size,
          };
        });

      return [...prev, ...newAttachments];
    });
  }, []);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        processFiles(e.target.files);
      }
      // Reset input so same file can be selected again
      e.target.value = "";
    },
    [processFiles]
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const removed = prev.find((a) => a.id === id);
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
      return prev.filter((a) => a.id !== id);
    });
  }, []);

  // ── Menu option click ─────────────────────────────────────────────────────

  const handleMenuOption = useCallback((option: MenuOption) => {
    setMenuOpen(false);
    activeAcceptRef.current = option.accept;
    activeCaptureRef.current = option.capture;

    // Small delay to let menu close animation finish
    setTimeout(() => {
      if (fileInputRef.current) {
        fileInputRef.current.accept = option.accept;
        if (option.capture) {
          fileInputRef.current.setAttribute("capture", option.capture);
        } else {
          fileInputRef.current.removeAttribute("capture");
        }
        fileInputRef.current.click();
      }
    }, 50);
  }, []);

  // ── Close menu on outside click ───────────────────────────────────────────

  useEffect(() => {
    if (!menuOpen) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen]);

  // ── Drag and drop ─────────────────────────────────────────────────────────

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files.length > 0) {
        processFiles(e.dataTransfer.files);
      }
    },
    [processFiles]
  );

  // ── Clipboard paste ───────────────────────────────────────────────────────

  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;

      const files: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
      if (files.length > 0) {
        processFiles(files);
      }
    },
    [processFiles]
  );

  // ── Cleanup preview URLs on unmount ───────────────────────────────────────

  useEffect(() => {
    return () => {
      attachments.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Render ────────────────────────────────────────────────────────────────

  const hasAttachments = attachments.length > 0;
  const canSend = value.trim() || hasAttachments;

  return (
    <div
      className={cn(
        "relative border-t border-[var(--color-gold-stroke)] bg-[var(--ink-950)] lg:bg-[var(--glass)] lg:backdrop-blur-xl",
        isDragging && "ring-2 ring-[var(--gold-500)] ring-inset"
      )}
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* ── Attachment preview strip ─────────────────────────────── */}
      {hasAttachments && (
        <div className="flex gap-2 px-4 pt-3 pb-1 overflow-x-auto scrollbar-thin">
          {attachments.map((att) => (
            <div
              key={att.id}
              className="relative flex-shrink-0 group"
            >
              {att.type === "image" && att.previewUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={att.previewUrl}
                  alt={att.name}
                  className="h-16 w-16 rounded-lg object-cover border border-[var(--stroke)]"
                />
              ) : (
                <div className="h-16 w-16 rounded-lg bg-white/5 border border-[var(--stroke)] flex flex-col items-center justify-center gap-1 px-1">
                  <File className="h-5 w-5 text-[var(--color-muted)]" />
                  <span className="text-[8px] text-[var(--color-muted)] truncate max-w-full leading-tight text-center">
                    {att.name.length > 10
                      ? att.name.slice(0, 7) + "..." + att.name.slice(att.name.lastIndexOf("."))
                      : att.name}
                  </span>
                </div>
              )}
              {/* Size badge */}
              <span className="absolute bottom-0.5 left-0.5 text-[8px] bg-black/70 text-white px-1 rounded">
                {formatSize(att.size)}
              </span>
              {/* Remove button — always visible on touch, hover-gated on pointer devices */}
              <button
                onClick={() => removeAttachment(att.id)}
                className="absolute -top-1.5 -right-1.5 h-5 w-5 rounded-full bg-red-500 text-white flex items-center justify-center opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 transition-opacity min-h-[44px] min-w-[44px] -m-[13px] p-[13px]"
                aria-label={`Remove ${att.name}`}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          {attachments.length < MAX_ATTACHMENTS && (
            <button
              onClick={() => setMenuOpen(true)}
              className="h-16 w-16 rounded-lg border-2 border-dashed border-[var(--stroke)] flex items-center justify-center text-[var(--color-muted)] hover:border-[var(--gold-500)]/30 hover:text-[var(--gold-500)] transition-colors flex-shrink-0"
              aria-label="Add more files"
            >
              <Plus className="h-5 w-5" />
            </button>
          )}
        </div>
      )}

      {/* ── Input row — single container with buttons inside (Gemini/Grok pattern) */}
      <div className="px-3 lg:px-4 py-2">
        <div className="relative" ref={menuRef}>
          {/* Action sheet menu — appears above */}
          {menuOpen && (
            <div className="absolute bottom-full left-0 mb-2 w-52 glass-panel p-1.5 shadow-xl z-50">
              {MENU_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => handleMenuOption(opt)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[var(--foreground)] hover:bg-white/5 transition-colors min-h-[44px]"
                >
                  <div className="h-8 w-8 rounded-lg bg-[var(--gold-500)]/10 flex items-center justify-center flex-shrink-0">
                    <opt.icon className="h-4 w-4 text-[var(--gold-500)]" />
                  </div>
                  {opt.label}
                </button>
              ))}
            </div>
          )}

          {/* Unified input container — border wraps everything */}
          <div className={cn(
            "flex items-end bg-white/5 border border-[var(--color-gold-stroke)] rounded-2xl",
            "focus-within:ring-2 focus-within:ring-[var(--gold-500)] focus-within:border-transparent",
          )}>
            {/* + Button — inside left */}
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              disabled={disabled}
              className={cn(
                "flex-shrink-0 h-10 w-10 min-h-[44px] min-w-[44px] rounded-xl",
                "flex items-center justify-center transition-colors",
                "text-[var(--color-muted)] hover:text-[var(--foreground)]",
                "disabled:opacity-40 disabled:cursor-not-allowed",
                menuOpen && "text-[var(--gold-500)]"
              )}
              aria-label="Attach file"
              aria-expanded={menuOpen}
            >
              <Plus className={cn("h-5 w-5 transition-transform", menuOpen && "rotate-45")} />
            </button>

            {/* UI LOCK: flex-1 w-full min-w-0 text-base — SACRED classes */}
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              disabled={disabled}
              placeholder={placeholder}
              rows={1}
              className={cn(
                "flex-1 w-full min-w-0 text-base font-body",
                "resize-none bg-transparent border-0",
                "px-1 py-3 lg:py-2.5 text-[var(--foreground)]",
                "placeholder:text-[var(--color-muted)]",
                "focus:outline-none focus:ring-0",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                "scrollbar-thin"
              )}
            />

            {/* Send button — inside right */}
            <button
              onClick={handleSend}
              disabled={disabled || !canSend}
              className={cn(
                "flex-shrink-0 h-10 w-10 min-h-[44px] min-w-[44px] rounded-xl m-0.5",
                "flex items-center justify-center",
                "bg-[var(--gold-500)] text-[#07111c]",
                "hover:bg-[var(--gold-600)] hover:brightness-110 transition-colors",
                "disabled:opacity-40 disabled:cursor-not-allowed",
              )}
              aria-label="Send message"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={handleFileSelect}
        className="hidden"
        aria-hidden="true"
      />

      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 bg-[var(--gold-500)]/5 border-2 border-dashed border-[var(--gold-500)]/40 rounded-xl flex items-center justify-center z-10 pointer-events-none">
          <p className="text-sm font-medium text-[var(--gold-500)]">
            Drop files here
          </p>
        </div>
      )}
    </div>
  );
}
