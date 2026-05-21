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
  alreadyWon: false,      // true once a /bingo claim succeeds — suppresses grace window
  graceActive: false,     // true while grace countdown is running
  graceTimerId: null,
  graceOnExpire: null,
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

// Warms up the browser's speech-synthesis engine on the first user
// interaction so Chrome doesn't block the first spoken word.
function initSpeech() {
  if (!("speechSynthesis" in window)) return;
  // Calling getVoices() triggers loading in Chrome; we discard the result.
  speechSynthesis.getVoices();
}

function speak(word) {
  if (state.muted) return;
  if (!("speechSynthesis" in window)) return;
  // Chrome bug: after inactivity or a pause, speechSynthesis can get stuck.
  // Resuming before cancelling + a short setTimeout reliably unsticks it.
  if (speechSynthesis.paused) speechSynthesis.resume();
  speechSynthesis.cancel();
  setTimeout(() => {
    const utt = new SpeechSynthesisUtterance(word);
    utt.rate = 0.9;
    utt.lang = "en-US";
    speechSynthesis.speak(utt);
  }, 80);
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
  btn.textContent = value ? "🔇 Muted" : "🔊 Audio on";
  btn.setAttribute("aria-pressed", String(value));
  btn.classList.toggle("muted", value);
  if (value) stopSpeaking();
}
// Default to NOT muted on every fresh page load so players don't sit through
// a game in silence because a leftover localStorage value muted them.
// The preference is still saved so a deliberate mute survives a refresh within
// the same session, but we never silently inherit mute from a previous session.
const _savedMute = localStorage.getItem("bingoMuted");
// Only honour a saved mute if it was set in THIS tab/session.
// We detect "same session" by checking sessionStorage rather than localStorage.
const _sessionMuted = sessionStorage.getItem("bingoMuted") === "true";
state.muted = _sessionMuted; // start unmuted unless the user muted in this session
setMuted(state.muted);
$("mute-toggle").addEventListener("click", () => {
  const next = !state.muted;
  setMuted(next);
  // Persist across refreshes within the same browser tab session.
  sessionStorage.setItem("bingoMuted", String(next));
  initSpeech(); // first click is a user gesture — prime TTS engine
});

// --- Section / step helpers ----------------------------------------------
const sections  = { join: $("join-section"), game: $("game-section"), end: $("end-section") };
const joinSteps = { email: $("email-step"), otp: $("otp-step"), name: $("name-step") };

function show(name) {
  for (const [key, el] of Object.entries(sections)) el.hidden = key !== name;
  if (name === "game") document.body.classList.add("game-bg");
}

function showJoinStep(name) {
  for (const [key, el] of Object.entries(joinSteps)) el.hidden = key !== name;
  // Animate the step progress indicator (email=0, otp=1, name=2)
  const order = ["email", "otp", "name"];
  const current = order.indexOf(name);
  document.querySelectorAll(".step-item").forEach((el, i) => {
    el.classList.toggle("done", i < current);
    el.classList.toggle("active", i === current);
  });
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

// Key used to persist the join session in localStorage so a page refresh
// does not force the player through the full auth flow again.
const SESSION_KEY = `bingo_session_${state.gameId}`;

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
    // 409 "already verified" means OTP is done; try to recover the session.
    if (res.status === 409 && (json.error || "").toLowerCase().includes("already verified")) {
      state.playerEmail = email;
      const rejoinRes = await fetch(`/api/games/${state.gameId}/rejoin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (rejoinRes.ok) {
        const rejoinData = await rejoinRes.json();
        restoreSession(rejoinData);
        return;
      }
      // Verified but no card yet — let them pick a display name.
      showJoinStep("name");
      return;
    }
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

  saveSession();
  $("who-am-i").textContent = state.playerName;
  initSpeech(); // prime TTS on this user-gesture-triggered join
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
  const calledSet = new Set(state.calledWords.map(norm));
  // Both conditions must hold: the host has called the word AND the player
  // manually marked that cell. This keeps the game interactive — players must
  // actively track the words being called.
  return getPatterns(state.pattern).some((pattern) =>
    pattern.every(([r, c]) => {
      const word = state.card[r][c];
      if (word === "FREE") return true;
      return calledSet.has(norm(word)) && state.marked.has(`${r},${c}`);
    })
  );
}

function updateBingoButton() {
  const btn = $("bingo-button");
  const ready = checkWinCondition();
  btn.disabled = !ready;
  btn.classList.toggle("ready", ready);
}

// Grace window: shown when game_ended fires but the player has a complete
// marked winning pattern. Gives them 8 seconds to click BINGO before the
// screen switches to the final leaderboard.
function startGraceWindow(onExpire) {
  state.graceActive  = true;
  state.graceOnExpire = onExpire;
  const banner  = $("grace-banner");
  const timerEl = $("grace-timer");
  banner.style.display = "flex";
  updateBingoButton(); // button should be enabled since checkWinCondition() is true

  let remaining = 8;
  timerEl.textContent = remaining;

  const tick = () => {
    remaining--;
    timerEl.textContent = remaining;
    if (remaining <= 0) {
      endGraceWindow();
      onExpire();
    } else {
      state.graceTimerId = setTimeout(tick, 1000);
    }
  };
  state.graceTimerId = setTimeout(tick, 1000);
}

function endGraceWindow() {
  state.graceActive = false;
  if (state.graceTimerId) {
    clearTimeout(state.graceTimerId);
    state.graceTimerId = null;
  }
  $("grace-banner").style.display = "none";
}

// --- Word display fit ----------------------------------------------------
// Shrinks the font so the word always stays on a single line regardless of
// how long the phrase is. Called each time a new word is set.
function fitCurrentWord() {
  const el = $("current-word");
  if (!el) return;
  el.style.fontSize = ""; // let CSS set the starting size
  const card = el.closest(".current-word-card");
  const maxW = (card ? card.clientWidth : 300) - 64; // 32px padding each side
  let size = parseFloat(getComputedStyle(el).fontSize);
  while (el.scrollWidth > maxW && size > 14) {
    size -= 1;
    el.style.fontSize = size + "px";
  }
}

// Normalize a word for comparison: lowercase + collapsed whitespace.
// Used in every calledSet lookup so AI-generated words with unusual spacing
// or capitalisation always match what appears on the card.
const norm = (w) => w.trim().toLowerCase().replace(/\s+/g, " ");

// --- Card rendering ------------------------------------------------------
function renderCard(newlyCalledWord = null) {
  const table = $("bingo-card");
  table.innerHTML = "";
  const calledSet = new Set(state.calledWords.map(norm));
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
      if (calledSet.has(norm(word))) td.classList.add("called");
      if (targets.has(key))       td.classList.add("target");
      // Animate the cell that was just called (if it's on this card).
      if (newlyCalledWord && norm(word) === norm(newlyCalledWord)) {
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
  updateBingoButton(); // re-check win condition whenever a cell is toggled
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
    state.alreadyWon = true;
    result.textContent = `You won place ${json.place}! (${json.pattern_matched})`;
    result.className = "success";
    // If inside the grace window, cancel the countdown and navigate to the
    // end screen after a short pause so the player can read their result.
    if (state.graceActive) {
      const onExpire = state.graceOnExpire;
      endGraceWindow();
      setTimeout(onExpire, 2000);
    }
  } else {
    result.textContent = json.error || `Error ${res.status}`;
    result.className = "error";
    // On a failed claim during grace (e.g. all spots filled), still navigate
    // to the end screen after a brief delay so the player isn't stuck.
    if (state.graceActive) {
      const onExpire = state.graceOnExpire;
      endGraceWindow();
      setTimeout(onExpire, 1500);
    }
  }
});

// --- Sockets -------------------------------------------------------------
let socket = null;

function connectSocket() {
  if (socket) return; // already connected — guard against double-call on rejoin
  socket = io();
  socket.on("connect", () => socket.emit("join_game_room", { game_id: state.gameId }));

  socket.on("word_called", ({ word, description }) => {
    state.calledWords.push(word);
    // Animate the word display
    const wordEl = $("current-word");
    wordEl.classList.remove("pop");
    void wordEl.offsetWidth; // flush reflow so animation restarts
    wordEl.textContent = word;
    fitCurrentWord(); // scale font so the word never wraps
    wordEl.classList.add("pop");
    $("current-description").textContent = description || "";
    speak(word);
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
    $("pause-overlay").classList.add("visible");
    stopSpeaking(); // stop any in-flight TTS announcement
  });

  socket.on("game_resumed", () => {
    $("pause-overlay").classList.remove("visible");
  });

  socket.on("game_ended", () => {
    stopSpeaking();
    const goToEnd = () => {
      fetch(`/api/games/${state.gameId}/state`)
        .then((r) => r.json())
        .then((s) => {
          if (s.max_winners) state.maxWinners = s.max_winners;
          show("end");
          renderFinalLeaderboard(s.wins || []);
        });
    };
    // If the player has a fully-marked winning pattern but hasn't claimed yet,
    // give them 8 seconds before the screen switches — so the last word
    // being called doesn't cut them off before they can click BINGO.
    if (!state.alreadyWon && checkWinCondition()) {
      startGraceWindow(goToEnd);
    } else {
      goToEnd();
    }
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

// --- Session persistence (survives page refresh) -------------------------

function saveSession() {
  if (!state.gameId) return;
  localStorage.setItem(SESSION_KEY, JSON.stringify({
    joinToken:  state.joinToken,
    playerName: state.playerName,
    card:       state.card,
    pattern:    state.pattern,
    maxWinners: state.maxWinners,
  }));
}

function restoreSession(data) {
  // Accepts both camelCase (localStorage) and snake_case (server response).
  state.joinToken  = data.joinToken  || data.join_token;
  state.playerName = data.playerName || data.player_name;
  state.card       = data.card;
  state.pattern    = data.pattern    || "horizontal";
  state.maxWinners = data.maxWinners || data.max_winners || 3;
  state.marked.add("2,2"); // FREE center is always marked

  saveSession();
  $("who-am-i").textContent = state.playerName;

  // Fetch called words so far so the card reflects the current game state.
  fetch(`/api/games/${state.gameId}/state`)
    .then((r) => r.json())
    .then((s) => {
      if (Array.isArray(s.called_words)) state.calledWords = s.called_words;
      if (s.max_winners) state.maxWinners = s.max_winners;

      const status = data.game_status || s.status;
      if (status === "finished") {
        show("end");
        renderFinalLeaderboard(s.wins || []);
        return;
      }
      renderCard();
      show("game");
      if (state.calledWords.length > 0) {
        const last = state.calledWords[state.calledWords.length - 1];
        $("current-word").textContent = last;
        fitCurrentWord();
      }
      updateBingoButton();
      connectSocket();
    })
    .catch(() => {
      // If state fetch fails, still show the card so the player isn't stuck.
      renderCard();
      show("game");
      connectSocket();
    });
}

function tryAutoRestore() {
  if (!state.gameId) return;
  const saved = localStorage.getItem(SESSION_KEY);
  if (!saved) return;
  try {
    const data = JSON.parse(saved);
    if (data.joinToken && data.card) restoreSession(data);
  } catch (_) {
    localStorage.removeItem(SESSION_KEY);
  }
}

// Attempt to restore a previous session on page load.
tryAutoRestore();
