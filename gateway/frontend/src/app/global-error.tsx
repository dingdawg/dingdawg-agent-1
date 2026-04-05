'use client'

import { useEffect } from "react";

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  useEffect(() => {
    console.error("[global-error]", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          background: "#0a0a0f",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
          padding: "1rem",
        }}
      >
        <div style={{ maxWidth: "28rem", width: "100%", textAlign: "center" }}>
          {/* Brand mark */}
          <div style={{ marginBottom: "1.5rem", fontSize: "3rem" }}>&#9889;</div>

          {/* Heading */}
          <h1
            style={{
              fontSize: "1.75rem",
              fontWeight: 700,
              color: "#ffffff",
              marginBottom: "0.75rem",
            }}
          >
            Something went wrong
          </h1>

          {/* Body copy */}
          <p
            style={{
              color: "#6b7280",
              fontSize: "1rem",
              lineHeight: 1.6,
              marginBottom: "2rem",
            }}
          >
            A critical error occurred. Please refresh the page to continue.
          </p>

          {/* Error digest */}
          {error.digest && (
            <p
              style={{
                color: "#6b7280",
                fontSize: "0.75rem",
                fontFamily: "monospace",
                background: "#111118",
                borderRadius: "0.375rem",
                padding: "0.5rem 0.75rem",
                display: "inline-block",
                marginBottom: "1.5rem",
              }}
            >
              Error code: {error.digest}
            </p>
          )}

          {/* Refresh CTA */}
          <div>
            <button
              onClick={reset}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                padding: "0.75rem 2rem",
                background: "#d4a017",
                color: "#0a0a0f",
                fontWeight: 600,
                fontSize: "1rem",
                borderRadius: "0.5rem",
                border: "none",
                cursor: "pointer",
              }}
            >
              Refresh page
            </button>
          </div>

          {/* Footer */}
          <p
            style={{
              marginTop: "2.5rem",
              color: "#6b7280",
              fontSize: "0.75rem",
            }}
          >
            &copy; {new Date().getFullYear()} DingDawg &mdash; Universal AI Agent Platform
          </p>
        </div>
      </body>
    </html>
  );
}
