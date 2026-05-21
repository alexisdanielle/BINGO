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
  const allowedEmailsRaw = (data.get("allowed_emails") || "").trim();
  // Emails are required — the game is invite-only.
  if (!allowedEmailsRaw) {
    showError("create-error", "Player invite list is required. Enter at least one email address.");
    return;
  }
  state.draft = {
    host_name: (data.get("host_name") || "").trim() || "Host",
    topic: (data.get("topic") || "").trim(),
    pattern: data.get("pattern") || "horizontal",
    call_interval_seconds: Number(data.get("call_interval_seconds") || 5),
    max_winners: Number(data.get("max_winners") || 3),
    allowed_emails: allowedEmailsRaw,
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
  // Disable both the create-form submit and the topic-screen regenerate button
  // so the host can't trigger two simultaneous requests.
  $("generate-button").disabled = isGenerating;
  const regen = $("regenerate-button");
  if (regen) {
    regen.disabled = isGenerating;
    // When regenerating from the topic screen the spinner paragraph is in the
    // hidden create section, so change the button text as the visual cue instead.
    regen.textContent = isGenerating ? "Regenerating…" : "Regenerate all";
  }
  // Use style.display directly so there is no ambiguity with the CSS class —
  // the spinner is hidden on page load via style="display:none" in HTML.
  $("generate-status").style.display = isGenerating ? "flex" : "none";
}

// --- Step 2: edit/delete/regenerate the topic list ----------------------
function renderTopicList() {
  const ul = $("topic-words");
  ul.innerHTML = "";
  state.topicWords.forEach((entry, idx) => {
    const li = document.createElement("li");
    li.className = "topic-row";

    // Row number badge for easy visual reference
    const num = document.createElement("span");
    num.className = "topic-row-num";
    num.textContent = idx + 1;

    const word = document.createElement("input");
    word.type = "text";
    word.className = "topic-word";
    word.placeholder = "Word";
    word.value = entry.word;
    // Two-way bind: edits in the DOM flow back into state immediately,
    // so when the host clicks Accept we send their current edits.
    word.addEventListener("input", () => {
      state.topicWords[idx].word = word.value;
    });

    const desc = document.createElement("textarea");
    desc.className = "topic-desc";
    desc.rows = 1;
    desc.placeholder = "Description (optional)";
    desc.value = entry.description;
    desc.addEventListener("input", () => {
      state.topicWords[idx].description = desc.value;
      // Auto-grow: match scroll height so one-liners stay compact
      desc.style.height = "auto";
      desc.style.height = desc.scrollHeight + "px";
    });
    // Set initial height after value is set
    requestAnimationFrame(() => {
      desc.style.height = "auto";
      desc.style.height = desc.scrollHeight + "px";
    });

    const del = document.createElement("button");
    del.type = "button";
    del.className = "delete-row";
    del.textContent = "×";
    del.title = "Remove this word";
    del.addEventListener("click", () => {
      state.topicWords.splice(idx, 1);
      renderTopicList();
    });

    li.appendChild(num);
    li.appendChild(word);
    li.appendChild(desc);
    li.appendChild(del);
    ul.appendChild(li);
  });

  // Update count + warnings every render.
  const count = state.topicWords.length;
  $("word-count").textContent = String(count);
  $("word-count-warning").hidden = count === EXACT_WORDS; // show whenever count ≠ 40
  $("accept-button").disabled = count !== EXACT_WORDS;   // only enable at exactly 40
  $("add-word-button").disabled = count >= MAX_WORDS;
}

const MAX_WORDS = 40;
const EXACT_WORDS = 40; // the list must contain exactly this many words

// Back button on topic screen — returns to create form without losing draft data.
$("back-to-create-button").addEventListener("click", () => {
  show("create");
});

// Manual entry: skip AI, go to the topic screen with an empty word list.
$("manual-button").addEventListener("click", () => {
  hideError("create-error");
  const data = new FormData($("create-form"));
  const topic = (data.get("topic") || "").trim();
  const hostName = (data.get("host_name") || "").trim();
  const allowedEmailsRaw = (data.get("allowed_emails") || "").trim();
  if (!hostName) { showError("create-error", "Host name is required."); return; }
  if (!topic)    { showError("create-error", "Topic is required."); return; }
  if (!allowedEmailsRaw) {
    showError("create-error", "Player invite list is required. Enter at least one email address.");
    return;
  }
  state.draft = {
    host_name: hostName,
    topic,
    pattern: data.get("pattern") || "horizontal",
    call_interval_seconds: Number(data.get("call_interval_seconds") || 5),
    max_winners: Number(data.get("max_winners") || 3),
    allowed_emails: allowedEmailsRaw,
  };
  state.topicWords = [];
  $("topic-display").textContent = topic;
  renderTopicList();
  show("topic");
});

// Add a blank word row so the host can type in their own word.
$("add-word-button").addEventListener("click", () => {
  if (state.topicWords.length >= MAX_WORDS) return;
  state.topicWords.push({ word: "", description: "" });
  renderTopicList();
  // Scroll the new row into view and focus its word input.
  const rows = document.querySelectorAll("#topic-words .topic-row");
  const lastRow = rows[rows.length - 1];
  if (lastRow) {
    lastRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const input = lastRow.querySelector("input.topic-word");
    if (input) input.focus();
  }
});

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

  if (cleaned.length !== EXACT_WORDS) {
    alert(`Need exactly ${EXACT_WORDS} words — currently have ${cleaned.length}.`);
    return;
  }

  const body = {
    ...state.draft,
    game_words: cleaned,
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

  // Show how many invitation emails are being dispatched.
  const n = json.invite_count || 0;
  if (n > 0) {
    const statusEl = $("invites-status");
    statusEl.textContent = `✉ Invitations sent to ${n} player${n === 1 ? "" : "s"}.`;
    statusEl.style.display = "block";
  }

  show("lobby");
  renderLobbySettings();
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

$("end-game-button").addEventListener("click", async () => {
  if (!confirm("End the game now for everyone? This cannot be undone.")) return;
  const res = await fetch(`/api/games/${state.gameId}/end`, {
    method: "POST",
    headers: { "X-Host-Token": state.hostToken },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to end game: " + (err.error || res.status));
  }
  // UI transition happens via the game_ended socket event, same as a natural end.
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
    document.body.classList.add("game-bg");
  });
  socket.on("word_called", ({ word, description, call_index }) => {
    state.calledWords.push(word);
    // Animate the word display
    const wordEl = $("current-word");
    wordEl.classList.remove("pop");
    void wordEl.offsetWidth;
    wordEl.textContent = word;
    fitCurrentWord(); // scale font so the word never wraps
    wordEl.classList.add("pop");
    $("current-description").textContent = description || "";
    $("call-count").textContent = state.calledWords.length;
    // Word chips — newest first, styled in call-history CSS
    const li = document.createElement("li");
    li.title = description || "";  // tooltip shows description on hover
    li.textContent = word;
    $("call-history").prepend(li);
    speak(word);
  });
  socket.on("win_declared", ({ place, player_name, pattern_matched }) => {
    state.wins.push({ place, player_name, pattern_matched });
    renderLeaderboard("leaderboard");
  });
  socket.on("game_paused", () => {
    $("pause-button").style.display = "none";
    $("resume-button").style.display = "inline-block";
    $("paused-badge").style.display = "inline-flex";
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  });
  socket.on("game_resumed", () => {
    $("pause-button").style.display = "inline-block";
    $("resume-button").style.display = "none";
    $("paused-badge").style.display = "none";
  });
  socket.on("game_ended", ({ reason }) => {
    show("end");
    const n = state.maxWinners;
    const reasonMessages = {
      last_winner: `We have our top ${n} winner${n === 1 ? "" : "s"}!`,
      pool_exhausted: "All words have been called.",
      host_ended: "The host ended the game.",
    };
    $("end-reason").textContent = reasonMessages[reason] || `Game ended (${reason}).`;
    // Fetch full game state so the host's final leaderboard can include emails.
    fetch(`/api/games/${state.gameId}/state`)
      .then((r) => r.json())
      .then((s) => renderFinalLeaderboard("final-leaderboard", s.wins || []))
      .catch(() => renderLeaderboard("final-leaderboard"));
  });
}

// --- Word display fit ---------------------------------------------------
// Shrinks the font so the called word always fits on one line.
function fitCurrentWord() {
  const el = $("current-word");
  if (!el) return;
  el.style.fontSize = "";
  const card = el.closest(".current-word-card");
  const maxW = (card ? card.clientWidth : 300) - 64;
  let size = parseFloat(getComputedStyle(el).fontSize);
  while (el.scrollWidth > maxW && size > 14) {
    size -= 1;
    el.style.fontSize = size + "px";
  }
}

// --- Rendering ----------------------------------------------------------
function show(name) {
  for (const [key, el] of Object.entries(sections)) {
    el.hidden = key !== name;
  }
  // History section is not in `sections` so it must be managed separately.
  const historySec = $("history-section");
  if (historySec) historySec.hidden = (name === "game" || name === "end");
  if (name === "game" || name === "end") document.body.classList.add("game-bg");
  else document.body.classList.remove("game-bg");
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

// Renders the final end-of-game leaderboard with player emails visible to host.
// Takes a `wins` array fetched from /api/games/:id/state (includes player_email).
function renderFinalLeaderboard(targetId, wins) {
  const container = $(targetId);
  container.innerHTML = "";
  const n = state.maxWinners;
  for (let i = 0; i < n; i++) {
    const div = document.createElement("div");
    const win = wins.find((w) => w.place === i + 1);
    div.className = `leaderboard-entry place-${Math.min(i + 1, 3)}`;
    const place = document.createElement("span");
    place.className = "place";
    place.textContent = ordinal(i + 1);
    const info = document.createElement("span");
    if (win) {
      div.classList.add("filled");
      info.textContent = win.player_name;
      // Show the player's email (host-only view — emails not exposed to players)
      if (win.player_email) {
        const email = document.createElement("span");
        email.className = "muted";
        email.textContent = ` <${win.player_email}>`;
        info.appendChild(email);
      }
      const pat = document.createElement("span");
      pat.className = "muted";
      pat.textContent = ` (${win.pattern_matched})`;
      info.appendChild(pat);
    } else {
      info.textContent = "—";
      div.style.opacity = "0.45";
    }
    div.appendChild(place);
    div.appendChild(info);
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

function renderLobbySettings() {
  const bar = $("lobby-settings-bar");
  if (!bar || !state.draft) return;
  const patternLabels = {
    horizontal: "Any row", vertical: "Any column",
    diagonal: "Any diagonal", full_house: "Full house",
    row_1: "Row 1", row_2: "Row 2", row_3: "Row 3", row_4: "Row 4", row_5: "Row 5",
    col_1: "Col 1", col_2: "Col 2", col_3: "Col 3", col_4: "Col 4", col_5: "Col 5",
    diag_main: "Main diagonal ↘", diag_anti: "Anti-diagonal ↙",
  };
  const pat = patternLabels[state.draft.pattern] || state.draft.pattern;
  const w = state.draft.max_winners;
  // Values are numbers/fixed labels — safe to write as innerHTML
  bar.innerHTML =
    `<span class="settings-chip">🎯 ${pat}</span>` +
    `<span class="settings-chip">⏱ ${state.draft.call_interval_seconds}s per word</span>` +
    `<span class="settings-chip">🏆 ${w} winner${w === 1 ? "" : "s"}</span>`;
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
function speak(word) {
  if (!("speechSynthesis" in window)) return;
  // Cancel any in-flight utterance so words don't pile up at short intervals.
  speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(word);
  utt.rate = 0.9;
  speechSynthesis.speak(utt);
}
