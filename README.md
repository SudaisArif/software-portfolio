# Sudais Arif — Software Portfolio

Computer science student at Carnegie Mellon University, building sports applications, practical automation, interactive systems and research tools.

**[Browse all project source](projects/) · [Professional experience](EXPERIENCE.md) · [Verification and scope](VERIFICATION.md)**

## Start here

### 1. Tartan Fantasy — full-stack sports application
A fantasy soccer platform for CMU's men's team. Managers build squads, join leagues and follow rankings driven by match data. The backend enforces budgets, transfers, deadlines and scoring; Cloudflare Workers and D1 provide hosting and persistence.

**JavaScript · Python · SQL · Cloudflare Workers/D1**  
[Source and setup](projects/tartan-fantasy/) · [Hosted application](https://tartan-fantasy-cmu.tartan-fantasy.workers.dev)

### 2. Soccer Stream Recorder — reliable desktop automation
A Python/macOS tool for scheduling and recording authorized soccer broadcasts. It imports spreadsheets, handles concurrent recordings, monitors provider status, validates MP4 output and retains recoverable recording parts. Provider adapters separate stream discovery from the recording engine.

**Python · Tkinter · FFmpeg · macOS Keychain · background workers**  
[Source, architecture and setup](projects/soccer-recorder/)

### 3. Gaffer's Gambit — daily football game
Seven timed questions, persistent progress, practice matches and a leaderboard. The server selects questions and computes scores, with ownership checks and atomic transitions to prevent double submissions.

**React · TypeScript · SQL · Drizzle · Cloudflare Workers/D1**  
[Source and setup](projects/gaffers-gambit/)

### 4. Apple health prototype — iOS and watchOS sensor integration
A collaborative SwiftUI prototype exploring motion-based fall alerts, HealthKit heart-rate queries and watchOS fall-event handling. The source shows native sensor APIs and UI state management; it is an experimental prototype, not a clinically validated seizure detector.

**Swift · SwiftUI · Core Motion · HealthKit · watchOS**  
[Source and implementation scope](projects/apple-health-prototype/)

## More engineering projects

| Project | Focus | Code |
| --- | --- | --- |
| Free Kick Symphony | Browser instrument connecting football-shot geometry to physical-model audio, melody editing and MIDI/WAV export | [Source](projects/free-kick-symphony/) |
| Gesture-controlled swing game | Python game with OpenCV/MediaPipe hand tracking, Vosk voice input and physics | [Repository](https://github.com/SudaisArif/Submission) |
| Web Audio fingerprinting | Controlled browser-audio experiments and Python analysis of stability and uniqueness | [Repository](https://github.com/SudaisArif/WebAudioAPI-testing) |
| DX7-style synthesis | Six-operator phase modulation and Yamaha SysEx parsing | [Core source](projects/dx7-synth/) |
| REP SIGNAL | Local content-production orchestration, review dashboard, revision-aware approvals and storage adapters | [Source](projects/rep-signal/) |
| Options research | Historical-data pipeline, rolling ML, backtesting and pricing utilities | [Source](projects/options-research/) |
| Computational geometry | Exact arithmetic, Held–Karp search and independent checking experiments | [Source](projects/geometry-experiments/) |
| Graph numerics | High-precision matrices, adaptive sampling and structured team handoffs | [My Stage 2 source](projects/graph-numerics/) |
| CCCG literature crawler | Cached PDF discovery/extraction, provenance and structured research exports | [Repository](https://github.com/SudaisArif/cccg-optimization-crawl) |
| 2DFA research verification | Automata constructions, finite checks and a research preprint | [Repository](https://github.com/SudaisArif/Complementation2DFA_LowerBound2n) |

## Reviewing the collection

Each project is independently structured. Start in its folder and follow its README; this repository is not a single deployable application. Public source snapshots exclude credentials, private runtime databases, team recordings and proprietary internship code. Existing project dependencies retain their own terms. No blanket license is applied to third-party material.

Project maturity varies: deployed application source, local tools, coursework and research prototypes are identified in their documentation. AI-assisted development was used in parts of the collection. The Apple prototype was collaborative; graph numerics contains my Stage 2 contribution. Repository hosting is not a claim of sole authorship of every dependency or contribution.
