"use strict";

const state = {
  gameId: null,
  joinToken: null,
  playerName: null,
  playerEmail: null,
  card: null,
  pattern: null,
  maxWinners: 3,
  marked: new Set(),  // "r,c" keys — player clicked; UX only
  calledWords: [],
  muted: false,
};

const $ = (id) => document.getElementById(id);

// --- Audio ---------------------------------------------------------------
const sounds = {
  click:     new Audio("/static/sounds/click.wav"),
  celebrate: new Audio("/static/sounds/celebrate.wav"),
};
sounds.click.preload = "auto";
sounds.celebrate.preload = "auto";

function playSound(name) {
  if (state.muted) return;
  const a = sounds[name];
  if (!a) return;
  try { a.currentTime = 0; a.play().catch(() => {}); } catch (_) {}
}

function speak(word, description) {
  if (state.muted) return;
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(
    description ? `${word}. ${description}` : word
  );
  utt.rate = 0.9;
  speechSynthesis.speak(utt);
}

function stopSpeaking() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

function celebrate() {
  if (typeof confetti !== "function") return;
  confetti({ particleCount: 150, spread: 80, origin: { y: 0.6 } });
  setTimeout(() => confetti({ particleCount: 100, angle:  60, spread: 60, origin: { x: 0 } }), 200);
  setTimeout(() => confetti({ particleCount: 100, angle: 120, spread: 60, origin: { x: 1 } }), 200);
}

// --- Mute toggle ---------------------------------------------------------
function setMuted(value) {
  state.muted = value;
  localStorage.setItem("bingoMuted", String(value));
  const btn = $("mute-toggle");
  btn.textContent = value ? "Audio: muted" : "Audio: on";
  btn.setAttribute("aria-pressed", String(value));
  btn.classList.toggle("muted", value);
  if (value) stopSpeaking();
}
state.muted = localStorage.getItem("bingoMuted") === "true";
setMuted(state.muted);
$("mute-toggle").addEventListener("click", () => setMuted(!state.muted));

// --- Section / step helpers ----------------------------------------------
const sections  = { join: $("join-section"), game: $("game-section"), end: $("end-section") };
const joinSteps = { email: $("email-step"), otp: $("otp-step"), name: $("name-step") };

function show(name) {
  for (const [key, el] of Object.entries(sections)) el.hidden = key !== name;
  if (name === "game") document.body.classList.add("game-bg");
}

function showJoinStep(name) {
  for (const [key, el] of Object.entries(joinSteps)) el.hidden = key !== name;
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

// --- URL / game id -------------------------------------------------------
const params = new URLSearchParams(location.search);
state.gameId = parseInt(params.get("game_id") || "0", 10);
$("header-game-id").textContent = state.gameId ? `#${state.gameId}` : "";
if (!state.gameId) {
  showFieldError("email-error", "Missing ?game_id= in URL. Ask the host for the link.");
}

// --- Step 1: request OTP -------------------------------------------------
$("email-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideFieldError("email-error");
  if (!state.gameId) return;
  await sendOtp((new FormData(e.target).get("player_email") || "").trim());
});

$("resend-otp-button").addEventListener("click", async () => {
  if (state.playerEmail) await sendOtp(state.playerEmail);
});

async function sendOtp(email) {
  const btn = $("send-otp-button");
  btn.disabled = true;
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

// --- Step 2: verify OTP --------------------------------------------------
$("otp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideFieldError("otp-error");
  const otp = ((new FormData(e.target).get("otp_code")) || "").trim();
  const res = await fetch(`/api/games/${state.gameId}/verify-otp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: state.playerEmail, otp }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) { showFieldError("otp-error", json.error || `Error ${res.status}`); return; }
  showJoinStep("name");
});

// --- Step 3: join --------------------------------------------------------
$("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.gameId) return;
  const res = await fetch(`/api/games/${state.gameId}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      player_name: new FormData(e.target).get("player_name"),
      email: state.playerEmail,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showFieldError("join-error", err.error || `Error ${res.status}`);
    return;
  }
  const json = await res.json();
  state.joinToken  = json.join_token;
  state.playerName = json.player_name;
  state.card       = json.card;
  state.pattern    = json.pattern || "horizontal";
  state.maxWinners = json.max_winners || 3;
  state.marked.add("2,2"); // FREE center always counted

  $("who-am-i").textContent = state.playerName;
  renderCard();
  show("game");
  connectSocket();
});

// --- Win-condition logic (mirrors server) --------------------------------
function getPatterns(patternType) {
  const G = 5;
  // Specific row: "row_1" – "row_5"
  const rowM = patternType.match(/^row_(\d)$/);
  if (rowM) {
    const r = parseInt(rowM[1]) - 1;
    return [Array.from({ length: G }, (_, c) => [r, c])];
  }
  // Specific column: "col_1" – "col_5"
  const colM = patternType.match(/^col_(\d)$/);
  if (colM) {
    const c = parseInt(colM[1]) - 1;
    return [Array.from({ length: G }, (_, r) => [r, c])];
  }
  if (patternType === "diag_main") return [Array.from({ length: G }, (_, i) => [i, i])];
  if (patternType === "diag_anti") return [Array.from({ length: G }, (_, i) => [i, G - 1 - i])];
  switch (patternType) {
    case "horizontal":
      return Array.from({ length: G }, (_, r) => Array.from({ length: G }, (_, c) => [r, c]));
    case "vertical":
      return Array.from({ length: G }, (_, c) => Array.from({ length: G }, (_, r) => [r, c]));
    case "diagonal":
      return [
        Array.from({ length: G }, (_, i) => [i, i]),
        Array.from({ length: G }, (_, i) => [i, G - 1 - i]),
      ];
    case "full_house":
      return [Array.from({ length: G * G }, (_, k) => [Math.floor(k / G), k % G])];
    default:
      return [];
  }
}

// For specific patterns only, return the set of target cells so we can
// highlight them on the card — gives the player a visual guide.
function targetCellSet() {
  const generic = ["horizontal", "vertical", "diagonal", "full_house"];
  if (!state.pattern || generic.includes(state.pattern)) return new Set();
  const cells = new Set();
  for (const pattern of getPatterns(state.pattern)) {
    for (const [r, c] of pattern) cells.add(`${r},${c}`);
  }
  return cells;
}

function checkWinCondition() {
  if (!state.card || !state.pattern) return false;
  const calledSet = new Set(state.calledWords.map((w) => w.toLowerCase()));
  return getPatterns(state.pattern).some((pattern) =>
    pattern.every(([r, c]) =>
      state.card[r][c] === "FREE" || calledSet.has(state.card[r][c].toLowerCase())
    )
  );
}

function updateBingoButton() {
  const btn = $("bingo-button");
  const ready = checkWinCondition();
  btn.disabled = !ready;
  btn.classList.toggle("ready", ready);
}

// --- Card rendering ------------------------------------------------------
function renderCard(newlyCalledWord = null) {
  const table = $("bingo-card");
  table.innerHTML = "";
  const calledSet = new Set(state.calledWords.map((w) => w.toLowerCase()));
  const targets   = targetCellSet();
  for (let r = 0; r < 5; r++) {
    const tr = document.createElement("tr");
    for (let c = 0; c < 5; c++) {
      const td  = document.createElement("td");
      const key = `${r},${c}`;
      const word = state.card[r][c];
      td.textContent = word;
      if (state.marked.has(key)) td.classList.add("marked");
      if (word === "FREE")        td.classList.add("free");
      if (calledSet.has(word.toLowerCase())) td.classList.add("called");
      if (targets.has(key))       td.classList.add("target");
      // Animate the cell that was just called (if it's on this card).
      if (newlyCalledWord && word.toLowerCase() === newlyCalledWord.toLowerCase()) {
        td.classList.add("just-called");
      }
      td.dataset.r = r;
      td.dataset.c = c;
      td.addEventListener("click", () => toggleMark(r, c));
      tr.appendChild(td);
    }
    table.appendChild(tr);
  }
}

function toggleMark(r, c) {
  if (state.card[r][c] === "FREE") return;
  const key = `${r},${c}`;
  state.marked.has(key) ? state.marked.delete(key) : state.marked.add(key);
  playSound("click");
  renderCard();
}

// --- Bingo claim ---------------------------------------------------------
$("bingo-button").addEventListener("click", async () => {
  const res  = await fetch(`/api/games/${state.gameId}/bingo`, {
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

// --- Sockets -------------------------------------------------------------
let socket = null;

function connectSocket() {
  socket = io();
  socket.on("connect", () => socket.emit("join_game_room", { game_id: state.gameId }));

  socket.on("word_called", ({ word, description }) => {
    state.calledWords.push(word);
    // Animate the word display
    const wordEl = $("current-word");
    wordEl.classList.remove("pop");
    void wordEl.offsetWidth; // flush reflow so animation restarts
    wordEl.textContent = word;
    wordEl.classList.add("pop");
    $("current-description").textContent = description || "";
    speak(word, description);
    renderCard(word);       // pass newly-called word for cell animation
    updateBingoButton();
  });

  socket.on("win_declared", ({ player_name }) => {
    if (player_name === state.playerName) {
      celebrate();
      playSound("celebrate");
    }
  });

  socket.on("game_paused", () => {
    $("paused-banner").hidden = false;
    stopSpeaking(); // stop any in-flight TTS announcement
  });

  socket.on("game_resumed", () => {
    $("paused-banner").hidden = true;
  });

  socket.on("game_ended", () => {
    fetch(`/api/games/${state.gameId}/state`)
      .then((r) => r.json())
      .then((s) => {
        if (s.max_winners) state.maxWinners = s.max_winners;
        show("end");
        renderFinalLeaderboard(s.wins || []);
      });
  });
}

// --- Leaderboard ---------------------------------------------------------
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
    const w   = wins.find((w) => w.place === i + 1);
    div.className = `leaderboard-entry place-${Math.min(i + 1, 3)}`;
    if (w) div.classList.add("filled");

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
