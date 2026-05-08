"use strict";

// All host-side state in one object so it's easy to inspect in the
// browser console during a demo (e.g. `state.players`).
const state = {
  gameId: null,
  hostToken: null,
  players: [],
  calledWords: [],
  wins: [],
};

const $ = (id) => document.getElementById(id);

const sections = {
  create: $("create-section"),
  lobby: $("lobby-section"),
  game: $("game-section"),
  end: $("end-section"),
};

let socket = null;

// --- Create game --------------------------------------------------------
$("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = new FormData(e.target);
  const body = {
    host_name: data.get("host_name"),
    pattern: data.get("pattern"),
    call_interval_seconds: Number(data.get("call_interval_seconds") || 5),
  };
  const res = await fetch("/api/games", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to create game: " + (err.error || res.status));
    return;
  }
  const json = await res.json();
  state.gameId = json.game_id;
  state.hostToken = json.host_token;

  const link = `${location.origin}/play?game_id=${json.game_id}`;
  const a = $("join-link");
  a.href = link;
  a.textContent = link;

  show("lobby");
  connectSocket();
});

// --- Start game ---------------------------------------------------------
$("start-button").addEventListener("click", async () => {
  const res = await fetch(`/api/games/${state.gameId}/start`, {
    method: "POST",
    headers: { "X-Host-Token": state.hostToken },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to start: " + (err.error || res.status));
  }
  // Section swap happens on the "game_started" event, so all clients
  // (host + players) move forward together.
});

// --- Sockets ------------------------------------------------------------
function connectSocket() {
  socket = io();
  socket.on("connect", () => {
    socket.emit("join_game_room", { game_id: state.gameId });
  });
  socket.on("player_joined", ({ player_name }) => {
    state.players.push(player_name);
    renderPlayers();
  });
  socket.on("game_started", () => {
    show("game");
  });
  socket.on("word_called", ({ word, call_index }) => {
    state.calledWords.push(word);
    $("current-word").textContent = word;
    $("call-count").textContent = state.calledWords.length;
    const li = document.createElement("li");
    li.textContent = `${call_index}. ${word}`;
    // Newest first so the host sees the latest at the top.
    $("call-history").prepend(li);
    speak(word);
  });
  socket.on("win_declared", ({ place, player_name, pattern_matched }) => {
    state.wins.push({ place, player_name, pattern_matched });
    renderLeaderboard("leaderboard");
  });
  socket.on("game_ended", ({ reason }) => {
    show("end");
    $("end-reason").textContent =
      reason === "third_winner"
        ? "We have our top 3 winners!"
        : `Game ended (${reason}).`;
    renderLeaderboard("final-leaderboard");
  });
}

// --- Rendering ----------------------------------------------------------
function show(name) {
  for (const [key, el] of Object.entries(sections)) {
    el.hidden = key !== name;
  }
}

function renderPlayers() {
  $("player-count").textContent = state.players.length;
  const ul = $("player-list");
  ul.innerHTML = "";
  for (const name of state.players) {
    const li = document.createElement("li");
    li.textContent = name;
    ul.appendChild(li);
  }
}

function renderLeaderboard(targetId) {
  const ol = $(targetId);
  ol.innerHTML = "";
  const labels = ["1st", "2nd", "3rd"];
  for (let i = 0; i < 3; i++) {
    const li = document.createElement("li");
    const win = state.wins.find((w) => w.place === i + 1);
    if (win) {
      li.textContent = `${labels[i]}: ${win.player_name} (${win.pattern_matched})`;
    } else {
      li.className = "placeholder";
      li.textContent = `${labels[i]}: —`;
    }
    ol.appendChild(li);
  }
}

// --- Text-to-speech -----------------------------------------------------
function speak(word) {
  if (!("speechSynthesis" in window)) return;
  // Cancel any in-flight utterance so words don't pile up if the host
  // picked a short call interval.
  speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(word);
  utt.rate = 0.9;
  speechSynthesis.speak(utt);
}
