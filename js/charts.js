/* ==========================================================================
   CHARTS & VISUALIZATIONS JS MODULE (Chart.js 4.4 Engine)
   ========================================================================== */

let mainRevChartInstance = null;
let gaugeChartInstance = null;

const REVENUE_TIMELINE_DATA = {
  all: {
    labels: ['Jan 12', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov 12', 'Dec', 'Jan 13', 'Feb', 'Mar', 'Apr', 'May 13', 'Jun', 'Jul', 'Aug 13'],
    values: [24200, 24800, 25100, 25600, 26200, 25800, 26900, 25200, 23800, 21400, 18200, 21100, 22800, 24100, 25400, 26200, 24900, 26800, 28400, 33200],
    headlineValue: '24,817',
    headlineDelta: '▼ 12.4%',
    isNegative: true,
    anomalies: {
      10: { key: 'supply', label: 'Supply Constraint (-$5.4k)', color: '#ef4444' },
      16: { key: 'billing', label: 'Billing Drift ($3.36)', color: '#f59e0b' },
      19: { key: 'pricecut', label: 'Price Cut (+42% Vol)', color: '#10b981' }
    }
  },
  '2012': {
    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    values: [24200, 24800, 25100, 25600, 26200, 25800, 26900, 25200, 23800, 21400, 18200, 21100],
    headlineValue: '21,950',
    headlineDelta: '▼ 18.2%',
    isNegative: true,
    anomalies: {
      10: { key: 'supply', label: 'Supply Constraint (-$5.4k)', color: '#ef4444' }
    }
  },
  '2013': {
    labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug'],
    values: [22800, 24100, 25400, 26200, 24900, 26800, 28400, 33200],
    headlineValue: '27,680',
    headlineDelta: '▲ 14.8%',
    isNegative: false,
    anomalies: {
      4: { key: 'billing', label: 'Billing Drift ($3.36)', color: '#f59e0b' },
      7: { key: 'pricecut', label: 'Price Cut (+42% Vol)', color: '#10b981' }
    }
  }
};

function initRevenueChart(rangeKey = 'all') {
  const canvas = document.getElementById('mainRevenueCanvas');
  if (!canvas) return;

  const dataset = REVENUE_TIMELINE_DATA[rangeKey];
  const anomalyMap = dataset.anomalies || {};

  // Point radii and color arrays
  const pointBgColors = dataset.values.map((_, i) => anomalyMap[i] ? anomalyMap[i].color : 'transparent');
  const pointBorderColors = dataset.values.map((_, i) => anomalyMap[i] ? '#ffffff' : 'transparent');
  const pointRadii = dataset.values.map((_, i) => anomalyMap[i] ? 7 : 2);
  const pointHoverRadii = dataset.values.map((_, i) => anomalyMap[i] ? 10 : 6);

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
      labels: dataset.labels,
      datasets: [{
        data: dataset.values,
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
              const anom = anomalyMap[idx];
              return anom ? `${dataset.labels[idx]}  •  ${anom.label}` : dataset.labels[idx];
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
            callback: (v) => `$${(v / 1000).toFixed(0)}k`
          }
        }
      },
      onClick(evt, elements) {
        if (!elements || !elements.length) return;
        const idx = elements[0].index;
        const anom = anomalyMap[idx];
        if (anom && anom.key) {
          openInvestigationDrawer(anom.key);
        }
      }
    }
  });

  // Update big number display
  const numEl = document.getElementById('revBigNumber');
  const deltaEl = document.getElementById('revDeltaBadge');
  if (numEl) numEl.textContent = dataset.headlineValue;
  if (deltaEl) {
    deltaEl.textContent = dataset.headlineDelta;
    deltaEl.className = `viz-delta-badge ${dataset.isNegative ? 'negative' : 'positive'}`;
  }
}

function setChartTimeRange(rangeKey, btnElement) {
  APP_STATE.activeTimeRange = rangeKey;
  document.querySelectorAll('.viz-filter-btn').forEach(btn => btn.classList.remove('active'));
  if (btnElement) btnElement.classList.add('active');
  initRevenueChart(rangeKey);
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

function renderPvmWaterfall(anomalyKey = 'supply') {
  const anom = ANOMALY_DATASET[anomalyKey] || ANOMALY_DATASET.supply;
  const container = document.getElementById('pvmBarsContainer');
  if (!container) return;

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
  const anom = ANOMALY_DATASET[APP_STATE.activeAnomalyKey] || ANOMALY_DATASET.supply;
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
