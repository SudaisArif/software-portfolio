"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  Volume2,
  VolumeX,
  Trophy,
  HelpCircle,
  X,
  RotateCcw,
  Copy,
  Download,
  Flag,
  Check,
  ChevronLeft,
  Share2,
  LoaderCircle,
} from "lucide-react";
import Pitch from "./pitch";
import {
  TIERS,
  ROUND_COUNT,
  edition,
  utcDay,
  type GameState,
  type RoundResult,
} from "@/lib/game";
type Board = {
  day: string;
  edition: number;
  total: number;
  rows: { id: string; name: string; score: number; finished_at: number }[];
};
type Panel = "rules" | "board" | "privacy" | "report" | null;
async function api<T = { game: GameState }>(
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(12000),
  });
  let data: T & { error?: string };
  try {
    data = (await res.json()) as T & { error?: string };
  } catch {
    throw new Error(
      "The ground is temporarily unavailable. Please reconnect and try again.",
    );
  }
  if (!res.ok)
    throw new Error(data.error ?? "The floodlights flickered. Try again.");
  return data;
}
function Crest() {
  return (
    <span className="crest" aria-hidden="true">
      <span>g</span>
      <i>★</i>
    </span>
  );
}
function sound(points: number) {
  try {
    const C =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    const ctx = new C();
    const notes =
      points === 100 ? [440, 554, 659, 880] : points > 0 ? [220, 330] : [130];
    notes.forEach((f, i) => {
      const o = ctx.createOscillator(),
        g = ctx.createGain();
      o.connect(g);
      g.connect(ctx.destination);
      o.type = "sine";
      o.frequency.value = f;
      g.gain.setValueAtTime(0, ctx.currentTime + i * 0.1);
      g.gain.linearRampToValueAtTime(0.08, ctx.currentTime + i * 0.1 + 0.02);
      g.gain.exponentialRampToValueAtTime(
        0.001,
        ctx.currentTime + i * 0.1 + 0.4,
      );
      o.start(ctx.currentTime + i * 0.1);
      o.stop(ctx.currentTime + i * 0.1 + 0.45);
    });
    setTimeout(() => void ctx.close(), 1500);
  } catch {}
}
export default function Game() {
  const [screen, setScreen] = useState<"home" | "match" | "result">("home"),
    [game, setGame] = useState<GameState | null>(null),
    [daily, setDaily] = useState<GameState | null>(null),
    [practice, setPractice] = useState<GameState | null>(null),
    [panel, setPanel] = useState<Panel>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [time, setTime] = useState(25),
    [board, setBoard] = useState<Board | null>(null),
    [boardLoading, setBoardLoading] = useState(false),
    [answer, setAnswer] = useState(""),
    [name, setName] = useState(""),
    [audioOn, setAudioOn] = useState(false),
    [ready, setReady] = useState(false),
    [today, setToday] = useState(utcDay()),
    [report, setReport] = useState<RoundResult | null>(null),
    [note, setNote] = useState(""),
    [reportDone, setReportDone] = useState(false),
    [copied, setCopied] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    answerInput = useRef<HTMLInputElement>(null),
    lock = useRef(false),
    clockOffset = useRef(0),
    timeoutSent = useRef(""),
    soundRef = useRef(false);
  const accept = useCallback((next: GameState) => {
    setGame(next);
    clockOffset.current = Date.now() - next.serverNow;
    if (next.mode === "daily") setDaily(next);
    if (next.mode === "practice") setPractice(next);
    setToday(next.day);
    if (next.mode === "practice")
      try {
        localStorage.setItem("gg-practice", next.id);
      } catch {}
  }, []);
  useEffect(() => {
    api("/api/game")
      .then((d) => {
        if (d.game) {
          setDaily(d.game);
          setToday(d.game.day);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setReady(true));
    try {
      const enabled = localStorage.getItem("gg-sound") === "on";
      setAudioOn(enabled);
      soundRef.current = enabled;
      setName(localStorage.getItem("gg-name") ?? "");
      const saved = localStorage.getItem("gg-practice");
      if (saved)
        api("/api/game?id=" + encodeURIComponent(saved))
          .then((d) => {
            if (d.game) setPractice(d.game);
          })
          .catch(() => {});
    } catch {}
  }, []);
  useEffect(() => {
    if (panel) dialog.current?.showModal();
    else dialog.current?.close();
  }, [panel]);
  useEffect(() => {
    if (toast) {
      const id = setTimeout(() => setToast(""), 3000);
      return () => clearTimeout(id);
    }
  }, [toast]);
  const loadBoard = useCallback(async () => {
    setBoardLoading(true);
    try {
      setBoard(await api<Board>("/api/leaderboard"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBoardLoading(false);
    }
  }, []);
  useEffect(() => {
    if (panel === "board") void loadBoard();
  }, [panel, loadBoard]);
  const sendAnswer = useCallback(
    async (value: string) => {
      if (!game || game.phase !== "question" || lock.current) return;
      lock.current = true;
      setBusy(true);
      setError("");
      try {
        const d = await api("/api/game", {
          action: "answer",
          id: game.id,
          round: game.round,
          answer: value,
        });
        accept(d.game);
        if (soundRef.current) sound(d.game.answers.at(-1)?.points ?? 0);
        setAnswer("");
      } catch (e) {
        setError((e as Error).message);
      } finally {
        lock.current = false;
        setBusy(false);
      }
    },
    [game, accept],
  );
  useEffect(() => {
    if (screen !== "match" || game?.phase !== "question") return;
    const update = () => {
      const remaining = Math.max(
        0,
        Math.ceil((game.deadline - (Date.now() - clockOffset.current)) / 1000),
      );
      setTime(remaining);
      const key = `${game.id}:${game.round}`;
      if (remaining === 0 && timeoutSent.current !== key && !lock.current) {
        timeoutSent.current = key;
        void sendAnswer("");
      }
    };
    update();
    const timer = setInterval(update, 150);
    answerInput.current?.focus();
    return () => clearInterval(timer);
  }, [game, screen, sendAnswer]);
  async function start(mode: "daily" | "practice", fresh = false) {
    if (lock.current) return;
    if (
      mode === "practice" &&
      !fresh &&
      practice &&
      practice.phase !== "finished"
    ) {
      setBusy(true);
      try {
        const d = await api("/api/game?id=" + practice.id);
        accept(d.game);
        setScreen("match");
        setAnswer("");
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
      return;
    }
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const d = await api("/api/game", { action: "start", mode });
      accept(d.game);
      setScreen(d.game.phase === "finished" ? "result" : "match");
      setAnswer("");
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function next() {
    if (!game) return;
    if (game.phase === "finished") {
      setScreen("result");
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const d = await api("/api/game", {
        action: "next",
        id: game.id,
        round: game.round,
      });
      accept(d.game);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function resync() {
    if (!game) return;
    setBusy(true);
    try {
      const d = await api(`/api/game?id=${game.id}`);
      if (d.game) accept(d.game);
      setError("");
      timeoutSent.current = "";
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (!game) return;
    setBusy(true);
    setError("");
    try {
      const d = await api("/api/game", {
        action: "publish",
        id: game.id,
        name,
      });
      accept(d.game);
      try {
        localStorage.setItem("gg-name", name);
      } catch {}
      setToast("Your name is on the teamsheet.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function unpublish() {
    if (!game) return;
    setBusy(true);
    try {
      const d = await api("/api/game", { action: "unpublish", id: game.id });
      accept(d.game);
      setToast("Removed from the public table.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function toggleSound() {
    const val = !audioOn;
    setAudioOn(val);
    soundRef.current = val;
    try {
      localStorage.setItem("gg-sound", val ? "on" : "off");
    } catch {}
    if (val) sound(20);
  }
  function shareText() {
    if (!game) return "";
    return `Gaffer’s Gambit ${game.mode === "daily" ? `#${game.edition}` : "— Training ground"}\n${game.score}/700 metres · ${game.answers.filter((a) => a.tier === 5).length} top bins\n${game.answers.map((a) => TIERS[a.tier].emoji).join("")}\nThink you know ball?\n${location.origin}`;
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(shareText());
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setToast("Copy isn’t available here. Use Share to send your result.");
    }
  }
  async function share() {
    const text = shareText();
    if (navigator.share) {
      try {
        await navigator.share({ title: "Gaffer’s Gambit", text });
      } catch (e) {
        if ((e as Error).name !== "AbortError") void copy();
      }
    } else void copy();
  }
  function download() {
    if (!game) return;
    const c = document.createElement("canvas");
    c.width = 1200;
    c.height = 630;
    const x = c.getContext("2d")!;
    x.fillStyle = "#162e25";
    x.fillRect(0, 0, 1200, 630);
    x.strokeStyle = "#536553";
    x.strokeRect(35, 35, 1130, 560);
    x.fillStyle = "#efa67d";
    x.font = "18px monospace";
    x.fillText(
      `THE DAILY FOOTBALL RARITY GAME   /   ${game.mode === "daily" ? "MATCHDAY #" + game.edition : "TRAINING GROUND"}`,
      70,
      88,
    );
    x.fillStyle = "#f1edda";
    x.font = "italic 66px Georgia";
    x.fillText("Gaffer’s Gambit", 65, 183);
    x.font = "bold 132px Georgia";
    x.fillText(`${game.score}`, 65, 338);
    x.fillStyle = "#b5c0ae";
    x.font = "28px monospace";
    x.fillText("/ 700 METRES", 330, 330);
    game.answers.forEach((a, i) => {
      x.fillStyle = TIERS[a.tier].color;
      x.fillRect(70 + i * 78, 392, 60, 60);
      x.fillStyle = "#162e25";
      x.font = "bold 20px monospace";
      x.fillText(String(a.points).padStart(2, "0"), 83 + i * 78, 429);
    });
    x.fillStyle = "#f1edda";
    x.font = "italic 32px Georgia";
    x.fillText("Think you know ball?", 70, 527);
    x.font = "16px monospace";
    x.fillStyle = "#b5c0ae";
    x.fillText(location.host, 70, 565);
    x.strokeStyle = "#efa67d";
    x.beginPath();
    x.arc(1000, 305, 90, 0, Math.PI * 2);
    x.stroke();
    x.font = "italic 150px Georgia";
    x.fillStyle = "#efa67d";
    x.fillText("g", 957, 337);
    const a = document.createElement("a");
    a.download = `gaffers-gambit-${game.day}.png`;
    a.href = c.toDataURL("image/png");
    a.click();
  }
  async function submitReport() {
    if (!game || !report) return;
    setBusy(true);
    try {
      await api("/api/report", {
        id: game.id,
        questionId: report.questionId,
        note,
      });
      setReportDone(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const last = game?.answers.at(-1),
    revealing = game && game.phase !== "question",
    active = screen === "match" && game;
  const rating = !game
    ? ""
    : game.score >= 600
      ? "You know serious ball."
      : game.score >= 440
        ? "The streets remember."
        : game.score >= 280
          ? "There’s a player in there."
          : "Back on the training pitch.";
  return (
    <div className="site-shell">
      <header className="site-header">
        <button
          className="brand"
          onClick={() => {
            setScreen("home");
            setError("");
          }}
          aria-label="Gaffer's Gambit home"
        >
          <Crest />
          <span>
            GAFFER’S
            <br />
            <b>GAMBIT</b>
          </span>
        </button>
        <nav aria-label="Main navigation">
          <button
            className={screen === "home" ? "nav-active" : ""}
            onClick={() => setScreen("home")}
          >
            The daily
          </button>
          <button aria-label="The table" onClick={() => setPanel("board")}>
            <Trophy size={16} />
            <span>The table</span>
          </button>
          <button
            className="icon-button"
            onClick={() => setPanel("rules")}
            aria-label="How to play"
          >
            <HelpCircle size={20} />
          </button>
          <button
            className="icon-button"
            onClick={toggleSound}
            aria-label={audioOn ? "Mute sound" : "Enable sound"}
            aria-pressed={audioOn}
          >
            {audioOn ? <Volume2 size={19} /> : <VolumeX size={19} />}
          </button>
        </nav>
      </header>
      <main>
        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            {game && (
              <button onClick={resync} disabled={busy}>
                Reconnect
              </button>
            )}
            <button onClick={() => setError("")} aria-label="Dismiss error">
              <X size={16} />
            </button>
          </div>
        )}
        {screen === "home" && (
          <>
            <section className="hero">
              <div className="eyebrow">
                <span className="live-dot" /> THE DAILY FOOTBALL RARITY GAME{" "}
                <span className="edition">
                  VOL. {String(edition(today)).padStart(3, "0")}
                </span>
              </div>
              <h1>
                Big knowledge.
                <br />
                <em>Beautifully obscure.</em>
              </h1>
              <p>
                Forgotten transfers. Freak records. Cult heroes.
                <br className="desktop-break" /> Seven questions. Rarer answers.
                Longer shots.
              </p>
              <div className="hero-actions">
                <button
                  className="button primary"
                  disabled={busy || !ready}
                  onClick={() => start("daily")}
                >
                  {busy ? <LoaderCircle className="spin" size={18} /> : null}
                  {!ready
                    ? "Opening the ground…"
                    : daily?.phase === "finished"
                      ? "View today’s result"
                      : daily
                        ? "Resume the daily"
                        : "Play today’s gambit"}
                  <ArrowUpRight size={21} />
                </button>
                <button
                  className="practice-link"
                  disabled={busy}
                  onClick={() => start("practice")}
                >
                  {practice && practice.phase !== "finished"
                    ? "Resume training"
                    : "Hit the training ground"}{" "}
                  <ArrowRight size={17} />
                </button>
              </div>
              {practice && practice.phase !== "finished" && (
                <button
                  className="fresh-practice"
                  disabled={busy}
                  onClick={() => start("practice", true)}
                >
                  <RotateCcw size={13} /> Start a fresh training match
                </button>
              )}
              <div className="hero-meta">
                <span>7 QUESTIONS</span>
                <i />
                <span>25 SECONDS EACH</span>
                <i />
                <span>NO SIGN-UP</span>
              </div>
            </section>
            <section className="ground-wrap" aria-label="Your football ground">
              <div className="ground-topline">
                <span>
                  <span className="live-dot" /> THE FLOODLIGHTS ARE ON
                </span>
                <button onClick={() => setPanel("rules")}>
                  AIM FOR THE UNEXPECTED <ArrowUpRight size={13} />
                </button>
              </div>
              <Pitch />
              <div className="ground-bottom">
                <span>FROM TAP-IN TO TOP BINS</span>
                <span>
                  YOUR KNOWLEDGE GOES THE DISTANCE <ArrowRight size={14} />
                </span>
              </div>
            </section>
            <section className="how-strip">
              <div className="strip-intro">
                <span className="eyebrow">THE GAME PLAN</span>
                <h2>
                  Don’t name the best.
                  <br />
                  <em>Name the forgotten.</em>
                </h2>
              </div>
              <div>
                <b className="step">01</b>
                <h3>Read the play.</h3>
                <p>
                  A football question with plenty of right answers. You only
                  need one.
                </p>
              </div>
              <div>
                <b className="step">02</b>
                <h3>Back your knowledge.</h3>
                <p>
                  Skip the obvious. An overlooked cult hero could take you all
                  the way.
                </p>
              </div>
              <div>
                <b className="step">03</b>
                <h3>Let it fly.</h3>
                <p>
                  The rarer your pick, the longer the shot. Hit 100 metres for
                  top bins.
                </p>
              </div>
            </section>
            <section className="rarity-strip">
              <span className="eyebrow">KNOW YOUR RANGE</span>
              <div>
                {TIERS.slice(1).map((t) => (
                  <div key={t.name}>
                    <span
                      className="tier-line"
                      style={{ background: t.color }}
                    />
                    <b>
                      {t.points}
                      <small>m</small>
                    </b>
                    <span>{t.name}</span>
                  </div>
                ))}
              </div>
              <button onClick={() => setPanel("rules")}>
                How rarity is scored <ArrowUpRight size={14} />
              </button>
            </section>
            <div className="bottom-note">
              <span>FOR THE FANS WHO REMEMBER THE BACKUP LEFT-BACK.</span>
              <span>NEW GAMBIT EVERY DAY · 00:00 UTC</span>
            </div>
          </>
        )}
        {active && (
          <section className="match-view">
            <div className="match-heading">
              <button className="back-link" onClick={() => setScreen("home")}>
                <ChevronLeft size={17} /> Clubhouse
              </button>
              <span className="eyebrow">
                {game.mode === "daily"
                  ? `DAILY GAMBIT #${game.edition}`
                  : "THE TRAINING GROUND"}
              </span>
              <span className="live-score">
                {game.score}
                <small> / 700 m</small>
              </span>
            </div>
            <div
              className="round-track"
              aria-label={`Question ${game.round + 1} of 7`}
            >
              {Array.from({ length: ROUND_COUNT }, (_, i) => (
                <div
                  key={i}
                  className={i === game.round ? "current" : ""}
                  style={
                    i < game.answers.length
                      ? {
                          borderColor: TIERS[game.answers[i].tier].color,
                          color: TIERS[game.answers[i].tier].color,
                        }
                      : undefined
                  }
                >
                  <span>{String(i + 1).padStart(2, "0")}</span>
                  <i>
                    {game.answers[i]
                      ? `${game.answers[i].points}m`
                      : i === game.round
                        ? "IN PLAY"
                        : "—"}
                  </i>
                </div>
              ))}
            </div>
            <div className="game-pitch">
              <Pitch
                points={revealing ? (last?.points ?? 0) : null}
                shotKey={`${game.id}-${game.round}-${game.phase}`}
              />
            </div>
            {!revealing && game.question ? (
              <section
                className="question-card"
                aria-labelledby="question-title"
              >
                <div className="question-meta">
                  <span>
                    {game.question.category} <i>/</i> {game.question.difficulty}
                  </span>
                  <div
                    className={`timer ${time <= 5 ? "timer-low" : ""}`}
                    role="timer"
                    aria-label={`${time} seconds remaining`}
                  >
                    <span>{String(time).padStart(2, "0")}</span>
                    <small>SEC</small>
                  </div>
                </div>
                <h2 id="question-title">{game.question.prompt}</h2>
                <p className="scope">{game.question.scope}</p>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void sendAnswer(answer);
                  }}
                >
                  <label htmlFor="answer" className="sr-only">
                    Your answer
                  </label>
                  <div className="answer-row">
                    <input
                      ref={answerInput}
                      id="answer"
                      name="answer"
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      placeholder="Name your pick…"
                      maxLength={100}
                      autoComplete="off"
                      autoCorrect="off"
                      spellCheck={false}
                      disabled={busy || time === 0}
                    />
                    <button
                      className="button primary"
                      disabled={!answer.trim() || busy || time === 0}
                    >
                      {busy ? (
                        <LoaderCircle className="spin" size={18} />
                      ) : (
                        <>
                          Let it fly <ArrowUpRight size={20} />
                        </>
                      )}
                    </button>
                  </div>
                  <div className="answer-hint">
                    <span>One answer. Trust your football brain.</span>
                    <button
                      type="button"
                      disabled={busy || time === 0}
                      onClick={() => sendAnswer("")}
                    >
                      Take the miss <ArrowRight size={13} />
                    </button>
                  </div>
                </form>
                <div className="time-bar">
                  <i
                    style={{
                      width: `${(time / 25) * 100}%`,
                      background: time <= 5 ? "#ed9b78" : undefined,
                    }}
                  />
                </div>
              </section>
            ) : (
              last && (
                <section className="reveal-card" aria-live="polite">
                  <div className="reveal-title">
                    <div>
                      <span
                        className="eyebrow"
                        style={{ color: TIERS[last.tier].color }}
                      >
                        {TIERS[last.tier].name}
                      </span>
                      <h2>{last.name ?? last.reason}</h2>
                    </div>
                    <div
                      className="shot-score"
                      style={{ color: TIERS[last.tier].color }}
                    >
                      +{last.points}
                      <span>METRES</span>
                    </div>
                  </div>
                  <p>
                    {last.fact ||
                      (last.example
                        ? `One you could have gone for: ${last.example.name}.`
                        : "A fresh question is up next.")}
                  </p>
                  <div className="reveal-bottom">
                    <a href={last.source.url} target="_blank" rel="noreferrer">
                      Check the source <ArrowUpRight size={13} />
                    </a>
                    <button
                      className="button primary"
                      onClick={next}
                      disabled={busy}
                    >
                      {game.phase === "finished"
                        ? "The final whistle"
                        : "Next question"}
                      <ArrowRight size={19} />
                    </button>
                  </div>
                  <button
                    className="report-link"
                    onClick={() => {
                      setReport(last);
                      setNote("");
                      setReportDone(false);
                      setPanel("report");
                    }}
                  >
                    <Flag size={12} /> Think we missed a valid answer?
                  </button>
                </section>
              )
            )}
          </section>
        )}
        {screen === "result" && game && (
          <section className="result-view">
            <div className="eyebrow">
              {game.mode === "daily"
                ? `MATCHDAY #${game.edition} · ${game.day}`
                : "THE TRAINING GROUND"}{" "}
              / FULL TIME
            </div>
            <h1>{rating}</h1>
            <div className="result-ticket">
              <div className="ticket-main">
                <Crest />
                <span className="eyebrow">GAFFER’S GAMBIT</span>
                <div className="final-score">
                  {game.score}
                  <small>/ 700 m</small>
                </div>
                <div className="result-squares">
                  {game.answers.map((a, i) => (
                    <span
                      key={i}
                      style={{ background: TIERS[a.tier].color }}
                      title={`${TIERS[a.tier].name}: ${a.points} metres`}
                    >
                      {a.points}
                    </span>
                  ))}
                </div>
                <p>
                  {game.answers.filter((a) => a.points > 0).length}/7 correct{" "}
                  <i>·</i> {game.answers.filter((a) => a.tier === 5).length} top
                  bins <i>·</i>{" "}
                  {game.mode === "daily"
                    ? "Same questions. Everyone."
                    : "Practice makes permanent."}
                </p>
              </div>
              <div className="ticket-bottom">
                <span>THINK YOU KNOW BALL?</span>
                <span>
                  PROVE IT. <ArrowUpRight size={15} />
                </span>
              </div>
            </div>
            <div className="share-actions">
              <button className="button primary" onClick={share}>
                <Share2 size={17} /> Challenge your mates
              </button>
              <button className="button secondary" onClick={copy}>
                {copied ? <Check size={17} /> : <Copy size={17} />}{" "}
                {copied ? "Copied" : "Copy result"}
              </button>
              <button className="button secondary" onClick={download}>
                <Download size={17} /> Save card
              </button>
            </div>
            {game.mode === "daily" && (
              <div className="publish-box">
                {game.published ? (
                  <>
                    <div>
                      <span className="eyebrow">ON THE TEAMSHEET</span>
                      <p>
                        You’re in as <b>{game.name}</b>.
                      </p>
                      <button
                        className="small-link"
                        onClick={unpublish}
                        disabled={busy}
                      >
                        Remove my public entry
                      </button>
                    </div>
                    <button
                      className="button secondary"
                      onClick={() => setPanel("board")}
                    >
                      <Trophy size={17} /> See the table
                    </button>
                  </>
                ) : (
                  <>
                    <div>
                      <h3>Put your name on the teamsheet.</h3>
                      <p>Join today’s public leaderboard. Pick a nickname.</p>
                    </div>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        void publish();
                      }}
                    >
                      <label className="sr-only" htmlFor="nickname">
                        Leaderboard nickname
                      </label>
                      <input
                        id="nickname"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        minLength={2}
                        maxLength={20}
                        placeholder="Your football alias"
                        required
                      />
                      <button className="button primary" disabled={busy}>
                        Join the table <ArrowRight size={16} />
                      </button>
                    </form>
                  </>
                )}
              </div>
            )}
            <div className="breakdown-heading">
              <h2>The match report.</h2>
              <span className="eyebrow">EVERY SHOT COUNTS</span>
            </div>
            <div className="breakdown">
              {game.answers.map((a, i) => (
                <details key={i}>
                  <summary>
                    <span className="report-num">{i + 1}</span>
                    <div>
                      <span>{a.name ?? a.reason}</span>
                      <small>{TIERS[a.tier].name}</small>
                    </div>
                    <b style={{ color: TIERS[a.tier].color }}>
                      {a.points}
                      <small> m</small>
                    </b>
                    <span className="expand">+</span>
                  </summary>
                  <div className="detail-body">
                    <h4>{a.prompt}</h4>
                    <p>
                      {a.fact ||
                        (a.example
                          ? `One valid answer: ${a.example.name}.`
                          : "")}
                    </p>
                    {a.input && a.input !== a.name && (
                      <p className="muted">You wrote: {a.input}</p>
                    )}
                    <a href={a.source.url} target="_blank" rel="noreferrer">
                      {a.source.label}
                      <ArrowUpRight size={13} />
                    </a>
                    <button
                      className="report-link"
                      onClick={() => {
                        setReport(a);
                        setNote("");
                        setReportDone(false);
                        setPanel("report");
                      }}
                    >
                      <Flag size={12} /> Report an answer
                    </button>
                  </div>
                </details>
              ))}
            </div>
            <div className="again">
              <p>
                {game.mode === "daily"
                  ? "Fresh questions tomorrow. Still got a shot in you?"
                  : "There’s always another name you’ve forgotten."}
              </p>
              <button
                className="button secondary"
                onClick={() => start("practice")}
                disabled={busy}
              >
                <RotateCcw size={16} /> Back to the training ground
              </button>
            </div>
          </section>
        )}
      </main>
      <footer>
        <span>
          Gaffer’s Gambit <i>© 2026</i>
        </span>
        <div>
          <button onClick={() => setPanel("rules")}>The rules</button>
          <button onClick={() => setPanel("privacy")}>
            Privacy & fair play
          </button>
          <span>INDEPENDENT. UNOFFICIAL. FOR THE LOVE OF IT.</span>
        </div>
      </footer>
      <dialog
        ref={dialog}
        onCancel={() => setPanel(null)}
        onClick={(e) => {
          if (e.target === e.currentTarget) setPanel(null);
        }}
        className="modal"
        aria-label={
          panel === "board"
            ? "Daily leaderboard"
            : panel === "rules"
              ? "How to play"
              : panel === "report"
                ? "Report an answer"
                : "Privacy and fair play"
        }
      >
        <div className="modal-inner">
          <button
            className="modal-close icon-button"
            aria-label="Close dialog"
            onClick={() => setPanel(null)}
          >
            <X size={22} />
          </button>
          {panel === "rules" && (
            <>
              <span className="eyebrow">THE GAFFER’S NOTES</span>
              <h2>
                A little less obvious.
                <br />
                <em>A lot more satisfying.</em>
              </h2>
              <p>
                Seven questions. 25 seconds each. Type one answer that fits the
                question, then let it fly. You have one shot per question.
              </p>
              <div className="rules-tiers">
                {TIERS.slice(1).map((t) => (
                  <div key={t.name}>
                    <span style={{ color: t.color }}>{t.name}</span>
                    <b>{t.points} m</b>
                  </div>
                ))}
              </div>
              <h3>What makes an answer rare?</h3>
              <p>
                At launch, every answer has an editorial tier based on how
                familiar it is likely to be to a football fan. A less obvious
                name earns more metres. These are judgments, not measured
                percentages of players. Fewer goals doesn’t automatically mean
                more obscure.
              </p>
              <p>
                Tiers stay fixed for the daily challenge. Common spellings,
                accents and unambiguous surnames count. We also accept a
                single-letter typo when it matches just one answer.
              </p>
              <h3>Same day. Same challenge.</h3>
              <p>
                The daily changes at 00:00 UTC. Your first daily run is saved in
                this browser, including the timer if you leave mid-question. It
                is the only run eligible for the daily table. Tied scores share
                a rank.
              </p>
              <p>
                The training ground is unlimited, unranked practice. Questions
                may overlap with the daily bank. For the fairest challenge, play
                the daily first.
              </p>
              <h3>Know your football history.</h3>
              <p>
                Questions say exactly which competition, season or match counts.
                Starting XI means starters, not unused substitutes. Read the
                small print, gaffer.
              </p>
              <button
                className="button primary full"
                onClick={() => setPanel(null)}
              >
                Got it. Let’s play. <ArrowRight size={17} />
              </button>
            </>
          )}
          {panel === "board" && (
            <>
              <span className="eyebrow">THE DAILY TABLE</span>
              <h2>
                The names on
                <br />
                <em>the teamsheet.</em>
              </h2>
              <div className="board-meta">
                <span>Matchday #{board?.edition ?? edition(today)}</span>
                <span>{board?.total ?? 0} entries · refreshes daily</span>
              </div>
              {boardLoading ? (
                <p className="loading-line">
                  <LoaderCircle className="spin" size={18} /> Checking the
                  scores…
                </p>
              ) : board?.rows.length ? (
                <div className="board-list">
                  <div className="board-row board-labels">
                    <span>POS</span>
                    <span>GAFFER</span>
                    <span>METRES</span>
                  </div>
                  {board.rows.map((row, i) => {
                    const rank =
                      board.rows.findIndex((r) => r.score === row.score) + 1;
                    return (
                      <div
                        className={`board-row ${row.id === daily?.id ? "your-row" : ""}`}
                        key={row.id}
                      >
                        <span>{String(rank).padStart(2, "0")}</span>
                        <b>
                          {row.name}
                          {row.id === daily?.id && <small> YOU</small>}
                        </b>
                        <span>{row.score}</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="empty-board">
                  <Trophy size={38} />
                  <h3>The table’s yours to start.</h3>
                  <p>
                    Finish today’s gambit and add your nickname. Only real
                    players appear here.
                  </p>
                  <button
                    className="button primary"
                    onClick={() => {
                      setPanel(null);
                      void start("daily");
                    }}
                    disabled={busy}
                  >
                    Take your seven shots <ArrowRight size={17} />
                  </button>
                </div>
              )}
              <p className="modal-footnote">
                Top 50 shown. Equal scores share a rank. Guest entries are tied
                to this browser, not a verified identity.
              </p>
              <button
                className="small-link"
                onClick={loadBoard}
                disabled={boardLoading}
              >
                Refresh table
              </button>
            </>
          )}
          {panel === "privacy" && (
            <>
              <span className="eyebrow">OFF THE PITCH</span>
              <h2>
                Your game.
                <br />
                <em>Your call.</em>
              </h2>
              <h3>What we save</h3>
              <p>
                An essential browser cookie identifies your match without an
                account. The game stores your answers, score and match
                timestamps to resume play and run the leaderboard. Sound and
                nickname preferences are stored on your device.
              </p>
              <h3>What everyone can see</h3>
              <p>
                Joining the table is optional. It makes your chosen nickname,
                daily score and completion order public. Your typed answers
                aren’t included in share cards or the public table. You can
                remove your entry from the results screen.
              </p>
              <h3>Fair play</h3>
              <p>
                Timers, answer checks and scores run on the server. One daily
                entry per browser; clearing cookies or switching devices can
                create another identity. This is a friendly competition, with no
                prizes or verified rankings.
              </p>
              <p>
                Requests are rate limited using your guest identifier, with a
                changing, hashed network identifier for first-time visits. We
                don’t add advertising trackers or third-party analytics. Hosting
                providers may keep standard request logs.
              </p>
              <h3>Football facts</h3>
              <p>
                Sources are linked after every answer. If something is wrong,
                use “Report an answer” in your match report. Editorial rarity is
                a game mechanic, not an objective ranking of a player’s ability.
              </p>
              <p>
                This is an independent fan game. It is not affiliated with
                Krillion, any club, league, broadcaster or governing body.
              </p>
            </>
          )}
          {panel === "report" && (
            <>
              <span className="eyebrow">THE VAR ROOM</span>
              <h2>
                Let’s check
                <br />
                <em>that decision.</em>
              </h2>
              {reportDone ? (
                <div className="report-success">
                  <Check size={32} />
                  <h3>Report saved.</h3>
                  <p>
                    Thanks for the detail. Your report is stored for the game’s
                    editor to review; the result of this match stays as played.
                  </p>
                </div>
              ) : (
                <>
                  <p>{report?.prompt}</p>
                  <p className="muted">
                    Your answer: {report?.input || "No answer"}
                  </p>
                  <label htmlFor="report-note">
                    What did we miss? A source link helps.
                  </label>
                  <textarea
                    id="report-note"
                    maxLength={500}
                    minLength={8}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="This player should count because…"
                    rows={4}
                  />
                  <button
                    className="button primary full"
                    disabled={busy || note.trim().length < 8}
                    onClick={submitReport}
                  >
                    Send to the VAR room <ArrowRight size={17} />
                  </button>
                  {error && (
                    <p role="alert" className="form-error">
                      {error}
                    </p>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </dialog>
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
