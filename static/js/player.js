"use strict";

const state = {
  gameId: null,
  joinToken: null,
  playerName: null,
  card: null,
  // Marks are client-only per D7 — they're a UX aid; the server
  // validates against the actual called words at /bingo time.
  marked: new Set(), // keyed by "r,c"
  calledWords: [],
};

const $ = (id) => document.getElementById(id);

const sections = {
  join: $("join-section"),
  game: $("game-section"),
  end: $("end-section"),
};

let socket = null;

// --- Read game id from URL ---------------------------------------------
const params = new URLSearchParams(location.search);
state.gameId = parseInt(params.get("game_id") || "0", 10);
$("header-game-id").textContent = state.gameId ? `#${state.gameId}` : "";
if (!state.gameId) {
  showJoinError("Missing ?game_id= in URL. Ask the host for the link.");
}

// --- Join ---------------------------------------------------------------
$("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.gameId) return;
  const data = new FormData(e.target);
  const body = { player_name: data.get("player_name") };
  const res = await fetch(`/api/games/${state.gameId}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showJoinError(err.error || `Error ${res.status}`);
    return;
  }
  const json = await res.json();
  state.joinToken = json.join_token;
  state.playerName = json.player_name;
  state.card = json.card;
  // FREE center is always counted as marked.
  state.marked.add("2,2");

  $("who-am-i").textContent = state.playerName;
  renderCard();
  show("game");
  connectSocket();
});

function showJoinError(msg) {
  const el = $("join-error");
  el.textContent = msg;
  el.hidden = false;
}

// --- Card rendering -----------------------------------------------------
function renderCard() {
  const table = $("bingo-card");
  table.innerHTML = "";
  for (let r = 0; r < 5; r++) {
    const tr = document.createElement("tr");
    for (let c = 0; c < 5; c++) {
      const td = document.createElement("td");
      td.textContent = state.card[r][c];
      const key = `${r},${c}`;
      if (state.marked.has(key)) td.classList.add("marked");
      if (state.card[r][c] === "FREE") td.classList.add("free");
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
  socket.on("word_called", ({ word }) => {
    state.calledWords.push(word);
    $("current-word").textContent = word;
  });
  socket.on("game_ended", () => {
    // Pull the final state from the server so the leaderboard reflects
    // wins this client may have missed (e.g. it just connected).
    fetch(`/api/games/${state.gameId}/state`)
      .then((r) => r.json())
      .then((s) => {
        show("end");
        renderFinalLeaderboard(s.wins || []);
      });
  });
}

function renderFinalLeaderboard(wins) {
  const ol = $("leaderboard");
  ol.innerHTML = "";
  const labels = ["1st", "2nd", "3rd"];
  for (let i = 0; i < 3; i++) {
    const li = document.createElement("li");
    const w = wins.find((w) => w.place === i + 1);
    if (w) {
      li.textContent = `${labels[i]}: ${w.player_name} (${w.pattern_matched})`;
    } else {
      li.className = "placeholder";
      li.textContent = `${labels[i]}: —`;
    }
    ol.appendChild(li);
  }
}

// --- Section swap helper ------------------------------------------------
function show(name) {
  for (const [key, el] of Object.entries(sections)) {
    el.hidden = key !== name;
  }
}
