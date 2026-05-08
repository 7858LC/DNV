/* ============================================================
   Sentinel 001 — Experience Conflict System — Frontend JS
   All API calls target /api/experience/* endpoints.
   State is module-level; no external framework dependencies.
   ============================================================ */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let _pendingAnalysis = null;   // last analyze response
let _findings = [];            // all findings from GET /findings
let _selectedId = null;        // currently selected finding_id
let _filterStatus = '';
let _filterCriticality = '';
let _pendingFindingId = null;  // for modal ops (promote / flag-tq / add-disp)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function el(id) { return document.getElementById(id); }

function showSpinner(id)  { const s = el(id); if (s) s.style.display = 'inline-block'; }
function hideSpinner(id)  { const s = el(id); if (s) s.style.display = 'none'; }

function openModal(id)    { const m = el(id); if (m) { m.classList.add('open'); } }
function closeModal(id)   { const m = el(id); if (m) { m.classList.remove('open'); } }

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  const json = await r.json().catch(() => ({ error: 'Non-JSON response from server' }));
  if (!r.ok) throw new Error(json.error || `HTTP ${r.status}`);
  return json;
}

function classificationBadge(cls) {
  const map = {
    HARD_BLOCK:              '<span class="badge badge-hard">HARD BLOCK</span>',
    SOFT_CONFLICT:           '<span class="badge badge-soft">SOFT CONFLICT</span>',
    COMPATIBLE_WITH_MARGIN:  '<span class="badge badge-margin">COMPATIBLE / MARGIN</span>',
    COMPATIBLE_AT_LIMIT:     '<span class="badge badge-limit">COMPATIBLE / LIMIT</span>',
  };
  return map[cls] || `<span class="badge">${cls}</span>`;
}

function criticalityBadge(c) {
  const map = {
    CRITICAL:    'badge-critical',
    OPERATIONAL: 'badge-operational',
    PLANNING:    'badge-planning',
    DESIGN:      'badge-design',
  };
  return `<span class="badge ${map[c] || ''}">${c || '—'}</span>`;
}

function statusBadge(s) {
  const map = {
    Open:         'badge-status-open',
    Assigned:     'badge-status-assigned',
    InReview:     'badge-status-inreview',
    Closed:       'badge-status-closed',
    Deferred:     'badge-status-deferred',
    AcceptedRisk: 'badge-status-acceptedrisk',
  };
  return `<span class="badge ${map[s] || ''}">${s || '—'}</span>`;
}

function dispTypeBadge(t) {
  const map = {
    Engineering:         'badge-eng',
    Procedural:          'badge-proc',
    Scheduling:          'badge-sched',
    CustomerManagement:  'badge-custmgmt',
  };
  return `<span class="badge ${map[t] || ''}">${t || '—'}</span>`;
}

function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---------------------------------------------------------------------------
// Stats bar
// ---------------------------------------------------------------------------

function updateStatsBar(summary) {
  el('stat-total').textContent    = summary.total_findings    ?? '—';
  el('stat-open').textContent     = summary.open_count        ?? '—';
  el('stat-critical').textContent = summary.critical_count    ?? '—';
  el('stat-overdue').textContent  = (summary.overdue_dispositions || []).length;
  const sigEl   = el('stat-signals');
  const pendEl  = el('stat-pending-review');
  const tabAlert= el('tab-signals-alert');
  if (sigEl)    sigEl.textContent  = summary.design_signal_count ?? '—';
  if (pendEl)   pendEl.textContent = summary.pending_signal_review ? 'YES' : '—';
  if (tabAlert) tabAlert.style.display = summary.pending_signal_review ? 'inline' : 'none';
}

// ---------------------------------------------------------------------------
// Panel 1 — Analysis results renderer
// ---------------------------------------------------------------------------

function renderAnalysisResults(data) {
  el('analysis-results').style.display = 'flex';

  // Criticality badge
  el('res-criticality-badge').innerHTML = criticalityBadge(data.criticality);

  // Dimensions
  const dims = data.dimensions_affected || [];
  el('res-dimensions').innerHTML = dims.map(d => `<span class="tag">${escHtml(d)}</span>`).join('');

  // Summary
  el('res-summary').textContent = data.summary || '';

  // Constraint checks
  const checks = data.single_dimension_checks || [];
  el('res-check-count').textContent = checks.length ? `(${checks.length})` : '';
  el('res-checks').innerHTML = checks.map(c => `
    <div class="check-item">
      <span class="con-id">${escHtml(c.constraint_id)}</span>
      <div class="con-text">
        ${classificationBadge(c.classification)}
        <div style="margin-top:3px;font-size:10px;color:var(--muted);">${escHtml(c.constraint_name)}</div>
        <div style="margin-top:2px;">${escHtml(c.explanation)}</div>
      </div>
    </div>
  `).join('');

  // Stacking risks
  const risks = data.stacking_risks || [];
  const stackSec = el('res-stacking-section');
  if (risks.length) {
    stackSec.style.display = '';
    el('res-stacking').innerHTML = risks.map(r => `<div class="risk-item">${escHtml(r)}</div>`).join('');
  } else {
    stackSec.style.display = 'none';
  }

  // Disposition options
  const dopts = data.disposition_options || [];
  el('res-dispositions').innerHTML = dopts.map(d => `
    <div class="disp-option">
      <div class="do-header">
        ${dispTypeBadge(d.type)}
      </div>
      <div class="do-desc">${escHtml(d.description)}</div>
      <div class="do-caveat">Does not resolve: ${escHtml(d.what_it_does_not_resolve)}</div>
      <div class="do-caveat">Residual risk: ${escHtml(d.residual_risk)}</div>
    </div>
  `).join('');
}

// ---------------------------------------------------------------------------
// Panel 2 — Findings list
// ---------------------------------------------------------------------------

function renderFindingsList() {
  const container = el('findings-list');
  let list = _findings.slice();

  if (_filterStatus)      list = list.filter(f => f.status === _filterStatus);
  if (_filterCriticality) list = list.filter(f => (f.conflict_analysis || {}).criticality === _filterCriticality);

  if (!list.length) {
    container.innerHTML = '<div class="empty-state">No findings match current filters.</div>';
    return;
  }

  container.innerHTML = list.map(f => {
    const ca = f.conflict_analysis || {};
    const disps = f.dispositions || [];
    const closed = disps.filter(d => d.status === 'Closed').length;
    const today = new Date().toISOString().slice(0,10);
    const hasOverdue = disps.some(d => d.status !== 'Closed' && d.planned_closure_date && d.planned_closure_date < today);
    return `
      <div class="finding-card ${f.finding_id === _selectedId ? 'selected' : ''}"
           data-id="${escHtml(f.finding_id)}" onclick="selectFinding('${escHtml(f.finding_id)}')">
        <div class="fc-header">
          <span class="fc-id">${escHtml(f.finding_id)}</span>
          ${criticalityBadge(ca.criticality)}
          ${statusBadge(f.status)}
          ${hasOverdue ? '<span class="overdue-dot" title="Overdue disposition"></span>' : ''}
        </div>
        <div class="fc-title">${escHtml(f.title)}</div>
        <div class="fc-meta">
          <span>${escHtml(f.created_date || '')}</span>
          ${disps.length ? `<span>DISPS ${closed}/${disps.length}</span>` : ''}
          ${f.action_tracker_ref ? `<span class="ref-badge ref-badge-act">${escHtml(f.action_tracker_ref)}</span>` : ''}
          ${f.tq_ref ? `<span class="ref-badge ref-badge-tq">${escHtml(f.tq_ref)}</span>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// ---------------------------------------------------------------------------
// Panel 3 — Finding detail
// ---------------------------------------------------------------------------

function selectFinding(id) {
  _selectedId = id;
  renderFindingsList();
  renderDetail();
}

function renderDetail() {
  const f = _findings.find(x => x.finding_id === _selectedId);
  if (!f) {
    el('detail-empty').style.display = '';
    el('detail-content').style.display = 'none';
    return;
  }
  el('detail-empty').style.display = 'none';
  const content = el('detail-content');
  content.style.display = 'flex';

  const ca = f.conflict_analysis || {};
  const checks = ca.single_dimension_checks || [];
  const disps  = f.dispositions || [];
  const today  = new Date().toISOString().slice(0,10);

  content.innerHTML = `

    <!-- Header -->
    <div class="detail-section">
      <div class="detail-section-title">
        <span>${escHtml(f.finding_id)} — ${escHtml(f.title)}</span>
        <select class="inline-edit" style="width:auto;font-size:11px;" onchange="patchFinding('${escHtml(f.finding_id)}','status',this.value)">
          ${['Open','Assigned','InReview','Closed','Deferred','AcceptedRisk'].map(s =>
            `<option${s===f.status?' selected':''}>${s}</option>`).join('')}
        </select>
      </div>
      <div class="detail-field">
        <div class="df-label">Customer Expectation</div>
        <div class="df-val">${escHtml(f.customer_expectation)}</div>
      </div>
      <div class="detail-field">
        <div class="df-label">Criticality</div>
        <div class="df-val">${criticalityBadge(ca.criticality)}</div>
      </div>
      <div class="detail-field">
        <div class="df-label">Dimensions Affected</div>
        <div class="df-val">${(f.dimensions_affected||[]).map(d=>`<span class="tag">${escHtml(d)}</span>`).join('')}</div>
      </div>
      <div class="detail-field">
        <div class="df-label">Created</div>
        <div class="df-val muted">${escHtml(f.created_date)} by ${escHtml(f.created_by)}</div>
      </div>
      ${(f.implied_assumptions||[]).length ? `
        <div class="detail-field">
          <div class="df-label">Implied Assumptions</div>
          ${f.implied_assumptions.map(a=>`<div class="df-val" style="margin-bottom:2px;">• ${escHtml(a)}</div>`).join('')}
        </div>` : ''}
    </div>

    <!-- Conflict analysis -->
    <div class="detail-section">
      <div class="detail-section-title">Conflict Analysis</div>
      ${checks.map(c=>`
        <div class="check-item">
          <span class="con-id">${escHtml(c.constraint_id)}</span>
          <div class="con-text">
            ${classificationBadge(c.classification)}
            <div style="margin-top:3px;font-size:10px;color:var(--muted);">${escHtml(c.constraint_name)}</div>
            <div style="margin-top:2px;font-size:11px;">${escHtml(c.explanation)}</div>
          </div>
        </div>`).join('')}
      ${(ca.stacking_risks||[]).length ? `
        <div style="margin-top:10px;">
          <div class="df-label">Stacking Risks</div>
          ${ca.stacking_risks.map(r=>`<div class="risk-item">${escHtml(r)}</div>`).join('')}
        </div>` : ''}
      ${ca.ai_reasoning ? `
        <button class="collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.textContent=this.nextElementSibling.classList.contains('open')?'Hide AI Reasoning':'Show AI Reasoning'">Show AI Reasoning</button>
        <div class="collapsible-body">
          <div style="font-size:11px;color:var(--muted);white-space:pre-wrap;">${escHtml(ca.ai_reasoning)}</div>
        </div>` : ''}
    </div>

    <!-- Dispositions -->
    <div class="detail-section">
      <div class="detail-section-title">
        <span>Dispositions (${disps.length})</span>
        <button class="btn btn-primary btn-sm" onclick="openAddDisposition('${escHtml(f.finding_id)}')">+ Add</button>
      </div>
      ${disps.length ? disps.map(d => {
        const overdue = d.status !== 'Closed' && d.planned_closure_date && d.planned_closure_date < today;
        return `
          <div class="disp-item" style="${overdue ? 'border-color:var(--red)' : ''}">
            <div class="di-header">
              <span class="di-id">${escHtml(d.disposition_id)}</span>
              ${dispTypeBadge(d.type)}
              ${overdue ? '<span class="badge badge-hard">OVERDUE</span>' : ''}
            </div>
            <div style="font-size:11px;color:var(--text);margin-bottom:8px;">${escHtml(d.description)}</div>
            <div class="di-fields">
              <div class="di-field">
                <div class="dif-label">Assignee</div>
                <input type="text" value="${escHtml(d.assignee||'')}"
                  onchange="patchDisposition('${escHtml(f.finding_id)}','${escHtml(d.disposition_id)}','assignee',this.value)">
              </div>
              <div class="di-field">
                <div class="dif-label">Status</div>
                <select onchange="patchDisposition('${escHtml(f.finding_id)}','${escHtml(d.disposition_id)}','status',this.value)">
                  ${['Open','InProgress','Closed','Deferred'].map(s=>
                    `<option${s===d.status?' selected':''}>${s}</option>`).join('')}
                </select>
              </div>
              <div class="di-field">
                <div class="dif-label">Planned Closure</div>
                <input type="date" value="${escHtml(d.planned_closure_date||'')}"
                  onchange="patchDisposition('${escHtml(f.finding_id)}','${escHtml(d.disposition_id)}','planned_closure_date',this.value)">
              </div>
              <div class="di-field">
                <div class="dif-label">Actual Closure</div>
                <input type="date" value="${escHtml(d.actual_closure_date||'')}"
                  onchange="patchDisposition('${escHtml(f.finding_id)}','${escHtml(d.disposition_id)}','actual_closure_date',this.value)">
              </div>
              <div class="di-field">
                <div class="dif-label">Verified By</div>
                <input type="text" value="${escHtml(d.verified_by||'')}"
                  onchange="patchDisposition('${escHtml(f.finding_id)}','${escHtml(d.disposition_id)}','verified_by',this.value)">
              </div>
              <div class="di-field">
                <div class="dif-label">Verified Date</div>
                <input type="date" value="${escHtml(d.verified_date||'')}"
                  onchange="patchDisposition('${escHtml(f.finding_id)}','${escHtml(d.disposition_id)}','verified_date',this.value)">
              </div>
            </div>
            ${d.what_it_does_not_resolve ? `
              <button class="collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.textContent=this.nextElementSibling.classList.contains('open')?'Hide Caveats':'Show Caveats'">Show Caveats</button>
              <div class="collapsible-body">
                <div class="df-label">Does Not Resolve</div>
                <div style="font-size:11px;color:var(--muted);">${escHtml(d.what_it_does_not_resolve)}</div>
                <div class="df-label" style="margin-top:6px;">Residual Risk</div>
                <div style="font-size:11px;color:var(--amber);">${escHtml(d.residual_risk||'—')}</div>
              </div>` : ''}
          </div>`;
      }).join('') : '<div class="empty-state" style="padding:12px 0;">No dispositions yet.</div>'}
    </div>

    <!-- Action Tracker integration -->
    <div class="detail-section">
      <div class="detail-section-title">Action Tracker</div>
      ${f.action_tracker_ref
        ? `<span class="ref-badge ref-badge-act">${escHtml(f.action_tracker_ref)}</span>
           <span style="font-size:11px;color:var(--muted);margin-left:8px;">Linked — visible in main dashboard</span>`
        : `<button class="btn btn-green btn-sm" onclick="openPromoteModal('${escHtml(f.finding_id)}')">Promote to Action Tracker</button>`}
    </div>

    <!-- TQ section -->
    <div class="detail-section">
      <div class="detail-section-title">Technical Query</div>
      ${f.tq_ref
        ? `<span class="ref-badge ref-badge-tq">${escHtml(f.tq_ref)}</span>
           <span style="font-size:11px;color:var(--muted);margin-left:8px;">TQ raised</span>`
        : (f.dnv_submittal_required
          ? `<button class="btn btn-amber btn-sm" onclick="openTqModal('${escHtml(f.finding_id)}')">Flag as TQ</button>`
          : `<span style="font-size:11px;color:var(--muted);">DNV submittal not required. </span>
             <button class="btn btn-muted btn-sm" onclick="openTqModal('${escHtml(f.finding_id)}')">Flag anyway</button>`)}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// API actions
// ---------------------------------------------------------------------------

async function patchFinding(id, field, value) {
  try {
    const updated = await api('PATCH', `/api/experience/findings/${id}`, { [field]: value });
    const idx = _findings.findIndex(f => f.finding_id === id);
    if (idx >= 0) _findings[idx] = updated;
    renderFindingsList();
    renderDetail();
  } catch (e) {
    alert(`Update failed: ${e.message}`);
  }
}

async function patchDisposition(findingId, dispId, field, value) {
  try {
    const updated = await api(
      'PATCH',
      `/api/experience/findings/${findingId}/dispositions/${dispId}`,
      { [field]: value }
    );
    const idx = _findings.findIndex(f => f.finding_id === findingId);
    if (idx >= 0) _findings[idx] = updated;
    renderFindingsList();
    renderDetail();
  } catch (e) {
    alert(`Update failed: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------
// Modal openers
// ---------------------------------------------------------------------------

function openAddDisposition(findingId) {
  _pendingFindingId = findingId;
  el('disp-type').value = 'Procedural';
  el('disp-desc').value = '';
  el('disp-not-resolve').value = '';
  el('disp-residual').value = '';
  el('disp-assignee').value = '';
  el('disp-planned-date').value = '';
  openModal('modal-add-disp');
}

function openPromoteModal(findingId) {
  _pendingFindingId = findingId;
  el('promote-owner').value = '';
  el('promote-due').value = '';
  openModal('modal-promote');
}

function openTqModal(findingId) {
  _pendingFindingId = findingId;
  el('tq-subject').value = '';
  el('tq-owner').value = '';
  openModal('modal-tq');
}

// ---------------------------------------------------------------------------
// Load all findings
// ---------------------------------------------------------------------------

async function loadFindings() {
  try {
    const data = await api('GET', '/api/experience/findings');
    _findings = data.findings || [];
    updateStatsBar(data.summary || {});
    renderFindingsList();
    if (_selectedId) renderDetail();
  } catch (e) {
    console.error('Failed to load findings:', e);
  }
}

// ---------------------------------------------------------------------------
// Stress test result renderer
// ---------------------------------------------------------------------------

function renderStressResult(result) {
  const panel = el('panel-discovery');
  let existing = el('stress-result-section');
  if (existing) existing.remove();

  const viabMap = { VIABLE: 'green', CONDITIONAL: 'amber', NOT_VIABLE: 'red' };
  const viab = result.overall_viability || 'UNKNOWN';
  const viabColor = viabMap[viab] || 'muted';

  const section = document.createElement('div');
  section.id = 'stress-result-section';
  section.className = 'result-section';
  section.innerHTML = `
    <div class="result-section-title">
      STRESS TEST RESULT
      <span class="badge" style="background:var(--${viabColor});color:${viabColor==='amber'?'var(--bg)':'#fff'}">${viab}</span>
    </div>
    <div class="summary-text" style="margin-bottom:10px;">${escHtml(result.summary||'')}</div>
    ${(result.critical_path||[]).length ? `
      <div class="df-label">Critical Failure Path</div>
      ${result.critical_path.map((s,i)=>`<div class="risk-item">${i+1}. ${escHtml(s)}</div>`).join('')}
    ` : ''}
    ${(result.conflict_register||[]).length ? `
      <div class="df-label" style="margin-top:8px;">Conflict Register (${result.conflict_register.length})</div>
      ${result.conflict_register.map(c=>`
        <div class="check-item">
          <span class="con-id">${escHtml(c.constraint_id)}</span>
          <div class="con-text">
            ${classificationBadge(c.classification)}
            <div style="margin-top:2px;font-size:11px;">${escHtml(c.explanation)}</div>
          </div>
        </div>`).join('')}
    ` : ''}
    ${(result.mitigation_register||[]).length ? `
      <div class="df-label" style="margin-top:8px;">Mitigations</div>
      ${result.mitigation_register.map(m=>`
        <div class="disp-option">
          <div class="do-desc">${escHtml(m.mitigation)}</div>
          <div class="do-caveat">Residual: ${escHtml(m.residual_risk)}</div>
        </div>`).join('')}
    ` : ''}
  `;

  const stressBtn = el('btn-stress-test').parentElement;
  stressBtn.insertAdjacentElement('beforebegin', section);
  section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ---------------------------------------------------------------------------
// Wire up events
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {

  // Filters
  el('filter-status').addEventListener('change', e => {
    _filterStatus = e.target.value; renderFindingsList();
  });
  el('filter-criticality').addEventListener('change', e => {
    _filterCriticality = e.target.value; renderFindingsList();
  });

  // Analyze
  el('btn-analyze').addEventListener('click', async () => {
    const expectation = el('inp-expectation').value.trim();
    if (!expectation) { alert('Enter a customer expectation first.'); return; }
    const context = el('inp-context').value.trim();
    const btn = el('btn-analyze');
    btn.disabled = true;
    showSpinner('spin-analyze');
    el('analysis-results').style.display = 'none';
    try {
      const result = await api('POST', '/api/experience/analyze', { expectation, context });
      _pendingAnalysis = result;
      renderAnalysisResults(result);
      el('analysis-results').style.display = 'flex';
    } catch (e) {
      alert(`Analysis failed: ${e.message}`);
    } finally {
      btn.disabled = false;
      hideSpinner('spin-analyze');
    }
  });

  // Save as Finding — open modal
  el('btn-save-finding').addEventListener('click', () => {
    if (!_pendingAnalysis) return;
    el('save-title').value = '';
    el('save-created-by').value = '';
    el('save-tags').value = '';
    el('save-dnv').value = 'false';
    openModal('modal-save');
  });

  el('modal-save-cancel').addEventListener('click', () => closeModal('modal-save'));

  el('modal-save-confirm').addEventListener('click', async () => {
    const title = el('save-title').value.trim();
    if (!title) { alert('Title is required.'); return; }
    showSpinner('spin-save');
    el('modal-save-confirm').disabled = true;
    try {
      const tags = el('save-tags').value.split(',').map(t => t.trim()).filter(Boolean);
      const body = {
        title,
        created_by: el('save-created-by').value.trim() || 'System',
        tags,
        dnv_submittal_required: el('save-dnv').value === 'true',
        customer_expectation: _pendingAnalysis.customer_expectation || '',
        implied_assumptions: _pendingAnalysis.implied_assumptions || [],
        dimensions_affected: _pendingAnalysis.dimensions_affected || [],
        conflict_analysis: {
          single_dimension_checks: _pendingAnalysis.single_dimension_checks || [],
          stacking_risks: _pendingAnalysis.stacking_risks || [],
          criticality: _pendingAnalysis.criticality || 'PLANNING',
          ai_reasoning: JSON.stringify(_pendingAnalysis, null, 2),
        },
      };
      const saved = await api('POST', '/api/experience/findings', body);
      _findings.push(saved);
      _selectedId = saved.finding_id;
      renderFindingsList();
      renderDetail();
      closeModal('modal-save');
      await loadFindings();
    } catch (e) {
      alert(`Save failed: ${e.message}`);
    } finally {
      hideSpinner('spin-save');
      el('modal-save-confirm').disabled = false;
    }
  });

  // Add disposition modal
  el('modal-disp-cancel').addEventListener('click', () => closeModal('modal-add-disp'));

  el('modal-disp-confirm').addEventListener('click', async () => {
    if (!_pendingFindingId) return;
    showSpinner('spin-disp');
    el('modal-disp-confirm').disabled = true;
    try {
      const body = {
        type: el('disp-type').value,
        description: el('disp-desc').value.trim(),
        what_it_does_not_resolve: el('disp-not-resolve').value.trim(),
        residual_risk: el('disp-residual').value.trim(),
        assignee: el('disp-assignee').value.trim(),
        planned_closure_date: el('disp-planned-date').value,
      };
      const updated = await api('POST', `/api/experience/findings/${_pendingFindingId}/dispositions`, body);
      const idx = _findings.findIndex(f => f.finding_id === _pendingFindingId);
      if (idx >= 0) _findings[idx] = updated;
      renderFindingsList();
      renderDetail();
      closeModal('modal-add-disp');
      await loadFindings();
    } catch (e) {
      alert(`Add disposition failed: ${e.message}`);
    } finally {
      hideSpinner('spin-disp');
      el('modal-disp-confirm').disabled = false;
    }
  });

  // Promote to action tracker modal
  el('modal-promote-cancel').addEventListener('click', () => closeModal('modal-promote'));

  el('modal-promote-confirm').addEventListener('click', async () => {
    if (!_pendingFindingId) return;
    const owner = el('promote-owner').value.trim();
    const due_date = el('promote-due').value;
    if (!owner || !due_date) { alert('Owner and due date are required.'); return; }
    showSpinner('spin-promote');
    el('modal-promote-confirm').disabled = true;
    try {
      const result = await api('POST', `/api/experience/findings/${_pendingFindingId}/promote`, { owner, due_date });
      const idx = _findings.findIndex(f => f.finding_id === _pendingFindingId);
      if (idx >= 0) _findings[idx] = result.finding;
      renderFindingsList();
      renderDetail();
      closeModal('modal-promote');
    } catch (e) {
      alert(`Promote failed: ${e.message}`);
    } finally {
      hideSpinner('spin-promote');
      el('modal-promote-confirm').disabled = false;
    }
  });

  // Flag TQ modal
  el('modal-tq-cancel').addEventListener('click', () => closeModal('modal-tq'));

  el('modal-tq-confirm').addEventListener('click', async () => {
    if (!_pendingFindingId) return;
    const subject = el('tq-subject').value.trim();
    if (!subject) { alert('Subject is required.'); return; }
    showSpinner('spin-tq');
    el('modal-tq-confirm').disabled = true;
    try {
      const result = await api('POST', `/api/experience/findings/${_pendingFindingId}/flag-tq`, {
        subject,
        response_owner: el('tq-owner').value.trim(),
      });
      const idx = _findings.findIndex(f => f.finding_id === _pendingFindingId);
      if (idx >= 0) _findings[idx] = result.finding;
      renderFindingsList();
      renderDetail();
      closeModal('modal-tq');
    } catch (e) {
      alert(`Flag TQ failed: ${e.message}`);
    } finally {
      hideSpinner('spin-tq');
      el('modal-tq-confirm').disabled = false;
    }
  });

  // Generate Use Cases
  el('btn-gen-usecases').addEventListener('click', async () => {
    const cat = el('sel-usecase-cat').value;
    if (!cat) { alert('Select a category first.'); return; }
    const btn = el('btn-gen-usecases');
    btn.disabled = true;
    showSpinner('spin-usecases');
    el('usecase-results').innerHTML = '';
    try {
      const result = await api('POST', '/api/experience/generate-usecases', { category: cat });
      const cases = result.use_cases || [];
      const riskColor = { HIGH: 'var(--red)', MEDIUM: 'var(--amber)', LOW: 'var(--green)' };
      el('usecase-results').innerHTML = cases.map(uc => `
        <div class="use-case-result">
          <div class="uc-title">
            <span style="color:${riskColor[uc.risk_level]||'var(--muted)'}">${escHtml(uc.risk_level)}</span>
            ${escHtml(uc.title)}
          </div>
          <div style="color:var(--muted);font-size:10px;">${escHtml(uc.description)}</div>
          ${uc.notes ? `<div style="color:var(--muted);font-size:10px;margin-top:2px;">${escHtml(uc.notes)}</div>` : ''}
        </div>
      `).join('');
    } catch (e) {
      el('usecase-results').innerHTML = `<div class="empty-state">Error: ${escHtml(e.message)}</div>`;
    } finally {
      btn.disabled = false;
      hideSpinner('spin-usecases');
    }
  });

  // Stress Test
  el('btn-stress-test').addEventListener('click', () => {
    el('stress-scenario').value = '';
    openModal('modal-stress');
  });

  el('modal-stress-cancel').addEventListener('click', () => closeModal('modal-stress'));

  el('modal-stress-confirm').addEventListener('click', async () => {
    const scenario = el('stress-scenario').value.trim();
    if (!scenario) { alert('Enter a scenario first.'); return; }
    showSpinner('spin-stress');
    el('modal-stress-confirm').disabled = true;
    try {
      const result = await api('POST', '/api/experience/stress-test', { scenario });
      closeModal('modal-stress');
      renderStressResult(result);
    } catch (e) {
      alert(`Stress test failed: ${e.message}`);
    } finally {
      hideSpinner('spin-stress');
      el('modal-stress-confirm').disabled = false;
    }
  });

  // Report link
  el('btn-report-link').addEventListener('click', async () => {
    openModal('modal-report');
    const box = el('report-link-box');
    box.innerHTML = 'Loading…';
    try {
      const data = await api('GET', '/api/experience/report-link');
      box.innerHTML = `<a href="${escHtml(data.url)}" target="_blank">${escHtml(data.url)}</a>`;
    } catch (e) {
      box.innerHTML = `Error: ${escHtml(e.message)}`;
    }
  });

  el('modal-report-close').addEventListener('click', () => closeModal('modal-report'));

  el('btn-copy-link').addEventListener('click', () => {
    const a = el('report-link-box').querySelector('a');
    if (a) navigator.clipboard.writeText(a.href).then(() => {
      el('btn-copy-link').textContent = 'Copied!';
      setTimeout(() => { el('btn-copy-link').textContent = 'Copy Link'; }, 2000);
    });
  });

  // Close modals on overlay click
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });

  // Resizable panels
  initResizablePanels();

  // Initial load
  loadFindings();
});

// ---------------------------------------------------------------------------
// Resizable panels
// ---------------------------------------------------------------------------

function initResizablePanels() {
  document.querySelectorAll('.drag-handle').forEach(handle => {
    handle.addEventListener('mousedown', e => {
      e.preventDefault();
      const left  = handle.previousElementSibling;
      const right = handle.nextElementSibling;
      const startX = e.clientX;
      const leftW0  = left.getBoundingClientRect().width;
      const rightW0 = right.getBoundingClientRect().width;
      const total   = leftW0 + rightW0;
      const MIN = 180;

      left.style.flex  = 'none';
      right.style.flex = 'none';
      left.style.width  = leftW0  + 'px';
      right.style.width = rightW0 + 'px';

      handle.classList.add('dragging');
      document.body.style.cursor     = 'col-resize';
      document.body.style.userSelect = 'none';

      const onMove = e => {
        const dx = e.clientX - startX;
        const newLeft = Math.min(Math.max(MIN, leftW0 + dx), total - MIN);
        left.style.width  = newLeft + 'px';
        right.style.width = (total - newLeft) + 'px';
      };

      const onUp = () => {
        handle.classList.remove('dragging');
        document.body.style.cursor     = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup',   onUp);
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
  });
}

// ===========================================================================
// DESIGN SIGNAL LAYER
// ===========================================================================

let _signals         = [];
let _selectedSignalId = null;
let _pendingSignalId  = null;

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

function switchRightTab(tab) {
  const isDetail = (tab === 'detail');
  el('panel-detail').style.display  = isDetail ? 'flex' : 'none';
  el('panel-signals').style.display = isDetail ? 'none'  : 'flex';
  el('tab-detail').classList.toggle('right-tab-active',  isDetail);
  el('tab-signals').classList.toggle('right-tab-active', !isDetail);
}

// ---------------------------------------------------------------------------
// Badge helpers
// ---------------------------------------------------------------------------

function signalTypeBadge(t) {
  const map = {
    DesignGap:           'badge-designgap',
    CapacityLimit:       'badge-capacitylimit',
    SinglePointOfFailure:'badge-spof',
    LatentRisk:          'badge-latentrisk',
  };
  return `<span class="badge ${map[t] || 'badge-designgap'}">${escHtml(t || 'DesignGap')}</span>`;
}

function signalStatusBadge(s) {
  const map = {
    Open:               'badge-sig-open',
    UnderReview:        'badge-underreview',
    DesignChangeRaised: 'badge-designchangeraised',
    Closed:             'badge-status-closed',
  };
  return `<span class="badge ${map[s] || 'badge-sig-open'}">${escHtml(s || 'Open')}</span>`;
}

// ---------------------------------------------------------------------------
// Render signals list
// ---------------------------------------------------------------------------

function renderSignalsList() {
  const container = el('signals-list');
  if (!_signals.length) {
    container.innerHTML = '<div class="empty-state">No design signals yet.<br>Click Compute to scan findings for engineering patterns.</div>';
    return;
  }
  container.innerHTML = _signals.map(s => {
    const cons = (s.affected_constraints || []).slice(0, 4);
    const extra = (s.affected_constraints || []).length - cons.length;
    return `
      <div class="signal-card ${s.signal_id === _selectedSignalId ? 'selected' : ''}"
           onclick="selectSignal('${escHtml(s.signal_id)}')">
        <div class="sc-header">
          <span class="sc-id">${escHtml(s.signal_id)}</span>
          ${signalTypeBadge(s.signal_type)}
          ${signalStatusBadge(s.status)}
          ${s.tq_ref ? `<span class="ref-badge ref-badge-tq">${escHtml(s.tq_ref)}</span>` : ''}
        </div>
        <div class="sc-title">${escHtml(s.title)}</div>
        <div class="sc-meta">
          ${cons.map(c => `<span class="tag">${escHtml(c)}</span>`).join('')}
          ${extra > 0 ? `<span class="tag">+${extra} more</span>` : ''}
          &nbsp;·&nbsp; ${(s.contributing_findings || []).length} finding${(s.contributing_findings||[]).length !== 1 ? 's' : ''}
        </div>
      </div>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// Signal detail
// ---------------------------------------------------------------------------

function selectSignal(id) {
  _selectedSignalId = id;
  renderSignalsList();
  renderSignalDetail();
  el('signal-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderSignalDetail() {
  const s   = _signals.find(x => x.signal_id === _selectedSignalId);
  const det = el('signal-detail');
  if (!s) { det.style.display = 'none'; return; }
  det.style.display = 'block';

  det.innerHTML = `
    <div class="detail-section">
      <div class="detail-section-title">
        <span>${escHtml(s.signal_id)} — ${escHtml(s.title)}</span>
        <select class="inline-edit" style="width:auto;font-size:11px;"
          onchange="patchSignal('${escHtml(s.signal_id)}','status',this.value)">
          ${['Open','UnderReview','DesignChangeRaised','Closed'].map(st =>
            `<option${st === s.status ? ' selected' : ''}>${st}</option>`).join('')}
        </select>
      </div>

      <div class="detail-field">
        <div class="df-label">Signal Type</div>
        <div class="df-val">${signalTypeBadge(s.signal_type)}</div>
      </div>

      <div class="detail-field">
        <div class="df-label">Description</div>
        <div class="df-val">${escHtml(s.description)}</div>
      </div>

      <div class="detail-field" style="border-left:3px solid var(--purple);padding-left:10px;margin-top:8px;">
        <div class="df-label">Engineering Implication</div>
        <div class="df-val">${escHtml(s.engineering_implication)}</div>
      </div>

      <div class="detail-field" style="margin-top:8px;">
        <div class="df-label">Recommended Action</div>
        <div class="df-val">${escHtml(s.recommended_action)}</div>
      </div>

      <div class="detail-field">
        <div class="df-label">Affected Constraints</div>
        <div class="df-val">${(s.affected_constraints||[]).map(c=>`<span class="tag">${escHtml(c)}</span>`).join('')}</div>
      </div>

      <div class="detail-field">
        <div class="df-label">Contributing Findings</div>
        <div class="df-val">${(s.contributing_findings||[]).map(f=>`<span class="tag" style="color:var(--amber);">${escHtml(f)}</span>`).join('')}</div>
      </div>

      <div class="detail-field">
        <div class="df-label">Trigger</div>
        <div class="df-val muted">${escHtml(s.trigger_threshold)}</div>
      </div>

      ${s.dnv_submittal_required ? `
      <div class="detail-field">
        <div class="df-val"><span class="badge badge-hard">DNV SUBMITTAL REQUIRED</span></div>
      </div>` : ''}

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;">
        <div>
          <div class="df-label">Assigned To</div>
          <input class="inline-edit" type="text" value="${escHtml(s.assigned_to||'')}"
            onchange="patchSignal('${escHtml(s.signal_id)}','assigned_to',this.value)"
            style="width:100%;">
        </div>
        <div>
          <div class="df-label">Target Date</div>
          <input class="inline-edit" type="date" value="${escHtml(s.target_date||'')}"
            onchange="patchSignal('${escHtml(s.signal_id)}','target_date',this.value)"
            style="width:100%;">
        </div>
      </div>

      <div class="btn-row" style="margin-top:10px;">
        ${!s.tq_ref
          ? `<button class="btn btn-amber btn-sm" onclick="openSignalTqModal('${escHtml(s.signal_id)}')">Flag TQ</button>`
          : `<span class="ref-badge ref-badge-tq">${escHtml(s.tq_ref)}</span>
             <span style="font-size:11px;color:var(--muted);margin-left:8px;">TQ raised</span>`}
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// API actions
// ---------------------------------------------------------------------------

async function patchSignal(id, field, value) {
  try {
    const updated = await api('PATCH', `/api/experience/design-signals/${id}`, { [field]: value });
    const idx = _signals.findIndex(s => s.signal_id === id);
    if (idx >= 0) _signals[idx] = updated;
    renderSignalsList();
    renderSignalDetail();
  } catch (e) {
    alert(`Signal update failed: ${e.message}`);
  }
}

async function loadSignals() {
  try {
    const data = await api('GET', '/api/experience/design-signals');
    _signals = data.signals || [];
    renderSignalsList();
    if (_selectedSignalId) renderSignalDetail();
  } catch (e) {
    console.error('Failed to load design signals:', e);
  }
}

function openSignalTqModal(signalId) {
  _pendingSignalId = signalId;
  el('signal-tq-subject').value = '';
  el('signal-tq-owner').value   = '';
  openModal('modal-signal-tq');
}

// ---------------------------------------------------------------------------
// Design Signal event wiring
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {

  el('btn-compute-signals').addEventListener('click', async () => {
    const btn = el('btn-compute-signals');
    btn.disabled = true;
    showSpinner('spin-compute-signals');
    el('signals-msg').textContent = 'Analysing findings for engineering patterns…';
    try {
      const result = await api('POST', '/api/experience/design-signals/compute');
      _signals = result.signals || [];
      renderSignalsList();
      const n = result.new_count || 0;
      const errs = (result.errors || []).length;
      el('signals-msg').textContent = n > 0
        ? `${n} new signal${n !== 1 ? 's' : ''} generated.${errs ? ` (${errs} error${errs>1?'s':''})` : ''}`
        : 'No new signals found.';
      await loadFindings();
    } catch (e) {
      el('signals-msg').textContent = `Error: ${e.message}`;
    } finally {
      btn.disabled = false;
      hideSpinner('spin-compute-signals');
    }
  });

  el('modal-signal-tq-cancel').addEventListener('click', () => closeModal('modal-signal-tq'));

  el('modal-signal-tq-confirm').addEventListener('click', async () => {
    const subject = el('signal-tq-subject').value.trim();
    if (!subject) { alert('Subject is required.'); return; }
    showSpinner('spin-signal-tq');
    el('modal-signal-tq-confirm').disabled = true;
    try {
      const result = await api('POST', `/api/experience/design-signals/${_pendingSignalId}/flag-tq`, {
        subject,
        response_owner: el('signal-tq-owner').value.trim(),
      });
      const idx = _signals.findIndex(s => s.signal_id === _pendingSignalId);
      if (idx >= 0) _signals[idx] = result.signal;
      renderSignalsList();
      renderSignalDetail();
      closeModal('modal-signal-tq');
    } catch (e) {
      alert(`Flag TQ failed: ${e.message}`);
    } finally {
      hideSpinner('spin-signal-tq');
      el('modal-signal-tq-confirm').disabled = false;
    }
  });

  loadSignals();
});
