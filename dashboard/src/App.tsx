import React from "react";

/**
 * Root application component for the ISG Agent 1 dashboard.
 */
export function App(): React.ReactElement {
  return (
    <main
      style={{
        fontFamily: "system-ui, -apple-system, sans-serif",
        maxWidth: "800px",
        margin: "0 auto",
        padding: "2rem",
      }}
    >
      <h1>ISG Agent 1 Dashboard</h1>
      <p>Innovative Systems Global — Agent Monitoring and Management</p>
      <section>
        <h2>Status</h2>
        <p>Gateway connection: initializing...</p>
      </section>
    </main>
  );
}
