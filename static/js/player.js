"use strict";

const state = {
  gameId: null,
  joinToken: null,
  playerName: null,
  playerEmail: null, // set after OTP verification
  card: null,
  pattern: null,     // set after join (e.g. "horizontal")
  maxWinners: 3,     // set after join
  // Marks are client-only per D7 — they're a UX aid; the server
  // validates against the actual called words at /bingo time.
  marked: new Set(), // keyed by "r,c"
  calledWords: [],
  muted: false, // hydrated from localStorage below
};

const $ = (id) => document.getElementById(id);

// --- Audio engagement layer --------------------------------------------
const sounds = {
  click: new Audio("/static/sounds/click.wav"),
  celebrate: new Audio("/static/sounds/celebrate.wav"),
};
sounds.click.preload = "auto";
sounds.celebrate.preload = "auto";

function playSound(name) {
  if (state.muted) return;
  const a = sounds[name];
  if (!a) return;
  // Reset to start so rapid clicks always retrigger. .play() returns a
  // Promise that rejects on autoplay-block or missing file; swallow it
  // so a missing sound file doesn't surface as a console error storm.
  try {
    a.currentTime = 0;
    a.play().catch(() => {});
  } catch (_) {
    /* element not ready yet — ignore */
  }
}

function speak(word, description) {
  if (state.muted) return;
  if (!("speechSynthesis" in window)) return;
  // Truncate any in-flight utterance — at a 5s cadence with a 15-word
  // description, the previous call would otherwise still be talking
  // when the next word arrives.
  speechSynthesis.cancel();
  const text = description ? `${word}. ${description}` : word;
  const utt = new SpeechSynthesisUtterance(text);
  utt.rate = 0.9; // slightly slower than default for clarity
  speechSynthesis.speak(utt);
}

// canvas-confetti is loaded from CDN in base.html and exposed as a
// global `confetti()`. We fire three bursts for a richer effect.
function celebrate() {
  if (typeof confetti !== "function") return;
  confetti({ particleCount: 150, spread: 80, origin: { y: 0.6 } });
  setTimeout(
    () =>
      confetti({
        particleCount: 100,
        angle: 60,
        spread: 60,
        origin: { x: 0 },
      }),
    200,
  );
  setTimeout(
    () =>
      confetti({
        particleCount: 100,
        angle: 120,
        spread: 60,
        origin: { x: 1 },
      }),
    200,
  );
}

// --- Mute toggle (persists across reloads via localStorage) ------------
function setMuted(value) {
  state.muted = value;
  localStorage.setItem("bingoMuted", String(value));
  const btn = $("mute-toggle");
  btn.textContent = value ? "Audio: muted" : "Audio: on";
  btn.setAttribute("aria-pressed", String(value));
  btn.classList.toggle("muted", value);
  // Cut off any in-flight speech the moment the user mutes.
  if (value && "speechSynthesis" in window) speechSynthesis.cancel();
}

state.muted = localStorage.getItem("bingoMuted") === "true";
setMuted(state.muted);
$("mute-toggle").addEventListener("click", () => setMuted(!state.muted));

const sections = {
  join: $("join-section"),
  game: $("game-section"),
  end: $("end-section"),
};

const joinSteps = {
  email: $("email-step"),
  otp: $("otp-step"),
  name: $("name-step"),
};

let socket = null;

// --- Read game id from URL ---------------------------------------------
const params = new URLSearchParams(location.search);
state.gameId = parseInt(params.get("game_id") || "0", 10);
$("header-game-id").textContent = state.gameId ? `#${state.gameId}` : "";
if (!state.gameId) {
  showFieldError("email-error", "Missing ?game_id= in URL. Ask the host for the link.");
}

// --- Step 1: request OTP ------------------------------------------------
$("email-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideFieldError("email-error");
  if (!state.gameId) return;
  const data = new FormData(e.target);
  const email = (data.get("player_email") || "").trim();
  await sendOtp(email);
});

$("resend-otp-button").addEventListener("click", async () => {
  if (state.playerEmail) await sendOtp(state.playerEmail);
});

async function sendOtp(email) {
  const btn = $("send-otp-button");
  btn.disabled = true;
  hideFieldError("email-error");
  const statusEl = $("email-status");
  statusEl.textContent = "Sending…";
  statusEl.hidden = false;

  const res = await fetch(`/api/games/${state.gameId}/request-otp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  btn.disabled = false;
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    statusEl.hidden = true;
    showFieldError("email-error", json.error || `Error ${res.status}`);
    return;
  }
  state.playerEmail = email;
  $("otp-email-display").textContent = email;
  statusEl.hidden = true;
  showJoinStep("otp");
}

// --- Step 2: verify OTP -------------------------------------------------
$("otp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideFieldError("otp-error");
  const data = new FormData(e.target);
  const otp = (data.get("otp_code") || "").trim();
  const res = await fetch(`/api/games/${state.gameId}/verify-otp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: state.playerEmail, otp }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    showFieldError("otp-error", json.error || `Error ${res.status}`);
    return;
  }
  showJoinStep("name");
});

// --- Step 3: join with display name -------------------------------------
$("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.gameId) return;
  const data = new FormData(e.target);
  const body = {
    player_name: data.get("player_name"),
    email: state.playerEmail,
  };
  const res = await fetch(`/api/games/${state.gameId}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showFieldError("join-error", err.error || `Error ${res.status}`);
    return;
  }
  const json = await res.json();
  state.joinToken = json.join_token;
  state.playerName = json.player_name;
  state.card = json.card;
  state.pattern = json.pattern || "horizontal";
  state.maxWinners = json.max_winners || 3;
  // FREE center is always counted as marked.
  state.marked.add("2,2");

  $("who-am-i").textContent = state.playerName;
  renderCard();
  show("game");
  connectSocket();
});

// --- Join step helpers ---------------------------------------------------
function showJoinStep(name) {
  for (const [key, el] of Object.entries(joinSteps)) {
    el.hidden = key !== name;
  }
}

function showFieldError(id, msg) {
  const el = $(id);
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
}

function hideFieldError(id) {
  const el = $(id);
  if (el) el.hidden = true;
}

// --- Win condition check (mirrors server logic) --------------------------
function getPatterns(patternType) {
  const G = 5;
  switch (patternType) {
    case "horizontal":
      return Array.from({ length: G }, (_, r) =>
        Array.from({ length: G }, (_, c) => [r, c]),
      );
    case "vertical":
      return Array.from({ length: G }, (_, c) =>
        Array.from({ length: G }, (_, r) => [r, c]),
      );
    case "diagonal":
      return [
        Array.from({ length: G }, (_, i) => [i, i]),
        Array.from({ length: G }, (_, i) => [i, G - 1 - i]),
      ];
    case "full_house":
      return [
        Array.from({ length: G * G }, (_, k) => [Math.floor(k / G), k % G]),
      ];
    default:
      return [];
  }
}

function checkWinCondition() {
  if (!state.card || !state.pattern) return false;
  const calledSet = new Set(state.calledWords.map((w) => w.toLowerCase()));
  return getPatterns(state.pattern).some((pattern) =>
    pattern.every(
      ([r, c]) =>
        state.card[r][c] === "FREE" ||
        calledSet.has(state.card[r][c].toLowerCase()),
    ),
  );
}

function updateBingoButton() {
  const btn = $("bingo-button");
  const ready = checkWinCondition();
  btn.disabled = !ready;
  btn.classList.toggle("ready", ready);
}

// --- Card rendering -----------------------------------------------------
function renderCard() {
  const table = $("bingo-card");
  table.innerHTML = "";
  const calledSet = new Set(state.calledWords.map((w) => w.toLowerCase()));
  for (let r = 0; r < 5; r++) {
    const tr = document.createElement("tr");
    for (let c = 0; c < 5; c++) {
      const td = document.createElement("td");
      td.textContent = state.card[r][c];
      const key = `${r},${c}`;
      if (state.marked.has(key)) td.classList.add("marked");
      if (state.card[r][c] === "FREE") td.classList.add("free");
      // Show which words have been officially called (independent of marks).
      if (calledSet.has(state.card[r][c].toLowerCase())) td.classList.add("called");
      td.dataset.r = r;
      td.dataset.c = c;
      td.addEventListener("click", () => toggleMark(r, c));
      tr.appendChild(td);
    }
    table.appendChild(tr);
  }
}

function toggleMark(r, c) {
  // FREE is always marked — clicking it does nothing.
  if (state.card[r][c] === "FREE") return;
  const key = `${r},${c}`;
  if (state.marked.has(key)) {
    state.marked.delete(key);
  } else {
    state.marked.add(key);
  }
  playSound("click");
  renderCard();
}

// --- Bingo claim --------------------------------------------------------
$("bingo-button").addEventListener("click", async () => {
  const res = await fetch(`/api/games/${state.gameId}/bingo`, {
    method: "POST",
    headers: { "X-Join-Token": state.joinToken },
  });
  const json = await res.json().catch(() => ({}));
  const result = $("claim-result");
  if (res.ok) {
    result.textContent = `You won place ${json.place}! (${json.pattern_matched})`;
    result.className = "success";
  } else {
    result.textContent = json.error || `Error ${res.status}`;
    result.className = "error";
  }
});

// --- Sockets ------------------------------------------------------------
function connectSocket() {
  socket = io();
  socket.on("connect", () => {
    socket.emit("join_game_room", { game_id: state.gameId });
  });
  socket.on("word_called", ({ word, description }) => {
    state.calledWords.push(word);
    $("current-word").textContent = word;
    // Description is optional — older games (no topic) emit no description.
    $("current-description").textContent = description || "";
    speak(word, description);
    renderCard();        // refresh called-word highlights
    updateBingoButton(); // enable bingo if a pattern is now complete
  });
  socket.on("win_declared", ({ player_name }) => {
    // Server broadcasts win_declared to everyone in the room; only the
    // actual winner gets the confetti + fanfare so each device cheers
    // for itself.
    if (player_name === state.playerName) {
      celebrate();
      playSound("celebrate");
    }
  });
  socket.on("game_paused", () => {
    $("paused-banner").hidden = false;
  });
  socket.on("game_resumed", () => {
    $("paused-banner").hidden = true;
  });
  socket.on("game_ended", () => {
    // Pull the final state from the server so the leaderboard reflects
    // wins this client may have missed (e.g. it just connected).
    fetch(`/api/games/${state.gameId}/state`)
      .then((r) => r.json())
      .then((s) => {
        if (s.max_winners) state.maxWinners = s.max_winners;
        show("end");
        renderFinalLeaderboard(s.wins || []);
      });
  });
}

function ordinal(n) {
  if (n >= 11 && n <= 13) return n + "th";
  const rem = n % 10;
  if (rem === 1) return n + "st";
  if (rem === 2) return n + "nd";
  if (rem === 3) return n + "rd";
  return n + "th";
}

function renderFinalLeaderboard(wins) {
  const container = $("leaderboard");
  container.innerHTML = "";
  const n = state.maxWinners;
  for (let i = 0; i < n; i++) {
    const div = document.createElement("div");
    const w = wins.find((w) => w.place === i + 1);
    div.className = `leaderboard-entry place-${Math.min(i + 1, 3)}`;
    const place = document.createElement("span");
    place.className = "place";
    place.textContent = ordinal(i + 1);
    const name = document.createElement("span");
    if (w) {
      name.textContent = w.player_name;
      const pat = document.createElement("span");
      pat.className = "muted";
      pat.textContent = ` (${w.pattern_matched})`;
      name.appendChild(pat);
    } else {
      name.textContent = "—";
      div.style.opacity = "0.45";
    }
    div.appendChild(place);
    div.appendChild(name);
    container.appendChild(div);
  }
}

// --- Section swap helper ------------------------------------------------
function show(name) {
  for (const [key, el] of Object.entries(sections)) {
    el.hidden = key !== name;
  }
}
