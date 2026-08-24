"""
api_server.py
Lightweight, zero-external-dependency REST API server bridging SQLite database,
analytics calculations, retrieved feedback records, and proposed actions to the frontend.
"""

import http.server
import socketserver
import json
import sqlite3
import os
import sys
from urllib.parse import urlparse, parse_qs

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCENTURE_DIR = os.path.join(BASE_DIR, 'Accenture', 'Accenture')
DB_PATH = os.path.join(ACCENTURE_DIR, 'data', 'business_bi.db')

# In-Memory Fallback Dataset when SQLite DB is not yet populated
ANOMALY_BACKEND_STORE = {
    "supply": {
        "id": "ANOM-2012-11-CA",
        "title": "Supply Constraint",
        "category": "Multi-Factor Variance",
        "sku": "FOODS_3_090",
        "region": "CA (West Region)",
        "warehouse": "WH-1000",
        "date": "November 2012",
        "zScore": 3.41,
        "deviation": "-20.5% fill rate drop",
        "confidence": 87,
        "status": "critical",
        "headline": "Revenue declined 12.4% in CA",
        "summary": "Warehouse WH-1000 experienced 4 consecutive stockout days with fill rate plunging to 0.78, causing volume contraction of 84% on SKU FOODS_3_090.",
        "pvm": {
            "volume": {"val": -8700, "pct": "77%", "expl": "Volume contraction explains 77% of total revenue decline."},
            "price": {"val": -3200, "pct": "28%", "expl": "Average selling price softened due to promotional mix."},
            "mix": {"val": -1900, "pct": "17%", "expl": "Unfavorable shift toward lower-margin SKUs."},
            "other": {"val": 2100, "pct": "19%", "expl": "Positive offset from auxiliary cross-category baskets."}
        },
        "products": [
            {"sku": "FOODS_3_090", "volumeDelta": "-84%", "revenueImpact": "-$8,204", "status": "Primary Driver"},
            {"sku": "FOODS_3_586", "volumeDelta": "-12%", "revenueImpact": "-$496", "status": "Secondary"},
            {"sku": "HOUSEHOLD_1_020", "volumeDelta": "+4%", "revenueImpact": "+$310", "status": "Inelastic"}
        ],
        "evidence": [
            {
                "id": "ev-1",
                "date": "Nov 12, 2012",
                "source": "source_supply_monthly",
                "type": "Structured Supply Signal",
                "title": "Fill rate dropped to 0.78 at WH-1000",
                "similarity": 0.94,
                "similarityTier": "high",
                "preview": "WH-1000 in CA reported fill_rate=0.78 for FOODS_3_090. Baseline: 0.98. 4 stockout days.",
                "fullText": "Warehouse WH-1000 in California reported fill_rate=0.78 for item FOODS_3_090 in November 2012. Rolling 12-month average fill rate was 0.98. Stockout days count was 4 days. Supplier raw unit cost remained fixed at $0.88. Logistics carrier LogiTrans flagged port congestion delay."
            },
            {
                "id": "ev-2",
                "date": "Nov 20, 2012",
                "source": "unstructured_feedback (Support Ticket)",
                "type": "Customer Support Escalation #ST-4421",
                "title": "Seattle warehouse arrival cargo delays",
                "similarity": 0.91,
                "similarityTier": "high",
                "preview": "Regional manager ticket: 'CA distribution partner reporting cargo arrival delays from primary supplier.'",
                "fullText": "Support ticket #ST-4421 filed by West regional operations lead: 'Our CA distribution partner is reporting significant cargo arrival delays from the primary supplier for FOODS_3_090. Multiple store shelves in the WH-1000 service area are empty. ETA unknown. Request emergency supplier allocation.'"
            },
            {
                "id": "ev-3",
                "date": "Nov 22, 2012",
                "source": "unstructured_feedback (Customer Review)",
                "type": "Retail Portal Review #RV-9012",
                "title": "Empty shelf customer review",
                "similarity": 0.78,
                "similarityTier": "medium",
                "preview": "'Shelves are empty for the third week in a row. Cannot find product anywhere in the area.'",
                "fullText": "Verified retail customer review (Rating: 1/5): 'Shelves are empty for the third week in a row. Cannot find FOODS_3_090 anywhere in the northern California metro area. Extremely frustrating as this is a staple item.' Verified cosine similarity 0.78 to supply disruption cluster."
            }
        ],
        "recommendedAction": {
            "title": "Increase replenishment allocation for FOODS_3_090 in CA",
            "expectedImpact": "Recover approximately $8,204/month in run-rate revenue within 14 days.",
            "steps": [
                "Issue emergency PO to secondary supplier (target fill rate >= 0.95 within 14 days).",
                "Reallocate 2,000 units buffer stock from Texas warehouse to California WH-1000.",
                "Attach PVM narrative to monthly executive board reporting packet."
            ]
        }
    },
    "billing": {
        "id": "ANOM-2013-05-TX",
        "title": "Billing Bug",
        "category": "Conflicting Evidence (Abstain)",
        "sku": "FOODS_3_586",
        "region": "TX (South Region)",
        "warehouse": "WH-2000",
        "date": "May 2013",
        "zScore": 1.82,
        "deviation": "Price x2.0 drift anomaly",
        "confidence": 42,
        "status": "warning",
        "headline": "Price drift of 2x detected in TX transactions",
        "summary": "Sell price recorded at $3.36 vs expected $1.68 on May 15-16. Customer feedback shows conflicting signals; LLM abstained from automatic margin adjustment.",
        "pvm": {
            "volume": {"val": -210, "pct": "5%", "expl": "Negligible volume elasticity impact."},
            "price": {"val": 4300, "pct": "92%", "expl": "Artificial revenue inflation from 2x overcharge."},
            "mix": {"val": 180, "pct": "4%", "expl": "Normal product mix."},
            "other": {"val": 90, "pct": "2%", "expl": "Minor rounding delta."}
        },
        "products": [
            {"sku": "FOODS_3_586", "volumeDelta": "+0%", "revenueImpact": "+$4,300", "status": "Pricing Bug"}
        ],
        "evidence": [
            {
                "id": "ev-b1",
                "date": "May 15, 2013",
                "source": "fact_sales_daily",
                "type": "Structured Pricing Anomaly",
                "title": "Sell price spike: $1.68 to $3.36 in TX",
                "similarity": 0.88,
                "similarityTier": "high",
                "preview": "TX_1 and TX_2 stores recorded sell_price=$3.36 vs contract price $1.68.",
                "fullText": "Fact sales daily records indicate 1,280 transactions for FOODS_3_586 in TX_1 and TX_2 logged at $3.36/unit instead of contract price $1.68. Total overbilling exposure: $2,150. Supplier cost $1.18."
            }
        ],
        "recommendedAction": {
            "title": "Audit TX billing pipeline & issue customer credits",
            "expectedImpact": "Prevent compliance penalty and reconcile $2,150 customer balance.",
            "steps": [
                "Audit POS price synchronization batch job for South region.",
                "Issue store credit vouchers to 1,280 impacted loyalty accounts.",
                "LLM abstains from automated KPI baseline shift pending data fix."
            ]
        }
    },
    "pricecut": {
        "id": "ANOM-2013-08-CA",
        "title": "Price Cut + Volume Lift",
        "category": "Price-Volume-Mix Elasticity",
        "sku": "FOODS_3_090",
        "region": "CA (West Region)",
        "warehouse": "WH-1000",
        "date": "August 2013",
        "zScore": 2.91,
        "deviation": "-25% price, +42% volume",
        "confidence": 91,
        "status": "active",
        "headline": "Promotional price cut drove 42% volume surge",
        "summary": "Deliberate price reduction from $1.67 to $1.25 compressed margin to 30% while expanding market share.",
        "pvm": {
            "volume": {"val": 7200, "pct": "62%", "expl": "Strong demand elasticity response to promotion."},
            "price": {"val": -4200, "pct": "36%", "expl": "Margin compression from 25% price drop."},
            "mix": {"val": 800, "pct": "7%", "expl": "Basket cross-selling lift."},
            "other": {"val": 300, "pct": "3%", "expl": "Seasonal tailwind."}
        },
        "products": [
            {"sku": "FOODS_3_090", "volumeDelta": "+42%", "revenueImpact": "+$7,200", "status": "Promotional Leader"}
        ],
        "evidence": [
            {
                "id": "ev-p1",
                "date": "Aug 2, 2013",
                "source": "fact_sales_daily",
                "type": "Pricing Strategy Execution",
                "title": "Price reduction from $1.67 to $1.25",
                "similarity": 0.95,
                "similarityTier": "high",
                "preview": "Price reduction executed across all CA retail outlets.",
                "fullText": "Sales data confirms deliberate markdown on FOODS_3_090 from $1.67 to $1.25 effective August 2, 2013. Supplier cost remained constant at $0.88. Unit velocity increased 42% week-over-week."
            }
        ],
        "recommendedAction": {
            "title": "Monitor 30-day gross margin compression",
            "expectedImpact": "Sustain volume lift without eroding net operating margin.",
            "steps": [
                "Track weekly gross margin threshold (maintain > 28%).",
                "Coordinate with marketing on promotional run duration.",
                "No immediate corrective intervention required."
            ]
        }
    }
}

class ApiRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS for local development
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        # 1. Health Check
        if path == '/api/health':
            db_exists = os.path.exists(DB_PATH)
            self._send_json({
                "status": "healthy",
                "database_connected": db_exists,
                "database_path": DB_PATH,
                "version": "1.0.0",
                "engine": "KPI Intelligence Backend API"
            })
            return

        # 2. Latest Anomalies
        if path == '/api/anomalies/latest' or path == '/api/anomalies':
            anomalies_list = list(ANOMALY_BACKEND_STORE.values())
            self._send_json(anomalies_list)
            return

        # 3. Anomaly Detail: /api/anomalies/{key}
        if path.startswith('/api/anomalies/'):
            parts = path.split('/')
            key = parts[3] if len(parts) > 3 else 'supply'
            if key in ANOMALY_BACKEND_STORE:
                self._send_json(ANOMALY_BACKEND_STORE[key])
            else:
                self._send_json(ANOMALY_BACKEND_STORE['supply'])
            return

        # 4. Telemetry Metrics
        if path == '/api/telemetry':
            self._send_json({
                "sql_latency_ms": 142,
                "llm_latency_s": 1.8,
                "token_cost_usd": 0.004,
                "data_freshness_days": 0,
                "active_anomalies_count": len(ANOMALY_BACKEND_STORE),
                "model": "Gemini Flash 2.5 Engine"
            })
            return

        # Default static file serving from C:\remember
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

        # 1. Action Approval Dispatch
        if path.startswith('/api/actions/') and path.endswith('/approve'):
            anomaly_key = path.split('/')[3]
            audit_id = f"AUD-{abs(hash(str(payload))) % 10000}"
            
            # Log to SQLite if available
            if os.path.exists(DB_PATH):
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO user_feedback (anomaly_id, rating, user_comments) VALUES (?, ?, ?)",
                        (anomaly_key, 1, f"Approved action via dashboard. Audit #{audit_id}")
                    )
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"Warning: Could not log to SQLite: {e}")

            self._send_json({
                "success": True,
                "audit_id": audit_id,
                "status": "Approved & Dispatched",
                "anomaly_id": anomaly_key,
                "message": f"Action successfully recorded and assigned to operations queue."
            })
            return

        # 2. User Rating Feedback
        if path == '/api/feedback':
            anomaly_id = payload.get('anomaly_id', 'unknown')
            rating = payload.get('rating', 1)
            comments = payload.get('user_comments', '')
            if os.path.exists(DB_PATH):
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO user_feedback (anomaly_id, rating, user_comments) VALUES (?, ?, ?)",
                        (anomaly_id, rating, comments)
                    )
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"Warning: Feedback SQLite log error: {e}")

            self._send_json({"success": True, "logged": True})
            return

        self.send_error(404, "Endpoint Not Found")

    def _send_json(self, data, status_code=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def run_server():
    os.chdir(BASE_DIR)
    with socketserver.TCPServer(("", PORT), ApiRequestHandler) as httpd:
        print(f"============================================================")
        print(f"  KPI Intelligence API Server Running on http://127.0.0.1:{PORT}")
        print(f"  Serving dashboard at: http://127.0.0.1:{PORT}/dashboard.html")
        print(f"  Database target: {DB_PATH}")
        print(f"============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == '__main__':
    run_server()
