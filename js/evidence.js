/* ==========================================================================
   EVIDENCE & KNOWLEDGE GRAPH JS MODULE
   ========================================================================== */

const KNOWLEDGE_GRAPH_RELATIONS = {
  all: [0, 1, 2],
  wh: [0, 1],
  tickets: [1],
  reviews: [2],
  sku: [0, 1, 2]
};

function renderEvidenceTimeline(anomalyKey = 'supply') {
  const anom = ANOMALY_DATASET[anomalyKey] || ANOMALY_DATASET.supply;
  const container = document.getElementById('evidenceTimelineDeck');
  if (!container) return;

  container.innerHTML = anom.evidence.map((ev, index) => `
    <div class="evidence-card-item scroll-reveal" id="evCard-${index}" onclick="toggleEvidenceAccordion(${index})">
      <div class="ev-node-bullet"></div>
      <div class="ev-card-surface">
        <div class="ev-card-header">
          <span class="ev-source-tag">${ev.source}</span>
          <span class="ev-similarity-badge ${ev.similarityTier}">Cosine Similarity: ${ev.similarity}</span>
        </div>
        <div class="ev-item-title">${ev.title}</div>
        <div class="ev-item-preview">${ev.preview}</div>
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
  `).join('');
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

function filterEvidenceByGraphNode(nodeKey) {
  const indices = KNOWLEDGE_GRAPH_RELATIONS[nodeKey] || [0, 1, 2];

  document.querySelectorAll('.evidence-card-item').forEach((card, i) => {
    if (indices.includes(i)) {
      card.style.opacity = '1';
      card.style.transform = 'translateX(6px)';
      setTimeout(() => { card.style.transform = 'translateX(0)'; }, 300);
    } else {
      card.style.opacity = '0.25';
    }
  });

  // Reset opacity after 3.5s
  setTimeout(() => {
    document.querySelectorAll('.evidence-card-item').forEach(card => {
      card.style.opacity = '1';
    });
  }, 3500);

  showAppToast(`Filtered evidence trail for node: ${nodeKey.toUpperCase()}`);
}
