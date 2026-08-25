/* ==========================================================================
   CHARTS & VISUALIZATIONS JS MODULE (Chart.js 4.4 Engine)
   ========================================================================== */

let mainRevChartInstance = null;
let gaugeChartInstance = null;
let LIVE_ANOMALY_NODES = {}; // chart point index -> real graph node id, for click-to-query

const LIVE_QUERY_DEFAULTS = { item: 'FOODS_3_090', state: 'CA' };

async function initRevenueChart(rangeKey = 'all') {
  const canvas = document.getElementById('mainRevenueCanvas');
  if (!canvas) return;

  let series;
  try {
    const res = await fetch(
      `${API_CONFIG.baseUrl}/api/history?item=${LIVE_QUERY_DEFAULTS.item}&state=${LIVE_QUERY_DEFAULTS.state}&year=${rangeKey}`,
      { signal: AbortSignal.timeout(5000) }
    );
    series = res.ok ? await res.json() : null;
  } catch (err) {
    series = null;
  }
  if (!series || series.error) {
    showAppToast('Could not load revenue history -- is the backend running?');
    return;
  }

  const labels = series.map(r => r.date);
  const values = series.map(r => r.revenue);

  LIVE_ANOMALY_NODES = {}; // rebuilt below from this real series
  const pointBgColors = series.map(r => r.is_anomaly ? '#ef4444' : 'transparent');
  const pointBorderColors = series.map(r => r.is_anomaly ? '#ffffff' : 'transparent');
  const pointRadii = series.map(r => r.is_anomaly ? 7 : 2);
  const pointHoverRadii = series.map(r => r.is_anomaly ? 10 : 6);
  series.forEach((r, i) => { if (r.is_anomaly && r.node_id) LIVE_ANOMALY_NODES[i] = r.node_id; });

  if (mainRevChartInstance) {
    mainRevChartInstance.destroy();
  }

  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 240);
  gradient.addColorStop(0, 'rgba(255, 255, 255, 0.05)');
  gradient.addColorStop(0.85, 'rgba(255, 255, 255, 0.005)');
  gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');

  mainRevChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        borderColor: '#ffffff',
        borderWidth: 1.5,
        fill: true,
        backgroundColor: gradient,
        tension: 0.42,
        pointBackgroundColor: pointBgColors,
        pointBorderColor: pointBorderColors,
        pointBorderWidth: 2,
        pointRadius: pointRadii,
        pointHoverRadius: pointHoverRadii,
        pointHoverBorderColor: '#ffffff',
        pointHoverBorderWidth: 2.5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: 700,
        easing: 'easeOutQuart'
      },
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a20',
          borderColor: '#373742',
          borderWidth: 1,
          padding: 12,
          cornerRadius: 8,
          titleFont: { size: 13, weight: 'bold', family: 'Inter' },
          bodyFont: { size: 12, family: 'Inter' },
          titleColor: '#ffffff',
          bodyColor: '#9ca3af',
          callbacks: {
            title(items) {
              const idx = items[0].dataIndex;
              return LIVE_ANOMALY_NODES[idx] ? `${labels[idx]}  •  Anomaly Detected` : labels[idx];
            },
            label(item) {
              return `  Revenue:  $${item.raw.toLocaleString()}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
          ticks: {
            color: '#6b7280',
            font: { size: 11, family: 'Inter' }
          }
        },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
          ticks: {
            color: '#6b7280',
            font: { size: 11, family: 'Inter' },
            callback: (v) => `$${v.toLocaleString()}`
          }
        }
      },
      onClick(evt, elements) {
        if (!elements || !elements.length) return;
        const idx = elements[0].index;
        const liveNodeId = LIVE_ANOMALY_NODES[idx];
        if (liveNodeId) {
          openInvestigationDrawer(liveNodeId);
        }
      }
    }
  });

  // Update big number + delta badge from the real series (last value vs first in range)
  const numEl = document.getElementById('revBigNumber');
  const deltaEl = document.getElementById('revDeltaBadge');
  if (numEl && values.length) numEl.textContent = values[values.length - 1].toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (deltaEl && values.length > 1) {
    const baseline = values[0];
    const pctChange = baseline ? ((values[values.length - 1] - baseline) / baseline) * 100 : 0;
    const isNeg = pctChange < 0;
    deltaEl.textContent = `${isNeg ? '▼' : '▲'} ${Math.abs(pctChange).toFixed(1)}%`;
    deltaEl.className = `viz-delta-badge ${isNeg ? 'negative' : 'positive'}`;
  }
}

async function setChartTimeRange(rangeKey, btnElement) {
  APP_STATE.activeTimeRange = rangeKey;
  document.querySelectorAll('.viz-filter-btn').forEach(btn => btn.classList.remove('active'));
  if (btnElement) btnElement.classList.add('active');
  await initRevenueChart(rangeKey);
}

/* Semicircular Gauge */
function initGaugeChart(score = 87) {
  const canvas = document.getElementById('confidenceGaugeCanvas');
  if (!canvas) return;

  if (gaugeChartInstance) {
    gaugeChartInstance.destroy();
  }

  const ctx = canvas.getContext('2d');
  gaugeChartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [score, 100 - score],
        backgroundColor: ['#10b981', '#121215'],
        borderWidth: 0,
        borderRadius: [2, 0]
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      circumference: 180,
      rotation: -90,
      cutout: '76%',
      animation: {
        animateRotate: true,
        duration: 900
      },
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false }
      }
    }
  });
}

/* PVM Waterfall Setup */
function getPvmColor(val) {
  if (val < 0) return '#ef4444';
  if (val > 0) return '#10b981';
  return '#718096';
}

function renderPvmWaterfall(anomalyKey = APP_STATE.activeAnomalyKey) {
  const anom = ANOMALY_DATASET[anomalyKey] || ANOMALY_DATASET[APP_STATE.activeAnomalyKey];
  const container = document.getElementById('pvmBarsContainer');
  if (!container || !anom) return;

  const factors = [
    { key: 'volume', label: 'Volume', data: anom.pvm.volume, color: getPvmColor(anom.pvm.volume.val) },
    { key: 'price', label: 'Price', data: anom.pvm.price, color: getPvmColor(anom.pvm.price.val) },
    { key: 'mix', label: 'Mix', data: anom.pvm.mix, color: getPvmColor(anom.pvm.mix.val) },
    { key: 'other', label: 'Other', data: anom.pvm.other, color: getPvmColor(anom.pvm.other.val) }
  ];

  const maxVal = Math.max(...factors.map(f => Math.abs(f.data.val)));

  container.innerHTML = factors.map(f => {
    const heightPx = Math.max(16, Math.round((Math.abs(f.data.val) / maxVal) * 120));
    const sign = f.data.val > 0 ? '+' : '';
    const formatted = `${sign}$${(f.data.val / 1000).toFixed(1)}k`;

    return `
      <div class="pvm-column-item" data-factor="${f.key}" onclick="togglePvmProductDrill('${f.key}')">
        <div class="pvm-val-tag" style="color: ${f.color}">${formatted}</div>
        <div class="pvm-bar-track">
          <div class="pvm-solid-bar" style="height: ${heightPx}px; background-color: ${f.color}; opacity: 0.9;"></div>
        </div>
        <div class="pvm-col-label">${f.label}</div>
        <div class="pvm-hover-card">
          <div class="pvm-tt-header">${f.label} Effect: ${formatted} (${f.data.pct})</div>
          <div class="pvm-tt-explanation">${f.data.expl}</div>
        </div>
      </div>
    `;
  }).join('');
}

function togglePvmProductDrill(factorKey) {
  const panel = document.getElementById('pvmExpandedPanel');
  const titleEl = document.getElementById('pvmPanelTitle');
  const listEl = document.getElementById('pvmDrillList');
  if (!panel || !titleEl || !listEl) return;

  if (APP_STATE.openPvmFactor === factorKey) {
    panel.classList.remove('open');
    APP_STATE.openPvmFactor = null;
    return;
  }

  APP_STATE.openPvmFactor = factorKey;
  const anom = ANOMALY_DATASET[APP_STATE.activeAnomalyKey];
  if (!anom) return;
  titleEl.textContent = `${factorKey.toUpperCase()} Variance — Underlying Product Breakdown`;

  listEl.innerHTML = anom.products.map(p => `
    <div class="pvm-drill-row">
      <div>
        <span class="pvm-drill-sku">${p.sku}</span>
        <span style="font-size: 11px; color: var(--text-tertiary); margin-left: 8px;">${p.status}</span>
      </div>
      <div style="font-size: 12px; color: var(--text-secondary);">${p.volumeDelta} volume</div>
      <div style="font-weight: 700; color: ${p.revenueImpact.startsWith('-') ? 'var(--accent-red)' : 'var(--accent-green)'}">
        ${p.revenueImpact}
      </div>
    </div>
  `).join('');

  panel.classList.add('open');
}

/* ==========================================================================
   LIVE STREAMING -- polls the backend for the next record and appends it to
   the existing revenue chart, simulating "as we get a new record". Paused
   automatically while the investigation drawer is open (see drawer.js).
   ========================================================================== */

const LIVE_STREAM_CONFIG = { pollMs: 2500, maxPoints: 40, intervalId: null };

function startLiveStream() {
  if (LIVE_STREAM_CONFIG.intervalId) return; // already running
  LIVE_STREAM_CONFIG.intervalId = setInterval(pollNextRecord, LIVE_STREAM_CONFIG.pollMs);
}

function stopLiveStream() {
  clearInterval(LIVE_STREAM_CONFIG.intervalId);
  LIVE_STREAM_CONFIG.intervalId = null;
}

async function pollNextRecord() {
  if (APP_STATE.isDrawerOpen || !mainRevChartInstance) return;
  try {
    const res = await fetch(`${API_CONFIG.baseUrl}/api/stream/next`, { signal: AbortSignal.timeout(2000) });
    if (!res.ok) return;
    const record = await res.json();
    if (record.error) return;
    appendLiveRecord(record);
  } catch (err) {
    // backend offline or unreachable this tick -- leave the chart as-is, try again next poll
  }
}

function appendLiveRecord(record) {
  const chart = mainRevChartInstance;
  const ds = chart.data.datasets[0];
  const labels = chart.data.labels;

  labels.push(record.date);
  ds.data.push(record.revenue);

  const idx = labels.length - 1;
  const isAnom = record.is_anomaly && record.node_id;
  ds.pointBackgroundColor[idx] = isAnom ? '#ef4444' : 'transparent';
  ds.pointBorderColor[idx] = isAnom ? '#ffffff' : 'transparent';
  ds.pointRadius[idx] = isAnom ? 7 : 2;
  ds.pointHoverRadius[idx] = isAnom ? 10 : 6;
  if (isAnom) LIVE_ANOMALY_NODES[idx] = record.node_id;

  if (labels.length > LIVE_STREAM_CONFIG.maxPoints) {
    labels.shift();
    ds.data.shift();
    ds.pointBackgroundColor.shift();
    ds.pointBorderColor.shift();
    ds.pointRadius.shift();
    ds.pointHoverRadius.shift();
    const shifted = {};
    Object.keys(LIVE_ANOMALY_NODES).forEach(k => {
      const n = parseInt(k, 10);
      if (n > 0) shifted[n - 1] = LIVE_ANOMALY_NODES[k];
    });
    LIVE_ANOMALY_NODES = shifted;
  }

  chart.update('none');

  const numEl = document.getElementById('revBigNumber');
  const deltaEl = document.getElementById('revDeltaBadge');
  if (numEl) numEl.textContent = record.revenue.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (deltaEl && ds.data.length > 1) {
    const baseline = ds.data[0];
    const pctChange = baseline ? ((record.revenue - baseline) / baseline) * 100 : 0;
    const isNeg = pctChange < 0;
    deltaEl.textContent = `${isNeg ? '▼' : '▲'} ${Math.abs(pctChange).toFixed(1)}%`;
    deltaEl.className = `viz-delta-badge ${isNeg ? 'negative' : 'positive'}`;
  }
}

/* ==========================================================================
   MANUAL DATE QUERY -- if the picked date isn't itself an anomaly, the
   backend returns that day's raw current stats instead (see
   resolve_anomaly_or_stats / build_current_stats_detail in api_server.py).
   ========================================================================== */

async function queryAnomalyByDate() {
  const input = document.getElementById('manualQueryDate');
  if (!input || !input.value) {
    showAppToast('Pick a date first');
    return;
  }
  try {
    const url = `${API_CONFIG.baseUrl}/api/query?date=${input.value}&item=${LIVE_QUERY_DEFAULTS.item}&state=${LIVE_QUERY_DEFAULTS.state}`;
    const res = await fetch(url, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) {
      showAppToast('No data for this item/state/date');
      return;
    }
    const result = await res.json();
    ANOMALY_DATASET[result.id] = result;
    if (result.category === 'No Anomaly Detected') {
      showAppToast(`No anomaly on ${input.value} -- showing that day's actual stats`);
    }
    openInvestigationDrawer(result.id);
  } catch (err) {
    showAppToast('Query failed -- is the backend running?');
  }
}

/* ==========================================================================
   TELEMETRY -- real measured values from /api/telemetry (see TELEMETRY /
   _record_telemetry in api_server.py), replacing the old hardcoded tiles.
   ========================================================================== */

async function loadTelemetry() {
  try {
    const res = await fetch(`${API_CONFIG.baseUrl}/api/telemetry`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) return;
    const t = await res.json();

    const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };

    set('teleSqlVal', t.sql_latency_ms != null ? `${t.sql_latency_ms}ms` : 'n/a');
    set('teleSqlSub', t.sample_size ? `Avg of last ${Math.min(t.sample_size, 20)} calls` : 'No calls yet');

    set('teleLlmVal', t.llm_latency_s != null ? `${t.llm_latency_s}s` : 'n/a');
    set('teleLlmSub', t.model);

    set('teleCostVal', t.token_cost_usd != null ? `$${t.token_cost_usd}` : 'n/a');
    set('teleCostSub', t.avg_tokens_per_call != null
      ? `${Math.round(t.avg_tokens_per_call)} avg tokens (est. cost)` : 'No chat calls yet');

    set('teleFreshVal', t.data_freshness_days != null ? `${t.data_freshness_days}d` : 'n/a');
    set('teleFreshSub', 'Fixed historical dataset, not live POS');
  } catch (err) {
    // backend offline this tick -- leave tiles as-is
  }
}
