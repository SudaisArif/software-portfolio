export default function NotFound() {
  return (
    <main
      style={{
        maxWidth: 650,
        margin: "15vh auto",
        padding: 30,
        textAlign: "center",
      }}
    >
      <p className="eyebrow">OFFSIDE. JUST.</p>
      <h1 style={{ margin: "20px 0" }}>This page is out of play.</h1>
      <p style={{ marginBottom: 30, color: "#a9b6a3" }}>
        The next seven questions are back at the ground.
      </p>
      <a className="button primary" href="/">
        Back to Gaffer’s Gambit →
      </a>
    </main>
  );
}
