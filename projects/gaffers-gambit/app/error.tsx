"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main
      style={{
        maxWidth: 650,
        margin: "15vh auto",
        padding: 30,
        textAlign: "center",
      }}
    >
      <p className="eyebrow">A BRIEF STOPPAGE</p>
      <h1 style={{ margin: "20px 0" }}>The floodlights flickered.</h1>
      <p style={{ marginBottom: 30, color: "#a9b6a3" }}>
        Your saved match is still on the server. Give it another go.
      </p>
      <button className="button primary" onClick={reset}>
        Try again →
      </button>
    </main>
  );
}
