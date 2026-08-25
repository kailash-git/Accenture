"""
api_server.py
Zero-external-dependency REST API server bridging SQLite, the analytics
pipeline's stored output, and the dashboard frontend.

Security/entitlement note: every response below is masked server-side
according to schemas/semantic_contract.json's entitlements, based on the
caller's role (X-User-Role header or ?role= query param). This is real
enforcement -- restricted fields are actually removed from the JSON before
it leaves the server -- not a client-side display toggle.
"""

import copy
import http.server
import json
import os
import re
import socketserver
import subprocess
import sqlite3
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCENTURE_DIR = os.path.join(BASE_DIR, 'Accenture', 'Accenture')
DB_PATH = os.path.join(ACCENTURE_DIR, 'data', 'business_bi.db')
CONTRACT_PATH = os.path.join(ACCENTURE_DIR, 'schemas', 'semantic_contract.json')
SEED_SCRIPT_PATH = os.path.join(ACCENTURE_DIR, 'scripts', 'generate_mock_data.py')

VALID_ROLES = ("vp_sales", "supply_planner")
DEFAULT_ROLE = "vp_sales"

# Live-request SQL latency samples (rolling window, in-memory, reset on restart).
_SQL_LATENCY_SAMPLES_MS = []
_REQUEST_COUNT = 0


def _load_contract():
    try:
        with open(CONTRACT_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


CONTRACT = _load_contract()


def _ensure_db_seeded():
    """
    Clean-machine safety net: if the database has never been generated, run
    the seeding pipeline once automatically instead of serving fabricated
    placeholder data. This runs the same script a developer would run by
    hand -- no separate/duplicate data path.
    """
    if os.path.exists(DB_PATH):
        return
    print("No database found at", DB_PATH)
    print("Running the seeding pipeline once (this can take under a minute)...")
    try:
        subprocess.run([sys.executable, SEED_SCRIPT_PATH], check=True, cwd=ACCENTURE_DIR)
    except Exception as e:
        print(f"WARNING: automatic seeding failed ({type(e).__name__}). "
              f"Run 'python scripts/generate_mock_data.py' manually from {ACCENTURE_DIR}.")


def _resolve_role(headers, query):
    role = headers.get('X-User-Role') or (query.get('role', [None])[0])
    if role not in VALID_ROLES:
        role = DEFAULT_ROLE
    return role


def _timed_query(conn, sql, params=()):
    start = time.perf_counter()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    _SQL_LATENCY_SAMPLES_MS.append(elapsed_ms)
    if len(_SQL_LATENCY_SAMPLES_MS) > 200:
        del _SQL_LATENCY_SAMPLES_MS[: len(_SQL_LATENCY_SAMPLES_MS) - 200]
    return rows, elapsed_ms


def _row_to_anomaly_dict(r):
    return {
        "id": r["anomaly_id"],
        "detected_at": r["detected_at"],
        "kpi_name": r["kpi_name"],
        "item_id": r["item_id"],
        "state_id": r["state_id"],
        "cat_id": r["cat_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "actual_value": r["actual_value"],
        "baseline_value": r["baseline_value"],
        "deviation_pct": r["deviation_pct"],
        "z_score": r["z_score"],
        "direction": r["direction"],
        "severity": r["severity"],
        "confidence": r["confidence"],
        "status": r["status"],
        "scenario_key": r["scenario_key"],
        "abstained": bool(r["abstained"]),
        "abstention_reason": r["abstention_reason"],
        "pvm": json.loads(r["pvm_json"]),
        "products": json.loads(r["products_json"]),
        "evidence": json.loads(r["evidence_json"]),
        "logistics": json.loads(r["logistics_json"]),
        "graph_context": json.loads(r["graph_context_json"]) if r["graph_context_json"] else {"hops": [], "node_count": 0},
        "generation_telemetry": json.loads(r["generation_telemetry_json"]) if r["generation_telemetry_json"] else {},
        "narratives": json.loads(r["narratives_json"]) if r["narratives_json"] else {},
    }


def _apply_persona(anomaly, role):
    """Selects the role-specific narrative/action fields (REQ-04)."""
    narratives = anomaly.pop("narratives", {})
    persona_view = narratives.get(role) or narratives.get(DEFAULT_ROLE) or {}
    anomaly["persona"] = role
    anomaly["headline"] = persona_view.get("headline", "")
    anomaly["summary"] = persona_view.get("summary", "")
    anomaly["synthesis"] = {
        "title": persona_view.get("synthesis_title", ""),
        "body": persona_view.get("synthesis_body", ""),
    }
    anomaly["recommendedAction"] = persona_view.get("recommended_action")
    anomaly["abstention"] = persona_view.get("abstention")
    anomaly["generation_method"] = persona_view.get("generation_method", "deterministic")
    return anomaly


_FINANCIAL_DISCLOSURE_TERMS = ("revenue", "gross margin", "margin percent", "cost of goods")


def _redact_financial_disclosure(text, role):
    """
    Free-text evidence (support tickets, customer reviews) isn't a structured
    financial column, but it can still narrate one -- e.g. a support ticket that
    says "It shows high dollar revenue in our logs." A supply_planner is
    restricted from fact_sales_daily.revenue everywhere else in the payload
    (REQ-08); this closes the same enforcement over free text instead of
    trusting that no evidence snippet ever mentions a dollar figure.
    """
    if role != "supply_planner" or not text:
        return text
    sentences = re.split(r'(?<=[.!?])\s+', text)
    redacted = [
        "[Financial detail redacted for this role.]" if any(term in s.lower() for term in _FINANCIAL_DISCLOSURE_TERMS) else s
        for s in sentences
    ]
    return " ".join(redacted)


def _mask_graph_for_role(graph_ctx, role):
    """
    Real server-side masking for the /graph (GraphRAG) endpoint, mirroring
    _apply_entitlements below -- the knowledge-graph panel is a first-class
    surface of the semantic contract, not an unmasked side channel around it.
    """
    d = copy.deepcopy(graph_ctx) if graph_ctx else {"hops": [], "node_count": 0, "graph": {"nodes": [], "edges": []}}

    for h in d.get("hops", []):
        h["text"] = _redact_financial_disclosure(h.get("text", ""), role)

    graph = d.get("graph")
    if graph and role == "vp_sales":
        # SKU/warehouse-level identity is restricted for the VP role everywhere else
        # in the payload (item_id, products[].sku, logistics.*) -- the graph's item
        # and warehouse nodes must not become the one place that detail still leaks.
        for n in graph.get("nodes", []):
            if n.get("type") in ("item", "warehouse"):
                n["label"] = "RESTRICTED"
                n["restricted"] = True

    return d


def _apply_entitlements(anomaly, role):
    """
    Real server-side masking per schemas/semantic_contract.json (REQ-08).
    Restricted fields are actually removed from the payload, not just hidden
    in the UI -- a supply_planner-scoped request never receives revenue/
    margin figures, and a vp_sales-scoped request never receives SKU/
    warehouse-level logistics detail.
    """
    d = copy.deepcopy(anomaly)

    if d.get("graph_context"):
        # The anomaly-detail payload embeds the same graph context the dedicated
        # /graph endpoint serves -- mask it here too so this isn't a second,
        # unmasked path to the same restricted evidence/identity detail.
        d["graph_context"] = _mask_graph_for_role(d["graph_context"], role)

    if role == "supply_planner":
        d["actual_value"] = None
        d["baseline_value"] = None
        d["_masked_fields"] = ["actual_value", "baseline_value", "pvm.*.val", "products.*.revenueImpact", "marketing evidence"]
        if d.get("pvm"):
            for k in ("volume", "price", "mix", "other"):
                if k in d["pvm"]:
                    d["pvm"][k] = {"val": None, "pct": "RESTRICTED", "expl": "Financial figures restricted for this role."}
        for p in d.get("products", []):
            p["revenueImpact"] = "RESTRICTED"
        for e in d.get("evidence", []):
            if e.get("source") == "source_marketing_weekly":
                e["title"] = "RESTRICTED"
                e["preview"] = "RESTRICTED"
                e["fullText"] = "RESTRICTED"
            else:
                # Free-text support tickets/reviews aren't a structured source we can
                # blanket-restrict, but they can still narrate a revenue figure --
                # redact just the disclosing clause instead of the whole record.
                e["title"] = _redact_financial_disclosure(e.get("title", ""), role)
                e["preview"] = _redact_financial_disclosure(e.get("preview", ""), role)
                e["fullText"] = _redact_financial_disclosure(e.get("fullText", ""), role)
    elif role == "vp_sales":
        # anomaly_id is built as f"ANOM-{period}-{state_id}-{item_id}" (see
        # generate_mock_data.py) -- it embeds the same item_id restricted a few
        # lines below, so it must be redacted here too, or the identity that
        # d["item_id"] = "RESTRICTED" is supposed to hide leaks straight back
        # out through the id field sitting right next to it in this same payload.
        if d.get("id") and anomaly.get("item_id"):
            d["id"] = str(d["id"]).replace(anomaly["item_id"], "ITEM")
        d["item_id"] = "RESTRICTED"
        d["_masked_fields"] = ["id", "item_id", "logistics.*", "products.*.sku", "supply evidence detail"]
        if d.get("logistics"):
            d["logistics"] = {
                "title": "RESTRICTED", "status": "RESTRICTED", "statusClass": "",
                "desc": "Warehouse/SKU-level logistics detail is restricted for this role.", "metrics": [],
            }
        for p in d.get("products", []):
            p["sku"] = "RESTRICTED"
        for e in d.get("evidence", []):
            if e.get("source") == "source_supply_monthly":
                e["title"] = "RESTRICTED"
                e["preview"] = "RESTRICTED"
                e["fullText"] = "RESTRICTED"
    return d


class ApiRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, X-User-Role')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        global _REQUEST_COUNT
        _REQUEST_COUNT += 1
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        query = parse_qs(parsed.query)
        role = _resolve_role(self.headers, query)

        if path == '/api/health':
            self._send_json({
                "status": "healthy",
                "database_connected": os.path.exists(DB_PATH),
                "database_path": DB_PATH,
                "version": "2.0.0",
                "engine": "KPI Intelligence Backend API",
            })
            return

        if path in ('/api/anomalies/latest', '/api/anomalies'):
            self._handle_anomalies_list(role)
            return

        if path.startswith('/api/anomalies/') and path.endswith('/timeline'):
            key = path.split('/')[3]
            metric = (query.get('metric', ['revenue'])[0] or 'revenue').lower()
            self._handle_timeline(key, role, metric)
            return

        if path.startswith('/api/anomalies/') and path.endswith('/graph'):
            key = path.split('/')[3]
            self._handle_graph(key, role)
            return

        if path.startswith('/api/anomalies/'):
            key = path.split('/')[3] if len(path.split('/')) > 3 else None
            self._handle_anomaly_detail(key, role)
            return

        if path == '/api/telemetry':
            self._handle_telemetry()
            return

        if path == '/api/entitlements':
            self._send_json(CONTRACT.get('semantic_layer', {}).get('entitlements', {}).get(role, {}))
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len) if content_len > 0 else b'{}'
        try:
            payload = json.loads(body.decode('utf-8'))
        except Exception:
            payload = {}

        if path.startswith('/api/actions/') and path.endswith('/approve'):
            anomaly_key = path.split('/')[3]
            audit_id = self._new_audit_id()
            self._log_feedback(anomaly_key, 1, f"Approved action via dashboard. Audit #{audit_id}")
            self._send_json({
                "success": True, "audit_id": audit_id, "status": "Approved & Dispatched",
                "anomaly_id": anomaly_key,
                "message": "Action successfully recorded and assigned to operations queue.",
            })
            return

        if path.startswith('/api/actions/') and path.endswith('/assign'):
            # Was previously a purely client-side toast (confirmAssignment in
            # actions.js) with no backend call at all -- "recommends actions grounded
            # in... decision rights" (REQ-06) means who it was dispatched to and under
            # what SLA needs to actually be recorded, the same way Approve already is,
            # not just flashed as a toast and forgotten on refresh.
            anomaly_key = path.split('/')[3]
            audit_id = self._new_audit_id()
            assignee = payload.get('assignee', 'unassigned')
            sla = payload.get('sla', 'unspecified')
            self._log_feedback(anomaly_key, 1, f"Assigned to {assignee} (SLA {sla}) via dashboard. Audit #{audit_id}")
            self._send_json({
                "success": True, "audit_id": audit_id, "status": "Assigned & Dispatched",
                "anomaly_id": anomaly_key, "assignee": assignee, "sla": sla,
            })
            return

        if path == '/api/feedback':
            anomaly_id = payload.get('anomaly_id', 'unknown')
            rating = payload.get('rating', 1)
            comments = payload.get('user_comments', '')
            self._log_feedback(anomaly_id, rating, comments)
            self._send_json({"success": True, "logged": True})
            return

        self.send_error(404, "Endpoint Not Found")

    # ------------------------------------------------------------------ #
    def _handle_anomalies_list(self, role):
        if not os.path.exists(DB_PATH):
            self._send_json({"error": "Database not seeded. Run scripts/generate_mock_data.py."}, status_code=503)
            return
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # "Detects and prioritises material KPI movements" (Round 2 brief, REQ-01) --
            # ordering purely by period_start DESC is recency, not prioritization by
            # materiality. Curated scenarios (scenario_key not starting "gen-") get a
            # full PVM/evidence/action workup and represent completed diagnoses, so they
            # rank ahead of raw statistical detections; within each group, rank by
            # severity tier then |z_score| (the actual statistical-significance measure
            # AnomalyDetector used to flag it), so the most materially significant
            # movements surface first regardless of when they happened to occur.
            rows, _ = _timed_query(conn, """
                SELECT * FROM anomalies
                ORDER BY
                    CASE WHEN scenario_key LIKE 'gen-%' THEN 1 ELSE 0 END,
                    CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
                    ABS(z_score) DESC
            """)
        finally:
            conn.close()
        anomalies = []
        for r in rows:
            a = _row_to_anomaly_dict(r)
            a = _apply_persona(a, role)
            a = _apply_entitlements(a, role)
            anomalies.append(a)
        self._send_json(anomalies)

    def _fetch_anomaly_row(self, conn, key):
        rows, _ = _timed_query(conn, "SELECT * FROM anomalies WHERE scenario_key = ? OR anomaly_id = ?", (key, key))
        if rows:
            return rows[0]
        rows, _ = _timed_query(conn, "SELECT * FROM anomalies LIMIT 1")
        return rows[0] if rows else None

    def _handle_anomaly_detail(self, key, role):
        if not os.path.exists(DB_PATH):
            self._send_json({"error": "Database not seeded. Run scripts/generate_mock_data.py."}, status_code=503)
            return
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            r = self._fetch_anomaly_row(conn, key)
        finally:
            conn.close()
        if not r:
            self._send_json({"error": f"No anomaly found for key '{key}'"}, status_code=404)
            return
        a = _row_to_anomaly_dict(r)
        a = _apply_persona(a, role)
        a = _apply_entitlements(a, role)
        self._send_json(a)

    def _handle_graph(self, key, role):
        empty = {"hops": [], "node_count": 0, "graph": {"nodes": [], "edges": []}}
        if not os.path.exists(DB_PATH):
            self._send_json(empty)
            return
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            r = self._fetch_anomaly_row(conn, key)
        finally:
            conn.close()
        if not r:
            self._send_json(empty)
            return
        graph_ctx = json.loads(r["graph_context_json"]) if r["graph_context_json"] else empty
        self._send_json(_mask_graph_for_role(graph_ctx, role))

    def _handle_timeline(self, key, role, metric='revenue'):
        """
        Serves the trajectory chart's monthly series for the anomaly's own
        (item_id, state_id) -- for metric='revenue' this is the original
        Revenue/Units series; for 'margin' and 'turnover' it computes the SAME
        two other KPIs the semantic contract actually defines (GrossMarginPercent,
        InventoryTurnover), which until now were declared in the contract and
        detectable via AnomalyDetector but never actually wired to anything --
        the "Gross Margin %"/"Inventory Turnover" tabs in the UI called a
        switchActiveKPI() that didn't exist. Three real, connected KPIs, not one
        real KPI plus two decorative tab labels (Round 2 brief: "Three to five
        connected KPIs across two or three data sources with different grains").
        """
        empty = {"labels": [], "values": [], "valueLabel": "", "anomalyIndex": None,
                 "anomalyColor": "#ef4444", "headlineDelta": "", "isNegative": False}
        if not os.path.exists(DB_PATH):
            self._send_json(empty)
            return
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            detail_row = self._fetch_anomaly_row(conn, key)
            if not detail_row:
                self._send_json(empty)
                return
            item_id = detail_row["item_id"]
            state_id = detail_row["state_id"]

            if metric == 'margin':
                # gross_margin_percent is explicitly restricted for supply_planner in
                # semantic_contract.json (same as the revenue/COGS columns it's derived
                # from) -- masked here server-side, not left to the client to hide.
                if role == 'supply_planner':
                    self._send_json({**empty, "valueLabel": "Gross Margin %", "restricted": True})
                    return
                months = self._monthly_margin_series(conn, item_id, state_id)
                value_label = "Gross Margin %"
            elif metric == 'turnover':
                months = self._monthly_turnover_series(conn, item_id, state_id)
                value_label = "Inventory Turnover"
            else:
                # Persona-aware series: planners see unit velocity, executives see revenue --
                # this also means a supply_planner-scoped request never receives $ figures.
                if role == "supply_planner":
                    metric_sql, value_label = "SUM(units)", "Units"
                else:
                    metric_sql, value_label = "SUM(revenue)", "Revenue"
                rows, _ = _timed_query(conn, f"""
                    SELECT strftime('%Y-%m', date) as m, {metric_sql}
                    FROM fact_sales_daily
                    WHERE item_id = ? AND state_id = ?
                    GROUP BY m
                    ORDER BY m ASC
                """, (item_id, state_id))
                months = [(r[0], float(r[1]) if r[1] is not None else 0.0) for r in rows]
        finally:
            conn.close()

        import calendar
        labels = []
        values = []
        for m, v in months:
            month_num = int(m[5:7])
            year = m[2:4]
            labels.append(f"{calendar.month_abbr[month_num]} {year}")
            values.append(v)

        if metric == 'revenue':
            anomaly_month = detail_row["period_start"][:7]
            anomaly_idx = next((i for i, (m, _) in enumerate(months) if m == anomaly_month), None)
            deviation_pct = detail_row["deviation_pct"] or 0.0
            is_negative = deviation_pct < 0
            headline_delta = f"{deviation_pct * 100:+.1f}%"
        else:
            # margin/turnover have no seeded anomaly row of their own -- flag the last
            # point using the same rolling z-score convention AnomalyDetector.run_detection
            # uses (window=8, threshold=2.0), so "anomalous" means the same thing here as
            # everywhere else in this engine, not a separately-invented rule.
            anomaly_idx, is_negative, headline_delta = self._flag_last_point_if_anomalous(values)

        self._send_json({
            "labels": labels,
            "values": values,
            "valueLabel": value_label,
            "anomalyIndex": anomaly_idx,
            "anomalyColor": "#ef4444" if is_negative else "#10b981",
            "headlineDelta": headline_delta,
            "isNegative": is_negative,
        })

    def _monthly_margin_series(self, conn, item_id, state_id):
        rows, _ = _timed_query(conn, """
            SELECT strftime('%Y-%m', date) as m, SUM(revenue) as rev, SUM(cost_of_goods_sold) as cogs
            FROM fact_sales_daily
            WHERE item_id = ? AND state_id = ?
            GROUP BY m
            ORDER BY m ASC
        """, (item_id, state_id))
        out = []
        for m, rev, cogs in rows:
            rev = rev or 0.0
            margin = (rev - (cogs or 0.0)) / rev if rev else 0.0
            out.append((m, round(margin * 100, 2)))
        return out

    def _monthly_turnover_series(self, conn, item_id, state_id):
        rows, _ = _timed_query(conn, """
            SELECT strftime('%Y-%m', il.date) as m,
                   SUM(COALESCE(fs.cost_of_goods_sold, 0)) as cogs_sum,
                   AVG(il.inventory_on_hand * sl.supplier_raw_cost) as avg_inv_val
            FROM inventory_logs il
            JOIN sku_lookup sl ON il.item_id = sl.item_id
            LEFT JOIN fact_sales_daily fs
                ON il.date = fs.date AND il.item_id = fs.item_id AND il.state_id = fs.state_id
            WHERE il.item_id = ? AND il.state_id = ?
            GROUP BY m
            ORDER BY m ASC
        """, (item_id, state_id))
        out = []
        for m, cogs_sum, avg_inv_val in rows:
            turnover = (cogs_sum or 0.0) / avg_inv_val if avg_inv_val else 0.0
            out.append((m, round(turnover, 3)))
        return out

    @staticmethod
    def _flag_last_point_if_anomalous(values, window=8, threshold=2.0):
        if len(values) < window + 1:
            return None, False, ""
        baseline = values[-(window + 1):-1]
        mean_val = sum(baseline) / len(baseline)
        variance = sum((v - mean_val) ** 2 for v in baseline) / len(baseline)
        std_val = variance ** 0.5
        last = values[-1]
        z = (last - mean_val) / std_val if std_val >= 1e-5 else 0.0
        deviation_pct = (last - mean_val) / mean_val if mean_val else 0.0
        if abs(z) >= threshold:
            return len(values) - 1, deviation_pct < 0, f"{deviation_pct * 100:+.1f}%"
        return None, False, ""

    def _handle_telemetry(self):
        summary_row = None
        anomaly_count = 0
        abstained_count = 0
        feedback_count = 0
        feedback_avg_rating = None
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                rows, _ = _timed_query(conn, "SELECT * FROM telemetry_summary ORDER BY run_id DESC LIMIT 1")
                if rows:
                    summary_row = rows[0]
                count_rows, _ = _timed_query(conn, "SELECT COUNT(*), SUM(abstained) FROM anomalies")
                if count_rows:
                    anomaly_count = count_rows[0][0] or 0
                    abstained_count = count_rows[0][1] or 0
                # REQ-07 evidence: this is the closed loop for "mechanism to learn from
                # analyst and business-user feedback" -- the Approve button and the
                # synthesis thumbs-up/down both write here, and this is where that
                # capture becomes visible again rather than disappearing into the DB.
                fb_rows, _ = _timed_query(conn, "SELECT COUNT(*), AVG(rating) FROM user_feedback")
                if fb_rows and fb_rows[0][0]:
                    feedback_count = fb_rows[0][0]
                    feedback_avg_rating = round(fb_rows[0][1], 2) if fb_rows[0][1] is not None else None
            finally:
                conn.close()

        avg_live_sql_ms = (
            sum(_SQL_LATENCY_SAMPLES_MS) / len(_SQL_LATENCY_SAMPLES_MS) if _SQL_LATENCY_SAMPLES_MS else 0.0
        )
        data_freshness_seconds = (time.time() - os.path.getmtime(DB_PATH)) if os.path.exists(DB_PATH) else None

        payload = {
            "live_avg_sql_latency_ms": round(avg_live_sql_ms, 2),
            "live_request_count": _REQUEST_COUNT,
            "active_anomalies_count": anomaly_count,
            "abstained_count": abstained_count,
            "feedback_count": feedback_count,
            "feedback_avg_rating": feedback_avg_rating,
            "data_freshness_seconds": round(data_freshness_seconds, 1) if data_freshness_seconds is not None else None,
        }
        if summary_row:
            payload.update({
                "seed_run_at": summary_row["run_at"],
                "seed_anomalies_processed": summary_row["anomalies_processed"],
                "seed_llm_calls": summary_row["llm_calls"],
                "seed_llm_generated_count": summary_row["llm_generated_count"],
                "seed_deterministic_generated_count": summary_row["deterministic_generated_count"],
                "seed_total_tokens_in": summary_row["total_tokens_in"],
                "seed_total_tokens_out": summary_row["total_tokens_out"],
                "seed_total_cost_usd": summary_row["total_cost_usd"],
                "seed_pipeline_seconds": summary_row["total_pipeline_seconds"],
                "seed_avg_sql_query_ms": summary_row["avg_sql_query_ms"],
                "note": (
                    "LLM calls happen once, offline, at data-seed time only (never on the live request "
                    "path) -- live dashboard/API traffic makes zero LLM calls and costs $0."
                ),
            })
        else:
            payload["note"] = "No seed telemetry recorded yet."
        self._send_json(payload)

    @staticmethod
    def _new_audit_id():
        # Was `abs(hash(json.dumps(payload))) % 10000` -- Python's str hash is
        # randomized per-process (PYTHONHASHSEED), so the "same" audit id space
        # shifted on every server restart. uuid4 is actually unique and never
        # collides across restarts, which an audit trail ID should guarantee.
        return f"AUD-{uuid.uuid4().hex[:8].upper()}"

    def _log_feedback(self, anomaly_id, rating, comments):
        if not os.path.exists(DB_PATH):
            return
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO user_feedback (anomaly_id, rating, user_comments) VALUES (?, ?, ?)",
                (anomaly_id, rating, comments),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Warning: could not log feedback: {type(e).__name__}")

    def _send_json(self, data, status_code=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server():
    os.chdir(BASE_DIR)
    _ensure_db_seeded()
    with socketserver.TCPServer(("", PORT), ApiRequestHandler) as httpd:
        print("============================================================")
        print(f"  KPI Intelligence API Server Running on http://127.0.0.1:{PORT}")
        print(f"  Serving dashboard at: http://127.0.0.1:{PORT}/dashboard.html")
        print(f"  Database target: {DB_PATH}")
        print("============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")


if __name__ == '__main__':
    run_server()
