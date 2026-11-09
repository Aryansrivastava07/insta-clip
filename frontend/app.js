// InstaClip Frontend Client
let authToken = localStorage.getItem("instaclip_token");
let currentUser = null;
let activeTag = null;
let searchTimeout = null;
let currentAuthMode = "login";

// --- INITIALIZATION ---
document.addEventListener("DOMContentLoaded", () => {
  if (authToken) {
    verifySession();
  } else {
    showAuthOverlay();
  }
});

// --- AUTH HANDLING ---
function showAuthOverlay() {
  document.getElementById("authOverlay").classList.remove("hidden");
  document.getElementById("appContainer").classList.add("hidden");
}

function hideAuthOverlay() {
  document.getElementById("authOverlay").classList.add("hidden");
  document.getElementById("appContainer").classList.remove("hidden");
}

function switchAuthTab(mode) {
  currentAuthMode = mode;
  const tabLogin = document.getElementById("tabLogin");
  const tabRegister = document.getElementById("tabRegister");
  const submitBtn = document.getElementById("authSubmitBtn");
  const errorBox = document.getElementById("authError");

  errorBox.classList.add("hidden");

  if (mode === "login") {
    tabLogin.classList.add("active");
    tabRegister.classList.remove("active");
    submitBtn.querySelector(".btn-text").textContent = "Sign In";
  } else {
    tabRegister.classList.add("active");
    tabLogin.classList.remove("active");
    submitBtn.querySelector(".btn-text").textContent = "Create Account";
  }
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const username = document.getElementById("authUsername").value.trim();
  const password = document.getElementById("authPassword").value;
  const submitBtn = document.getElementById("authSubmitBtn");
  const errorBox = document.getElementById("authError");

  submitBtn.querySelector(".btn-text").classList.add("hidden");
  submitBtn.querySelector(".spinner").classList.remove("hidden");
  submitBtn.disabled = true;
  errorBox.classList.add("hidden");

  const endpoint = currentAuthMode === "login" ? "/api/auth/login" : "/api/auth/register";

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Authentication failed");
    }

    authToken = data.token;
    localStorage.setItem("instaclip_token", authToken);
    await verifySession();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove("hidden");
  } finally {
    submitBtn.querySelector(".btn-text").classList.remove("hidden");
    submitBtn.querySelector(".spinner").classList.add("hidden");
    submitBtn.disabled = false;
  }
}

async function verifySession() {
  try {
    const res = await fetch("/api/auth/me", {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (!res.ok) throw new Error("Invalid token");

    currentUser = await res.json();
    hideAuthOverlay();
    updateUserStatusUI();
    loadTags();
    loadReels();
  } catch (err) {
    logout();
  }
}

function logout() {
  localStorage.removeItem("instaclip_token");
  authToken = null;
  currentUser = null;
  showAuthOverlay();
}

function updateUserStatusUI() {
  const badge = document.getElementById("igStatusBadge");
  if (!badge || !currentUser) return;

  if (currentUser.has_ig_session) {
    badge.className = "status-pill status-connected";
    badge.querySelector(".status-text").textContent = "IG: Connected";
  } else {
    badge.className = "status-pill status-disconnected";
    badge.querySelector(".status-text").textContent = "IG: Not Connected";
  }
}

// --- DATA FETCHING & RENDERING ---

async function loadReels(query = "") {
  const grid = document.getElementById("reelsGrid");
  const emptyState = document.getElementById("emptyState");
  const reelsCount = document.getElementById("reelsCount");

  let url = `/api/reels?q=${encodeURIComponent(query)}`;
  if (activeTag) {
    url += `&tag=${encodeURIComponent(activeTag)}`;
  }

  try {
    const res = await fetch(url, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    const data = await res.json();
    const reels = data.results || [];

    reelsCount.textContent = data.total || reels.length;

    if (reels.length === 0) {
      grid.innerHTML = "";
      emptyState.classList.remove("hidden");
      return;
    }

    emptyState.classList.add("hidden");
    grid.innerHTML = reels.map(renderReelCard).join("");
  } catch (err) {
    showToast("Error loading reels: " + err.message);
  }
}

function renderReelCard(reel) {
  const scorePercent = reel.score && reel.score > 0 ? Math.round(reel.score * 100) : null;
  const tagsHtml = (reel.tags || [])
    .map(t => `<span class="card-tag" onclick="selectTag('${escapeHtml(t)}')">#${escapeHtml(t)}</span>`)
    .join("");

  return `
    <div class="reel-card" id="card-${reel.reel_id}">
      <div class="reel-header">
        <a href="https://instagram.com/${escapeHtml(reel.creator_username || '')}" target="_blank" class="creator-badge">
          <div class="creator-avatar">📷</div>
          <span>@${escapeHtml(reel.creator_username || "creator")}</span>
        </a>
        ${scorePercent ? `<span class="match-score-badge">${scorePercent}% Match</span>` : ''}
      </div>

      <div class="reel-summary-box">
        <strong>💡 AI Summary</strong>
        ${escapeHtml(reel.summary || "No summary available")}
      </div>

      <!-- COLLAPSIBLE AUDIO TRANSCRIPT -->
      <div class="details-collapsible">
        <button class="details-toggle" onclick="toggleDetails('transcript-${reel.reel_id}')">
          <span>📝</span>
          <span>Spoken Dialogue / Transcript</span>
          <span>▾</span>
        </button>
        <div id="transcript-${reel.reel_id}" class="details-content hidden">
          ${escapeHtml(reel.transcript || "No dialogue detected or transcribed.")}
        </div>
      </div>

      <!-- COLLAPSIBLE ON-SCREEN TEXT -->
      <div class="details-collapsible">
        <button class="details-toggle" onclick="toggleDetails('visual-${reel.reel_id}')">
          <span>👁️</span>
          <span>On-Screen Text & Notes</span>
          <span>▾</span>
        </button>
        <div id="visual-${reel.reel_id}" class="details-content hidden">
          ${escapeHtml(reel.on_screen_text || "No on-screen text recorded.")}
        </div>
      </div>

      ${tagsHtml ? `<div class="reel-tags">${tagsHtml}</div>` : ''}

      <div class="reel-footer">
        <a href="${escapeHtml(reel.reel_url)}" target="_blank" class="reel-link-btn">
          <span>Open on Instagram</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
        </a>
        <button class="delete-btn" onclick="deleteReel('${reel.reel_id}')" title="Delete">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    </div>
  `;
}

function toggleDetails(elementId) {
  const el = document.getElementById(elementId);
  if (el) {
    el.classList.toggle("hidden");
  }
}

async function loadTags() {
  const container = document.getElementById("tagsContainer");
  try {
    const res = await fetch("/api/tags", {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    const data = await res.json();
    const tags = data.tags || [];

    if (tags.length === 0) {
      container.innerHTML = "";
      return;
    }

    container.innerHTML = tags.map(t => `
      <button class="tag-pill ${activeTag === t.tag ? 'active' : ''}" onclick="selectTag('${escapeHtml(t.tag)}')">
        #${escapeHtml(t.tag)} (${t.count})
      </button>
    `).join("");
  } catch (err) {
    console.error("Failed to load tags", err);
  }
}

function selectTag(tag) {
  if (activeTag === tag) {
    clearTagFilter();
    return;
  }
  activeTag = tag;
  const filterBadge = document.getElementById("activeFilterBadge");
  const filterName = document.getElementById("filterName");

  filterName.textContent = `#${tag}`;
  filterBadge.classList.remove("hidden");

  loadTags();
  const query = document.getElementById("searchInput").value.trim();
  loadReels(query);
}

function clearTagFilter() {
  activeTag = null;
  document.getElementById("activeFilterBadge").classList.add("hidden");
  loadTags();
  const query = document.getElementById("searchInput").value.trim();
  loadReels(query);
}

// --- SEARCH HANDLING ---
function debounceSearch() {
  clearTimeout(searchTimeout);
  const input = document.getElementById("searchInput");
  const clearBtn = document.getElementById("clearSearchBtn");

  if (input.value.trim().length > 0) {
    clearBtn.classList.remove("hidden");
  } else {
    clearBtn.classList.add("hidden");
  }

  searchTimeout = setTimeout(() => {
    loadReels(input.value.trim());
  }, 250);
}

function clearSearch() {
  const input = document.getElementById("searchInput");
  input.value = "";
  document.getElementById("clearSearchBtn").classList.add("hidden");
  loadReels("");
}

// --- SYNC & ACTIONS ---

async function triggerSync() {
  const syncBtn = document.getElementById("syncBtn");
  const syncIcon = document.getElementById("syncIcon");
  const syncText = document.getElementById("syncText");

  syncBtn.disabled = true;
  syncIcon.style.animation = "spin 1s linear infinite";
  syncText.textContent = "Syncing...";

  try {
    const res = await fetch("/api/reels/sync", {
      method: "POST",
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Sync failed");

    showToast(`Sync complete! ${data.new_indexed} new reels indexed (${data.already_indexed} already up to date).`);
    loadTags();
    loadReels(document.getElementById("searchInput").value.trim());
  } catch (err) {
    showToast("Sync Error: " + err.message);
  } finally {
    syncBtn.disabled = false;
    syncIcon.style.animation = "none";
    syncText.textContent = "Sync Inbox";
  }
}

async function submitManualReel() {
  const input = document.getElementById("manualReelUrl");
  const url = input.value.trim();
  const btn = document.getElementById("addReelBtn");
  const msgBox = document.getElementById("addMsg");

  if (!url) return;

  btn.querySelector(".btn-text").classList.add("hidden");
  btn.querySelector(".spinner").classList.remove("hidden");
  btn.disabled = true;
  msgBox.classList.add("hidden");

  try {
    const res = await fetch("/api/reels/index-manual", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
      },
      body: JSON.stringify({ reel_url: url })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Indexing failed");

    msgBox.textContent = "Reel indexed successfully!";
    msgBox.className = "settings-msg success";
    msgBox.classList.remove("hidden");
    input.value = "";

    setTimeout(() => {
      closeModal("addModal");
      loadTags();
      loadReels();
    }, 1200);
  } catch (err) {
    msgBox.textContent = err.message;
    msgBox.className = "settings-msg error";
    msgBox.classList.remove("hidden");
  } finally {
    btn.querySelector(".btn-text").classList.remove("hidden");
    btn.querySelector(".spinner").classList.add("hidden");
    btn.disabled = false;
  }
}

async function deleteReel(reelId) {
  if (!confirm("Are you sure you want to remove this reel from your index?")) return;

  try {
    const res = await fetch(`/api/reels/${reelId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (!res.ok) throw new Error("Failed to delete reel");

    const card = document.getElementById(`card-${reelId}`);
    if (card) card.remove();
    showToast("Reel removed");
    loadTags();
  } catch (err) {
    showToast(err.message);
  }
}

// --- SETTINGS MODAL ---

function openSettingsModal() {
  const modal = document.getElementById("settingsModal");
  modal.classList.remove("hidden");
  document.getElementById("settingsMsg").classList.add("hidden");
}

function openAddModal() {
  const modal = document.getElementById("addModal");
  modal.classList.remove("hidden");
  document.getElementById("addMsg").classList.add("hidden");
}

function closeModal(modalId) {
  document.getElementById(modalId).classList.add("hidden");
}

function closeModalOnBackdrop(event, modalId) {
  if (event.target.id === modalId) {
    closeModal(modalId);
  }
}

async function saveSettings() {
  const igSession = document.getElementById("igSessionInput").value.trim();
  const geminiKey = document.getElementById("geminiKeyInput").value.trim();
  const msgBox = document.getElementById("settingsMsg");

  const payload = {};
  if (igSession) payload.ig_session_id = igSession;
  if (geminiKey) payload.gemini_api_key = geminiKey;

  try {
    const res = await fetch("/api/auth/settings", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${authToken}`
      },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error("Failed to update settings");

    msgBox.textContent = "Settings saved successfully!";
    msgBox.className = "settings-msg success";
    msgBox.classList.remove("hidden");

    await verifySession();
    setTimeout(() => closeModal("settingsModal"), 1200);
  } catch (err) {
    msgBox.textContent = err.message;
    msgBox.className = "settings-msg error";
    msgBox.classList.remove("hidden");
  }
}

// --- HELPERS ---
function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3500);
}

function escapeHtml(str) {
  if (!str) return "";
  return str.toString()
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
