/* ==========================================================================
   STATE & DATA STORE — Real Injected Anomalies & RBAC Contract
   ========================================================================== */

const APP_STATE = {
  activeRole: 'vp_sales', // 'vp_sales' or 'supply_planner'
  activeAnomalyKey: 'revenue_anom_FOODS_3_090_CA_2012-11-23', // real supply-constraint anomaly, set by loadRealScenarioCards() on load
  activeTimeRange: 'all',
  activeTab: 'overview',
  isDrawerOpen: false,
  isGraphOpen: false,
  openPvmFactor: null
};

// Write-through cache for fetched anomaly details (see apiClient.fetchAnomalyDetail,
// openInvestigationDrawer, selectScenario) -- populated entirely from real backend
// data, never seeded with mock content.
const ANOMALY_DATASET = {};
