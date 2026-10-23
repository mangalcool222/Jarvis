let currentTab = 'today';
let companyDrill = false;      // true while viewing a single company's contacts
let _companies = [], _prospects = [], _campaigns = [];
let _signals = null;           // last /api/signals payload, for the cohort builder
let _desk = { items: [], i: 0 };
let _workspaceInfo = null;

async function loadWorkspaceInfo() {
  try {
    const info = await api('/api/workspace/info');
    if (info) {
      _workspaceInfo = info;
      const headerLink = document.getElementById('header-sheet-link');
      const crmLink = document.getElementById('crm-sheet-link');
      const wsTagline = document.getElementById('workspace-tagline');
      const isColdEmail = (info.workspace === 'cold_email_outreach');

      if (wsTagline) {
        wsTagline.textContent = isColdEmail
          ? 'Autonomous Outbound SDR • B2B SaaS & Dev Agencies'
          : 'Autonomous Outbound Intelligence • TrackKaro AI';
      }

      const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
      document.title = isLocal
        ? (isColdEmail ? '[Cold Outreach :5556] Jarvis AI SDR' : '[TrackKaro :5555] Jarvis AI SDR')
        : 'Jarvis AI SDR — Autonomous B2B Prospecting Engine | TrackKaro AI';

      if (info.has_sheet && info.sheet_url) {
        if (headerLink) {
          headerLink.href = info.sheet_url;
          headerLink.style.display = 'inline-flex';
        }
        if (crmLink) {
          crmLink.href = info.sheet_url;
          crmLink.style.display = 'inline-flex';
        }
      } else {
        if (headerLink) headerLink.style.display = 'none';
        if (crmLink) crmLink.style.display = 'none';
      }
    }
  } catch (e) {
    console.warn('loadWorkspaceInfo error:', e);
  }
}
loadWorkspaceInfo();


// ── Appearance ──
//
// Three states, not two: "auto" follows the OS and is the default, so the
// dashboard matches the rest of your machine until you deliberately override
// it. Stored per-browser; nothing is sent anywhere.

const THEMES = ['auto', 'light', 'dark'];

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === 'auto') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', mode);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = mode;
}

function cycleTheme() {
  const now = localStorage.getItem('harvey-theme') || 'auto';
  const next = THEMES[(THEMES.indexOf(now) + 1) % THEMES.length];
  try { localStorage.setItem('harvey-theme', next); } catch { /* private mode */ }
  applyTheme(next);
}

(function initTheme() {
  let saved = 'auto';
  try { saved = localStorage.getItem('harvey-theme') || 'auto'; } catch { /* ignore */ }
  applyTheme(THEMES.includes(saved) ? saved : 'auto');
})();

// ── Utilities ──

function escHtml(s) {
  if (s === null || s === undefined || s === '') return '';
  return String(s).replace(/[&<>"']/g, ch => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]
  ));
}

// ── One status vocabulary ──
//
// Harvey's tables each carry their own words for state: a prospect is `new`,
// a campaign is `draft`, an email is `pending_review`, a signal is `proposed`.
// Five of those mean "waiting on you" and the old dashboard styled every one
// differently. Everything now resolves through this map, so a status reads the
// same way no matter which table it came out of.
//
// tone: waiting (needs a human) | active (in flight) | good | bad | idle
const STATUS = {
  // prospects
  new:            ['New', 'active'],
  contacted:      ['Contacted', 'active'],
  replied:        ['Replied', 'good'],
  interested:     ['Interested', 'good'],
  meeting:        ['Meeting booked', 'note'],
  not_interested: ['Not interested', 'bad'],
  bounced:        ['Bounced', 'bad'],
  // campaigns
  draft:          ['Draft', 'waiting'],
  active:         ['Active', 'good'],
  completed:      ['Completed', 'idle'],
  paused:         ['Paused', 'bad'],
  // conversations
  open:           ['Open', 'active'],
  closed:         ['Closed', 'idle'],
  closed_won:     ['Won', 'good'],
  closed_lost:    ['Lost', 'bad'],
  objection:      ['Objection', 'waiting'],
  // outbox
  pending_review: ['Waiting on you', 'waiting'],
  approved:       ['Approved', 'good'],
  scheduled:      ['Scheduled', 'active'],
  sent:           ['Sent', 'good'],
  failed:         ['Failed', 'bad'],
  rejected:       ['Rejected', 'idle'],
  cancelled:      ['Cancelled', 'idle'],
  // signals
  proposed:       ['Waiting on you', 'waiting'],
  confirmed:      ['Confirmed', 'good'],
  // email deliverability
  verified:       ['Verified', 'good'],
  risky:          ['Catch-all', 'waiting'],
  guess:          ['Unverified', 'idle'],
  invalid:        ['Invalid', 'bad'],
  // runs
  running:        ['Running', 'active'],
  stale:          ['Stale', 'bad'],
};

function statusMeta(status) {
  const key = String(status || '').toLowerCase().replace(/[^a-z0-9]+/g, '_');
  const hit = STATUS[key];
  if (hit) return { label: hit[0], tone: hit[1] };
  const label = String(status || 'unknown').replace(/_/g, ' ');
  return { label: label.charAt(0).toUpperCase() + label.slice(1), tone: 'idle' };
}

function badge(status) {
  const m = statusMeta(status);
  return '<span class="badge t-' + m.tone + '">' + escHtml(m.label) + '</span>';
}

function formatDate(d) {
  if (!d) return '';
  try {
    const dt = new Date(d);
    if (isNaN(dt)) return escHtml(d);
    return dt.toLocaleString('en-US', {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
  } catch { return escHtml(d); }
}

function emptyState(glyph, title, copy) {
  return '<div class="empty"><div class="glyph">' + glyph + '</div>' +
    '<div class="title">' + title + '</div>' +
    '<div class="copy">' + copy + '</div></div>';
}

function offlineState() {
  return emptyState('&#9888;', 'Dashboard can\'t reach the server',
    'The dashboard process may have stopped. Restart it with <b>harvey dashboard</b> and refresh this page.');
}

async function api(path, opts) {
  try {
    const r = await fetch(path, opts);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

function showToast(msg, type) {
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

function toggleVisibility(inputId) {
  const el = document.getElementById(inputId);
  el.type = el.type === 'password' ? 'text' : 'password';
}

// ── Apple Segmented Dock & Bento Micro-physics ──

function updateDockSlider(activeBtn) {
  const slider = document.getElementById('dock-slider');
  if (!slider) return;
  if (!activeBtn) {
    activeBtn = document.querySelector('nav button.active') ||
      document.querySelector('nav button[onclick*="showTab(\'' + (currentTab || 'today') + '\'"]') ||
      document.querySelector('nav button');
  }
  if (!activeBtn) return;
  slider.style.opacity = '1';
  slider.style.width = activeBtn.offsetWidth + 'px';
  slider.style.transform = `translateX(${activeBtn.offsetLeft}px)`;
}

function initBentoSpotlight() {
  const cards = document.querySelectorAll('.bento-card, .seq-node, .ticker-card, .hey-senders-card');
  cards.forEach(card => {
    card.addEventListener('mousemove', e => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.setProperty('--mouse-x', `${x}px`);
      card.style.setProperty('--mouse-y', `${y}px`);
    });
  });
}

// ── Tabs ──

function showTab(id, btn) {
  currentTab = id;
  if (id === 'companies') companyDrill = false;
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  const sec = document.getElementById(id);
  if (sec) sec.classList.add('active');
  if (!btn) btn = document.querySelector('nav button[onclick*="\'' + id + '\'"]');
  if (btn) btn.classList.add('active');
  updateDockSlider(btn);
  try { history.replaceState(null, '', '#' + id); } catch(e) {}
  window.scrollTo({ top: 0, behavior: 'smooth' });
  loadCurrentTab();
}

window.addEventListener('DOMContentLoaded', () => {
  const hash = (location.hash || '').replace('#', '');
  if (hash && document.getElementById(hash)) {
    showTab(hash);
  } else {
    setTimeout(updateDockSlider, 60);
  }
  initBentoSpotlight();
});

window.addEventListener('load', () => {
  updateDockSlider();
});

window.addEventListener('resize', () => {
  updateDockSlider();
});

function loadCurrentTab() {
  switch (currentTab) {
    case 'today': loadToday(); loadSetupStatus(); loadRuns(); loadTodayActivity(); break;
    case 'signals': loadSignals(); break;
    case 'discover': loadDiscoverProviders(); break;
    case 'companies': if (!companyDrill) loadCompanies(); break;
    case 'prospects': loadProspects(); break;
    case 'campaigns': loadCampaigns(); break;
    case 'outbox': loadOutbox(); break;
    case 'crm-sheet': loadCrmSheet(); break;
    case 'conversations': loadConversations(); break;
    case 'activity': loadActivity(); break;
    case 'usage': loadUsage(); break;
    case 'settings': loadSettings(); break;
    case 'controls': loadHarveyStatus(); loadLogs(); break;
  }
}

// ── Today: what needs a human ──

async function loadToday() {
  const data = await api('/api/today');
  const el = document.getElementById('today-queue');
  if (!data) { el.innerHTML = offlineState(); return; }

  navCount('nav-today', (data.items || []).filter(i => i.tone !== 'good').length);
  navCount('nav-outbox', (data.stats || {}).outbox_pending || 0);
  renderFigures(data.stats || {});

  const items = data.items || [];
  if (!items.length) {
    el.innerHTML = '<div class="queue-clear">' +
      '<div class="glyph">&#10003;</div><div>' +
      '<div class="qtitle">Nothing needs you</div>' +
      '<div class="qdetail">Jarvis has everything it needs. Anything that requires a ' +
      'decision — an email to approve, a signal to confirm — shows up here.</div>' +
      '</div></div>';
    return;
  }

  el.innerHTML = '<div class="queue">' + items.map(it =>
    '<div class="queue-item ' + escHtml(it.tone || 'warn') + '">' +
      '<div class="qtext">' +
        '<div class="qtitle">' + escHtml(it.title) + '</div>' +
        '<div class="qdetail">' + escHtml(it.detail) + '</div>' +
      '</div>' +
      '<button class="btn btn-secondary btn-sm" onclick="goTab(\'' + escHtml(it.tab) + '\')">' +
        escHtml(it.action) + '</button>' +
    '</div>'
  ).join('') + '</div>';
}

function renderFigures(stats) {
  const el = document.getElementById('today-figures');
  if (!el) return;
  const row = (label, value) =>
    '<div class="figure"><span class="k">' + label + '</span>' +
    '<span class="v' + (value ? '' : ' zero') + '">' + value + '</span></div>';

  el.innerHTML = '<div class="figures">' +
    row('Companies', stats.companies || 0) +
    row('Contacts', stats.prospects || 0) +
    row('Signals on', stats.signals_confirmed || 0) +
    row('Not yet read', stats.unprofiled || 0) +
    row('Awaiting approval', stats.outbox_pending || 0) +
    row('Scheduled', stats.outbox_approved || 0) +
    row('Live conversations', stats.open_conversations || 0) +
  '</div>';
}

async function loadTodayActivity() {
  const el = document.getElementById('today-activity');
  if (!el) return;
  const data = await api('/api/activity');
  if (!Array.isArray(data) || !data.length) {
    el.innerHTML = '<p class="muted" style="font-size:12.5px">' +
      'Nothing yet. Every action Jarvis takes shows up here.</p>';
    return;
  }
  el.innerHTML = '<div class="activity-feed">' + data.slice(0, 12).map(a =>
    '<div class="activity-item">' +
      '<span class="time">' + formatDate(a.created_at) + '</span>' +
      '<span class="agent">' + escHtml(a.agent) + '</span>' +
      '<span class="action">' + escHtml(String(a.action_type).replace(/_/g, ' ')) + '</span>' +
    '</div>').join('') + '</div>';
}

function navCount(id, n) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = n > 0 ? n : '';
  el.className = 'nav-count' + (n > 0 ? ' on' : '');
}

// Jump to a tab from a link that isn't itself a nav button.
function goTab(id) {
  const btns = [...document.querySelectorAll('nav button')];
  const btn = btns.find(b => (b.getAttribute('onclick') || '').includes("'" + id + "'"));
  showTab(id, btn);
}

async function loadRuns() {
  const el = document.getElementById('today-runs');
  const block = document.getElementById('today-runs-block');
  if (!el) return;
  const runs = await api('/api/runs');
  if (!Array.isArray(runs) || !runs.length) {
    if (block) block.style.display = 'none';
    el.innerHTML = '';
    return;
  }
  if (block) block.style.display = '';

  // A rail is 300px wide — a seven-column table does not belong here.
  el.innerHTML = '<div class="figures">' + runs.slice(0, 6).map(r =>
    '<div class="figure" style="align-items:flex-start">' +
      '<span class="k">' + escHtml(r.stage) +
        '<br><span class="muted" style="font-size:11px">' +
        formatDate(r.started_at) + '</span></span>' +
      '<span style="text-align:right;flex:none">' + badge(r.status) +
        '<br><span class="muted" style="font-family:var(--mono);font-size:11px">' +
        (r.records || 0) + ' rec &middot; ' +
        (r.cost_usd ? '$' + Number(r.cost_usd).toFixed(4) : 'free') + '</span></span>' +
    '</div>').join('') + '</div>';
}

// ── Setup checklist (lives on Today, and disappears once it's done) ──

async function loadSetupStatus() {
  const el = document.getElementById('today-setup');
  if (!el) return;
  const data = await api('/api/setup-status');
  if (!data || !data.checks) { el.innerHTML = ''; return; }

  const pct = data.percent || 0;
  // Finished setup disappears completely rather than greeting you forever.
  if (pct === 100) { el.innerHTML = ''; return; }

  const renderCheck = (c, optional) =>
    '<div class="check-item">' +
      (c.done ? '<span class="check-icon done">&#10003;</span>'
              : '<span class="check-icon pending"></span>') +
      '<div class="check-info">' +
        '<div class="check-label ' + (c.done ? 'done' : '') + '">' + escHtml(c.label) +
          (optional ? '<span class="optional-tag">optional</span>' : '') + '</div>' +
        (!c.done ? '<div class="check-help">' + escHtml(c.help) + '</div>' : '') +
      '</div></div>';

  const required = data.checks.filter(c => c.required);
  const optional = data.checks.filter(c => !c.required);

  el.innerHTML =
    '<div class="rail-block">' +
      '<div class="subhead">Setup &mdash; ' + pct + '%</div>' +
      '<div class="progress-bar" style="margin-bottom:14px">' +
        '<div class="progress-fill yellow" style="width:' + pct + '%"></div></div>' +
      required.map(c => renderCheck(c, false)).join('') +
      (optional.length
        ? '<details style="margin-top:10px"><summary class="muted" ' +
          'style="font-size:12px">' + optional.length + ' optional</summary>' +
          '<div style="margin-top:6px">' +
          optional.map(c => renderCheck(c, true)).join('') + '</div></details>'
        : '') +
    '</div>';
}

// ── Signals: Harvey proposes, you confirm ──

async function loadSignals() {
  const data = await api('/api/signals');
  const sumEl = document.getElementById('signals-summary');
  const grpEl = document.getElementById('signals-groups');
  if (!data || data.error) { grpEl.innerHTML = offlineState(); sumEl.innerHTML = ''; return; }
  _signals = data;

  const s = data.summary || {};
  navCount('nav-signals', s.proposed || 0);
  sumEl.innerHTML = '<div class="sig-summary">' +
    ['confirmed', 'proposed', 'rejected'].map(k =>
      '<div class="sig-stat ' + k + '"><div class="n">' + (s[k] || 0) + '</div>' +
      '<div class="k">' + (k === 'proposed' ? 'awaiting you' : k) + '</div></div>'
    ).join('') +
    '</div>';

  grpEl.innerHTML = (data.groups || []).map(g => {
    const codes = g.signals.map(x => x.code);
    const undecided = g.signals.filter(x => x.status === 'proposed').length;
    return '<div class="sig-group">' +
      '<div class="sig-group-head"><div>' +
        '<h3>' + escHtml(g.label) + '</h3><p>' + escHtml(g.blurb) + '</p>' +
      '</div>' +
      (undecided
        ? '<div style="display:flex;gap:6px;flex-shrink:0">' +
            '<button class="btn btn-primary btn-sm" onclick=\'setSignals(' +
              JSON.stringify(codes) + ", \"confirmed\")'>Confirm all " + undecided + '</button>' +
            '<button class="btn btn-secondary btn-sm" onclick=\'setSignals(' +
              JSON.stringify(codes) + ", \"rejected\")'>Skip all</button>" +
          '</div>'
        : '') +
      '</div>' +
      '<div class="card" style="padding:4px 0">' + g.signals.map(sigRow).join('') + '</div>' +
    '</div>';
  }).join('');

  renderCohortBuilder();
}

function sigRow(sig) {
  const free = /free|included/i.test(sig.cost_note || '');
  const costCls = free ? 'free' : (/\$/.test(sig.cost_note || '') ? 'paid' : '');
  const seen = sig.companies
    ? '<span class="cost-chip">seen on ' + sig.companies +
      (sig.companies === 1 ? ' company' : ' companies') + ' so far</span>' : '';
  const floor = sig.confidence_floor > 0
    ? '<span class="cost-chip">only recorded above ' +
      Math.round(sig.confidence_floor * 100) + '% confidence</span>' : '';

  const decide = sig.status === 'confirmed'
    ? '<button class="btn btn-secondary btn-sm" onclick="setSignals([\'' + sig.code +
        '\'],\'rejected\')">Turn off</button>'
    : sig.status === 'rejected'
      ? '<button class="btn btn-secondary btn-sm" onclick="setSignals([\'' + sig.code +
          '\'],\'confirmed\')">Turn on</button>'
      : '<button class="btn btn-primary btn-sm" onclick="setSignals([\'' + sig.code +
          '\'],\'confirmed\')">Confirm</button>' +
        '<button class="btn btn-secondary btn-sm" onclick="setSignals([\'' + sig.code +
          '\'],\'rejected\')">Skip</button>';

  return '<div class="sig-row ' + (sig.status === 'rejected' ? 'rejected' : '') + '">' +
    '<div class="sig-main">' +
      '<div class="sig-label">' + escHtml(sig.label || sig.code) +
        '<span class="sig-code">' + escHtml(sig.code) + '</span></div>' +
      '<div class="sig-desc">' + escHtml(sig.description) + '</div>' +
      '<div class="sig-meta">' +
        '<span class="cost-chip ' + costCls + '">' + escHtml(sig.cost_note || 'cost unknown') + '</span>' +
        floor + seen + badge(sig.status) +
      '</div>' +
    '</div>' +
    '<div class="sig-decide">' + decide + '</div>' +
  '</div>';
}

async function setSignals(codes, status) {
  const data = await api('/api/signals/status', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({codes: codes, status: status}),
  });
  if (data && data.success) {
    showToast(
      status === 'confirmed'
        ? 'Confirmed ' + data.changed + ' signal' + (data.changed === 1 ? '' : 's') +
          ' — Jarvis will collect ' + (data.changed === 1 ? 'it' : 'them') + ' from now on.'
        : data.changed + ' signal' + (data.changed === 1 ? '' : 's') + ' turned off.',
      'success');
  } else {
    showToast('Could not update that signal.', 'error');
  }
  loadSignals();
}

// ── Discover: pick a source, price it, then run it ──

let _provider = null;
let _discoverPoll = null;

async function loadDiscoverProviders() {
  const el = document.getElementById('discover-providers');
  const data = await api('/api/discover/providers');
  if (!data || !data.providers) { el.innerHTML = offlineState(); return; }

  _provider = _provider || data.selected || data.default;
  el.innerHTML = '<div class="prov-grid">' + data.providers.map(p => {
    const ready = p.configured
      ? '<span class="badge t-good">ready</span>'
      : '<span class="badge t-waiting">needs a key</span>';
    return '<div class="prov-card ' + (p.key === _provider ? 'selected' : '') +
      '" onclick="pickProvider(\'' + p.key + '\')">' +
      '<div class="prov-head"><h3>' + escHtml(p.label) + '</h3>' + ready + '</div>' +
      '<div class="blurb">' + escHtml(p.blurb) + '</div>' +
      '<div class="row"><span class="k">Cost</span><span class="v">' +
        escHtml(p.cost_note) + '</span></div>' +
      '<div class="row"><span class="k">Free</span><span class="v">' +
        escHtml(p.free_tier) + '</span></div>' +
      (p.needs_key
        ? '<div class="row"><span class="k">Setup</span><span class="v">' +
          escHtml(p.env_keys.join(', ')) + ' in .env &middot; ' +
          '<a href="' + escHtml(p.signup_url) + '" target="_blank" rel="noopener">get a key</a>' +
          '</span></div>'
        : '') +
      (p.caveat ? '<div class="caveat">' + escHtml(p.caveat) + '</div>' : '') +
    '</div>';
  }).join('') + '</div>';

  const running = data.running;
  document.getElementById('disc-stop').style.display = running ? '' : 'none';
  if (running && !_discoverPoll) {
    _discoverPoll = setInterval(loadDiscoverProviders, 4000);
  } else if (!running && _discoverPoll) {
    clearInterval(_discoverPoll);
    _discoverPoll = null;
    // A finished run leaves the button stuck on "Running…" otherwise.
    const btn = document.getElementById('disc-run');
    btn.disabled = true;
    btn.textContent = 'Estimate first';
    showToast('Discovery finished.', 'success');
  }
  renderDiscoverResult(data.last_report, running);
}

function pickProvider(key) {
  _provider = key;
  document.getElementById('disc-run').disabled = true;
  document.getElementById('disc-run').textContent = 'Estimate first';
  document.getElementById('discover-estimate').innerHTML = '';
  loadDiscoverProviders();
}

function discoverBody() {
  const raw = document.getElementById('disc-cities').value.trim();
  return {
    provider: _provider,
    // Semicolons, commas, or newlines
    cities: raw ? raw.split(/[;,\n]/).map(c => c.trim()).filter(Boolean) : [],
    depth: Number(document.getElementById('disc-depth').value) || 30,
    limit: Number(document.getElementById('disc-limit').value) || 100,
    max_spend: Number(document.getElementById('disc-cap').value) || 1,
  };
}

async function estimateDiscovery() {
  const el = document.getElementById('discover-estimate');
  el.innerHTML = '<p class="muted" style="font-size:13px">Pricing it…</p>';
  const data = await api('/api/discover/estimate', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(discoverBody()),
  });
  if (!data || data.error) {
    el.innerHTML = '<div class="test-result error">' +
      escHtml((data && data.error) || 'Could not estimate.') + '</div>';
    return;
  }

  const cap = discoverBody().max_spend;
  const over = data.estimated_cost > cap;
  el.innerHTML = '<div class="estimate-box">' +
    '<div class="amount ' + (data.free ? 'free' : 'paid') + '">' +
      (data.free ? 'Free' : '$' + data.estimated_cost.toFixed(4)) + '</div>' +
    '<div class="muted" style="font-size:13px;margin-top:2px">' +
      data.query_count + ' quer' + (data.query_count === 1 ? 'y' : 'ies') +
      (data.free ? '' : ' &middot; cap is $' + cap.toFixed(2)) + '</div>' +
    (over ? '<div class="test-result error" style="margin-top:12px">' +
      'Over your cap. Raise the cap or narrow the search.</div>' : '') +
    '<div class="query-list">' +
      data.queries.slice(0, 40).map(escHtml).join('<br>') +
      (data.queries.length > 40 ? '<br>… and ' + (data.queries.length - 40) + ' more' : '') +
    '</div></div>';

  const btn = document.getElementById('disc-run');
  btn.disabled = over;
  btn.textContent = over ? 'Over cap'
    : (data.free ? 'Run — free' : 'Run — spend up to $' + data.estimated_cost.toFixed(2));
}

async function runDiscovery() {
  const btn = document.getElementById('disc-run');
  btn.disabled = true;
  btn.textContent = 'Running…';
  const data = await api('/api/discover/run', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(discoverBody()),
  });
  if (data && data.success) {
    showToast('Discovery started — ' + data.queries + ' queries.', 'success');
  } else {
    showToast((data && data.message) || 'Could not start.', 'error');
    btn.disabled = false;
  }
  loadDiscoverProviders();
}

async function stopDiscovery() {
  const data = await api('/api/discover/stop', {method: 'POST'});
  showToast(data && data.success ? 'Stopping after the current query.'
                                 : 'Could not stop.', data ? 'success' : 'error');
  loadDiscoverProviders();
}

function renderDiscoverResult(report, running) {
  const el = document.getElementById('discover-result');
  if (running) {
    el.innerHTML = '<div class="card"><h2>Running…</h2>' +
      '<p class="muted" style="font-size:13px">Jarvis is working through the ' +
      'queries. Results land in Companies, and the run log is on Today.</p></div>';
    return;
  }
  if (!report) { el.innerHTML = ''; return; }

  const stat = (label, value, tone) =>
    '<div class="stat-card"><div class="label">' + label + '</div>' +
    '<div class="value"' + (tone ? ' style="color:var(--' + tone + ')"' : '') + '>' +
    value + '</div></div>';

  el.innerHTML = '<div class="subhead">Last run</div>' +
    '<div class="stats-grid">' +
      stat('New companies', report.new_companies || 0, 'accent') +
      stat('Already known', report.known_companies || 0) +
      stat('Observations', report.observations || 0) +
      stat('Filtered as junk', report.junk || 0) +
      stat('Actual cost', report.actual_cost ? '$' + report.actual_cost.toFixed(4) : 'free') +
    '</div>' +
    (report.stopped ? '<div class="test-result error" style="margin-top:14px">' +
      'Stopped early: ' + escHtml(report.stopped) + '</div>' : '') +
    ((report.errors || []).length
      ? '<div class="card" style="margin-top:14px"><h2>Problems</h2>' +
        (report.errors || []).slice(0, 8).map(e =>
          '<div class="check-help">' + escHtml(e) + '</div>').join('') + '</div>'
      : '');
}

// ── Cohort builder: a prospect list is a query ──

let _cohort = { require: new Set(), exclude: new Set() };

function renderCohortBuilder() {
  const el = document.getElementById('cohort-builder');
  if (!el || !_signals) return;

  const confirmed = (_signals.groups || [])
    .flatMap(g => g.signals)
    .filter(s => s.status === 'confirmed');

  if (!confirmed.length) {
    el.innerHTML = '<p class="muted" style="font-size:13px">' +
      'Confirm some signals above and they become the building blocks here.</p>';
    document.getElementById('cohort-result').innerHTML = '';
    return;
  }

  const col = (title, key, hint) =>
    '<div><div class="subhead" style="margin-top:0">' + title +
      ' <span class="muted" style="font-weight:400;text-transform:none;letter-spacing:0">' +
      hint + '</span></div><div class="cohort-grid">' +
    confirmed.map(s =>
      '<label class="cohort-pick"><input type="checkbox" ' +
        (_cohort[key].has(s.code) ? 'checked ' : '') +
        'onchange="toggleCohort(\'' + key + '\',\'' + s.code + '\',this.checked)">' +
        '<span>' + escHtml(s.label || s.code) + '</span>' +
        '<span class="n">' + (s.companies || 0) + '</span></label>'
    ).join('') + '</div></div>';

  el.innerHTML = col('Must have', 'require', '&mdash; every company in the cohort carries all of these') +
    '<div style="height:18px"></div>' +
    col('Must not have', 'exclude', '&mdash; disqualifiers');
}

function toggleCohort(key, code, on) {
  if (on) _cohort[key].add(code); else _cohort[key].delete(code);
  // A company can't be both required and excluded on the same signal.
  const other = key === 'require' ? 'exclude' : 'require';
  if (on) _cohort[other].delete(code);
  runCohort();
  renderCohortBuilder();
}

async function runCohort() {
  const el = document.getElementById('cohort-result');
  if (!el) return;
  const require = [..._cohort.require], exclude = [..._cohort.exclude];
  if (!require.length) { el.innerHTML = ''; return; }

  const data = await api('/api/cohort', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({require: require, exclude: exclude}),
  });
  if (!data) { el.innerHTML = ''; return; }

  let html = '<div style="border-top:1px solid var(--border);margin-top:20px;padding-top:20px">' +
    '<div class="cohort-size">' + data.size + '</div>' +
    '<div class="muted" style="font-size:13px;margin-top:2px">compan' +
      (data.size === 1 ? 'y matches' : 'ies match') + ' this cohort right now</div>';

  if (data.companies && data.companies.length) {
    html += '<div class="table-card" style="margin-top:16px"><table><thead><tr>' +
      '<th>Company</th><th>Domain</th><th>Industry</th><th>Location</th>' +
      '</tr></thead><tbody>' +
      data.companies.slice(0, 50).map(c =>
        '<tr><td>' + escHtml(c.name) + '</td><td class="muted">' + escHtml(c.domain) + '</td>' +
        '<td class="muted">' + escHtml(c.industry) + '</td>' +
        '<td class="muted">' + escHtml(c.location) + '</td></tr>'
      ).join('') + '</tbody></table></div>';
    if (data.size > 50) {
      html += '<p class="muted" style="font-size:12px;margin-top:10px">Showing the first 50.</p>';
    }
  } else if (data.size === 0) {
    html += '<p class="muted" style="font-size:13px;margin-top:12px">' +
      'No company carries all of those yet. Either loosen the cohort, or run ' +
      'prospecting to collect more.</p>';
  }
  el.innerHTML = html + '</div>';
}

// ── Settings ──

async function loadSettings() {
  const data = await api('/api/settings');
  if (!data) return;

  // Active provider indicator
  const prov = data.provider || 'instantly';
  const provEl = document.getElementById('active-provider');
  if (provEl) provEl.textContent = prov;

  // Secret fields never echo a value — show a "saved" placeholder instead.
  const savedPh = (id, isSet, base) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.value = '';
    el.placeholder = isSet ? 'Saved — enter new value to change' : base;
  };
  const tag = (id, ok, okLabel) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = 'email-tag ' + (ok ? 'verified' : 'guess');
    el.textContent = ok ? okLabel : 'not set';
  };

  // Non-secret values repopulate
  document.getElementById('gmail-id').value = data.gmail_client_id || '';
  document.getElementById('smtp-host').value = data.smtp_host || '';
  document.getElementById('smtp-port').value = data.smtp_port || '';
  document.getElementById('smtp-user').value = data.smtp_username || '';
  document.getElementById('linkedin-email').value = data.linkedin_email || '';
  document.getElementById('cf-account-id').value = data.cloudflare_account_id || '';

  savedPh('gmail-secret', data.gmail_client_secret_set, 'Enter client secret');
  savedPh('smtp-pass', data.smtp_password_set, 'Enter password / app password');
  savedPh('instantly-key', data.instantly_api_key_set, 'Enter your Instantly API key');
  savedPh('reoon-key', data.reoon_api_key_set, '600 free/mo — reoon.com/email-verifier');
  savedPh('zerobounce-key', data.zerobounce_api_key_set, '100 free/mo — best for M365/Workspace catch-alls');
  savedPh('hunter-key', data.hunter_api_key_set, '50 free/mo + email-pattern lookup');
  savedPh('linkedin-password', data.linkedin_password_set, 'Enter password');
  savedPh('cf-api-token', data.cloudflare_api_token_set, 'Your Cloudflare API Token');

  // Gmail auth status chip
  const g = document.getElementById('gmail-status');
  if (g) {
    if (data.gmail_authorized) { g.className = 'email-tag verified'; g.textContent = 'authorized'; }
    else if (data.gmail_client_secret_set) { g.className = 'email-tag risky'; g.textContent = 'run: harvey gmail auth'; }
    else { g.className = 'email-tag guess'; g.textContent = 'not set up'; }
  }
  tag('reoon-status', data.reoon_api_key_set, 'set');
  tag('zerobounce-status', data.zerobounce_api_key_set, 'set');
  tag('hunter-status', data.hunter_api_key_set, 'set');
}

function saveGmail() {
  const payload = {GMAIL_CLIENT_ID: document.getElementById('gmail-id').value.trim()};
  const sec = document.getElementById('gmail-secret').value;
  if (sec) payload.GMAIL_CLIENT_SECRET = sec;
  saveEnv(payload, 'Gmail OAuth saved. Now run "harvey gmail auth" in your terminal.').then(loadSettings);
}

function saveSmtp() {
  const payload = {
    SMTP_HOST: document.getElementById('smtp-host').value.trim(),
    SMTP_PORT: document.getElementById('smtp-port').value.trim(),
    SMTP_USERNAME: document.getElementById('smtp-user').value.trim(),
  };
  const pass = document.getElementById('smtp-pass').value;
  if (pass) payload.SMTP_PASSWORD = pass;
  saveEnv(payload, 'SMTP settings saved.').then(loadSettings);
}

function saveVerifiers() {
  const payload = {};
  const r = document.getElementById('reoon-key').value;
  const z = document.getElementById('zerobounce-key').value;
  const h = document.getElementById('hunter-key').value;
  if (r) payload.REOON_API_KEY = r;
  if (z) payload.ZEROBOUNCE_API_KEY = z;
  if (h) payload.HUNTER_API_KEY = h;
  if (!Object.keys(payload).length) { showToast('Enter at least one key first.', 'error'); return; }
  saveEnv(payload, 'Verification keys saved.').then(loadSettings);
}

async function saveEnv(payload, okMsg) {
  const data = await api('/api/settings/env', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  if (data && data.success) showToast(okMsg, 'success');
  else showToast((data && data.message) || 'Save failed — is the dashboard still running?', 'error');
}

function saveInstantly() {
  saveEnv({INSTANTLY_API_KEY: document.getElementById('instantly-key').value.trim()}, 'Instantly API key saved.');
}

function saveLinkedIn() {
  const payload = {LINKEDIN_EMAIL: document.getElementById('linkedin-email').value.trim()};
  const pass = document.getElementById('linkedin-password').value;
  if (pass) payload.LINKEDIN_PASSWORD = pass;
  saveEnv(payload, 'LinkedIn credentials saved.');
}

function saveCloudflare() {
  saveEnv({
    CLOUDFLARE_ACCOUNT_ID: document.getElementById('cf-account-id').value.trim(),
    CLOUDFLARE_API_TOKEN: document.getElementById('cf-api-token').value.trim()
  }, 'Cloudflare credentials saved.');
}

async function testInstantly() {
  const key = document.getElementById('instantly-key').value.trim();
  const el = document.getElementById('instantly-test-result');
  el.innerHTML = '<div class="test-result pending">Testing&hellip;</div>';
  const data = await api('/api/settings/test-instantly', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({api_key: key})
  });
  if (!data) {
    el.innerHTML = '<div class="test-result error">Could not reach the dashboard server.</div>';
    return;
  }
  el.innerHTML = '<div class="test-result ' + (data.success ? 'success' : 'error') + '">' + escHtml(data.message) + '</div>';
}

// ── Controls ──

async function loadHarveyStatus() {
  const data = await api('/api/harvey/status');
  const headerDot = document.getElementById('header-dot');
  const headerText = document.getElementById('header-status-text');

  if (!data) {
    headerDot.className = 'status-dot offline';
    headerText.textContent = 'Offline';
    return;
  }
  const running = !!data.running;

  if (headerDot) headerDot.className = 'status-dot ' + (running ? 'running' : 'stopped');
  if (headerText) headerText.textContent = running ? 'Autonomous Loop' : 'Engine Ready';
  document.getElementById('control-dot').className = 'dot ' + (running ? 'running' : 'stopped');
  const label = document.getElementById('control-label');
  label.className = 'label ' + (running ? 'running' : 'stopped');
  label.textContent = running ? 'Running' : 'Stopped';

  const meta = document.getElementById('control-meta');
  if (running && data.pid) {
    let info = 'PID ' + escHtml(String(data.pid));
    if (data.started_at) info += ' &middot; started ' + formatDate(data.started_at);
    meta.innerHTML = info;
  } else {
    meta.innerHTML = 'Jarvis wakes every few minutes, does what needs doing, and sleeps.';
  }

  document.getElementById('btn-start').style.display = running ? 'none' : '';
  document.getElementById('btn-stop').style.display = running ? '' : 'none';
}

async function startHarvey() {
  const btn = document.getElementById('btn-start');
  btn.disabled = true;
  const data = await api('/api/harvey/start', {method: 'POST'});
  if (data && data.success) showToast('Jarvis started.', 'success');
  else showToast((data && data.message) || 'Failed to start.', 'error');
  btn.disabled = false;
  loadHarveyStatus();
}

async function stopHarvey() {
  const btn = document.getElementById('btn-stop');
  btn.disabled = true;
  const data = await api('/api/harvey/stop', {method: 'POST'});
  if (data && data.success) showToast('Jarvis stopped.', 'success');
  else showToast((data && data.message) || 'Failed to stop.', 'error');
  btn.disabled = false;
  loadHarveyStatus();
}

async function loadLogs() {
  const data = await api('/api/harvey/logs');
  const el = document.getElementById('log-viewer');
  if (data && data.lines && data.lines.length) {
    const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.textContent = data.lines.join('\n');
    if (stick) el.scrollTop = el.scrollHeight;
  } else {
    el.textContent = 'No logs yet. Start Jarvis to see activity.';
  }
}

// ── Pipeline data ──

async function loadStats() {
  const grid = document.getElementById('stats-grid');
  const data = await api('/api/stats');
  if (!data) { grid.innerHTML = offlineState(); return; }
  if (data.error) {
    grid.innerHTML = emptyState('&#9670;', 'No pipeline data yet',
      'Start Jarvis from the <b>Controls</b> tab and it will begin prospecting, writing, and sending on its own.');
    return;
  }
  const p = data.prospects || {}, c = data.campaigns || {}, v = data.conversations || {};
  const chips = (map) => {
    const entries = Object.entries(map || {});
    if (!entries.length) return '<span class="chip muted">none yet</span>';
    return entries.map(([k, n]) =>
      '<span class="chip">' + escHtml(k) + ' <b>' + escHtml(String(n)) + '</b></span>'
    ).join('');
  };
  const card = (label, value, breakdown) =>
    '<div class="stat-card"><div class="label">' + label + '</div>' +
    '<div class="value">' + value + '</div>' +
    '<div class="breakdown">' + breakdown + '</div></div>';

  grid.innerHTML =
    card('Prospects', p.total || 0, chips(p.by_status)) +
    card('Campaigns', c.total || 0, chips(c.by_status)) +
    card('Conversations', v.total || 0, chips(v.by_status)) +
    card('Actions Logged', data.actions_total || 0, brainCallChips(data));
}

// Calls today per subscription — each labelled with the provider it ran on.
function brainCallChips(data) {
  const chip = (label, n) => '<span class="chip">' + label + ' calls today <b>' + escHtml(String(n || 0)) + '</b></span>';
  const codex = data.codex_calls_today || 0;
  const st = data.brain_status || {};
  // A paused brain must not look healthy: say so, and why.
  const paused = st.status === 'paused'
    ? '<span class="chip" title="' + escHtml(st.reason || '') + '">' +
      escHtml(st.provider === 'codex' ? 'Codex' : 'Brain') + ' <b>paused</b>: ' +
      escHtml((st.reason || '').slice(0, 120)) + '</span>'
    : '';
  if (data.brain_provider === 'codex') {
    return paused + chip('Codex', codex) + (data.claude_calls_today ? chip('Claude', data.claude_calls_today) : '');
  }
  return paused + chip('Claude', data.claude_calls_today) + (codex ? chip('Codex', codex) : '');
}

function fmtTokens(n) {
  n = n || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}


function emailTag(p) {
  if (!p.email) return '';
  // Fall back to the legacy boolean for rows predating email_status.
  const status = p.email_status || (p.email_verified ? 'verified' : 'guess');
  if (!STATUS[status]) return '';
  const m = statusMeta(status);
  return ' <span class="badge t-' + m.tone + '" style="margin-left:6px">' + escHtml(m.label) + '</span>';
}

// Quota gauges for the ACTIVE provider only: Claude's are the numbers
// `/usage` shows in Claude Code; Codex's are the ChatGPT plan's limits.
// When they can't be read, say so rather than hiding the card.
function quotaCardHtml(data) {
  const provider = data && data.quota_provider;
  if (!provider) return '';
  const title = provider === 'codex' ? 'Codex (ChatGPT plan) Quota' : 'Claude Subscription Quota';
  let html = '<h2>' + escHtml(title) + '</h2>';
  if (!data.quota || !Object.keys(data.quota).length) {
    const why = provider === 'codex'
      ? "Quota unavailable: Jarvis couldn't read your ChatGPT plan's limits (check codex login, the Codex CLI version, and network)."
      : "Quota unavailable: Jarvis couldn't read your Claude subscription's limits (check claude login and network).";
    return html + '<p class="muted">' + escHtml(why) + ' Until it can, budgets count Jarvis\'s own calls.</p>';
  }
  const labels = {five_hour: '5-hour window', seven_day: 'Weekly', primary: 'Primary window',
                  secondary: 'Secondary window', limit_reached: 'Usage limit reached'};
  for (const [key, w] of Object.entries(data.quota)) {
    const pct = Math.min(100, Math.max(0, w.utilization || 0));
    const color = pct >= 80 ? 'yellow' : 'green';
    const resets = w.resets_at ? 'resets ' + formatDate(w.resets_at) : '';
    html += '<div class="progress-wrap">' +
      '<div class="progress-label">' +
        '<span class="text">' + escHtml(labels[key] || key) + (resets ? ' &middot; ' + escHtml(resets) : '') + '</span>' +
        '<span class="pct">' + pct.toFixed(0) + '%</span>' +
      '</div>' +
      '<div class="progress-bar"><div class="progress-fill ' + color + '" style="width:' + pct + '%"></div></div>' +
    '</div>';
  }
  return html;
}

async function loadUsage() {
  const data = await api('/api/usage');
  const statsEl = document.getElementById('usage-stats');
  if (!data) { statsEl.innerHTML = offlineState(); return; }

  const quotaEl = document.getElementById('usage-quota');
  const qHtml = quotaCardHtml(data);
  quotaEl.innerHTML = qHtml;
  quotaEl.style.display = qHtml ? 'block' : 'none';

  // Totals cards — usage-first (calls is the headline; tokens as chips).
  // No dollars: on a subscription plan usage isn't billed per token.
  const t = data.totals || {};
  const card = (label, p) => {
    p = p || {};
    return '<div class="stat-card"><div class="label">' + label + '</div>' +
      '<div class="value">' + (p.calls || 0) + '</div>' +
      '<div class="breakdown">' +
        '<span class="chip">calls</span>' +
        '<span class="chip">out <b>' + fmtTokens(p.output_tokens) + '</b></span>' +
        '<span class="chip">in <b>' + fmtTokens(p.input_tokens) + '</b></span>' +
        '<span class="chip">cached <b>' + fmtTokens(p.cache_read_tokens) + '</b></span>' +
      '</div></div>';
  };
  statsEl.innerHTML = card('Today', t.today) + card('Last 7 Days', t.week) + card('Last 30 Days', t.month);

  // Daily bars — output tokens per day (the work done)
  const dailyEl = document.getElementById('usage-daily');
  const days = data.by_day || [];
  if (days.length) {
    const maxOut = Math.max(...days.map(d => d.output_tokens || 0), 1);
    let dHtml = '<h2>Daily Output Tokens (30 days)</h2>';
    for (const d of days.slice(-30)) {
      const pct = Math.max(2, (d.output_tokens || 0) / maxOut * 100);
      dHtml += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:12px">' +
        '<span class="muted" style="width:78px;flex-shrink:0;font-family:var(--mono)">' + escHtml(d.day || '') + '</span>' +
        '<div style="flex:1;background:rgba(255,255,255,0.05);border-radius:99px;height:10px;overflow:hidden">' +
          '<div style="width:' + pct + '%;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent-deep),var(--accent))"></div>' +
        '</div>' +
        '<span style="width:130px;text-align:right;font-variant-numeric:tabular-nums">' + fmtTokens(d.output_tokens) + ' out' +
          ' <span class="muted">&middot; ' + (d.calls || 0) + ' calls</span></span>' +
      '</div>';
    }
    dailyEl.innerHTML = dHtml;
    dailyEl.style.display = 'block';
  } else {
    dailyEl.style.display = 'none';
  }

  // Breakdown tables — calls + tokens, no cost column
  const tablesEl = document.getElementById('usage-tables');
  const table = (title, rows, keyName) => {
    if (!rows || !rows.length) return '';
    let h = '<div class="card"><h2>' + title + '</h2><div class="table-card"><table><thead><tr>' +
      '<th>' + keyName + '</th><th>Calls</th><th>Input</th><th>Output</th><th>Cache read</th>' +
      '</tr></thead><tbody>';
    for (const r of rows) {
      h += '<tr><td>' + escHtml(String(r[keyName.toLowerCase()] || '')) + '</td>' +
        '<td>' + (r.calls || 0) + '</td>' +
        '<td class="muted">' + fmtTokens(r.input_tokens) + '</td>' +
        '<td>' + fmtTokens(r.output_tokens) + '</td>' +
        '<td class="muted">' + fmtTokens(r.cache_read_tokens) + '</td></tr>';
    }
    return h + '</tbody></table></div></div>';
  };

  const anyRows = (data.by_agent || []).length || (data.by_task || []).length;
  if (!anyRows) {
    tablesEl.innerHTML = emptyState('&#9680;', 'No usage recorded yet',
      'Once Jarvis starts making model calls (Claude or Codex), every one is logged here with exact calls and tokens by provider, agent and task.');
  } else {
    const providers = data.by_provider || [];
    const showProviders = providers.length > 1 || (providers.length === 1 && providers[0].provider !== 'claude');
    tablesEl.innerHTML =
      (showProviders ? table('By Provider (30 days)', providers, 'Provider') : '') +
      table('By Agent (30 days)', data.by_agent, 'Agent') +
      table('By Task (30 days)', data.by_task, 'Task') +
      table('By Model (30 days)', data.by_model, 'Model');
  }
}

// ── Outbox: a decisions desk, not a wall of drafts ──
//
// Approving mail is a queue of one-at-a-time judgements. Showing all of them
// stacked invites a single "approve all" reflex, which is exactly the review
// the approval ladder exists to prevent. One email fills the pane; the rest
// wait in the rail.

async function syncCrmSheets() {
  const btn = document.getElementById('sync-sheets-btn');
  const origText = btn ? btn.innerText : '';
  if (btn) btn.innerText = 'Syncing CRM...';
  try {
    const res = await api('/api/sync/sheets', { method: 'POST' });
    if (res && res.success) {
      showToast('✅ ' + (res.message || 'CRM Synced!'), 'success');
    } else {
      showToast('⚠️ Sync error: ' + (res?.message || 'failed'), 'error');
    }
  } catch(e) {
    showToast('Failed to trigger CRM sync', 'error');
  } finally {
    if (btn) btn.innerText = origText || '🔄 Sync to Google Sheet';
  }
}

async function archiveCatchAlls() {
  if (!confirm('Move all Catch-All drafts to LinkedIn Backlog and remove from email queue?')) return;
  const btn = document.getElementById('archive-catchalls-btn');
  const origText = btn ? btn.innerText : '';
  if (btn) btn.innerText = 'Archiving...';
  try {
    const res = await api('/api/outbox/archive-catch-alls', { method: 'POST' });
    if (res && res.success) {
      showToast('📦 ' + (res.message || 'Archived catch-all drafts!'), 'success');
      loadOutbox();
    } else {
      showToast('Failed to archive', 'error');
    }
  } catch(e) {
    showToast('Archive error: ' + e, 'error');
  } finally {
    if (btn) btn.innerText = origText;
  }
}

async function loadOutbox() {
  const data = await api('/api/outbox');
  const banner = document.getElementById('outbox-banner');
  const desk = document.getElementById('outbox-desk');
  const list = document.getElementById('outbox-list');
  const actions = document.getElementById('outbox-actions');
  if (!data) { desk.innerHTML = offlineState(); list.innerHTML = ''; return; }

  const pending = data.pending || [];
  _desk.items = pending;
  if (_desk.i >= pending.length) _desk.i = Math.max(0, pending.length - 1);
  navCount('nav-outbox', pending.length);

  const approved = data.approved || [];
  const archived = data.archived || [];
  const catchAllCount = pending.filter(it => it.email_status !== 'verified').length;
  const safeCount = pending.filter(it => it.email_status === 'verified').length;

  const sheetControls = (_workspaceInfo && _workspaceInfo.has_sheet && _workspaceInfo.sheet_url)
    ? '<a href="' + _workspaceInfo.sheet_url + '" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" style="display:inline-flex;align-items:center;gap:6px;border-color:rgba(34,197,94,0.4);color:#22c55e;background:rgba(34,197,94,0.08);text-decoration:none;font-weight:600;"><span style="font-size:13px;">📊</span> Google Sheet CRM ↗</a>' +
      '<button id="sync-sheets-btn" class="btn btn-secondary btn-sm" onclick="syncCrmSheets()" title="Trigger live Google Sheet sync">🔄 Sync to Google Sheet</button>'
    : '';

  actions.innerHTML =
    sheetControls +
    (catchAllCount > 0
      ? '<button id="archive-catchalls-btn" class="btn btn-secondary btn-sm" onclick="archiveCatchAlls()" style="color:#f59e0b;border-color:rgba(245,158,11,0.4);background:rgba(245,158,11,0.08);font-weight:600;" title="Archive all risky catch-all drafts to LinkedIn Backlog">📦 Archive Catch-Alls (' + catchAllCount + ')</button>' : '') +
    (archived.length
      ? '<button class="btn btn-secondary btn-sm" onclick="document.getElementById(\'archived-catchalls-card\')?.scrollIntoView({behavior:\'smooth\'})" style="color:#f59e0b;border-color:rgba(245,158,11,0.4);background:rgba(245,158,11,0.08);font-weight:600;">' +
        '📦 Archived (' + archived.length + ')</button>' : '') +
    (approved.length
      ? '<button class="btn btn-secondary btn-sm" onclick="document.getElementById(\'outbox-list\').scrollIntoView({behavior:\'smooth\'})">' +
        '📅 Scheduled (' + approved.length + ')</button>' : '') +
    (pending.length && !data.paused
      ? '<button class="btn btn-primary btn-sm" onclick="outboxApproveAll()">' +
        (safeCount > 0 && catchAllCount > 0 ? 'Approve Safe (' + safeCount + ')' : 'Approve all ' + pending.length) +
        '</button>' : '') +
    (data.paused
      ? '<button class="btn btn-secondary btn-sm" onclick="sendingToggle(\'resume\')">' +
        'Resume sending</button>'
      : '<button class="btn btn-secondary btn-sm" onclick="sendingToggle(\'pause\')">' +
        'Pause all sending</button>');

  // The kill switch gets a banner only when it's actually on — a permanent
  // bar for a thing that isn't happening is just noise.
  banner.innerHTML = data.paused
    ? '<div class="card" style="border-color:var(--red);margin-bottom:16px">' +
        '<h2 style="color:var(--red)">&#9888; Sending is paused</h2>' +
        '<p style="color:var(--text-2);font-size:13px">' + escHtml(data.paused) +
        '. Approved mail stays queued until you resume.</p></div>'
    : '';

  desk.innerHTML = pending.length ? renderDesk(pending, _desk.i) :
    '<div class="card">' + emptyState('&#10003;', 'Nothing to review',
      'Every draft Jarvis writes lands here first. Approve one and it sends on schedule.') +
    '</div>';

  const table = (title, rows, cols) => {
    if (!rows || !rows.length) return '';
    let h = '<div class="card"><h2>' + title + '</h2><div class="table-card"><table><thead><tr>' +
      cols.map(c => '<th>' + c[0] + '</th>').join('') + '</tr></thead><tbody>';
    for (const r of rows) {
      h += '<tr>' + cols.map(c => '<td' + (c[2] ? ' class="muted"' : '') + '>' +
        (c[3] ? c[1](r) : escHtml(String(c[1](r) ?? ''))) + '</td>').join('') + '</tr>';
    }
    return h + '</tbody></table></div></div>';
  };

  function getProspectTzInfo(r) {
    const loc = (r.location || '').toLowerCase();
    const email = (r.to_email || '').toLowerCase();
    const comp = (r.company || '').toLowerCase();
    
    let country = 'Global';
    let flag = '🌐';
    let tzCode = 'Local';
    let diffMinsVsIst = 0;
    let idealWindowText = '10:00 AM – 4:00 PM';
    let idealIstText = '10:00 AM – 4:30 PM IST';

    if (loc.includes('dubai') || loc.includes('uae') || email.endsWith('.ae') || comp.includes('dubai') || comp.includes('uae')) {
      country = 'Dubai, UAE';
      flag = '🇦🇪';
      tzCode = 'GST (UTC+4)';
      diffMinsVsIst = -90; // Dubai is 1.5 hrs behind IST
      idealWindowText = '10:00 AM – 3:30 PM GST';
      idealIstText = '11:30 AM – 5:00 PM IST';
    } else if (loc.includes('india') || loc.includes('gurgaon') || loc.includes('delhi') || loc.includes('mumbai') || loc.includes('bangalore') || email.endsWith('.in')) {
      country = 'India';
      flag = '🇮🇳';
      tzCode = 'IST (UTC+5:30)';
      diffMinsVsIst = 0;
      idealWindowText = '10:30 AM – 4:30 PM IST';
      idealIstText = '10:30 AM – 4:30 PM IST';
    } else if (loc.includes('london') || loc.includes('uk') || loc.includes('united kingdom') || email.endsWith('.uk') || email.endsWith('.co.uk')) {
      country = 'London, UK';
      flag = '🇬🇧';
      tzCode = 'BST (UTC+1)';
      diffMinsVsIst = -270; // 4.5 hrs behind IST
      idealWindowText = '9:30 AM – 2:00 PM BST';
      idealIstText = '2:00 PM – 6:30 PM IST';
    } else if (loc.includes('miami') || loc.includes('austin') || loc.includes('dallas') || loc.includes('ny') || loc.includes('tx') || loc.includes('fl') || loc.includes('usa') || loc.includes('united states') || email.endsWith('.us')) {
      country = 'US (East/Central)';
      flag = '🇺🇸';
      tzCode = 'EST (UTC-4)';
      diffMinsVsIst = -570; // 9.5 hrs behind IST
      idealWindowText = '9:00 AM – 1:00 PM US';
      idealIstText = '6:30 PM – 10:30 PM IST';
    }

    let localSendStr = '';
    let slotBadge = '<span class="badge t-good" style="font-size:10px;padding:2px 6px;">🎯 Prime Slot</span>';
    
    if (r.send_at) {
      try {
        const dt = new Date(r.send_at);
        if (!isNaN(dt)) {
          const localDt = new Date(dt.getTime() + (diffMinsVsIst * 60 * 1000));
          const hrs = localDt.getHours();
          const mins = localDt.getMinutes().toString().padStart(2, '0');
          const ampm = hrs >= 12 ? 'PM' : 'AM';
          const h12 = hrs % 12 || 12;
          localSendStr = `${h12}:${mins} ${ampm}`;

          if (hrs >= 10 && hrs < 16) {
            slotBadge = '<span class="badge t-good" style="font-size:10px;padding:1px 6px;">🎯 Prime Slot</span>';
          } else if ((hrs >= 8 && hrs < 10) || (hrs >= 16 && hrs <= 19)) {
            slotBadge = '<span class="badge t-waiting" style="font-size:10px;padding:1px 6px;">⏰ Fair Slot</span>';
          } else {
            slotBadge = '<span class="badge t-bad" style="font-size:10px;padding:1px 6px;">🌙 Off-Hours</span>';
          }
        }
      } catch(e) {}
    }

    return {
      country,
      flag,
      tzCode,
      diffMinsVsIst,
      idealWindowText,
      idealIstText,
      localSendStr,
      slotBadge
    };
  }

  window.dispatchDueOutbox = async function() {
    const btn = document.getElementById('btn-dispatch-now');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '⏳ Dispatching emails via SMTP...';
    }
    try {
      const res = await api('/api/outbox/drain', { method: 'POST' });
      if (res && res.sent !== undefined) {
        alert('✅ Success! ' + res.sent + ' email(s) dispatched successfully.');
      } else if (res && res.error) {
        alert('Dispatch notice: ' + res.error);
      }
    } catch (e) {
      alert('Dispatch notice: ' + e);
    }
    await renderOutbox();
  };

  const renderApprovedTable = (items) => {
    if (!items || !items.length) return '';

    const now = new Date();
    const fmt = (d) => {
      const h = d.getHours() % 12 || 12;
      const m = d.getMinutes().toString().padStart(2, '0');
      const ap = d.getHours() >= 12 ? 'PM' : 'AM';
      return `${h}:${m} ${ap}`;
    };
    const dubaiNow = new Date(now.getTime() - 90 * 60 * 1000);
    const ukNow = new Date(now.getTime() - 270 * 60 * 1000);
    const clocks = {
      ist: fmt(now),
      dubai: fmt(dubaiNow),
      uk: fmt(ukNow)
    };

    let dueCount = 0;
    for (const it of items) {
      if (!it.send_at || new Date(it.send_at) <= now) {
        dueCount++;
      }
    }

    let h = '<div class="card" id="approved-scheduled-card">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:10px;">' +
        '<div>' +
          '<h2 style="margin:0;">📅 Approved &amp; scheduled (' + items.length + ')</h2>' +
          '<p style="font-size:12px;color:var(--text-2);margin:4px 0 0 0;">' +
            (dueCount > 0 ? '<b style="color:var(--s-good);">' + dueCount + ' emails</b> are approved and ready to dispatch right now.' : 'All emails are queued for upcoming dispatch.') +
          '</p>' +
        '</div>' +
        (dueCount > 0 ? (
          '<button class="btn btn-primary" id="btn-dispatch-now" onclick="dispatchDueOutbox()" style="font-weight:600;padding:8px 16px;display:inline-flex;align-items:center;gap:6px;">' +
            '<span>🚀 Send ' + dueCount + ' Ready Emails Now</span>' +
          '</button>'
        ) : '') +
      '</div>' +

      // LIVE TIMEZONE HELPER BANNER
      '<div style="background:var(--panel-raised);border:1px solid var(--border);border-radius:8px;padding:8px 12px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:11px;">' +
        '<div>' +
          '⏱️ <b>Live Clocks:</b> 🇮🇳 India <b>' + clocks.ist + '</b> • 🇦🇪 Dubai <b>' + clocks.dubai + '</b> (Peak Working Hours 🟢) • 🇬🇧 London <b>' + clocks.uk + '</b>' +
        '</div>' +
        '<div style="color:var(--text-2);">' +
          '🎯 <b>Dubai Target Window:</b> 11:30 AM – 5:00 PM IST (10 AM–3:30 PM Dubai)' +
        '</div>' +
      '</div>' +

      '<div class="table-card"><table><thead><tr>' +
      '<th>To</th><th>Company &amp; Country</th><th>Step</th><th>Subject</th><th>When It Sends (Dispatch Status)</th><th style="text-align:right">Actions</th>' +
      '</tr></thead><tbody>';

    for (const r of items) {
      const comp = r.company || (r.to_email ? r.to_email.split('@')[1] : '');
      const tz = getProspectTzInfo(r);
      const isDue = !r.send_at || new Date(r.send_at) <= now;

      h += '<tr>' +
        '<td><b>' + escHtml(r.to_email) + '</b></td>' +
        '<td>' +
          '<div style="font-weight:500;">' + escHtml(comp) + '</div>' +
          '<div style="font-size:11px;color:var(--text-2);margin-top:2px;">' + tz.flag + ' ' + escHtml(tz.country) + '</div>' +
        '</td>' +
        '<td><span class="badge" style="font-size:11px;">Step ' + r.step + '</span></td>' +
        '<td style="max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escHtml(r.subject) + '</td>' +
        '<td>' +
          (isDue ? (
            '<div>' +
              '<div style="display:inline-flex;align-items:center;gap:5px;background:rgba(34,197,94,0.12);border:1px solid rgba(34,197,94,0.3);padding:2px 7px;border-radius:4px;">' +
                '<span style="font-size:11px;font-weight:700;color:var(--s-good);">🟢 Ready to Send NOW</span>' +
              '</div>' +
              '<div style="font-size:11px;color:var(--text-2);margin-top:3px;">' +
                'Recipient local time: <b>' + (tz.localSendStr || 'Active') + '</b>' +
              '</div>' +
            '</div>'
          ) : (
            '<div>' +
              '<div style="font-size:12px;font-weight:600;color:var(--text-1);">📅 ' + formatDate(r.send_at) + ' IST</div>' +
              '<div style="font-size:11px;color:var(--text-2);margin-top:2px;">' +
                tz.flag + ' ' + (tz.localSendStr || '') + ' local • Auto Follow-up (Step ' + r.step + ')' +
              '</div>' +
            '</div>'
          )) +
        '</td>' +
        '<td style="text-align:right"><div style="display:inline-flex;gap:6px;">' +
          '<button class="btn btn-secondary btn-sm" onclick="unapproveItem(\'' + r.id + '\')" title="Open in review desk to edit text or check website">✏️ Review &amp; Edit</button>' +
          '<button class="btn btn-secondary btn-sm" style="color:var(--red);border-color:rgba(239,68,68,0.4);" onclick="cancelApprovedItem(\'' + r.id + '\',\'' + escHtml(r.to_email) + '\')" title="Cancel this scheduled email">🚫 Cancel</button>' +
        '</div></td>' +
      '</tr>';
    }
    h += '</tbody></table></div></div>';
    return h;
  };

  const renderArchivedTable = (archived) => {
    if (!archived || !archived.length) return '';
    let h = '<div class="card" id="archived-catchalls-card" style="border-color:rgba(245,158,11,0.3);">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:10px;">' +
        '<div>' +
          '<h2 style="margin:0;color:#f59e0b;display:flex;align-items:center;gap:8px;">' +
            '<span>📦</span> Archived for LinkedIn / Multi-channel Outreach (' + archived.length + ')' +
          '</h2>' +
          '<p style="font-size:12px;color:var(--text-2);margin:4px 0 0 0;">' +
            'These accounts are catch-all domains. Excluded from email sending to protect domain health, but saved for direct LinkedIn &amp; Website outreach.' +
          '</p>' +
        '</div>' +
      '</div>' +
      '<div class="table-card"><table><thead><tr>' +
      '<th>Decision Maker &amp; Company</th><th>Catch-All Email</th><th>Target Channel</th><th>Profile &amp; Links</th><th style="text-align:right">Action</th>' +
      '</tr></thead><tbody>';

    for (const r of archived) {
      const name = (r.first_name || r.last_name) ? (r.first_name + ' ' + (r.last_name || '')).trim() : 'Decision Maker';
      const comp = r.company || (r.to_email ? r.to_email.split('@')[1] : 'Target Account');
      const title = r.title || 'Executive';
      const li = r.linkedin_url ? '<a href="' + escHtml(r.linkedin_url) + '" target="_blank" class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 8px;display:inline-flex;align-items:center;gap:4px;">LinkedIn ↗</a>' : '';
      const web = r.website ? '<a href="' + escHtml(r.website) + '" target="_blank" class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 8px;display:inline-flex;align-items:center;gap:4px;">Website 🌐</a>' : '';

      h += '<tr>' +
        '<td>' +
          '<div style="font-weight:600;font-size:13px;">' + escHtml(name) + '</div>' +
          '<div style="font-size:11px;color:var(--text-2);margin-top:2px;">' + escHtml(title) + ' &bull; <b style="color:var(--accent);">' + escHtml(comp) + '</b></div>' +
        '</td>' +
        '<td>' +
          '<code>' + escHtml(r.to_email) + '</code>' +
          '<div style="font-size:10px;color:#eab308;font-weight:600;margin-top:2px;">⚠️ Catch-All Mailbox</div>' +
        '</td>' +
        '<td>' +
          '<span style="font-size:11px;background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);color:#f59e0b;padding:3px 8px;border-radius:4px;font-weight:600;">' +
            '💼 LinkedIn InMail / Form' +
          '</span>' +
        '</td>' +
        '<td><div style="display:flex;gap:6px;align-items:center;">' + (li || '<span class="muted" style="font-size:11px;">No LinkedIn</span>') + (web || '') + '</div></td>' +
        '<td style="text-align:right">' +
          '<button class="btn btn-secondary btn-sm" onclick="restoreArchivedDraft(\'' + r.id + '\')" style="font-size:11px;" title="Restore back to Outbox review desk">' +
            '↩️ Restore' +
          '</button>' +
        '</td>' +
      '</tr>';
    }
    h += '</tbody></table></div></div>';
    return h;
  };

  list.innerHTML =
    renderApprovedTable(data.approved) +
    renderArchivedTable(data.archived) +
    table('Recently sent', data.sent, [
      ['To', r => r.to_email], ['Step', r => r.step], ['Subject', r => r.subject],
      ['Sent', r => formatDate(r.sent_at), true],
    ]) +
    table('Didn\'t send', data.failed, [
      ['To', r => r.to_email], ['Status', r => badge(r.status), false, true],
      ['Reason', r => r.error, true], ['Updated', r => formatDate(r.updated_at), true],
    ]);
}

async function restoreArchivedDraft(id) {
  try {
    const res = await api('/api/outbox/' + id + '/unarchive', { method: 'POST' });
    if (res && res.success) {
      showToast('Restored draft back to Outbox review desk!', 'success');
      loadOutbox();
    } else {
      showToast('Failed to restore draft', 'error');
    }
  } catch(e) {
    showToast('Restore error: ' + e, 'error');
  }
}

function renderDesk(items, i) {
  const cur = items[i];
  const rail = items.map((it, n) => {
    let domain = it.domain || '';
    if (!domain && it.website) {
      try { domain = new URL(it.website).hostname.replace(/^www\./, ''); } catch (e) {}
    }
    if (!domain && it.to_email && it.to_email.includes('@')) {
      domain = it.to_email.split('@')[1];
    }
    const compName = it.company || domain || 'Verified Target';
    const activeClass = n === i ? 'active' : '';
    let badgeHtml = '';
    if (it.email_status === 'verified') {
      badgeHtml = '<span style="font-size:10px;padding:2px 6px;border-radius:10px;background:rgba(34,197,94,0.15);color:#22c55e;font-weight:700;">✅ Safe</span>';
    } else if (it.email_status === 'risky') {
      badgeHtml = '<span style="font-size:10px;padding:2px 6px;border-radius:10px;background:rgba(234,179,8,0.15);color:#eab308;font-weight:600;">⚠️ Catch-All</span>';
    } else if (it.email_status === 'invalid') {
      badgeHtml = '<span style="font-size:10px;padding:2px 6px;border-radius:10px;background:rgba(239,68,68,0.15);color:#ef4444;font-weight:600;">❌ Invalid</span>';
    }
    return '<div class="desk-item ' + activeClass + '" onclick="deskGo(' + n + ')">' +
      '<div class="to" style="display:flex;justify-content:space-between;align-items:center;gap:6px;">' +
        '<span style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px;">' + escHtml(it.to_email) + '</span>' +
        badgeHtml +
      '</div>' +
      '<div style="font-size:12px;color:var(--accent);margin-top:2px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
        '🏢 ' + escHtml(compName) +
      '</div>' +
      '<div class="sub" style="margin-top:2px;">' + escHtml(it.subject || '(no subject)') + '</div>' +
    '</div>';
  }).join('');

  // Target website URL resolution
  let targetUrl = cur.website || '';
  let displayDomain = cur.domain || '';
  if (!targetUrl && cur.domain) {
    targetUrl = 'https://' + cur.domain;
  } else if (!targetUrl && cur.to_email && cur.to_email.includes('@')) {
    const dom = cur.to_email.split('@')[1];
    if (dom && !['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com'].includes(dom.toLowerCase())) {
      targetUrl = 'https://' + dom;
      displayDomain = dom;
    }
  }
  if (targetUrl && !displayDomain) {
    try { displayDomain = new URL(targetUrl).hostname.replace(/^www\./, ''); } catch(e) {}
  }
  const compTitle = cur.company || displayDomain || 'Target Company';

  let curBadge = '';
  if (cur.email_status === 'verified') {
    curBadge = '<span style="font-size:11px;padding:3px 8px;border-radius:12px;background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.3);color:#22c55e;font-weight:700;">✅ 100% Verified (Reoon Safe)</span>';
  } else if (cur.email_status === 'risky') {
    curBadge = '<span style="font-size:11px;padding:3px 8px;border-radius:12px;background:rgba(234,179,8,0.15);border:1px solid rgba(234,179,8,0.3);color:#eab308;font-weight:600;">⚠️ Catch-All Domain (Risky)</span>';
  } else if (cur.email_status === 'invalid') {
    curBadge = '<span style="font-size:11px;padding:3px 8px;border-radius:12px;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#ef4444;font-weight:600;">❌ Invalid Mailbox</span>';
  }

  // Company banner header with direct clickable website link
  const companyBanner = 
    '<div style="background:linear-gradient(90deg, rgba(59,130,246,0.08), rgba(99,102,241,0.04)); border:1px solid rgba(59,130,246,0.25); border-radius:8px; padding:10px 14px; margin-bottom:14px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">' +
      '<div style="display:flex; align-items:center; gap:10px;">' +
        '<span style="font-size:18px;">🏢</span>' +
        '<div>' +
          '<div style="font-weight:700; font-size:14px; color:var(--text);">' + escHtml(compTitle) + '</div>' +
          (cur.industry ? '<div style="font-size:11px; color:var(--text-2); margin-top:1px;">' + escHtml(cur.industry) + '</div>' : '') +
        '</div>' +
      '</div>' +
      '<div style="display:flex; align-items:center; gap:10px;">' +
        curBadge +
        (targetUrl ? 
          '<a href="' + escHtml(targetUrl) + '" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" style="display:inline-flex; align-items:center; gap:6px; font-weight:600; color:#38bdf8; border-color:rgba(56,189,248,0.4); background:rgba(56,189,248,0.08); padding:6px 14px; border-radius:6px; text-decoration:none;">' +
            '🌐 Open Website (' + escHtml(displayDomain || 'site') + ') <span style="font-size:12px;">↗</span>' +
          '</a>' : '') +
      '</div>' +
    '</div>';

  return '<div class="desk">' +
    '<div class="desk-list">' + rail + '</div>' +
    '<div class="desk-pane">' +
      companyBanner +
      '<div class="to-line">To <b>' + escHtml(cur.to_email) + '</b> &middot; step ' +
        cur.step + ' (' + escHtml(cur.kind) + ') &middot; sends ' +
        formatDate(cur.send_at) + '</div>' +
      '<div class="subject" id="desk-sub">' + escHtml(cur.subject || '(no subject)') + '</div>' +
      '<div class="body" id="desk-body" style="white-space:pre-wrap;">' + escHtml(cur.body) + '</div>' +
      '<div class="desk-actions" id="desk-actions-bar">' +
        '<button class="btn btn-primary" onclick="outboxAct(\'' + cur.id + '\',\'approve\')">' +
          'Approve <kbd>A</kbd></button>' +
        '<button class="btn btn-secondary" onclick="outboxAct(\'' + cur.id + '\',\'reject\')">' +
          'Reject <kbd>R</kbd></button>' +
        '<button id="desk-edit-btn" class="btn btn-secondary" onclick="toggleEdit(\'' + cur.id + '\')">' +
          '✏️ Edit Mail</button>' +
        (targetUrl ? 
          '<a href="' + escHtml(targetUrl) + '" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;">' +
            '🌐 Open Website ↗</a>' : '') +
        '<span class="muted" style="font-size:12px;margin-left:auto">' +
          (i + 1) + ' of ' + items.length + '</span>' +
      '</div>' +
    '</div></div>';
}

let _editing = false;
function toggleEdit(id) {
  _editing = !_editing;
  if (!_editing) {
    deskGo(_desk.i);
    return;
  }
  const cur = _desk.items[_desk.i];
  const subEl = document.getElementById('desk-sub');
  const bodyEl = document.getElementById('desk-body');
  if (subEl && bodyEl) {
    subEl.outerHTML = '<input id="desk-sub-edit" class="input" style="width:100%;font-size:18px;font-weight:600;margin-bottom:12px;padding:8px 12px;background:var(--bg-2);color:var(--text);border:1px solid var(--accent);border-radius:6px;" value="' + escHtml(cur.subject || '') + '">';
    bodyEl.outerHTML = '<textarea id="desk-body-edit" class="input" style="width:100%;min-height:240px;font-size:14px;line-height:1.6;padding:12px;background:var(--bg-2);color:var(--text);border:1px solid var(--accent);border-radius:6px;font-family:inherit;">' + escHtml(cur.body || '') + '</textarea>';
    const actionsBar = document.getElementById('desk-actions-bar');
    if (actionsBar) {
      actionsBar.innerHTML = '<button class="btn btn-primary" onclick="saveAndApprove(\'' + cur.id + '\')">💾 Save &amp; Approve</button> ' +
        '<button class="btn btn-secondary" onclick="saveOnly(\'' + cur.id + '\')">💾 Save Draft</button> ' +
        '<button class="btn btn-secondary" onclick="toggleEdit(\'' + cur.id + '\')">Cancel</button>';
    }
  }
}

async function saveOnly(id) {
  const sub = document.getElementById('desk-sub-edit')?.value || '';
  const body = document.getElementById('desk-body-edit')?.value || '';
  const cur = _desk.items[_desk.i];
  if (cur) {
    cur.subject = sub;
    cur.body = body;
  }
  await api('/api/outbox/' + encodeURIComponent(id) + '/edit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({subject: sub, body: body})
  });
  showToast('Draft updated successfully!', 'success');
  _editing = false;
  loadOutbox();
}

async function saveAndApprove(id) {
  const sub = document.getElementById('desk-sub-edit')?.value || '';
  const body = document.getElementById('desk-body-edit')?.value || '';
  const cur = _desk.items[_desk.i];
  if (cur) {
    cur.subject = sub;
    cur.body = body;
  }
  await api('/api/outbox/' + encodeURIComponent(id) + '/edit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({subject: sub, body: body})
  });
  _editing = false;
  await outboxAct(id, 'approve');
}

async function quickProspectUrl() {
  const input = document.getElementById('quick-url-input');
  const btn = document.getElementById('quick-url-btn');
  const statusEl = document.getElementById('quick-url-status');
  if (!input) return;
  const url = input.value.trim();
  if (!url) {
    showToast('Please enter a website URL', 'error');
    input.focus();
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span>⏳ Writing Pitch...</span>';
  if (statusEl) {
    statusEl.style.display = 'block';
    statusEl.style.color = 'var(--text-2)';
    statusEl.textContent = 'Profiling website and creating speed-to-lead sequence in Outbox...';
  }

  try {
    const res = await api('/api/prospect/instant-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url: url })
    });

    if (res && res.success) {
      input.value = '';
      if (statusEl) {
        statusEl.style.color = '#10b981';
        statusEl.innerHTML = '✅ Draft created for <b>' + escHtml(res.company) + '</b> (<a href="' + escHtml(res.website) + '" target="_blank" style="color:#38bdf8;text-decoration:underline;">' + escHtml(res.domain) + '</a>)! Ready in Outbox below.';
        setTimeout(() => { if (statusEl) statusEl.style.display = 'none'; }, 6000);
      }
      showToast('Pitch generated for ' + res.company + '!', 'success');
      await loadOutbox();
      const targetIdx = _desk.items.findIndex(it => it.id === res.item_id || it.to_email === res.email);
      if (targetIdx >= 0) {
        deskGo(targetIdx);
        setTimeout(() => {
          const activeEl = document.querySelector('.desk-item.active');
          if (activeEl) activeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 100);
      }
    } else {
      const err = (res && res.message) ? res.message : 'Failed to generate pitch';
      if (statusEl) {
        statusEl.style.color = 'var(--red)';
        statusEl.textContent = '❌ ' + err;
      }
      showToast(err, 'error');
    }
  } catch (e) {
    if (statusEl) {
      statusEl.style.color = 'var(--red)';
      statusEl.textContent = '❌ ' + e.message;
    }
    showToast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>🚀 Generate Pitch</span>';
  }
}

function deskGo(n) {
  if (n < 0 || n >= _desk.items.length) return;
  _desk.i = n;
  document.getElementById('outbox-desk').innerHTML = renderDesk(_desk.items, n);
}

// Keyboard review. Ignored while typing into a field, so Settings still works.
document.addEventListener('keydown', e => {
  if (currentTab !== 'outbox' || e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
  const cur = _desk.items[_desk.i];
  const k = e.key.toLowerCase();
  if (k === 'j') { e.preventDefault(); deskGo(_desk.i + 1); }
  else if (k === 'k') { e.preventDefault(); deskGo(_desk.i - 1); }
  else if (k === 'a' && cur) { e.preventDefault(); outboxAct(cur.id, 'approve'); }
  else if (k === 'r' && cur) { e.preventDefault(); outboxAct(cur.id, 'reject'); }
});

async function outboxAct(id, action) {
  const data = await api('/api/outbox/' + encodeURIComponent(id) + '/' + action, {method: 'POST'});
  if (data && data.success) showToast(action === 'approve' ? 'Approved — will send on schedule.' : 'Rejected.', 'success');
  else showToast('Action failed.', 'error');
  loadOutbox();
}

async function unapproveItem(id) {
  showToast('Moving back to Review Desk...', 'info');
  const res = await api('/api/outbox/' + encodeURIComponent(id) + '/unapprove', {method: 'POST'});
  if (res && res.success) {
    await loadOutbox();
    const idx = _desk.items.findIndex(it => it.id === id);
    if (idx >= 0) {
      deskGo(idx);
    }
    const deskEl = document.getElementById('outbox-desk');
    if (deskEl) deskEl.scrollIntoView({behavior: 'smooth', block: 'start'});
    showToast('Loaded in Review Desk! Click ✏️ Edit Mail to change copy.', 'success');
  } else {
    showToast('Failed to move item.', 'error');
  }
}

async function cancelApprovedItem(id, email) {
  if (!confirm('Are you sure you want to cancel the scheduled email to ' + email + '?')) return;
  const res = await api('/api/outbox/' + encodeURIComponent(id) + '/cancel', {method: 'POST'});
  if (res && res.success) {
    showToast('Cancelled scheduled email to ' + email, 'success');
    await loadOutbox();
  } else {
    showToast('Failed to cancel item.', 'error');
  }
}

async function outboxApproveAll() {
  const data = await api('/api/outbox/approve-all', {method: 'POST'});
  if (data && data.success) showToast('Approved ' + data.approved + ' email(s).', 'success');
  else showToast('Approve-all failed.', 'error');
  loadOutbox();
}

async function sendingToggle(action) {
  const data = await api('/api/sending/' + action, {method: 'POST'});
  if (data && data.success) showToast(action === 'pause' ? 'Sending paused.' : 'Sending resumed.', 'success');
  else showToast('Failed.', 'error');
  loadOutbox();
}

async function loadCompanies() {
  companyDrill = false;
  const el = document.getElementById('companies-list');
  const data = await api('/api/companies');
  if (!data) { el.innerHTML = offlineState(); return; }
  _companies = data;
  if (!data.length) {
    el.innerHTML = emptyState('&#9906;', 'No companies yet',
      'Jarvis\'s Scout agent hasn\'t researched any companies. Finish <b>Setup</b>, then start Jarvis from the <b>Controls</b> tab.');
    return;
  }
  let html = '<div class="table-card"><table><thead><tr><th>Company</th><th>Domain</th><th>Industry</th><th>Size</th><th>Location</th><th>Contacts</th><th>Source</th><th>Added</th></tr></thead><tbody>';
  data.forEach((c, i) => {
    const website = c.website || (c.domain ? 'https://' + c.domain : '');
    const nameLink = website
      ? '<a href="' + escHtml(website) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()">' + escHtml(c.name) + '</a>'
      : escHtml(c.name);
    html += '<tr style="cursor:pointer" onclick="showCompanyContacts(' + i + ')">' +
      '<td>' + nameLink + '</td><td class="muted">' + escHtml(c.domain) + '</td><td>' + escHtml(c.industry) + '</td>' +
      '<td>' + escHtml(c.company_size) + '</td><td>' + escHtml(c.location) + '</td>' +
      '<td>' + (c.contact_count || 0) + '</td><td class="muted">' + escHtml(c.source) + '</td>' +
      '<td class="muted">' + formatDate(c.created_at) + '</td></tr>';
  });
  el.innerHTML = html + '</tbody></table></div>';
}

async function showCompanyContacts(index) {
  const company = _companies[index];
  if (!company) return;
  companyDrill = true;
  const el = document.getElementById('companies-list');
  const data = await api('/api/companies/' + encodeURIComponent(company.id) + '/contacts');
  let html = '<div class="card"><h2>' + escHtml(company.name) + ' — Contacts</h2>' +
    '<button class="btn btn-secondary btn-sm" onclick="loadCompanies()" style="margin-bottom:16px">&larr; Back to Companies</button>';
  if (!data || !data.length) {
    html += '<p style="color:var(--text-3);font-size:13px">No contacts found at this company yet.</p></div>';
  } else {
    html += '<div class="table-card"><table><thead><tr><th>Name</th><th>Title</th><th>Email</th><th>Phone</th><th>LinkedIn</th><th>Status</th><th>Source</th></tr></thead><tbody>';
    for (const p of data) {
      const emailIcon = emailTag(p);
      const phoneIcon = p.phone_verified ? ' <span class="verified">&#10003;</span>' : '';
      html += '<tr><td>' + escHtml(p.first_name) + ' ' + escHtml(p.last_name) + '</td>' +
        '<td>' + escHtml(p.title) + '</td><td>' + escHtml(p.email) + emailIcon + '</td>' +
        '<td>' + escHtml(p.phone) + phoneIcon + '</td>' +
        '<td>' + (p.linkedin_url ? '<a href="' + escHtml(p.linkedin_url) + '" target="_blank" rel="noopener">Profile</a>' : '') + '</td>' +
        '<td>' + badge(p.status) + '</td><td class="muted">' + escHtml(p.source) + '</td></tr>';
    }
    html += '</tbody></table></div></div>';
  }
  el.innerHTML = html;
}

async function submitFeedback(entityType, entityId, promptText) {
  const comment = prompt(promptText || 'Add your feedback:');
  if (!comment) return;
  const data = await api('/api/feedback', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({entity_type: entityType, entity_id: entityId, comment: comment})
  });
  if (data && data.success) showToast('Feedback saved. Jarvis will take it into account.', 'success');
  else showToast((data && data.message) || 'Could not save feedback.', 'error');
}

function fbProspect(i) {
  const p = _prospects[i];
  if (p) submitFeedback('contact', p.id, 'Feedback on this contact:');
}

function fbCampaign(i) {
  const c = _campaigns[i];
  if (c) submitFeedback('campaign', c.id, 'Leave feedback on this campaign:');
}

async function loadProspects() {
  const el = document.getElementById('prospects-table');
  const data = await api('/api/prospects');
  if (!data) { el.innerHTML = offlineState(); return; }
  _prospects = data;
  if (!data.length) {
    el.innerHTML = emptyState('&#9673;', 'No contacts yet',
      'Jarvis hasn\'t found any prospects. Once it\'s running, the Scout agent searches the web for people matching your ideal customer profile in <b>harvey.yaml</b>.');
    return;
  }
  let html = '<div class="table-card"><table><thead><tr><th>Name</th><th>Title</th><th>Company</th><th>Email</th><th>Phone</th><th>Status</th><th>Source</th><th>Added</th><th></th></tr></thead><tbody>';
  data.forEach((p, i) => {
    const emailV = p.email ? (escHtml(p.email) + emailTag(p)) : '';
    const phoneV = p.phone ? (escHtml(p.phone) + (p.phone_verified ? ' <span class="verified">&#10003;</span>' : '')) : '';
    html += '<tr><td>' + escHtml(p.first_name) + ' ' + escHtml(p.last_name) + '</td>' +
      '<td>' + escHtml(p.title) + '</td><td>' + escHtml(p.company) + '</td>' +
      '<td>' + emailV + '</td><td>' + phoneV + '</td><td>' + badge(p.status) + '</td>' +
      '<td class="muted">' + escHtml(p.source) + '</td><td class="muted">' + formatDate(p.created_at) + '</td>' +
      '<td><button class="btn btn-secondary btn-sm" onclick="fbProspect(' + i + ')">Feedback</button></td></tr>';
  });
  el.innerHTML = html + '</tbody></table></div>';
}

async function loadCampaigns() {
  const el = document.getElementById('campaigns-list');
  const data = await api('/api/campaigns');
  if (!data) { el.innerHTML = offlineState(); return; }
  _campaigns = data;
  if (!data.length) {
    el.innerHTML = emptyState('&#9993;', 'No campaigns yet',
      'The Writer agent hasn\'t drafted any sequences. It kicks in automatically once Jarvis has scored prospects to write for.');
    return;
  }
  let html = '';
  data.forEach((c, i) => {
    let stepsHtml = '';
    for (const step of (c.sequence || [])) {
      stepsHtml += '<div class="email-step"><div class="step-num">Email ' + escHtml(String(step.step || '?')) +
        (step.delay_days ? ' &middot; send after ' + escHtml(String(step.delay_days)) + ' days' : '') + '</div>' +
        '<div class="subject">' + escHtml(step.subject) + '</div>' +
        '<div class="body">' + escHtml(step.body) + '</div></div>';
    }
    const pc = (c.prospect_ids || []).length;
    html += '<div class="campaign-card"><h3>' + escHtml(c.name || 'Untitled Campaign') + '</h3>' +
      '<div class="meta">' + badge(c.status) + '<span>' + escHtml(c.channel || 'email') + '</span>' +
      '<span>' + pc + ' prospect' + (pc !== 1 ? 's' : '') + '</span><span>' + formatDate(c.created_at) + '</span>' +
      '<button class="btn btn-secondary btn-sm" onclick="fbCampaign(' + i + ')">Feedback</button></div>' +
      (stepsHtml || '<p style="color:var(--text-3);font-size:13px">No email steps in this campaign.</p>') + '</div>';
  });
  el.innerHTML = html;
}

async function loadConversations() {
  const el = document.getElementById('conversations-list');
  const data = await api('/api/conversations');
  if (!data) { el.innerHTML = offlineState(); return; }
  if (!data.length) {
    el.innerHTML = emptyState('&#9737;', 'No conversations yet',
      'No prospects have replied so far. When they do, the Handler agent classifies each reply and responds — every thread shows up here.');
    return;
  }
  let html = '';
  for (const c of data) {
    let threadHtml = '';
    for (const msg of (c.thread || [])) {
      const cls = msg.sender === 'harvey' ? 'sent' : 'received';
      threadHtml += '<div class="thread-msg ' + cls + '"><div class="sender">' + escHtml(msg.sender) +
        ' &middot; ' + formatDate(msg.timestamp) + '</div>' + escHtml(msg.content) + '</div>';
    }
    const name = [c.first_name, c.last_name].filter(Boolean).join(' ') || 'Unknown';
    html += '<div class="convo-card"><h3>' + escHtml(name) +
      (c.company ? ' <span style="color:var(--text-3);font-weight:500">&mdash; ' + escHtml(c.company) + '</span>' : '') + '</h3>' +
      '<div class="meta">' + badge(c.status) + (c.intent ? badge(c.intent) : '') +
      '<span>' + escHtml(c.prospect_email || '') + '</span><span>' + formatDate(c.updated_at) + '</span></div>' +
      (threadHtml || '<p style="color:var(--text-3);font-size:13px">No messages in this thread yet.</p>') + '</div>';
  }
  el.innerHTML = html;
}

async function loadActivity() {
  const el = document.getElementById('activity-list');
  const data = await api('/api/activity');
  if (!data) { el.innerHTML = offlineState(); return; }
  if (!data.length) {
    el.innerHTML = emptyState('&#9202;', 'No activity yet',
      'Jarvis hasn\'t taken any actions. Every prospect found, email written, and reply handled will appear here the moment it happens.');
    return;
  }
  let html = '<div class="activity-feed">';
  for (const a of data) {
    html += '<div class="activity-item"><span class="time">' + formatDate(a.created_at) + '</span>' +
      '<span class="agent">' + escHtml(a.agent) + '</span>' +
      '<span class="action">' + escHtml(a.action_type) + '</span></div>';
  }
  el.innerHTML = html + '</div>';
}

// ── Init & live refresh ──

loadToday();
loadSetupStatus();
loadRuns();
loadTodayActivity();
loadHarveyStatus();

// Agent status: quick poll
setInterval(loadHarveyStatus, 8000);

// Nav counts stay live wherever you are, so "something needs me" is visible
// from any tab without polling that tab's contents.
setInterval(async () => {
  if (document.hidden || currentTab === 'today') return;
  const data = await api('/api/today');
  if (!data) return;
  navCount('nav-today', (data.items || []).filter(i => i.tone !== 'good').length);
  navCount('nav-outbox', (data.stats || {}).outbox_pending || 0);
}, 20000);

// Data tabs: auto-refresh live views without clobbering anything in progress.
// Outbox, settings and help are deliberately excluded — re-rendering the desk
// under someone mid-decision loses their place, and settings may be mid-edit.
setInterval(() => {
  if (document.hidden) return;
  switch (currentTab) {
    case 'today': loadToday(); loadRuns(); loadTodayActivity(); break;
    case 'companies': if (!companyDrill) loadCompanies(); break;
    case 'prospects': loadProspects(); break;
    case 'campaigns': loadCampaigns(); break;
    case 'conversations': loadConversations(); break;
    case 'activity': loadActivity(); break;
    case 'usage': loadUsage(); break;
    case 'controls': loadLogs(); break;
    case 'crm-sheet': loadCrmSheet(); break;
  }
}, 15000);

// ── TrackKaro Native CRM Sheet Engine ──

let _crmRows = [];
let _crmCurrentFilter = 'all';

async function loadCrmSheet() {
  const container = document.getElementById('crm-table-container');
  if (!container) return;

  const crmLink = document.getElementById('crm-sheet-link');
  if (crmLink) {
    if (_workspaceInfo && _workspaceInfo.has_sheet && _workspaceInfo.sheet_url) {
      crmLink.href = _workspaceInfo.sheet_url;
      crmLink.style.display = 'inline-flex';
    } else {
      crmLink.style.display = 'none';
    }
  }
  
  if (!_crmRows.length) {
    container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-2);">' +
      '<div style="font-size:24px;margin-bottom:8px;">⏳</div>' +
      '<div>Loading CRM Sheet Data Vault...</div>' +
    '</div>';
  }
  
  try {
    const data = await api('/api/crm/table');
    if (!data || !data.rows || !data.rows.length) {
      _crmRows = [];
      renderCrmFilterPills([]);
      container.innerHTML = '<div class="card" style="padding:54px 20px;text-align:center;">' +
        '<div style="font-size:36px;margin-bottom:12px;">📊</div>' +
        '<h3 style="font-size:17px;font-weight:600;margin-bottom:6px;">Clean Slate — No Leads Scraped in this Workspace Yet</h3>' +
        '<p style="color:var(--text-3);font-size:13px;max-width:520px;margin:0 auto 20px;line-height:1.6;">' +
        'This is an isolated client/offer workspace. Go to the <b>Discover</b> tab to search & scrape prospects matching your ICP, and verified leads will automatically appear in this vault.' +
        '</p>' +
        '<button class="btn btn-primary btn-sm" onclick="showTab(\'discover\', document.querySelector(\'nav button:nth-child(3)\'))">🚀 Start Discovering Leads</button>' +
      '</div>';
      return;
    }
    _crmRows = data.rows;
    renderCrmFilterPills(_crmRows);
    filterCrmTable();
  } catch(e) {
    container.innerHTML = '<div class="card" style="padding:30px;color:var(--red);">Failed to load CRM Sheet: ' + e + '</div>';
  }
}

function renderCrmFilterPills(rows) {
  const el = document.getElementById('crm-filter-pills');
  if (!el) return;

  const counts = {
    all: rows.length,
    contacted: rows.filter(r => (r.status || '').includes('Contacted') || (r.status || '').includes('🚀')).length,
    verified: rows.filter(r => (r.status || '').includes('Verified') || (r.status || '').includes('✅')).length,
    catchall: rows.filter(r => (r.status || '').includes('Catch-All') || (r.status || '').includes('⚠️')).length,
    replied: rows.filter(r => (r.status || '').includes('Replied') || (r.status || '').includes('🔥')).length,
    bounced: rows.filter(r => (r.status || '').includes('Bounced') || (r.status || '').includes('❌')).length
  };

  const pills = [
    { id: 'all', label: 'All Leads (' + counts.all + ')', color: 'var(--text-1)' },
    { id: 'contacted', label: '🚀 Contacted (' + counts.contacted + ')', color: '#0284c7' },
    { id: 'verified', label: '✅ Verified Safe (' + counts.verified + ')', color: '#16a34a' },
    { id: 'catchall', label: '⚠️ Catch-All (' + counts.catchall + ')', color: '#d97706' },
    { id: 'replied', label: '🔥 Replied (' + counts.replied + ')', color: '#15803d' },
    { id: 'bounced', label: '❌ Bounced (' + counts.bounced + ')', color: '#dc2626' }
  ];

  el.innerHTML = pills.map(p => {
    const active = _crmCurrentFilter === p.id 
      ? 'style="font-weight:700;border-color:' + p.color + ';background:rgba(255,255,255,0.08);color:' + p.color + ';"' 
      : 'style="color:var(--text-2);"';
    return '<button class="btn btn-secondary btn-sm" onclick="setCrmFilter(\'' + p.id + '\')" ' + active + '>' + p.label + '</button>';
  }).join('');
}

function setCrmFilter(f) {
  _crmCurrentFilter = f;
  renderCrmFilterPills(_crmRows);
  filterCrmTable();
}

function filterCrmTable() {
  const q = (document.getElementById('crm-search-input')?.value || '').toLowerCase().trim();
  let filtered = _crmRows;

  if (_crmCurrentFilter === 'contacted') filtered = filtered.filter(r => (r.status || '').includes('Contacted') || (r.status || '').includes('🚀'));
  else if (_crmCurrentFilter === 'verified') filtered = filtered.filter(r => (r.status || '').includes('Verified') || (r.status || '').includes('✅'));
  else if (_crmCurrentFilter === 'catchall') filtered = filtered.filter(r => (r.status || '').includes('Catch-All') || (r.status || '').includes('⚠️'));
  else if (_crmCurrentFilter === 'replied') filtered = filtered.filter(r => (r.status || '').includes('Replied') || (r.status || '').includes('🔥'));
  else if (_crmCurrentFilter === 'bounced') filtered = filtered.filter(r => (r.status || '').includes('Bounced') || (r.status || '').includes('❌'));

  if (q) {
    filtered = filtered.filter(r => 
      (r.company || '').toLowerCase().includes(q) ||
      (r.decision_maker || '').toLowerCase().includes(q) ||
      (r.contact || '').toLowerCase().includes(q) ||
      (r.region || '').toLowerCase().includes(q) ||
      (r.status || '').toLowerCase().includes(q)
    );
  }

  renderCrmTable(filtered);
}

function renderCrmTable(rows) {
  const container = document.getElementById('crm-table-container');
  if (!container) return;

  if (!rows || !rows.length) {
    container.innerHTML = '<div class="card" style="padding:32px;text-align:center;color:var(--text-2);">No matching prospects found for this filter.</div>';
    return;
  }

  let html = '<div class="card" style="padding:0;overflow:hidden;border:1px solid var(--border);"><div class="table-card" style="margin:0;max-height:75vh;overflow:auto;"><table style="font-size:12px;width:100%;border-collapse:collapse;">' +
    '<thead><tr style="background:var(--bg-2);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:2;">' +
    '<th style="padding:10px 12px;text-align:left;">Target Company</th>' +
    '<th style="padding:10px 12px;text-align:left;">Decision Maker</th>' +
    '<th style="padding:10px 12px;text-align:left;">Direct Contact</th>' +
    '<th style="padding:10px 12px;text-align:left;">Outreach Status</th>' +
    '<th style="padding:10px 12px;text-align:left;">Region</th>' +
    '<th style="padding:10px 12px;text-align:left;">Retainer Deal</th>' +
    '<th style="padding:10px 12px;text-align:left;">Links</th>' +
    '<th style="padding:10px 12px;text-align:left;">Strategy Notes</th>' +
    '</tr></thead><tbody>';

  rows.forEach((r, idx) => {
    let statusStyle = 'background:rgba(255,255,255,0.06);color:var(--text);';
    if ((r.status || '').includes('Replied') || (r.status || '').includes('🔥')) {
      statusStyle = 'background:#bbf7d0;color:#166534;font-weight:700;';
    } else if ((r.status || '').includes('Contacted') || (r.status || '').includes('🚀')) {
      statusStyle = 'background:#e0f2fe;color:#0369a1;font-weight:700;';
    } else if ((r.status || '').includes('Catch-All') || (r.status || '').includes('⚠️')) {
      statusStyle = 'background:#fef3c7;color:#92400e;font-weight:700;';
    } else if ((r.status || '').includes('Verified') || (r.status || '').includes('✅')) {
      statusStyle = 'background:#dcfce7;color:#15803d;font-weight:700;';
    } else if ((r.status || '').includes('Bounced') || (r.status || '').includes('❌')) {
      statusStyle = 'background:#fee2e2;color:#991b1b;font-weight:700;';
    }

    const webLink = r.website ? '<a href="' + escHtml(r.website) + '" target="_blank" class="btn btn-secondary btn-sm" style="font-size:10px;padding:2px 6px;">Web 🌐</a>' : '';
    const liLink = r.linkedin ? '<a href="' + escHtml(r.linkedin) + '" target="_blank" class="btn btn-secondary btn-sm" style="font-size:10px;padding:2px 6px;">LinkedIn ↗</a>' : '';

    html += '<tr style="border-bottom:1px solid var(--border);">' +
      '<td style="padding:10px 12px;"><div style="font-weight:600;font-size:13px;">' + escHtml(r.company) + '</div><div style="font-size:11px;color:var(--text-3);margin-top:2px;">' + escHtml(r.niche) + '</div></td>' +
      '<td style="padding:10px 12px;"><div style="font-weight:500;">' + escHtml(r.decision_maker) + '</div></td>' +
      '<td style="padding:10px 12px;"><code>' + escHtml(r.contact) + '</code></td>' +
      '<td style="padding:10px 12px;"><span style="display:inline-block;padding:3px 8px;border-radius:4px;font-size:11px;' + statusStyle + '">' + escHtml(r.status) + '</span></td>' +
      '<td style="padding:10px 12px;"><span style="font-size:11px;">' + escHtml(r.region) + '</span></td>' +
      '<td style="padding:10px 12px;"><b style="color:var(--accent);">' + escHtml(r.deal_size) + '</b></td>' +
      '<td style="padding:10px 12px;"><div style="display:flex;gap:4px;">' + webLink + liLink + '</div></td>' +
      '<td style="padding:10px 12px;max-width:240px;color:var(--text-2);font-size:11px;">' + escHtml(r.notes) + '</td>' +
      '</tr>';
  });

  html += '</tbody></table></div></div>';
  container.innerHTML = html;
}
