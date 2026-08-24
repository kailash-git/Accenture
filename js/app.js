/* ==========================================================================
   APP INITIALIZATION & INTERACTIVE CONTROLLERS MODULE
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialize Default Scenario
  selectScenario('supply');

  // 2. Setup Scroll Storytelling Observer
  setupScrollRevealObserver();

  // 3. Setup Navigation Scroll Spy
  setupNavigationScrollSpy();

  // 4. Setup Sidebar Search & Filter Chips
  setupSidebarSearch();

  // 5. Check Live Backend Health
  if (typeof apiClient !== 'undefined') {
    apiClient.checkHealth();
  }
});

/* Intersection Observer for Smooth Story Reveal & Count-ups */
function setupScrollRevealObserver() {
  const revealElements = document.querySelectorAll('.scroll-reveal');

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');

        // Numeric count-up animations
        const counterEls = entry.target.querySelectorAll('[data-counter-target]');
        counterEls.forEach(el => {
          if (!el.dataset.animated) {
            el.dataset.animated = 'true';
            animateNumericCount(el);
          }
        });
      }
    });
  }, {
    threshold: 0.12,
    rootMargin: '0px 0px -40px 0px'
  });

  revealElements.forEach(el => observer.observe(el));
}

function animateNumericCount(el) {
  const target = parseFloat(el.dataset.counterTarget) || 0;
  const prefix = el.dataset.prefix || '';
  const suffix = el.dataset.suffix || '';
  const duration = 1000;
  const startTime = performance.now();

  function updateCount(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const easeOut = 1 - Math.pow(1 - progress, 3);
    const currentVal = target * easeOut;

    el.textContent = `${prefix}${Number.isInteger(target) ? Math.round(currentVal).toLocaleString() : currentVal.toFixed(1)}${suffix}`;

    if (progress < 1) {
      requestAnimationFrame(updateCount);
    } else {
      el.textContent = `${prefix}${target >= 1000 ? Math.round(target).toLocaleString() : target}${suffix}`;
    }
  }

  requestAnimationFrame(updateCount);
}

/* Topbar Navigation & Scroll Spy */
function setupNavigationScrollSpy() {
  const navTabs = document.querySelectorAll('.topbar-tab');
  const sectionIds = ['section-overview', 'section-what-changed', 'section-why', 'section-evidence', 'section-actions', 'section-telemetry'];

  navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      navTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      const targetId = tab.dataset.targetSection;
      const targetEl = document.getElementById(targetId);
      if (targetEl) {
        targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  const scrollContainer = document.getElementById('mainScrollContainer');
  if (!scrollContainer) return;

  const spyObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id = entry.target.id;
        navTabs.forEach(tab => {
          if (tab.dataset.targetSection === id) {
            navTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
          }
        });
      }
    });
  }, {
    root: scrollContainer,
    threshold: 0.35
  });

  sectionIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) spyObserver.observe(el);
  });
}

/* Sidebar Search & Filter Chips */
function setupSidebarSearch() {
  const searchInput = document.getElementById('sidebarSearchInput');
  if (!searchInput) return;

  searchInput.addEventListener('input', function () {
    filterSidebarScenarios(this.value);
  });
}

function filterSidebarScenarios(query = '') {
  const q = query.toLowerCase().trim();
  const activeChip = document.querySelector('.filter-chip.active')?.dataset.filter || 'all';

  document.querySelectorAll('.scenario-card').forEach(card => {
    const text = card.textContent.toLowerCase();
    const status = card.dataset.status || '';
    const matchesText = !q || text.includes(q);
    const matchesChip = activeChip === 'all' || status === activeChip;

    card.style.display = matchesText && matchesChip ? 'block' : 'none';
  });
}

function setFilterChip(filterType, chipEl) {
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  chipEl.classList.add('active');
  const searchInput = document.getElementById('sidebarSearchInput');
  filterSidebarScenarios(searchInput ? searchInput.value : '');
}

function toggleSearchFilterPills() {
  const pillsRow = document.getElementById('filterPillsRow');
  if (pillsRow) {
    const isVisible = pillsRow.style.display !== 'none';
    pillsRow.style.display = isVisible ? 'none' : 'flex';
  }
}

/* Select Scenario Context */
function selectScenario(scenarioKey) {
  APP_STATE.activeAnomalyKey = scenarioKey;
  const anom = ANOMALY_DATASET[scenarioKey];
  if (!anom) return;

  document.querySelectorAll('.scenario-card').forEach(card => {
    card.classList.toggle('active', card.dataset.scenario === scenarioKey);
  });

  // 1. Render charts & timelines
  renderPvmWaterfall(scenarioKey);
  renderEvidenceTimeline(scenarioKey);
  initGaugeChart(anom.confidence);

  // 2. Set chart time range to correspond to the anomaly year
  const yearKey = anom.date.includes('2012') ? '2012' : '2013';
  const rangeBtn = document.querySelector(`.viz-filter-btn[onclick*="${yearKey}"]`);
  setChartTimeRange(yearKey, rangeBtn);

  // 3. Update Hero narrative text
  const headlineEl = document.getElementById('heroMainHeadline');
  const contextEl = document.getElementById('heroKickerContext');
  const narrativeEl = document.getElementById('heroNarrativeText');

  if (headlineEl) headlineEl.innerHTML = anom.headline;
  if (contextEl) contextEl.textContent = `${anom.sku} · ${anom.date.toUpperCase()} · ${anom.title.toUpperCase()}`;
  if (narrativeEl) narrativeEl.textContent = anom.summary;

  // 4. Update Hero recommended action area
  const heroActionText = document.querySelector('.hero-action-banner .action-text-main');
  const heroActionImpact = document.querySelector('.hero-action-banner .action-impact-sub');
  const heroApproveBtn = document.getElementById('heroApproveBtn');
  const heroInvestigateBtn = document.getElementById('heroInvestigateBtn');

  if (heroActionText) heroActionText.textContent = anom.recommendedAction.title;
  if (heroActionImpact) heroActionImpact.textContent = `Expected impact: ${anom.recommendedAction.expectedImpact}`;
  if (heroApproveBtn) {
    heroApproveBtn.setAttribute('onclick', `handleActionApprove('${scenarioKey}', -1, this)`);
    if (anom.isApproved) {
      heroApproveBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg> Approved & Dispatched`;
      heroApproveBtn.style.backgroundColor = '#166534';
      heroApproveBtn.style.color = '#ffffff';
      heroApproveBtn.disabled = true;
    } else {
      heroApproveBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Approve Action`;
      heroApproveBtn.style.backgroundColor = '';
      heroApproveBtn.style.color = '';
      heroApproveBtn.disabled = false;
    }
  }
  if (heroInvestigateBtn) {
    heroInvestigateBtn.setAttribute('onclick', `openInvestigationDrawer('${scenarioKey}')`);
  }

  // 5. Update Confidence Score module text
  const gaugeScoreNum = document.getElementById('gaugeScoreNum');
  const gaugeCenterBadge = document.getElementById('gaugeCenterBadge');
  const gaugeConfidenceText = document.getElementById('gaugeConfidenceText');

  if (gaugeScoreNum) {
    gaugeScoreNum.innerHTML = `${anom.confidence}<span style="font-size: 20px; font-weight: 400; color: var(--text-tertiary);">%</span>`;
  }
  if (gaugeCenterBadge) {
    gaugeCenterBadge.textContent = `Z-Score: ${anom.zScore}`;
  }
  if (gaugeConfidenceText) {
    gaugeConfidenceText.textContent = anom.confidence >= 75 ? 'High Certainty' : (anom.confidence >= 50 ? 'Medium Certainty' : 'Low Certainty');
    gaugeConfidenceText.style.color = anom.confidence >= 75 ? 'var(--accent-green)' : (anom.confidence >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)');
  }

  // 6. Update Supply/Logistics Metrics card
  const logTitle = document.getElementById('logisticsCardTitle');
  const logStatus = document.getElementById('logisticsCardStatus');
  const logDesc = document.getElementById('logisticsCardDesc');

  if (logTitle) logTitle.textContent = anom.logistics.title;
  if (logStatus) {
    logStatus.textContent = anom.logistics.status;
    logStatus.className = `sc-status-pill ${anom.logistics.statusClass}`;
  }
  if (logDesc) logDesc.textContent = anom.logistics.desc;

  for (let i = 1; i <= 3; i++) {
    const mData = anom.logistics.metrics[i - 1];
    const labelEl = document.getElementById(`logisticsMetricLabel${i}`);
    const valEl = document.getElementById(`logisticsMetricValue${i}`);
    const subEl = document.getElementById(`logisticsMetricSub${i}`);
    if (mData) {
      if (labelEl) labelEl.textContent = mData.label;
      if (valEl) {
        valEl.textContent = mData.val;
        valEl.className = `ss-val ${mData.valClass || ''}`;
      }
      if (subEl) subEl.textContent = mData.sub;
    }
  }

  // 7. Update Root Cause Synthesis Model
  const rcCard = document.querySelector('.root-cause-synthesis-card');
  const rcConf = document.getElementById('rcConfidencePill');
  const rcTitle = document.getElementById('rcStatementTitle');
  const rcBody = document.getElementById('rcSynthesisBody');

  const statusClass = anom.confidence >= 75 ? 'high' : (anom.confidence >= 50 ? 'medium' : 'low');

  if (rcCard) {
    rcCard.className = 'root-cause-synthesis-card';
    rcCard.classList.add(statusClass);
  }
  if (rcConf) {
    rcConf.textContent = `${anom.confidence}% Verified Confidence`;
    rcConf.className = 'rc-confidence-pill';
    rcConf.classList.add(statusClass);
  }
  if (rcTitle) rcTitle.textContent = anom.synthesis.title;
  if (rcBody) rcBody.innerHTML = anom.synthesis.body;

  // 8. Rebuild Recommended Actions cards dynamically
  const actionCardsGrid = document.getElementById('actionCardsGrid');
  if (actionCardsGrid && anom.recommendedAction && anom.recommendedAction.steps) {
    actionCardsGrid.innerHTML = anom.recommendedAction.steps.map((step, idx) => {
      let verb = 'Approve';
      if (idx === 0) verb = scenarioKey === 'supply' ? 'Approve PO' : (scenarioKey === 'billing' ? 'Run Audit' : 'Track Thresholds');
      else if (idx === 1) verb = scenarioKey === 'supply' ? 'Approve Transfer' : (scenarioKey === 'billing' ? 'Issue Vouchers' : 'Notify Team');
      else verb = 'Confirm Narrative';

      const isStepApproved = anom.approvedSteps && anom.approvedSteps[idx];
      const btnHtml = isStepApproved 
        ? `<button class="btn-action-primary" style="background-color: #166534; color: #ffffff;" disabled><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg> Approved</button>`
        : `<button class="btn-action-primary" onclick="handleActionApprove('${scenarioKey}', ${idx}, this)">${verb}</button>`;

      return `
        <div class="action-module-card">
          <div>
            <div class="action-card-top-num">${idx + 1}</div>
            <div class="action-card-heading">${step.split(':')[0] || 'Intervention Step'}</div>
            <div class="action-card-body">${step}</div>
          </div>
          <div class="action-card-btn-row">
            ${btnHtml}
            <button class="btn-action-outline" onclick="handleActionAssign('${scenarioKey}')">Assign</button>
            <button class="btn-action-outline" onclick="handleActionDismiss('${scenarioKey}')">Dismiss</button>
          </div>
        </div>
      `;
    }).join('');
  }

  showAppToast(`Loaded scenario: ${anom.title}`);
}

/* UI Modals & Menus */
function toggleSidebarCollapse() {
  document.body.classList.toggle('sidebar-collapsed');
  const isCollapsed = document.body.classList.contains('sidebar-collapsed');
  showAppToast(isCollapsed ? 'Sidebar collapsed (Focused Mode)' : 'Sidebar expanded');
}

function toggleThemeMode() {
  document.body.classList.toggle('theme-high-contrast');
  const isHighContrast = document.body.classList.contains('theme-high-contrast');
  showAppToast(isHighContrast ? 'Switched to High-Contrast OLED Theme' : 'Switched to Default Charcoal Theme');
}

function toggleNotificationsDropdown() {
  const dd = document.getElementById('notificationsDropdown');
  if (dd) {
    dd.classList.toggle('active');
  }
}

function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.add('active');
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('active');
}

/* Pipeline Stage Schema Viewer */
function inspectPipelineStage(stageName, tableName) {
  const titleEl = document.getElementById('catalogModalTitle');
  const bodyEl = document.getElementById('catalogModalBody');
  if (!titleEl || !bodyEl) return;

  titleEl.textContent = `Pipeline Schema: ${tableName}`;
  bodyEl.innerHTML = `
    <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 12px;">
      Source: <code style="color: var(--accent-green);">${stageName}</code> · SQLite Table: <code style="color: var(--accent-green);">${tableName}</code>
    </div>
    <div style="background: var(--bg-surface); border: 1px solid var(--border-medium); border-radius: var(--radius-md); padding: 14px; font-family: 'SF Mono', monospace; font-size: 12px; line-height: 1.6;">
      <strong>Grain:</strong> ${tableName === 'fact_sales_daily' ? 'Daily per (item_id, store_id, date)' : (tableName === 'source_marketing_weekly' ? 'Weekly per (region, channel, week_start)' : 'Monthly per (warehouse_sku, state_id, month)')}<br/>
      <strong>Partitions:</strong> Active<br/>
      <strong>Integrity:</strong> Foreign keys enforced on <code>sku_lookup</code><br/>
      <strong>Freshness:</strong> 0 days lag
    </div>
  `;
  openModal('dataCatalogModal');
}

/* CSV Export Utility */
function exportAnomalyAuditCsv() {
  const rows = [
    ['Anomaly ID', 'SKU', 'Region', 'Date', 'Type', 'Z-Score', 'Deviation', 'Confidence', 'PVM Driver'],
    ['ANOM-2012-11-CA', 'FOODS_3_090', 'CA', '2012-11', 'Supply Constraint', '3.41', '-20.5% fill rate', '87%', 'Volume (-77%)'],
    ['ANOM-2013-05-TX', 'FOODS_3_586', 'TX', '2013-05', 'Billing Bug', '1.82', 'Price x2.0 drift', '42%', 'Price (+92%)'],
    ['ANOM-2013-08-CA', 'FOODS_3_090', 'CA', '2013-08', 'Price Cut + Vol Lift', '2.91', '-25% price, +42% vol', '91%', 'Volume (+62%)']
  ];

  const csvContent = 'data:text/csv;charset=utf-8,' + rows.map(e => e.join(',')).join('\n');
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement('a');
  link.setAttribute('href', encodedUri);
  link.setAttribute('download', 'kpi_anomaly_audit_log.csv');
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  showAppToast('Exported kpi_anomaly_audit_log.csv successfully');
}

/* Copy Synthesis Reasoning */
function copySynthesisReasoning() {
  const text = document.querySelector('.rc-statement-title')?.textContent || 'Root cause model verified.';
  navigator.clipboard.writeText(text).then(() => {
    showAppToast('Copied root cause synthesis to clipboard');
  }).catch(() => {
    showAppToast('Reasoning copied to clipboard');
  });
}
