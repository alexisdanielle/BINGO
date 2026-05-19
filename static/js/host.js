"use strict";

// All host-side state in one object so it's easy to inspect in the
// browser console during a demo (e.g. `state.players`).
const state = {
  // Draft details captured from the create form before a game exists.
  // We hold these aside while the host reviews the generated topic list.
  draft: null, // {host_name, topic, pattern, call_interval_seconds, max_winners, allowed_emails}
  topicWords: [], // [{word, description}, ...] -- editable preview
  gameId: null,
  hostToken: null,
  players: [],
  calledWords: [],
  wins: [],
  maxWinners: 3,
  topicHistoryCache: null, // fetched once per page load
};

const $ = (id) => document.getElementById(id);

const sections = {
  create: $("create-section"),
  topic: $("topic-section"),
  lobby: $("lobby-section"),
  game: $("game-section"),
  end: $("end-section"),
};

let socket = null;

// --- Copy link (registered once; reads link from anchor text) -----------
$("copy-link-button").addEventListener("click", () => {
  const link = $("join-link").href;
  if (!link) return;
  navigator.clipboard.writeText(link).then(() => {
    const btn = $("copy-link-button");
    btn.textContent = "Copied!";
    setTimeout(() => (btn.textContent = "Copy link"), 2000);
  });
});

// --- Step 1: capture form, generate topic preview -----------------------
$("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  hideError("create-error");
  const data = new FormData(e.target);
  // Capture the allowlist textarea; send as-is (server parses comma/newline).
  const allowedEmailsRaw = (data.get("allowed_emails") || "").trim();
  state.draft = {
    host_name: (data.get("host_name") || "").trim() || "Host",
    topic: (data.get("topic") || "").trim(),
    pattern: data.get("pattern") || "horizontal",
    call_interval_seconds: Number(data.get("call_interval_seconds") || 5),
    max_winners: Number(data.get("max_winners") || 3),
    allowed_emails: allowedEmailsRaw || null,
  };
  if (!state.draft.topic) {
    showError("create-error", "Topic is required.");
    return;
  }
  await fetchTopicPreview();
});

async function fetchTopicPreview() {
  setGenerating(true);
  try {
    const res = await fetch("/api/topics/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: state.draft.topic }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(
        "create-error",
        "Failed to generate topic: " + (err.error || res.status),
      );
      // Keep the user on the create screen so they can adjust the topic.
      show("create");
      return;
    }
    const json = await res.json();
    state.topicWords = json.words;
    $("topic-display").textContent = json.topic;
    renderTopicList();
    show("topic");
  } finally {
    setGenerating(false);
  }
}

function setGenerating(isGenerating) {
  const btn = $("generate-button");
  const status = $("generate-status");
  btn.disabled = isGenerating;
  if (isGenerating) {
    status.textContent = "Generating word list — this can take a few seconds…";
    status.hidden = false;
  } else {
    status.hidden = true;
  }
}

// --- Step 2: edit/delete/regenerate the topic list ----------------------
function renderTopicList() {
  const ul = $("topic-words");
  ul.innerHTML = "";
  state.topicWords.forEach((entry, idx) => {
    const li = document.createElement("li");
    li.className = "topic-row";

    const word = document.createElement("input");
    word.type = "text";
    word.className = "topic-word";
    word.value = entry.word;
    // Two-way bind: edits in the DOM flow back into state immediately,
    // so when the host clicks Accept we send their current edits.
    word.addEventListener("input", () => {
      state.topicWords[idx].word = word.value;
    });

    const desc = document.createElement("textarea");
    desc.className = "topic-desc";
    desc.rows = 2;
    desc.value = entry.description;
    desc.addEventListener("input", () => {
      state.topicWords[idx].description = desc.value;
    });

    const del = document.createElement("button");
    del.type = "button";
    del.className = "delete-row";
    del.textContent = "Delete";
    del.addEventListener("click", () => {
      state.topicWords.splice(idx, 1);
      renderTopicList();
    });

    li.appendChild(word);
    li.appendChild(desc);
    li.appendChild(del);
    ul.appendChild(li);
  });

  // Update the count + warning every render so the host sees the state
  // change after deletes/regenerates without an extra click.
  const count = state.topicWords.length;
  $("word-count").textContent = String(count);
  $("word-count-warning").hidden = count >= 25;
  $("accept-button").disabled = count < 25;
}

$("regenerate-button").addEventListener("click", async () => {
  await fetchTopicPreview();
});

$("accept-button").addEventListener("click", async () => {
  // Strip empty rows the host may have created by clearing a word field.
  const cleaned = state.topicWords
    .map((e) => ({
      word: (e.word || "").trim(),
      description: (e.description || "").trim(),
    }))
    .filter((e) => e.word);

  if (cleaned.length < 25) {
    alert(`Need at least 25 words, currently have ${cleaned.length}.`);
    return;
  }

  const body = {
    ...state.draft,
    game_words: cleaned,
    // Only send allowed_emails when the host actually entered something.
    allowed_emails: state.draft.allowed_emails || undefined,
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
  state.maxWinners = json.max_winners || 3;

  const link = `${location.origin}/play?game_id=${json.game_id}`;
  const a = $("join-link");
  a.href = link;
  a.textContent = link;

  show("lobby");
  connectSocket();
});

// --- Step 3: start game -------------------------------------------------
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

// --- Pause / Resume -----------------------------------------------------
$("pause-button").addEventListener("click", async () => {
  const res = await fetch(`/api/games/${state.gameId}/pause`, {
    method: "POST",
    headers: { "X-Host-Token": state.hostToken },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to pause: " + (err.error || res.status));
  }
});

$("resume-button").addEventListener("click", async () => {
  const res = await fetch(`/api/games/${state.gameId}/resume`, {
    method: "POST",
    headers: { "X-Host-Token": state.hostToken },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to resume: " + (err.error || res.status));
  }
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
  socket.on("word_called", ({ word, description, call_index }) => {
    state.calledWords.push(word);
    $("current-word").textContent = word;
    $("current-description").textContent = description || "";
    $("call-count").textContent = state.calledWords.length;
    const li = document.createElement("li");
    // Show the description inline with each historical call so the host
    // has a teleprompter-style script during the demo.
    li.textContent = description
      ? `${call_index}. ${word} — ${description}`
      : `${call_index}. ${word}`;
    // Newest first so the host sees the latest at the top.
    $("call-history").prepend(li);
    speak(word, description);
  });
  socket.on("win_declared", ({ place, player_name, pattern_matched }) => {
    state.wins.push({ place, player_name, pattern_matched });
    renderLeaderboard("leaderboard");
  });
  socket.on("game_paused", () => {
    $("pause-button").hidden = true;
    $("resume-button").hidden = false;
    $("paused-badge").hidden = false;
    $("current-word").textContent = "—";
    $("current-description").textContent = "";
  });
  socket.on("game_resumed", () => {
    $("pause-button").hidden = false;
    $("resume-button").hidden = true;
    $("paused-badge").hidden = true;
  });
  socket.on("game_ended", ({ reason }) => {
    show("end");
    const n = state.maxWinners;
    $("end-reason").textContent =
      reason === "last_winner"
        ? `We have our top ${n} winner${n === 1 ? "" : "s"}!`
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

function ordinal(n) {
  if (n >= 11 && n <= 13) return n + "th";
  const rem = n % 10;
  if (rem === 1) return n + "st";
  if (rem === 2) return n + "nd";
  if (rem === 3) return n + "rd";
  return n + "th";
}

function renderLeaderboard(targetId) {
  const container = $(targetId);
  container.innerHTML = "";
  const n = state.maxWinners;
  for (let i = 0; i < n; i++) {
    const div = document.createElement("div");
    const win = state.wins.find((w) => w.place === i + 1);
    div.className = `leaderboard-entry place-${Math.min(i + 1, 3)}`;
    const place = document.createElement("span");
    place.className = "place";
    place.textContent = ordinal(i + 1);
    const name = document.createElement("span");
    if (win) {
      name.textContent = win.player_name;
      const pat = document.createElement("span");
      pat.className = "muted";
      pat.textContent = ` (${win.pattern_matched})`;
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

function showError(id, msg) {
  const el = $(id);
  el.textContent = msg;
  el.hidden = false;
}
function hideError(id) {
  $(id).hidden = true;
}

// --- Topic history -------------------------------------------------------
$("history-toggle").addEventListener("click", async () => {
  const panel = $("history-panel");
  const btn = $("history-toggle");
  if (!panel.hidden) {
    panel.hidden = true;
    btn.textContent = "Show";
    return;
  }
  panel.hidden = false;
  btn.textContent = "Hide";

  // Use cached data if already fetched to avoid redundant requests.
  if (state.topicHistoryCache !== null) {
    renderTopicHistory(state.topicHistoryCache);
    return;
  }

  const res = await fetch("/api/topics/history");
  if (!res.ok) {
    $("history-body").innerHTML =
      '<tr><td colspan="4" class="error">Failed to load history.</td></tr>';
    return;
  }
  const { topics } = await res.json();
  state.topicHistoryCache = topics;
  renderTopicHistory(topics);
});

function renderTopicHistory(topics) {
  const tbody = $("history-body");
  if (!topics.length) {
    tbody.innerHTML =
      '<tr><td colspan="4" class="muted" style="padding:1rem 0.75rem;">No topics generated yet.</td></tr>';
    return;
  }
  tbody.innerHTML = "";
  for (const t of topics) {
    const tr = document.createElement("tr");
    // Build cells with textContent to avoid XSS from user-supplied topic names.
    const cells = [t.topic_name, t.word_count, t.times_used, t.created_at];
    for (const val of cells) {
      const td = document.createElement("td");
      td.textContent = val;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

// --- Text-to-speech -----------------------------------------------------
function speak(word, description) {
  if (!("speechSynthesis" in window)) return;
  // Cancel any in-flight utterance so words don't pile up if the host
  // picked a short call interval (the new word truncates the old one).
  speechSynthesis.cancel();
  // Speak "<word>. <description>" so the audience hears both the term
  // and a short factual blurb. The period gives the engine a natural
  // pause between the two. If a description is missing (legacy games
  // without a topic), fall back to just the word.
  const text = description ? `${word}. ${description}` : word;
  const utt = new SpeechSynthesisUtterance(text);
  utt.rate = 0.9; // slightly slower than default for clarity
  speechSynthesis.speak(utt);
}
