"use client";

import { useCallback, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

// ── Copy button for code blocks ─────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    }
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 px-2 py-1 rounded-md text-[10px] font-medium bg-white/10 hover:bg-white/20 text-white/70 hover:text-white transition-all duration-150 opacity-0 group-hover/pre:opacity-100 focus:opacity-100 min-h-[28px]"
      aria-label={copied ? "Copied to clipboard" : "Copy code"}
    >
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

// ── Extract text from React children (for copy) ────────────────────────────

function extractText(node: ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node && typeof node === "object" && "props" in node) {
    return extractText((node as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

// ── Custom components for react-markdown ────────────────────────────────────

const markdownComponents: Components = {
  pre({ children, ...props }) {
    const codeText = extractText(children);
    return (
      <div className="relative group/pre">
        <pre {...props}>{children}</pre>
        <CopyButton text={codeText.trim()} />
      </div>
    );
  },
  code({ children, className, ...props }) {
    // Detect language from className (e.g. "language-python")
    const lang = className?.replace("language-", "") ?? "";
    const isInline = !className;

    if (isInline) {
      return <code {...props}>{children}</code>;
    }

    return (
      <code className={className} data-language={lang} {...props}>
        {children}
      </code>
    );
  },
};

// ── Main component ──────────────────────────────────────────────────────────

export default function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={`dd-markdown ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
