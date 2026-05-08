/**
 * auth.js — DNV Bastion Portal
 * Handles: sign-in modal, user identity chip, timezone detection, timestamp formatting.
 * Loaded by every page. Injects its own CSS. No external dependencies.
 */
(function () {
  'use strict';

  // ── CSS ────────────────────────────────────────────────────────────────────
  const CSS = `
  /* ── Auth modal overlay ── */
  #auth-overlay {
    position: fixed; inset: 0; z-index: 9000;
    background: rgba(7,10,20,0.92);
    display: flex; align-items: center; justify-content: center;
    backdrop-filter: blur(4px);
  }
  #auth-overlay.hidden { display: none; }
  #auth-box {
    background: #111827; border: 1px solid #1E2D45;
    border-radius: 8px; padding: 36px 40px; width: 380px;
    box-shadow: 0 24px 64px rgba(0,0,0,0.6);
  }
  #auth-box .auth-logo {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 18px; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: #E8ECF0; margin-bottom: 4px;
  }
  #auth-box .auth-logo span { color: #6B7280; font-weight: 400; }
  #auth-box .auth-sub {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; color: #6B7280; margin-bottom: 28px;
    letter-spacing: 0.04em;
  }
  #auth-box .auth-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; color: #6B7280; letter-spacing: 0.08em;
    text-transform: uppercase; margin-bottom: 5px;
  }
  #auth-box .auth-field {
    width: 100%; background: #1A2234; border: 1px solid #1E2D45;
    color: #E8ECF0; font-family: 'IBM Plex Mono', monospace;
    font-size: 13px; padding: 8px 12px; border-radius: 4px;
    margin-bottom: 18px; outline: none;
    transition: border-color .15s;
  }
  #auth-box .auth-field:focus { border-color: #2563EB; }
  #auth-box .auth-tz {
    font-family: 'IBM Plex Mono', monospace; font-size: 10px;
    color: #4B5563; margin-top: -14px; margin-bottom: 18px;
  }
  #auth-box .auth-btn {
    width: 100%; font-family: 'Barlow Condensed', sans-serif;
    font-size: 15px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; padding: 10px; border-radius: 4px;
    border: none; background: #2563EB; color: #fff;
    cursor: pointer; transition: background .15s;
  }
  #auth-box .auth-btn:hover { background: #1D4ED8; }
  #auth-box .auth-err {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    color: #EF4444; margin-bottom: 12px; display: none;
  }

  /* ── User chip in topbar ── */
  #auth-user-chip {
    display: flex; align-items: center; gap: 8px;
    margin-left: 8px; padding-left: 10px;
    border-left: 1px solid #1E2D45;
    flex-shrink: 0;
  }
  #auth-user-chip .chip-name {
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    color: #E8ECF0; white-space: nowrap;
  }
  #auth-user-chip .chip-role {
    font-family: 'Barlow Condensed', sans-serif; font-size: 10px;
    font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
    padding: 2px 6px; border-radius: 3px;
    background: rgba(37,99,235,0.15); color: #60A5FA;
    white-space: nowrap;
  }
  #auth-user-chip .chip-role.role-dnv  { background: rgba(245,158,11,0.15); color: #F59E0B; }
  #auth-user-chip .chip-role.role-admin { background: rgba(239,68,68,0.12); color: #EF4444; }
  #auth-user-chip .chip-tz {
    font-family: 'IBM Plex Mono', monospace; font-size: 10px;
    color: #4B5563; white-space: nowrap;
  }
  #auth-logout-btn {
    font-family: 'Barlow Condensed', sans-serif; font-size: 11px;
    font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
    padding: 3px 8px; border-radius: 3px;
    border: 1px solid #374151; background: transparent;
    color: #6B7280; cursor: pointer; white-space: nowrap;
    transition: all .15s;
  }
  #auth-logout-btn:hover { border-color: #EF4444; color: #EF4444; }
  `;

  const ROLES = [
    'Bastion Engineer',
    'Bastion Coordinator',
    'DNV Reviewer',
    'Admin',
  ];

  // ── Internal state ─────────────────────────────────────────────────────────
  let _identity   = { name: '', role: '', tz: '' };
  let _csrfToken  = '';

  // ── CSRF fetch interceptor ─────────────────────────────────────────────────
  // Wraps the native fetch so every POST/PUT/DELETE automatically carries the
  // X-CSRF-Token header. Pages need zero changes — existing fetch() calls work.
  const _nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    const method = (init.method || 'GET').toUpperCase();
    if (_csrfToken && ['POST','PUT','DELETE','PATCH'].includes(method)) {
      init.headers = Object.assign({}, init.headers || {}, {
        'X-CSRF-Token': _csrfToken,
      });
    }
    return _nativeFetch(input, init);
  };

  // ── Timezone utility ───────────────────────────────────────────────────────
  function _browserTZ() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone; }
    catch (e) { return 'UTC'; }
  }

  /**
   * window.formatTS(utcStr, opts?)
   * Converts a UTC timestamp string to the signed-in user's local timezone.
   * Safe to call before sign-in (falls back to browser TZ).
   */
  window.formatTS = function (utcStr, opts) {
    if (!utcStr || utcStr === '—') return '—';
    try {
      let s = String(utcStr).trim();
      // Ensure ISO format: replace space separator and append Z if no offset
      s = s.replace(' ', 'T');
      if (!s.endsWith('Z') && !s.includes('+') && !/[0-9]T[0-9].*-[0-9]/.test(s)) s += 'Z';
      const d = new Date(s);
      if (isNaN(d.getTime())) return utcStr;
      const tz = (_identity && _identity.tz) || _browserTZ();
      return d.toLocaleString(undefined, { timeZone: tz, ...(opts || {}) });
    } catch (e) { return utcStr; }
  };

  /**
   * window.formatDate(utcStr)
   * Date-only version of formatTS.
   */
  window.formatDate = function (utcStr) {
    if (!utcStr || utcStr === '—') return '—';
    try {
      let s = String(utcStr).trim().replace(' ', 'T');
      if (!s.endsWith('Z') && !s.includes('+')) s += 'T00:00:00Z';
      const d = new Date(s);
      if (isNaN(d.getTime())) return utcStr;
      const tz = (_identity && _identity.tz) || _browserTZ();
      return d.toLocaleDateString(undefined, { timeZone: tz });
    } catch (e) { return utcStr; }
  };

  /** window.getIdentity() — returns current {name, role, tz} */
  window.getIdentity = function () { return Object.assign({}, _identity); };

  // ── Inject CSS ─────────────────────────────────────────────────────────────
  function _injectCSS() {
    if (document.getElementById('auth-styles')) return;
    const el = document.createElement('style');
    el.id = 'auth-styles';
    el.textContent = CSS;
    document.head.appendChild(el);
  }

  // ── Modal ──────────────────────────────────────────────────────────────────
  function _buildModal() {
    if (document.getElementById('auth-overlay')) return;
    const tz = _browserTZ();

    const html = `
    <div id="auth-overlay">
      <div id="auth-box">
        <div class="auth-logo">DNV <span>BASTION</span> COORDINATOR</div>
        <div class="auth-sub">Sign in to continue — your name and role are recorded with every action.</div>
        <div class="auth-label">Full Name</div>
        <input id="auth-name-input" class="auth-field" type="text"
               placeholder="e.g. Larry Chase" autocomplete="name"
               onkeydown="if(event.key==='Enter')window._authSave()">
        <div class="auth-label">Role</div>
        <select id="auth-role-input" class="auth-field">
          <option value="">— Select your role —</option>
          ${ROLES.map(r => `<option value="${r}">${r}</option>`).join('')}
        </select>
        <div class="auth-tz">&#128205; Timezone auto-detected: <strong>${tz}</strong></div>
        <div class="auth-err" id="auth-err">Please enter your name and select a role.</div>
        <button class="auth-btn" onclick="window._authSave()">SIGN IN ›</button>
      </div>
    </div>`;

    const wrap = document.createElement('div');
    wrap.innerHTML = html;
    document.body.appendChild(wrap.firstElementChild);
  }

  window._authSave = async function () {
    const name = (document.getElementById('auth-name-input').value || '').trim();
    const role = (document.getElementById('auth-role-input').value || '').trim();
    const err  = document.getElementById('auth-err');

    if (!name || !role) { err.style.display = 'block'; return; }
    err.style.display = 'none';

    const tz = _browserTZ();
    try {
      await fetch('/api/identity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, role, tz }),
      });
      _identity = { name, role, tz };
      document.getElementById('auth-overlay').classList.add('hidden');
      _renderChip();
      await _fetchCSRFToken();
    } catch (e) {
      err.textContent = 'Could not save — server error.';
      err.style.display = 'block';
    }
  };

  // ── User chip ──────────────────────────────────────────────────────────────
  function _roleClass(role) {
    if (!role) return '';
    if (role.toLowerCase().includes('dnv')) return 'role-dnv';
    if (role.toLowerCase().includes('admin')) return 'role-admin';
    return '';
  }

  function _renderChip() {
    // Remove existing chip first
    const old = document.getElementById('auth-user-chip');
    if (old) old.remove();

    const topbar = document.getElementById('topbar');
    if (!topbar) return;

    const chip = document.createElement('div');
    chip.id = 'auth-user-chip';
    chip.innerHTML = `
      <span class="chip-name">&#128100; ${_esc(_identity.name)}</span>
      <span class="chip-role ${_roleClass(_identity.role)}">${_esc(_identity.role)}</span>
      <span class="chip-tz">${_esc(_identity.tz.split('/').pop().replace('_',' '))}</span>
      <button id="auth-logout-btn" onclick="window._authLogout()">SIGN OUT</button>
    `;
    topbar.appendChild(chip);
  }

  window._authLogout = async function () {
    if (!confirm('Sign out? You will need to enter your name and role again.')) return;
    try { await fetch('/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
    _identity = { name: '', role: '', tz: '' };
    const chip = document.getElementById('auth-user-chip');
    if (chip) chip.remove();
    _buildModal();
    const overlay = document.getElementById('auth-overlay');
    if (overlay) overlay.classList.remove('hidden');
  };

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Bootstrap ──────────────────────────────────────────────────────────────
  async function _init() {
    _injectCSS();

    // Fetch identity from server (reads cookie)
    let data = {};
    try {
      const res = await fetch('/api/identity');
      if (res.ok) data = await res.json();
    } catch (e) { /* server not ready */ }

    if (data.name && data.role) {
      // Already signed in
      _identity = {
        name: data.name,
        role: data.role,
        tz:   data.tz || _browserTZ(),
      };
      _renderChip();
      await _fetchCSRFToken();
    } else {
      // Need sign-in — CSRF token will be fetched after sign-in completes
      _buildModal();
    }
  }

  async function _fetchCSRFToken() {
    try {
      // Use the native fetch here so we don't create a circular dependency
      // before _csrfToken is populated.
      const res = await _nativeFetch('/api/csrf-token');
      if (res.ok) {
        const d = await res.json();
        _csrfToken = d.token || '';
      }
    } catch (e) { /* server not ready */ }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }
})();
