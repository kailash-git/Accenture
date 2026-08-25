/* ==========================================================================
   EVIDENCE & KNOWLEDGE GRAPH JS MODULE
   ========================================================================== */

/* Relevance framing shown to the user -- the underlying cosine-similarity score
   (evidence_reconciler.py) still drives sort order and the tier-color coding,
   it's just never surfaced as a raw number. A tier + one plain-language reason
   is the actual answer to "why is this here," which a bare "0.47" is not. */
const _EV_RELEVANCE = {
  high: { badge: 'Strong Match', reason: 'Directly matches this anomaly\'s signature -- a primary explanation.' },
  medium: { badge: 'Possible Match', reason: 'Plausibly related -- a secondary signal worth a look.' },
  low: { badge: 'Background Only', reason: 'Context that happened to occur this period, but doesn\'t explain the anomaly.' },
};

function renderEvidenceTimeline(anomalyKey = 'supply') {
  const anom = ANOMALY_DATASET[anomalyKey] || ANOMALY_DATASET.supply;
  const container = document.getElementById('evidenceTimelineDeck');
  if (!container) return;

  container.innerHTML = anom.evidence.map((ev, index) => {
    const rel = _EV_RELEVANCE[ev.similarityTier] || _EV_RELEVANCE.low;
    return `
    <div class="evidence-card-item scroll-reveal" id="evCard-${index}" onclick="toggleEvidenceAccordion(${index})">
      <div class="ev-node-bullet"></div>
      <div class="ev-card-surface">
        <div class="ev-card-header">
          <span class="ev-source-tag">${ev.type}</span>
          <span class="ev-similarity-badge ${ev.similarityTier}">${rel.badge}</span>
        </div>
        <div class="ev-item-title">${ev.title}</div>
        <div class="ev-item-preview">${ev.preview}</div>
        <div class="ev-relevance-reason">${rel.reason}</div>
        <div class="ev-full-transcript-panel" id="evTranscript-${index}">
          <div class="ev-meta-table">
            <div class="ev-meta-col">
              <div class="evm-label">Timestamp</div>
              <div class="evm-val">${ev.date}</div>
            </div>
            <div class="ev-meta-col">
              <div class="evm-label">Source Classification</div>
              <div class="evm-val">${ev.type}</div>
            </div>
          </div>
          <div class="ev-full-text-box">
            ${ev.fullText}
          </div>
        </div>
      </div>
    </div>
  `;
  }).join('');

  // Re-renders happen only in direct response to a user click (selecting a
  // scenario) -- the deck is already on-screen when this runs, so reveal
  // immediately rather than waiting on an IntersectionObserver. The observer
  // exists to progressively reveal content on the *initial* scroll-driven
  // page load; re-observing a freshly injected node here was unreliable in
  // practice and left every re-rendered card stuck at opacity:0.
  container.querySelectorAll('.scroll-reveal').forEach(el => el.classList.add('revealed'));
}

function toggleEvidenceAccordion(index) {
  const item = document.getElementById(`evCard-${index}`);
  if (!item) return;

  const isExpanded = item.classList.contains('expanded');
  // Close any open item
  document.querySelectorAll('.evidence-card-item').forEach(el => el.classList.remove('expanded'));

  if (!isExpanded) {
    item.classList.add('expanded');
  }
}

function toggleKnowledgeGraph() {
  const panel = document.getElementById('knowledgeGraphPanel');
  const arrow = document.getElementById('kgToggleArrow');
  if (!panel || !arrow) return;

  APP_STATE.isGraphOpen = !APP_STATE.isGraphOpen;
  panel.classList.toggle('open', APP_STATE.isGraphOpen);
  arrow.classList.toggle('open', APP_STATE.isGraphOpen);
}

