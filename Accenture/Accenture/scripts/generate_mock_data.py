"""
generate_mock_data.py
Seeding script to load Parquet sources, compute costs/margins, generate unstructured text reviews,
and initialize the SQLite database (business_bi.db).
"""
import os
import sqlite3
import pandas as pd
import sys
import json
import numpy as np
import zlib


def _stable_jitter(key: str, spread: int) -> int:
    """
    Deterministic replacement for Python's built-in hash() on strings, which is
    randomized per-process (PYTHONHASHSEED) unless explicitly disabled -- using
    it here meant every reseed silently reshuffled inventory_on_hand noise,
    which flips which anomalies clear the fill-rate/stockout thresholds and
    therefore which ones abstain. crc32 is stable across processes/machines,
    so a reseed reproduces byte-identical anomalies every time.
    """
    return zlib.crc32(key.encode("utf-8")) % spread

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SCHEMAS_DIR = os.path.join(BASE_DIR, 'schemas')

DB_PATH = os.path.join(DATA_DIR, 'business_bi.db')
SQL_INIT_PATH = os.path.join(SCHEMAS_DIR, 'db_init.sql')

# Parquet Input Paths
SALES_PARQUET = os.path.join(DATA_DIR, 'fact_sales_daily.parquet')
MARKETING_PARQUET = os.path.join(DATA_DIR, 'source_marketing_weekly.parquet')
SUPPLY_PARQUET = os.path.join(DATA_DIR, 'source_supply_monthly.parquet')
LOOKUP_PARQUET = os.path.join(DATA_DIR, 'lookup_sku_to_item.parquet')

# Pre-defined Supplier Costs (representing 70% of typical selling prices)
SUPPLIER_COSTS = {
    "FOODS_3_090": 0.88,    # Avg price ~$1.25 -> Cost $0.88
    "FOODS_3_586": 1.18,    # Avg price ~$1.68 -> Cost $1.18
    "HOUSEHOLD_1_020": 3.49 # Avg price ~$4.99 -> Cost $3.49
}

# Short, anomaly_id-safe abbreviations for each detected KPI -- anomalies.anomaly_id
# is the table's PRIMARY KEY and must be unique per (kpi, item, state, period), not
# just per (item, state, period).
_KPI_ID_ABBREV = {"Revenue": "REV", "GrossMarginPercent": "MARGIN", "InventoryTurnover": "TURNOVER"}

def init_database():
    print(f"Initializing database at: {DB_PATH}")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Removed existing database.")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    with open(SQL_INIT_PATH, 'r') as f:
        sql_script = f.read()
    
    cursor.executescript(sql_script)
    conn.commit()
    conn.close()
    print("Database tables initialized successfully.")

def seed_sku_lookup():
    print("Seeding sku_lookup table...")
    df_lookup = pd.read_parquet(LOOKUP_PARQUET)
    
    # Map raw costs
    df_lookup['supplier_raw_cost'] = df_lookup['item_id'].map(SUPPLIER_COSTS)
    
    conn = sqlite3.connect(DB_PATH)
    df_lookup.to_sql('sku_lookup', conn, if_exists='append', index=False)
    conn.close()
    print(f"Seeded {len(df_lookup)} SKU mappings.")

def seed_sales():
    print("Seeding fact_sales_daily table...")
    df_sales = pd.read_parquet(SALES_PARQUET)
    
    # Map supplier raw cost to compute COGS and Margin
    df_sales['supplier_raw_cost'] = df_sales['item_id'].map(SUPPLIER_COSTS)
    df_sales['cost_of_goods_sold'] = df_sales['units'] * df_sales['supplier_raw_cost']
    
    # Margin calculation: (Revenue - COGS) / Revenue, handle 0 revenue
    df_sales['gross_margin_percent'] = (df_sales['revenue'] - df_sales['cost_of_goods_sold']) / df_sales['revenue']
    df_sales['gross_margin_percent'] = df_sales['gross_margin_percent'].fillna(0.0)
    
    # Drop temp column
    df_sales = df_sales.drop(columns=['supplier_raw_cost'])
    
    # Ensure dates are stored as string format YYYY-MM-DD
    df_sales['date'] = pd.to_datetime(df_sales['date']).dt.strftime('%Y-%m-%d')
    
    conn = sqlite3.connect(DB_PATH)
    df_sales.to_sql('fact_sales_daily', conn, if_exists='append', index=False)
    conn.close()
    print(f"Seeded {len(df_sales)} daily sales records.")

def seed_marketing():
    print("Seeding source_marketing_weekly table...")
    df_mkt = pd.read_parquet(MARKETING_PARQUET)
    
    # Format dates
    df_mkt['week_start_monday'] = pd.to_datetime(df_mkt['week_start_monday']).dt.strftime('%Y-%m-%d')
    
    conn = sqlite3.connect(DB_PATH)
    df_mkt.to_sql('source_marketing_weekly', conn, if_exists='append', index=False)
    conn.close()
    print(f"Seeded {len(df_mkt)} weekly marketing records.")

def seed_supply():
    print("Seeding source_supply_monthly table...")
    df_supply = pd.read_parquet(SUPPLY_PARQUET)
    
    # Month period to string
    df_supply['month'] = df_supply['month'].astype(str)
    
    conn = sqlite3.connect(DB_PATH)
    df_supply.to_sql('source_supply_monthly', conn, if_exists='append', index=False)
    conn.close()
    print(f"Seeded {len(df_supply)} monthly supply records.")

def seed_unstructured_feedback():
    print("Seeding unstructured_feedback table...")
    # We inject realistic customer feedback and support tickets to match the anomaly events
    feedbacks = [
        # 1. Nov 2012 Supply Constraint feedback (FOODS_3_090, CA Seattle Warehouse)
        {
            "item_id": "FOODS_3_090",
            "state_id": "CA",
            "source": "support ticket",
            "text_content": "Seattle warehouse reporting critical cargo arrival delays at Port of Seattle. Carrier LogiTrans delayed container shipment by 5 days. Inventory on hand of SKU FOODS_3_090 is completely stockout.",
            "date": "2012-11-20"
        },
        {
            "item_id": "FOODS_3_090",
            "state_id": "CA",
            "source": "customer review",
            "text_content": "Disappointed. Shelves are empty for the third day in a row. They never have this product (FOODS_3_090) in stock in CA stores lately.",
            "date": "2012-11-22"
        },
        # 2. Conflicting Evidence Anomaly (High margins in reporting, but customer support reviews complain about billing bugs)
        {
            "item_id": "FOODS_3_586",
            "state_id": "TX",
            "source": "customer review",
            "text_content": "WARNING: There is a pricing billing bug for FOODS_3_586. The self-checkout register charged my card exactly double the listed shelf price. Please fix this price checker error!",
            "date": "2013-05-15"
        },
        {
            "item_id": "FOODS_3_586",
            "state_id": "TX",
            "source": "support ticket",
            "text_content": "Customer support hotline received 12 complaints today regarding pricing discrepancies for FOODS_3_586. Register is overcharging by double the contract price. It shows high dollar revenue in our logs but customers are demanding refunds.",
            "date": "2013-05-16"
        },
        # 3. Aug 2013 Price Cut (FOODS_3_090 CA/TX)
        {
            "item_id": "FOODS_3_090",
            "state_id": "CA",
            "source": "customer review",
            "text_content": "Great new price on this item! Love the sudden 25% price cut in August. Buying bulk now.",
            "date": "2013-08-18"
        }
    ]
    
    df_fb = pd.DataFrame(feedbacks)
    conn = sqlite3.connect(DB_PATH)
    df_fb.to_sql('unstructured_feedback', conn, if_exists='append', index=False)
    conn.close()
    print(f"Seeded {len(df_fb)} unstructured text records.")

def inject_scenario_impacts():
    """
    fact_sales_daily is real M5 sales history; source_supply_monthly and
    source_marketing_weekly are synthetic 'source system' tables seeded with
    deliberate anomalies (e.g. the WH-1000/CA fill_rate=0.78 stockout in
    2012-11 asserted by tests/test_mock_data.py). Left alone, those synthetic
    signals point at real sales data that never actually moved -- the
    detector, PVM engine, and evidence reconciler would each be reasoning
    about a different, disconnected story.

    This step projects the effect of those already-seeded synthetic anomalies
    back onto fact_sales_daily for exactly the three demo scenario windows, so
    every layer of the pipeline is reasoning about one consistent, internally
    coherent event. This is a stated simulation assumption (Round 2 brief:
    "use reasonable assumptions... state them clearly"), not a fabricated
    analytical claim -- the recommended actions/narratives are still computed
    live from whatever numbers land here.
    """
    print("Injecting scenario impacts into fact_sales_daily for internal consistency...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # --- Scenario 1: Supply constraint (CA / FOODS_3_090 / Nov 2012) ---
    # Demand suppression proportional to the already-seeded fill_rate for
    # WH-1000/CA in 2012-11, with near-total suppression during the exact
    # stockout window already forced to zero on-hand (Nov 18-21) by
    # seed_inventory_logs() below.
    cur.execute("""
        SELECT fill_rate FROM source_supply_monthly
        WHERE warehouse_sku = 'WH-1000' AND state_id = 'CA' AND month = '2012-11'
    """)
    row = cur.fetchone()
    fill_rate = row[0] if row else 0.78

    cur.execute("""
        SELECT date, item_id, store_id, units, sell_price FROM fact_sales_daily
        WHERE item_id = 'FOODS_3_090' AND state_id = 'CA' AND date BETWEEN '2012-11-01' AND '2012-11-30'
    """)
    for date_str, item_id, store_id, units, sell_price in cur.fetchall():
        factor = 0.05 if '2012-11-18' <= date_str <= '2012-11-21' else fill_rate
        new_units = max(0, round(units * factor))
        new_revenue = round(new_units * sell_price, 2)
        cur.execute(
            "UPDATE fact_sales_daily SET units = ?, revenue = ? WHERE date = ? AND item_id = ? AND store_id = ?",
            (new_units, new_revenue, date_str, item_id, store_id),
        )

    # --- Scenario 2: Billing/pricing bug (TX / FOODS_3_586 / May 15-16, 2013) ---
    # Register overcharges customers exactly double the listed price for two days.
    cur.execute("""
        SELECT date, item_id, store_id, units, sell_price FROM fact_sales_daily
        WHERE item_id = 'FOODS_3_586' AND state_id = 'TX' AND date IN ('2013-05-15', '2013-05-16')
    """)
    for date_str, item_id, store_id, units, sell_price in cur.fetchall():
        new_price = round(sell_price * 2.0, 2)
        new_revenue = round(units * new_price, 2)
        cur.execute(
            "UPDATE fact_sales_daily SET sell_price = ?, revenue = ? WHERE date = ? AND item_id = ? AND store_id = ?",
            (new_price, new_revenue, date_str, item_id, store_id),
        )

    # --- Scenario 3: Promotional price cut (CA / FOODS_3_090 / Aug 2013) ---
    # Assumed unit price elasticity of demand ~= -1.68 (25% markdown -> ~42% volume lift),
    # a standard illustrative FMCG elasticity figure -- a stated assumption, not a fitted value.
    cur.execute("""
        SELECT date, item_id, store_id, units, sell_price FROM fact_sales_daily
        WHERE item_id = 'FOODS_3_090' AND state_id = 'CA' AND date BETWEEN '2013-08-01' AND '2013-08-31'
    """)
    for date_str, item_id, store_id, units, sell_price in cur.fetchall():
        new_price = round(sell_price * 0.75, 2)
        new_units = round(units * 1.42)
        new_revenue = round(new_units * new_price, 2)
        cur.execute(
            "UPDATE fact_sales_daily SET units = ?, sell_price = ?, revenue = ? WHERE date = ? AND item_id = ? AND store_id = ?",
            (new_units, new_price, new_revenue, date_str, item_id, store_id),
        )

    conn.commit()

    # Recompute COGS/margin for every touched row so the database stays mathematically consistent.
    touched_where = """
        (item_id = 'FOODS_3_090' AND state_id = 'CA' AND date BETWEEN '2012-11-01' AND '2012-11-30')
        OR (item_id = 'FOODS_3_586' AND state_id = 'TX' AND date IN ('2013-05-15', '2013-05-16'))
        OR (item_id = 'FOODS_3_090' AND state_id = 'CA' AND date BETWEEN '2013-08-01' AND '2013-08-31')
    """
    cur.execute(f"""
        UPDATE fact_sales_daily
        SET cost_of_goods_sold = units * (
            SELECT supplier_raw_cost FROM sku_lookup WHERE sku_lookup.item_id = fact_sales_daily.item_id
        )
        WHERE {touched_where}
    """)
    cur.execute(f"""
        UPDATE fact_sales_daily
        SET gross_margin_percent = CASE WHEN revenue > 0 THEN (revenue - cost_of_goods_sold) / revenue ELSE 0.0 END
        WHERE {touched_where}
    """)
    conn.commit()
    conn.close()
    print("Scenario impacts injected and COGS/margin recomputed for affected rows.")


def seed_inventory_logs():
    print("Seeding inventory_logs table...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT date, item_id, state_id FROM fact_sales_daily ORDER BY date, item_id")
    rows = cursor.fetchall()
    
    inv_rows = []
    for date_str, item_id, state_id in rows:
        warehouse_name = "WH-1000" if state_id == "CA" else "WH-2000"
        
        # Default inventory on hand values
        if item_id == "FOODS_3_090":
            base_inv = 1000 if state_id == "CA" else 900
            # Force stockout on CA FOODS_3_090 between 2012-11-18 and 2012-11-21
            if state_id == "CA" and "2012-11-18" <= date_str <= "2012-11-21":
                inv = 0
            else:
                inv = int(base_inv + _stable_jitter(date_str, 50) - 25)
        elif item_id == "FOODS_3_586":
            base_inv = 500 if state_id == "CA" else 600
            inv = int(base_inv + _stable_jitter(date_str, 30) - 15)
        else: # HOUSEHOLD_1_020
            base_inv = 200 if state_id == "CA" else 300
            inv = int(base_inv + _stable_jitter(date_str, 20) - 10)
            
        inv_rows.append((date_str, item_id, warehouse_name, state_id, max(0, inv)))
        
    cursor.executemany(
        "INSERT INTO inventory_logs (date, item_id, warehouse_name, state_id, inventory_on_hand) VALUES (?, ?, ?, ?, ?)",
        inv_rows
    )
    conn.commit()
    conn.close()
    print(f"Seeded {len(inv_rows)} daily inventory log records.")

def run_and_seed_anomalies():
    print("Running analytics pipeline to detect and reconcile anomalies...")
    import time
    sys.path.append(os.path.join(BASE_DIR, 'src'))
    from analytics.anomaly_detector import AnomalyDetector
    from analytics.pvm_analyzer import PvmAnalyzer
    from retrieval.evidence_reconciler import EvidenceReconciler
    from retrieval.knowledge_graph import build_graph, get_related_context
    from llm.narrative_generator import NarrativeGenerator
    from llm import llm_client

    pipeline_start = time.perf_counter()

    detector = AnomalyDetector(DB_PATH)
    pvm_analyzer = PvmAnalyzer(DB_PATH)
    reconciler = EvidenceReconciler(DB_PATH)
    kg = build_graph(DB_PATH)

    # LLM polish is only attempted for the curated, demo-featured core scenarios --
    # this caps external API calls at a small, predictable number regardless of how
    # many anomalies the statistical detector surfaces (REQ-09 cost discipline).
    narrative_gen_llm = NarrativeGenerator(use_llm=True)
    narrative_gen_det = NarrativeGenerator(use_llm=False)
    if llm_client.is_available():
        print("OPENAI_API_KEY detected: core scenarios will use one cached LLM call each for prose polish.")
    else:
        print("No OPENAI_API_KEY: running fully deterministic (this is a supported, zero-cost mode).")

    detected = detector.run_detection(kpi_name="Revenue", time_grain="monthly", window_periods=8, threshold=2.0)
    # GrossMarginPercent and InventoryTurnover are both fully defined in
    # schemas/semantic_contract.json and supported by AnomalyDetector, but were never
    # actually run here -- the dashboard's KPI tabs for them were decorative. Detecting
    # (not just displaying trend lines for) all three is what "connected KPI" means per
    # the Round 2 brief's "three to five connected KPIs" minimum expectation.
    detected_margin = detector.run_detection(kpi_name="GrossMarginPercent", time_grain="monthly", window_periods=8, threshold=2.0)
    detected_turnover = detector.run_detection(kpi_name="InventoryTurnover", time_grain="monthly", window_periods=8, threshold=2.0)

    core_scenarios = [
        {"key": "supply", "item_id": "FOODS_3_090", "state_id": "CA", "period": "2012-11"},
        {"key": "billing", "item_id": "FOODS_3_586", "state_id": "TX", "period": "2013-05"},
        {"key": "pricecut", "item_id": "FOODS_3_090", "state_id": "CA", "period": "2013-08"},
        # HOUSEHOLD_1_020 genuinely launches in TX on 2015-10-10 in the real M5 data --
        # we anchor the sparse-history demo scenario on that real launch month instead of
        # an arbitrary date, so "only a few days of history" is a real data fact, not a claim.
        {"key": "sparse", "item_id": "HOUSEHOLD_1_020", "state_id": "TX", "period": "2015-10"}
    ]
    
    seed_list = []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Process core scenarios first
    for cs in core_scenarios:
        key = cs["key"]
        item_id = cs["item_id"]
        state_id = cs["state_id"]
        period = cs["period"]
        
        found = None
        for a in detected:
            if a["item_id"] == item_id and a["state_id"] == state_id and a["period"] == period:
                found = a.copy()
                break
                
        if found is None:
            # Manually calculate baseline stats
            cursor.execute("""
                SELECT SUM(revenue)
                FROM fact_sales_daily 
                WHERE item_id = ? AND state_id = ? AND strftime('%Y-%m', date) = ?
            """, (item_id, state_id, period))
            row = cursor.fetchone()
            actual_rev = row[0] if row and row[0] else 0.0
            
            cursor.execute("""
                SELECT strftime('%Y-%m', date) as m, SUM(revenue) 
                FROM fact_sales_daily 
                WHERE item_id = ? AND state_id = ? AND m < ? 
                GROUP BY m 
                ORDER BY m DESC 
                LIMIT 8
            """, (item_id, state_id, period))
            baselines = cursor.fetchall()
            sparse_history = len(baselines) < 3
            if not sparse_history:
                baseline_vals = [b[1] for b in baselines]
                mean_val = np.mean(baseline_vals)
                std_val = np.std(baseline_vals)
                deviation_pct = (actual_rev - mean_val) / mean_val if mean_val > 0 else 0.0
                z_score = (actual_rev - mean_val) / std_val if std_val > 0 else 0.0

                # Confidence is derived from |z_score| using the same convention as
                # AnomalyDetector.run_detection -- never a per-scenario constant.
                abs_z = abs(z_score)
                if abs_z >= 3.0:
                    confidence = 95.0
                elif abs_z >= 2.0:
                    confidence = 90.0
                elif abs_z >= 1.0:
                    confidence = 65.0
                else:
                    confidence = 45.0
            else:
                # Genuinely insufficient rolling history to compute a statistical baseline
                # (fewer than 3 prior periods) -- a real data fact for a newly launched item,
                # not a fabricated anomaly. Reported honestly as low confidence rather than
                # a fake z-score.
                mean_val = actual_rev
                deviation_pct = 0.0
                z_score = 0.0
                confidence = 30.0

            found = {
                "kpi_name": "Revenue",
                "item_id": item_id,
                "state_id": state_id,
                "period": period,
                "actual_value": float(actual_rev),
                "baseline_value": float(mean_val),
                "deviation_pct": float(deviation_pct),
                "z_score": float(z_score),
                "direction": "DOWN" if actual_rev < mean_val else "UP",
                "severity": "CRITICAL" if abs(z_score) > 3.0 else "WARNING",
                "confidence": confidence,
                "time_grain": "monthly",
                "sparse_history": sparse_history,
            }
        found.setdefault("sparse_history", False)
        found["scenario_key"] = key
        seed_list.append(found)

    # Process all other detected anomalies
    for a in detected:
        is_core = False
        for s in seed_list:
            if s["item_id"] == a["item_id"] and s["state_id"] == a["state_id"] and s["period"] == a["period"]:
                is_core = True
                break
        if not is_core:
            gen_anomaly = a.copy()
            gen_anomaly.setdefault("sparse_history", False)
            gen_anomaly["scenario_key"] = f"gen-{a['item_id']}-{a['period']}-{a['state_id']}"
            seed_list.append(gen_anomaly)

    # GrossMarginPercent/InventoryTurnover anomalies have no curated core scenario --
    # every one detected goes in as a "gen-" entry, same treatment as the raw Revenue
    # detections above. scenario_key is prefixed with the KPI so it can't collide with
    # a Revenue gen- key for the same (item, period, state).
    _KPI_SCENARIO_PREFIX = {"GrossMarginPercent": "gen-margin", "InventoryTurnover": "gen-turnover"}
    for kpi_detected in (detected_margin, detected_turnover):
        for a in kpi_detected:
            gen_anomaly = a.copy()
            gen_anomaly.setdefault("sparse_history", False)
            prefix = _KPI_SCENARIO_PREFIX[a["kpi_name"]]
            gen_anomaly["scenario_key"] = f"{prefix}-{a['item_id']}-{a['period']}-{a['state_id']}"
            seed_list.append(gen_anomaly)

    # Now compute analysis components (PVM, evidence, graph, persona narratives) and save to DB.
    core_keys = {"supply", "billing", "pricecut", "sparse"}
    telemetry_totals = {
        "llm_calls": 0, "llm_generated_count": 0, "deterministic_generated_count": 0,
        "total_tokens_in": 0, "total_tokens_out": 0, "total_cost_usd": 0.0,
    }
    abstained_count = 0
    sql_query_durations = []

    for found in seed_list:
        key = found["scenario_key"]
        item_id = found["item_id"]
        state_id = found["state_id"]
        period = found["period"]

        period_start = f"{period}-01"
        year, month = map(int, period.split('-'))
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        period_end = f"{period}-{last_day}"

        found["period_start"] = period_start
        found["period_end"] = period_end

        step_start = time.perf_counter()
        if found.get("kpi_name", "Revenue") == "Revenue":
            pvm_res = pvm_analyzer.analyze_variance(
                state_id=state_id,
                period_start=period_start,
                period_end=period_end,
                time_grain="monthly",
                baseline_periods=8,
                item_id=item_id,
            )
        else:
            # Price-Volume-Mix decomposes REVENUE variance specifically -- calling it for
            # a GrossMarginPercent/InventoryTurnover anomaly would decompose that item's
            # revenue movement, not the margin/turnover movement actually flagged here
            # (the same item/region-vs-item scope-mismatch class of bug fixed earlier this
            # session, just for KPI instead of geography). Use the analyzer's own empty
            # result instead of a decomposition that doesn't apply to this KPI --
            # narrative_generator.py's non-Revenue branch is written to handle it honestly.
            pvm_res = pvm_analyzer._empty_pvm_result()

        evidence_res = reconciler.reconcile_evidence(
            item_id=item_id,
            state_id=state_id,
            period_start=period_start,
            period_end=period_end,
            anomaly_type_key=key
        )

        graph_res = get_related_context(kg, item_id, state_id, period_start, period_end=period_end, max_hops=3)
        sql_query_durations.append(time.perf_counter() - step_start)

        # LLM prose polish is attempted only for the curated core scenarios to keep
        # external API calls minimal and predictable; every other anomaly still gets
        # a full, non-hardcoded deterministic narrative + action.
        generator = narrative_gen_llm if key in core_keys else narrative_gen_det
        bundle = generator.generate_bundle(found, pvm_res, evidence_res, graph_res)

        tel = bundle["telemetry"]
        telemetry_totals["llm_calls"] += tel["calls"]
        telemetry_totals["total_tokens_in"] += tel["tokens_in"]
        telemetry_totals["total_tokens_out"] += tel["tokens_out"]
        telemetry_totals["total_cost_usd"] += tel["cost_usd"]
        if tel["generation_method"] == "llm":
            telemetry_totals["llm_generated_count"] += 1
        else:
            telemetry_totals["deterministic_generated_count"] += 1

        vp = bundle["vp_sales"]
        abstained = vp["abstention"] is not None
        if abstained:
            abstained_count += 1

        status = "abstained" if abstained else (
            "critical" if found["severity"] == "CRITICAL" else ("warning" if found["severity"] == "WARNING" else "active")
        )

        cursor.execute("""
            INSERT OR REPLACE INTO anomalies (
                anomaly_id, detected_at, kpi_name, item_id, state_id, cat_id,
                period_start, period_end, actual_value, baseline_value, deviation_pct,
                z_score, direction, severity, confidence, status, headline, summary,
                pvm_json, products_json, evidence_json, recommended_action_json,
                synthesis_json, logistics_json, scenario_key,
                narratives_json, abstained, abstention_reason, graph_context_json, generation_telemetry_json
            ) VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            # anomaly_id is the table's PRIMARY KEY -- it used to be built from just
            # (period, state_id, item_id), which any two KPIs sharing that same
            # combination (e.g. a Revenue anomaly and a GrossMarginPercent anomaly for
            # the same item/state/month) collide on. With "INSERT OR REPLACE", that
            # collision silently overwrote one anomaly's entire row with the other's --
            # seeding Revenue then GrossMarginPercent/InventoryTurnover dropped the
            # Revenue count from 20 to 6 real anomalies before this fix. kpi_name must
            # be part of the key.
            f"ANOM-{_KPI_ID_ABBREV.get(found['kpi_name'], found['kpi_name'])}-{period}-{state_id}-{item_id}",
            found["kpi_name"],
            item_id,
            state_id,
            "FOODS" if "FOODS" in item_id else "HOUSEHOLD",
            period_start,
            period_end,
            found["actual_value"],
            found["baseline_value"],
            found["deviation_pct"],
            found["z_score"],
            found["direction"],
            found["severity"],
            found["confidence"],
            status,
            vp["headline"],
            vp["summary"],
            json.dumps(pvm_res),
            json.dumps(pvm_res.get("products", [])),
            json.dumps(evidence_res.get("evidence", [])),
            json.dumps(vp["recommended_action"] or {}),
            json.dumps({"title": vp["synthesis_title"], "body": vp["synthesis_body"]}),
            json.dumps(bundle["logistics"]),
            key,
            json.dumps({"vp_sales": bundle["vp_sales"], "supply_planner": bundle["supply_planner"]}),
            1 if abstained else 0,
            vp["abstention"]["reason"] if abstained else None,
            json.dumps(graph_res),
            json.dumps(tel),
        ))

    pipeline_seconds = time.perf_counter() - pipeline_start
    avg_sql_ms = (sum(sql_query_durations) / len(sql_query_durations) * 1000) if sql_query_durations else 0.0

    cursor.execute("""
        INSERT INTO telemetry_summary (
            anomalies_processed, abstained_count, llm_calls, llm_generated_count,
            deterministic_generated_count, total_tokens_in, total_tokens_out,
            total_cost_usd, total_pipeline_seconds, avg_sql_query_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        len(seed_list), abstained_count, telemetry_totals["llm_calls"],
        telemetry_totals["llm_generated_count"], telemetry_totals["deterministic_generated_count"],
        telemetry_totals["total_tokens_in"], telemetry_totals["total_tokens_out"],
        telemetry_totals["total_cost_usd"], pipeline_seconds, avg_sql_ms,
    ))

    conn.commit()
    conn.close()
    print(f"Analytics calculations run and stored {len(seed_list)} anomalies in database successfully.")
    print(f"  Abstained: {abstained_count} | LLM-generated: {telemetry_totals['llm_generated_count']} | "
          f"Deterministic: {telemetry_totals['deterministic_generated_count']} | "
          f"LLM calls: {telemetry_totals['llm_calls']} | Total LLM cost: ${telemetry_totals['total_cost_usd']:.4f} | "
          f"Pipeline time: {pipeline_seconds:.2f}s")

def main():
    if not os.path.exists(SALES_PARQUET):
        raise FileNotFoundError(f"Parquet files not found in {DATA_DIR}. Please copy them from KPI-data first.")
        
    init_database()
    seed_sku_lookup()
    seed_sales()
    seed_marketing()
    seed_supply()
    inject_scenario_impacts()
    seed_unstructured_feedback()
    seed_inventory_logs()
    run_and_seed_anomalies()
    print("\nDatabase seeding completed successfully. Verification ready!")

if __name__ == '__main__':
    main()
