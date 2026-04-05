"use client";

/**
 * AdminErrorBoundary — catches render-time exceptions inside the admin shell
 * and replaces the blank Next.js "Application error" page with a readable
 * error panel that shows the crash message and a reload button.
 *
 * React Error Boundaries must be class components — hooks cannot catch errors
 * in the render phase. This is the standard React pattern.
 *
 * Why this matters on iPhone Safari:
 *   - Safari has stricter JIT compilation thresholds than V8.
 *   - Recharts' ResponsiveContainer calls window.getComputedStyle() before the
 *     element is laid out, which can throw on certain Safari versions.
 *   - Without a boundary, that throw propagates to the Next.js root and shows
 *     a blank "Application error" screen with no useful information.
 *   - With this boundary, the admin section fails gracefully and shows the
 *     error so the owner can report it precisely.
 */

import { Component, type ReactNode } from "react";
import { reportError } from "@/services/errorReporter";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: string;
  stack: string;
}

export class AdminErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: "", stack: "" };

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error: error?.message ?? String(error),
      stack: error?.stack ?? "",
    };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    // Log to console — visible in Safari Web Inspector when debugging
    console.error("[AdminErrorBoundary] Caught render error:", error);
    console.error("[AdminErrorBoundary] Component stack:", info.componentStack);

    // Report to backend error collection endpoint
    reportError(error, {
      type: "render_error",
      extra: {
        componentStack: info.componentStack.slice(0, 2000),
      },
    });
  }

  handleReload = () => {
    // Reset state first so the boundary tries to render children again
    this.setState({ hasError: false, error: "", stack: "" });
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: 24,
            background: "#07111c",
            minHeight: "100vh",
            color: "#e5e7eb",
            fontFamily: "system-ui, -apple-system, sans-serif",
          }}
        >
          <div
            style={{
              maxWidth: 560,
              margin: "0 auto",
              paddingTop: 48,
            }}
          >
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 10,
                  background: "rgba(239,68,68,0.15)",
                  border: "1px solid rgba(239,68,68,0.3)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 18,
                  flexShrink: 0,
                }}
              >
                !
              </div>
              <div>
                <h2
                  style={{
                    margin: 0,
                    fontSize: 16,
                    fontWeight: 700,
                    color: "#fff",
                    lineHeight: 1.3,
                  }}
                >
                  Admin Panel Error
                </h2>
                <p style={{ margin: 0, fontSize: 12, color: "#6b7280", marginTop: 2 }}>
                  A render error occurred in the Command Center
                </p>
              </div>
            </div>

            {/* Error message */}
            <div
              style={{
                background: "rgba(239,68,68,0.08)",
                border: "1px solid rgba(239,68,68,0.2)",
                borderRadius: 12,
                padding: "12px 16px",
                marginBottom: 16,
              }}
            >
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  color: "#f87171",
                  fontWeight: 600,
                  wordBreak: "break-word",
                }}
              >
                {this.state.error || "Unknown render error"}
              </p>
            </div>

            {/* Stack trace — collapsed but visible for Safari Web Inspector */}
            {this.state.stack && (
              <details style={{ marginBottom: 20 }}>
                <summary
                  style={{
                    fontSize: 12,
                    color: "#6b7280",
                    cursor: "pointer",
                    userSelect: "none",
                    marginBottom: 8,
                  }}
                >
                  Stack trace
                </summary>
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    color: "#9ca3af",
                    background: "#0a1520",
                    border: "1px solid #1a2a3d",
                    borderRadius: 8,
                    padding: 12,
                    overflowX: "auto",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                    lineHeight: 1.5,
                  }}
                >
                  {this.state.stack}
                </pre>
              </details>
            )}

            {/* Reload button */}
            <button
              onClick={this.handleReload}
              style={{
                padding: "10px 20px",
                background: "#c9a227",
                color: "#000",
                border: "none",
                borderRadius: 10,
                fontSize: 14,
                fontWeight: 600,
                cursor: "pointer",
                minHeight: 44,
                minWidth: 100,
              }}
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
