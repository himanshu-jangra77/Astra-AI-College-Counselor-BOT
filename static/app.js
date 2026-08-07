/**
 * ============================================================================
 * ASTRA AI — HIGHER EDUCATION COUNSELOR & COLLEGE DIRECTORY (APP.JS)
 * Fast SSE Real-Time Streaming, Interactive Directory, and Modal Details
 * ============================================================================
 */

// ── 1. GLOBAL STATE ─────────────────────────────────────────────────────────
const state = {
  activeTab: 'chat-pane',
  isGenerating: false,
  fastMode: true,
  directoryColleges: [],
  directoryView: 'grid',
  selectedCollegeForModal: null,
  speechSynth: window.speechSynthesis || null,
  activeSpeechUtterance: null
};

// ── 2. DOM REFERENCES ───────────────────────────────────────────────────────
const DOM = {
  // Navigation
  navTabs: document.querySelectorAll('.nav-tab'),
  tabPanes: document.querySelectorAll('.tab-pane'),
  
  // Chat
  chatFeed: document.getElementById('chat-feed'),
  messagesContainer: document.getElementById('messages-container'),
  heroCard: document.getElementById('hero-card'),
  chatForm: document.getElementById('chat-form'),
  chatInput: document.getElementById('chat-input'),
  sendBtn: document.getElementById('send-btn'),
  thinkingBox: document.getElementById('thinking-box'),
  thinkingStatus: document.getElementById('thinking-status'),
  resetSessionBtn: document.getElementById('reset-session-btn'),
  scrollAnchor: document.getElementById('scroll-anchor'),
  
  // Directory
  dirSearch: document.getElementById('dir-search'),
  dirStream: document.getElementById('dir-stream'),
  dirState: document.getElementById('dir-state'),
  dirSort: document.getElementById('dir-sort'),
  matrixResultsGrid: document.getElementById('matrix-results-grid'),
  viewModeGrid: document.getElementById('view-mode-grid'),
  viewModeList: document.getElementById('view-mode-list'),
  dirCountLbl: document.getElementById('dir-count-lbl'),
  
  // Modal & Toast
  collegeModal: document.getElementById('college-detail-modal'),
  modalBody: document.getElementById('modal-college-body'),
  toastContainer: document.getElementById('toast-container')
};

// ── 3. TOAST NOTIFICATIONS ──────────────────────────────────────────────────
function showToast(msg, type = 'info') {
  if (!DOM.toastContainer) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : '⚡';
  toast.innerHTML = `<span>${icon} ${msg}</span>`;
  DOM.toastContainer.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(40px)';
    toast.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

// ── 4. TAB NAVIGATION ───────────────────────────────────────────────────────
function initNavigation() {
  DOM.navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetPaneId = tab.dataset.tab;
      switchTab(targetPaneId);
    });
  });
}

function switchTab(paneId) {
  state.activeTab = paneId;
  DOM.navTabs.forEach(t => {
    t.classList.toggle('active', t.dataset.tab === paneId);
  });
  DOM.tabPanes.forEach(p => {
    p.classList.toggle('active', p.id === paneId);
  });

  if (paneId === 'matrix-pane' && (!state.directoryColleges || state.directoryColleges.length === 0)) {
    loadDirectoryColleges();
  }
}

// ── 5. SCROLL HELPER (SMOOTH & PINNED) ───────────────────────────────────────
function scrollToBottom() {
  if (!DOM.chatFeed) return;
  // Instant scroll directly to bottom so the user does not need to scroll
  DOM.chatFeed.scrollTop = DOM.chatFeed.scrollHeight;
  if (DOM.scrollAnchor) {
    DOM.scrollAnchor.scrollIntoView({ behavior: 'auto', block: 'end' });
  }
}

// ── 6. REAL-TIME STREAMING AI COUNSELOR CHAT ────────────────────────────────
function initChat() {
  if (!DOM.chatForm) return;

  // Auto expand textarea
  DOM.chatInput.addEventListener('input', function() {
    this.style.height = '26px';
    this.style.height = Math.min(this.scrollHeight, 140) + 'px';
  });

  // Handle Enter key submit
  DOM.chatInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      DOM.chatForm.dispatchEvent(new Event('submit'));
    }
  });

  // Submit Handler
  DOM.chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = DOM.chatInput.value.trim();
    if (!query || state.isGenerating) return;

    submitCounselorQuery(query);
  });

  // Reset Session
  if (DOM.resetSessionBtn) {
    DOM.resetSessionBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/reset', { method: 'POST' });
        DOM.messagesContainer.innerHTML = '';
        if (DOM.heroCard) DOM.heroCard.style.display = 'block';
        showToast('Chat history cleared!', 'success');
      } catch {
        showToast('Error resetting chat', 'error');
      }
    });
  }
}

async function submitCounselorQuery(queryText) {
  if (state.isGenerating) return;

  // Hide welcome hero card
  if (DOM.heroCard) DOM.heroCard.style.display = 'none';

  // 1. Append User Bubble
  appendUserMessage(queryText);
  DOM.chatInput.value = '';
  DOM.chatInput.style.height = '26px';

  state.isGenerating = true;
  DOM.sendBtn.disabled = true;

  // 2. Thinking indicator
  DOM.thinkingBox.style.display = 'flex';
  DOM.thinkingStatus.textContent = 'Searching 6,780+ institutional records & generating counsel...';
  scrollToBottom();

  // 3. Create AI Message Container for streaming
  const { row, mdContainer, setFinalActions } = createAiMessageStreamRow();
  DOM.messagesContainer.appendChild(row);

  let accumulatedText = '';
  let receivedFirstToken = false;

  try {
    const streamUrl = `/api/chat/stream?message=${encodeURIComponent(queryText)}&fast_mode=true`;
    const response = await fetch(streamUrl);

    if (!response.ok) {
      throw new Error(`Server returned ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data: ')) continue;

        const jsonStr = trimmed.slice(6);
        try {
          const data = JSON.parse(jsonStr);

          if (data.type === 'meta') {
            if (data.matched_colleges > 0) {
              DOM.thinkingStatus.textContent = `Found ${data.matched_colleges} matching institutions. Formulating response...`;
              scrollToBottom();
            }
          } else if (data.token) {
            if (!receivedFirstToken) {
              receivedFirstToken = true;
              DOM.thinkingBox.style.display = 'none';
            }
            accumulatedText += data.token;
            mdContainer.innerHTML = marked.parse(accumulatedText);
            // Automatic pinned scroll as AI streams
            scrollToBottom();
          } else if (data.done) {
            DOM.thinkingBox.style.display = 'none';
            scrollToBottom();
          }
        } catch (err) {
          // Non-JSON line
        }
      }
    }

    if (!accumulatedText) {
      accumulatedText = "No response generated. Please try asking again.";
      mdContainer.innerHTML = marked.parse(accumulatedText);
    }

    setFinalActions(accumulatedText);

  } catch (err) {
    console.error('Stream error:', err);
    DOM.thinkingBox.style.display = 'none';
    
    // Fallback sync request if stream fails
    try {
      DOM.thinkingStatus.textContent = 'Re-routing query to fast database engine...';
      DOM.thinkingBox.style.display = 'flex';
      scrollToBottom();
      
      const fallbackRes = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: queryText, fast_mode: true })
      });
      const data = await fallbackRes.json();
      DOM.thinkingBox.style.display = 'none';
      accumulatedText = data.response || '⚠️ Unable to process query.';
      mdContainer.innerHTML = marked.parse(accumulatedText);
      setFinalActions(accumulatedText);
      scrollToBottom();
    } catch (fallbackErr) {
      DOM.thinkingBox.style.display = 'none';
      accumulatedText = `⚠️ **Connection Error**: Unable to reach backend server. Please verify the server is running on http://localhost:8000.`;
      mdContainer.innerHTML = marked.parse(accumulatedText);
      setFinalActions(accumulatedText);
      scrollToBottom();
    }
  } finally {
    DOM.thinkingBox.style.display = 'none';
    state.isGenerating = false;
    DOM.sendBtn.disabled = false;
    DOM.chatInput.focus();
    scrollToBottom();
  }
}

function appendUserMessage(text) {
  const row = document.createElement('div');
  row.className = 'msg-row user';
  row.innerHTML = `
    <div class="avatar user" title="You">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    </div>
    <div class="msg-body">
      <div class="msg-sender">You</div>
      <div class="bubble">${escapeHtml(text)}</div>
    </div>
  `;
  DOM.messagesContainer.appendChild(row);
  scrollToBottom();
}

function createAiMessageStreamRow() {
  const row = document.createElement('div');
  row.className = 'msg-row ai';
  
  row.innerHTML = `
    <div class="avatar ai" title="ASTRA AI">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/></svg>
    </div>
    <div class="msg-body">
      <div class="msg-sender">ASTRA AI Counselor</div>
      <div class="bubble">
        <div class="md-rendered streaming-content"></div>
        <div class="bubble-actions" style="display:none;">
          <button class="action-icon-btn copy-btn">
            <svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy
          </button>
          <button class="action-icon-btn speech-btn">
            <svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg> Listen
          </button>
        </div>
      </div>
    </div>
  `;

  const mdContainer = row.querySelector('.md-rendered');
  const actionsBox = row.querySelector('.bubble-actions');
  const copyBtn = row.querySelector('.copy-btn');
  const speechBtn = row.querySelector('.speech-btn');

  function setFinalActions(finalText) {
    actionsBox.style.display = 'flex';
    
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(finalText);
      showToast('Response copied to clipboard!', 'success');
    };

    speechBtn.onclick = () => speakResponse(finalText);
  }

  return { row, mdContainer, setFinalActions };
}

function speakResponse(text) {
  if (!state.speechSynth) {
    showToast('Speech synthesis not available.', 'error');
    return;
  }

  if (state.speechSynth.speaking) {
    state.speechSynth.cancel();
    showToast('Voice playback stopped.');
    return;
  }

  const clean = text.replace(/[*#_`~>|\-\n]/g, ' ').replace(/\s+/g, ' ').substring(0, 350);
  const utter = new SpeechSynthesisUtterance(clean);
  utter.rate = 1.05;
  utter.pitch = 1.0;
  state.speechSynth.speak(utter);
  showToast('Playing audio summary...', 'info');
}

function sendPresetQuery(queryText) {
  switchTab('chat-pane');
  DOM.chatInput.value = queryText;
  submitCounselorQuery(queryText);
}

// ── 7. COLLEGE DIRECTORY ────────────────────────────────────────────────────
function initDirectory() {
  if (!DOM.dirSearch) return;

  let searchTimer;
  DOM.dirSearch.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadDirectoryColleges, 250);
  });

  DOM.dirStream.addEventListener('change', loadDirectoryColleges);
  DOM.dirState.addEventListener('change', loadDirectoryColleges);
  if (DOM.dirSort) DOM.dirSort.addEventListener('change', loadDirectoryColleges);

  if (DOM.viewModeGrid && DOM.viewModeList) {
    DOM.viewModeGrid.addEventListener('click', () => {
      state.directoryView = 'grid';
      DOM.viewModeGrid.classList.add('active');
      DOM.viewModeList.classList.remove('active');
      renderDirectoryGrid();
    });

    DOM.viewModeList.addEventListener('click', () => {
      state.directoryView = 'list';
      DOM.viewModeList.classList.add('active');
      DOM.viewModeGrid.classList.remove('active');
      renderDirectoryGrid();
    });
  }
}

async function loadDirectoryColleges() {
  const q = DOM.dirSearch ? DOM.dirSearch.value.trim() : '';
  const stream = DOM.dirStream ? DOM.dirStream.value : '';
  const stateVal = DOM.dirState ? DOM.dirState.value : '';

  DOM.matrixResultsGrid.innerHTML = `
    <div style="grid-column:1/-1; text-align:center; padding:60px 20px; color:var(--text-sub);">
      <div class="spinner" style="margin:0 auto 16px auto;"></div>
      Filtering 6,780+ verified college records...
    </div>
  `;

  let url = '/api/colleges?limit=48';
  if (q) url += `&q=${encodeURIComponent(q)}`;
  if (stream) url += `&stream=${encodeURIComponent(stream)}`;
  if (stateVal) url += `&state=${encodeURIComponent(stateVal)}`;

  try {
    const res = await fetch(url);
    const data = await res.json();
    state.directoryColleges = data.colleges || [];

    const sortVal = DOM.dirSort ? DOM.dirSort.value : 'rating-desc';
    sortColleges(state.directoryColleges, sortVal);

    if (DOM.dirCountLbl) {
      DOM.dirCountLbl.textContent = `Showing ${state.directoryColleges.length} verified institutions`;
    }

    renderDirectoryGrid();
  } catch (err) {
    DOM.matrixResultsGrid.innerHTML = `
      <div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--accent-rose);">
        ⚠️ Failed to load colleges from database.
      </div>
    `;
  }
}

function sortColleges(colleges, sortVal) {
  if (sortVal === 'rating-desc') {
    colleges.sort((a, b) => (b.rating || 0) - (a.rating || 0));
  } else if (sortVal === 'placement-desc') {
    colleges.sort((a, b) => (b.placement || 0) - (a.placement || 0));
  } else if (sortVal === 'fee-asc') {
    colleges.sort((a, b) => (a.ug_fee || 9999999) - (b.ug_fee || 9999999));
  } else if (sortVal === 'name-asc') {
    colleges.sort((a, b) => (a.college_name || '').localeCompare(b.college_name || ''));
  }
}

function renderDirectoryGrid() {
  if (!state.directoryColleges || state.directoryColleges.length === 0) {
    DOM.matrixResultsGrid.innerHTML = `
      <div style="grid-column:1/-1; text-align:center; padding:60px 20px; color:var(--text-muted);">
        <p style="font-size:16px; font-weight:700; color:var(--text-main); margin-bottom:6px;">No Institutions Found</p>
        <p style="font-size:13px;">Try adjusting your filter search criteria.</p>
      </div>
    `;
    return;
  }

  if (state.directoryView === 'list') {
    DOM.matrixResultsGrid.innerHTML = `
      <div class="directory-list-card">
        <table class="directory-table">
          <thead>
            <tr>
              <th>Institution Name</th>
              <th>Location</th>
              <th>Stream</th>
              <th>Rating</th>
              <th>Placement</th>
              <th>Annual UG Fee</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${state.directoryColleges.map((c, i) => `
              <tr class="${i % 2 === 0 ? 'even-row' : ''}">
                <td class="col-name" onclick="openCollegeModalById(${c.id})">${escapeHtml(c.college_name)}</td>
                <td class="col-location">📍 ${escapeHtml(c.state || 'India')}</td>
                <td><span class="brand-tag">${escapeHtml(c.stream || 'General')}</span></td>
                <td class="col-rating">⭐ ${c.rating || 'N/A'}</td>
                <td class="col-placement">📈 ${c.placement ? c.placement + '/10' : 'N/A'}</td>
                <td class="col-fee">${c.ug_fee ? '₹' + Number(c.ug_fee).toLocaleString() : 'N/A'}</td>
                <td style="text-align:right;">
                  <button class="btn-table" onclick="openCollegeModalById(${c.id})">Details</button>
                  <button class="btn-table primary" onclick="sendPresetQuery('Give me detailed admission info and placement report for ${escapeJsText(c.college_name)}')">Ask AI</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  } else {
    DOM.matrixResultsGrid.innerHTML = state.directoryColleges.map(c => `
      <div class="college-item-card">
        <div>
          <div class="college-item-head">
            <div class="college-item-name" onclick="openCollegeModalById(${c.id})">${escapeHtml(c.college_name)}</div>
            <div class="rating-badge">⭐ ${c.rating || 'N/A'}</div>
          </div>
          
          <div class="college-item-meta">
            <div class="meta-tag-box">
              <div class="meta-tag-lbl">State / Region</div>
              <div class="meta-tag-val">📍 ${escapeHtml(c.state || 'India')}</div>
            </div>
            <div class="meta-tag-box">
              <div class="meta-tag-lbl">Stream</div>
              <div class="meta-tag-val">🎓 ${escapeHtml(c.stream || 'General')}</div>
            </div>
            <div class="meta-tag-box">
              <div class="meta-tag-lbl">Annual UG Tuition</div>
              <div class="meta-tag-val fee-val">
                ${c.ug_fee ? '₹ ' + Number(c.ug_fee).toLocaleString() + ' / yr' : 'Undisclosed'}
              </div>
            </div>
            <div class="meta-tag-box">
              <div class="meta-tag-lbl">Placement Score</div>
              <div class="meta-tag-val placement-val">
                📈 ${c.placement ? c.placement + ' / 10' : 'N/A'}
              </div>
            </div>
          </div>
        </div>

        <div class="college-item-foot">
          <button class="btn-sm" onclick="openCollegeModalById(${c.id})">
            🔍 View Profile
          </button>
          <button class="btn-primary" style="padding:7px 12px; font-size:12px;" onclick="sendPresetQuery('Provide an exhaustive admissions and placement breakdown for ${escapeJsText(c.college_name)}')">
            💬 Consult AI
          </button>
        </div>
      </div>
    `).join('');
  }
}

// ── 8. COLLEGE MODAL ────────────────────────────────────────────────────────
function openCollegeModalById(id) {
  const c = state.directoryColleges.find(col => col.id === id);
  if (!c) return;
  openCollegeModal(c);
}

function openCollegeModal(c) {
  state.selectedCollegeForModal = c;
  if (!DOM.collegeModal || !DOM.modalBody) return;

  const ugFeeFormatted = c.ug_fee ? `₹ ${Number(c.ug_fee).toLocaleString()} / year` : 'Not Disclosed';
  const fourYearEst = c.ug_fee ? `₹ ${(Number(c.ug_fee) * 4).toLocaleString()}` : 'N/A';

  DOM.modalBody.innerHTML = `
    <div>
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">
        <div>
          <span class="brand-tag">${escapeHtml(c.stream || 'Academic Degree')}</span>
          <h2 style="font-size:22px; font-weight:800; color:var(--text-main); margin-top:8px;">${escapeHtml(c.college_name)}</h2>
          <p style="font-size:13px; color:var(--text-sub); margin-top:4px;">📍 State: <strong>${escapeHtml(c.state || 'India')}</strong></p>
        </div>
        <div class="rating-badge" style="font-size:15px; padding:6px 14px;">
          ⭐ ${c.rating || 'N/A'} / 10
        </div>
      </div>

      <!-- 6 Key Radar Metrics Breakdown -->
      <div style="margin-top:22px; background:var(--bg-surface-subtle); padding:20px; border-radius:var(--radius-lg); border:1px solid var(--border-subtle);">
        <h4 style="font-size:12px; font-weight:800; text-transform:uppercase; color:var(--text-muted); margin-bottom:14px; letter-spacing:0.05em;">
          Institutional Performance Index (out of 10)
        </h4>
        
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
          <div>
            <div class="metric-row">
              <span class="metric-name">📈 Career Placement & Package</span>
              <span class="metric-val">${c.placement || 'N/A'}</span>
            </div>
            <div class="score-bar-track"><div class="score-bar-fill emerald" style="width:${(c.placement || 5)*10}%;"></div></div>
          </div>

          <div>
            <div class="metric-row">
              <span class="metric-name">📚 Academic Rigor</span>
              <span class="metric-val">${c.academic || 'N/A'}</span>
            </div>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${(c.academic || 5)*10}%;"></div></div>
          </div>

          <div>
            <div class="metric-row">
              <span class="metric-name">🏢 Campus Infrastructure</span>
              <span class="metric-val">${c.infrastructure || 'N/A'}</span>
            </div>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${(c.infrastructure || 5)*10}%;"></div></div>
          </div>

          <div>
            <div class="metric-row">
              <span class="metric-name">👨‍🏫 Faculty Quality</span>
              <span class="metric-val">${c.faculty || 'N/A'}</span>
            </div>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${(c.faculty || 5)*10}%;"></div></div>
          </div>

          <div>
            <div class="metric-row">
              <span class="metric-name">🏠 Hostel Facilities</span>
              <span class="metric-val">${c.accommodation || 'N/A'}</span>
            </div>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${(c.accommodation || 5)*10}%;"></div></div>
          </div>

          <div>
            <div class="metric-row">
              <span class="metric-name">🎉 Campus Social Life</span>
              <span class="metric-val">${c.social_life || 'N/A'}</span>
            </div>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${(c.social_life || 5)*10}%;"></div></div>
          </div>
        </div>
      </div>

      <!-- Financials -->
      <div style="margin-top:16px; display:grid; grid-template-columns:1fr 1fr; gap:14px;">
        <div class="meta-tag-box" style="padding:14px;">
          <div class="meta-tag-lbl">Annual UG Tuition Fee</div>
          <div class="meta-tag-val fee-val" style="font-size:16px;">${ugFeeFormatted}</div>
        </div>
        <div class="meta-tag-box" style="padding:14px;">
          <div class="meta-tag-lbl">Estimated 4-Year Total</div>
          <div class="meta-tag-val" style="font-size:16px; color:var(--primary); font-family:'JetBrains Mono';">${fourYearEst}</div>
        </div>
      </div>

      <!-- Actions -->
      <div style="margin-top:22px;">
        <button class="btn-primary" style="width:100%; padding:12px;" onclick="closeModal(); sendPresetQuery('Evaluate admission probability and placement statistics for ${escapeJsText(c.college_name)}')">
          💬 Consult AI Counselor About ${escapeJsText(c.college_name)}
        </button>
      </div>
    </div>
  `;

  DOM.collegeModal.classList.add('open');
}

function closeModal() {
  if (DOM.collegeModal) DOM.collegeModal.classList.remove('open');
}

// Close modal on backdrop click or ESC
window.addEventListener('click', (e) => {
  if (e.target === DOM.collegeModal) closeModal();
});

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
});

// ── 9. UTILITIES ────────────────────────────────────────────────────────────
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeJsText(str) {
  if (!str) return '';
  return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ── 10. BOOTSTRAP ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  initChat();
  initDirectory();
});
