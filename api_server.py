"""
api_server.py
Lightweight, zero-external-dependency REST API server bridging SQLite database,
analytics calculations, retrieved feedback records, and proposed actions to the frontend.
"""

import http.server
import socketserver
import json
import re
import sqlite3
import os
import sys
import time
from urllib.parse import urlparse, parse_qs

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'business_bi.db')
GRAPH_PATH = os.path.join(BASE_DIR, 'data', 'evidence_graph.gpickle')

# Live-stream demo series: one representative item/state, replayed record by
# record to simulate "as we get a new record" for the dashboard's live chart.
LIVE_ITEM = 'FOODS_3_090'
LIVE_STATE = 'CA'

# Populated by _load_live_backend() if the graph + its pandas/networkx
# dependencies are available; left empty otherwise so the server still runs
# in the original static-demo-only mode (see requirements.txt for what's
# needed to enable this).
GRAPH = None
LIVE_SERIES = []
LIVE_CURSOR = {'i': 0}
LATEST_ANOMALY = {'node_id': None}  # updated as /api/stream/next surfaces anomalies

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Real measured latency/usage, rolling window of the last 20 calls each --
# replaces the old hardcoded 142ms/1.8s/$0.004 telemetry mock.
TELEMETRY_WINDOW = 20
TELEMETRY = {'sql_latencies_ms': [], 'llm_latencies_s': [], 'llm_tokens': []}


def _record_telemetry(key, value):
    lst = TELEMETRY[key]
    lst.append(value)
    del lst[:-TELEMETRY_WINDOW]

# The 4 real anomalies featured on the sidebar cards, replacing the old
# hardcoded supply/billing/pricecut/sparse mock scenarios. Chosen and
# verified this session -- see plan doc for the reasoning behind each.
FEATURED_ANOMALY_KEYS = [
    ('supply', 'revenue_anom_FOODS_3_090_CA_2012-11-23'),
    ('pricecut', 'revenue_anom_FOODS_3_090_CA_2013-08-23'),
    ('conflicting', 'revenue_anom_FOODS_3_586_TX_2013-05-15'),
    ('sparse', 'cold_start_HOUSEHOLD_1_020'),
]
FEATURED_ANOMALIES = []  # populated at startup by _load_live_backend()


def _build_daily_series(item_id, state_id, df):
    """[{date, revenue, is_anomaly, node_id}] from an item_state_daily-shaped df, using GRAPH to flag anomalies."""
    series = []
    for _, row in df.iterrows():
        date_str = row['date'].strftime('%Y-%m-%d')
        node_id = f"revenue_anom_{item_id}_{state_id}_{date_str}"
        is_anomaly = GRAPH.has_node(node_id)
        series.append({
            'date': date_str,
            'revenue': round(float(row['revenue']), 2),
            'is_anomaly': is_anomaly,
            'node_id': node_id if is_anomaly else None,
        })
    return series


def build_history_series(item_id, state_id, year='all'):
    """
    Full real daily revenue series for an item/state, optionally filtered to
    one year -- replaces the frontend's hardcoded REVENUE_TIMELINE_DATA mock
    for the chart's "2012"/"2013"/"All" filter buttons.
    """
    if GRAPH is None:
        return None
    from src.analytics.aggregation import get_item_state_daily
    df = get_item_state_daily(DB_PATH)
    df = df[(df['item_id'] == item_id) & (df['state_id'] == state_id)].sort_values('date')
    if year != 'all':
        df = df[df['date'].dt.strftime('%Y') == str(year)]
    return _build_daily_series(item_id, state_id, df)


def _load_live_backend():
    global GRAPH, LIVE_SERIES, FEATURED_ANOMALIES
    try:
        sys.path.insert(0, BASE_DIR)
        from src.analytics.graph_store import load_graph
        from src.analytics.aggregation import get_item_state_daily

        if not os.path.exists(GRAPH_PATH):
            print(f"No evidence graph at {GRAPH_PATH} -- run scripts/build_graph.py first. "
                  f"Live streaming and dynamic anomaly detail disabled.")
            return

        GRAPH = load_graph(GRAPH_PATH)

        df = get_item_state_daily(DB_PATH)
        df = df[(df['item_id'] == LIVE_ITEM) & (df['state_id'] == LIVE_STATE)].sort_values('date')
        LIVE_SERIES.extend(_build_daily_series(LIVE_ITEM, LIVE_STATE, df))
        print(f"Live backend ready: {len(LIVE_SERIES)} daily records for {LIVE_ITEM}/{LIVE_STATE}, "
              f"graph has {GRAPH.number_of_nodes()} nodes.")

        for role, key in FEATURED_ANOMALY_KEYS:
            detail = (build_cold_start_detail(COLD_START_ITEM_ID) if key.startswith('cold_start_')
                      else build_dynamic_anomaly_detail(key))
            if detail:
                detail['role'] = role
                FEATURED_ANOMALIES.append(detail)
            else:
                print(f"Warning: featured anomaly '{key}' (role={role}) could not be built -- skipped.")
        print(f"Featured anomaly cards ready: {len(FEATURED_ANOMALIES)}/{len(FEATURED_ANOMALY_KEYS)}")
    except Exception as e:
        print(f"Warning: live backend unavailable ({e}). Running in static demo mode only.")


def build_current_stats_detail(item_id, state_id, date_str):
    """
    Raw current-day stats for a date that is NOT itself a flagged anomaly --
    shaped compatibly with the same drawer UI (pvm/evidence/etc. present but
    empty/neutral) so it renders without any frontend changes, but clearly
    marked as 'no anomaly' rather than pretending to explain something that
    wasn't flagged.
    """
    if GRAPH is None:
        return None
    from src.analytics.aggregation import get_item_state_daily
    import pandas as pd

    df = get_item_state_daily(DB_PATH)
    row = df[(df['item_id'] == item_id) & (df['state_id'] == state_id) & (df['date'] == pd.Timestamp(date_str))]
    if row.empty:
        return None
    row = row.iloc[0]

    region_map = {'CA': 'CA (West Region)', 'TX': 'TX (South Region)'}
    return {
        'id': f"stats_{item_id}_{state_id}_{date_str}",
        'title': f"{item_id} Daily Stats",
        'category': 'No Anomaly Detected',
        'sku': item_id,
        'region': region_map.get(state_id, state_id),
        'warehouse': 'N/A',
        'date': date_str,
        'queriedDate': date_str,
        'resolvedDate': date_str,
        'isExactMatch': True,
        'zScore': 0,
        'deviation': 'Within normal range',
        'confidence': 0,
        'status': 'active',
        'headline': f"{item_id} in {state_id} on {date_str}: no anomaly detected",
        'summary': (f"Revenue was ${row['revenue']:.2f} ({int(row['units'])} units at "
                    f"${row['sell_price']:.2f} avg price). This day was not flagged as an anomaly "
                    f"by any detector (units, revenue, or price)."),
        'pvm': {
            'volume': {'val': 0, 'pct': '0%', 'expl': 'No anomaly on this date -- decomposition not applicable.'},
            'price': {'val': 0, 'pct': '0%', 'expl': 'No anomaly on this date -- decomposition not applicable.'},
            'mix': {'val': 0, 'pct': '0%', 'expl': 'Not applicable at this grain.'},
            'other': {'val': 0, 'pct': '0%', 'expl': 'Not applicable.'},
        },
        'products': [{
            'sku': item_id, 'volumeDelta': 'n/a',
            'revenueImpact': f"${row['revenue']:,.2f}", 'status': 'Normal',
        }],
        'evidence': [{
            'id': 'no-anomaly', 'date': date_str, 'source': 'fact_sales_daily',
            'type': 'Current Day Stats',
            'title': f"Units={int(row['units'])}, Revenue=${row['revenue']:.2f}, Price=${row['sell_price']:.2f}",
            'similarity': 1.0, 'similarityTier': 'high',
            'preview': 'No detector flagged this date -- these are the raw daily figures.',
            'fullText': (f"On {date_str}, {item_id} in {state_id} sold {int(row['units'])} units for "
                         f"${row['revenue']:.2f} total revenue (avg price ${row['sell_price']:.2f}). "
                         f"No units/revenue/price detector flagged this day as anomalous."),
        }],
        'recommendedAction': {
            'title': 'No action needed', 'expectedImpact': 'Day is within normal statistical range.',
            'steps': ['No action needed -- this date was not flagged as an anomaly.'],
        },
    }


def resolve_anomaly_or_stats(item_id, state_id, date_str):
    """
    Returns the full anomaly detail if (item_id, state_id, date_str) is a
    flagged revenue anomaly; otherwise the raw current-day stats for that
    date. Returns None if neither exists (e.g. no data at all for that date).
    Shared by /api/query and the chatbot so both resolve dates identically.
    """
    if GRAPH is None:
        return None
    node_id = f"revenue_anom_{item_id}_{state_id}_{date_str}"
    if GRAPH.has_node(node_id):
        return build_dynamic_anomaly_detail(node_id)
    return build_current_stats_detail(item_id, state_id, date_str)


def build_dynamic_anomaly_detail(node_id):
    """
    Maps a real revenue_anomaly graph node into the exact same JSON shape
    the frontend's ANOMALY_DATASET objects already use, via explain_revenue_drop.
    Returns None if the graph is unavailable or the node doesn't exist/parse.
    """
    if GRAPH is None or not node_id.startswith('revenue_anom_'):
        return None

    tokens = node_id[len('revenue_anom_'):].split('_')
    if len(tokens) < 3:
        return None
    date_str = tokens[-1]
    state_id = tokens[-2]
    item_id = '_'.join(tokens[:-2])

    from src.analytics.graph_query import explain_revenue_drop
    r = explain_revenue_drop(GRAPH, item_id, state_id, date_str)
    if r is None:
        return None

    attrs = r['attrs']
    pct = r['pct_change'] or 0.0
    is_drop = pct < 0
    direction_word = 'decreased' if is_drop else 'increased'
    drivers = r['drivers']
    driver_label = drivers[0]['driver'] if drivers else 'unattributed'

    # Confidence heuristic: +13 per independent corroborating evidence source
    # found, capped at 95. This is an explicit, documented heuristic based on
    # evidence *count*, not a trained/calibrated confidence model -- kept
    # deliberately simple and inspectable rather than fabricating precision.
    evidence_sources = sum([
        bool(r['supply_evidence']), bool(r['review_sentiment']),
        bool(r['marketing_evidence']), bool(r['same_day_event']), bool(drivers),
    ])
    confidence = min(95, 30 + evidence_sources * 13)
    status = 'critical' if abs(attrs['score']) >= 3 else ('warning' if abs(attrs['score']) >= 2 else 'active')
    warehouse = r['supply_evidence'][0]['warehouse_sku'] if r['supply_evidence'] else 'N/A'
    region_map = {'CA': 'CA (West Region)', 'TX': 'TX (South Region)'}
    region_label = region_map.get(attrs['state'], attrs['state'])

    price_val = attrs.get('price_effect') or 0.0
    volume_val = attrs.get('volume_effect') or 0.0
    interaction_val = attrs.get('interaction_effect') or 0.0
    total_abs = abs(price_val) + abs(volume_val) + abs(interaction_val) or 1.0

    def pct_of(v):
        return f"{abs(v) / total_abs * 100:.0f}%"

    evidence_list = []
    for s in r['supply_evidence']:
        evidence_list.append({
            'id': s['node'], 'date': s['month'], 'source': 'source_supply_monthly',
            'type': 'Structured Supply Signal',
            'title': f"Fill rate {s['fill_rate']} at {s['warehouse_sku']}",
            'similarity': 0.9, 'similarityTier': 'high',
            'preview': f"Warehouse {s['warehouse_sku']} reported fill_rate={s['fill_rate']}, "
                       f"{s['stockout_days']} stockout days in {s['month']}.",
            'fullText': f"Warehouse {s['warehouse_sku']} ({s['state']}) reported fill_rate={s['fill_rate']} "
                        f"and {s['stockout_days']} stockout days for {s['month']}. Flagged as a supply "
                        f"anomaly (fill_rate < 0.90 or stockout_days >= 2).",
        })
    rs = r['review_sentiment']
    if rs:
        evidence_list.append({
            'id': rs['node'], 'date': rs['month'], 'source': 'unstructured_feedback',
            'type': f"Review Sentiment Shift ({rs['direction']})",
            'title': f"Customer sentiment turned {'negative' if rs['mean_sentiment'] < 0 else 'positive'} in {rs['month']}",
            'similarity': 0.8, 'similarityTier': 'medium' if rs['review_count'] <= 1 else 'high',
            'preview': f"Mean sentiment {rs['mean_sentiment']:.1f} across {rs['review_count']} review(s), z={rs['z']:.2f}.",
            'fullText': f"Aggregated review/support-ticket sentiment for {attrs['item']} in {attrs['state']} "
                        f"during {rs['month']}: mean polarity {rs['mean_sentiment']:.1f} across "
                        f"{rs['review_count']} record(s) (z={rs['z']:.2f}, {rs['direction']}). "
                        + ("Based on a single record -- treat with caution." if rs['review_count'] <= 1
                           else "Multiple corroborating records."),
        })
    for m in r['marketing_evidence']:
        evidence_list.append({
            'id': m['node'], 'date': m['week_start'], 'source': 'source_marketing_weekly',
            'type': f"{m['channel']} Spend Anomaly",
            'title': f"{m['channel']} spend anomalous week of {m['week_start']}",
            'similarity': 0.65, 'similarityTier': 'medium',
            'preview': f"{m['channel']} spend ${m['value']:.2f} in {m['state']} (z={m['z']:.2f}) -- "
                       f"same week, correlational only.",
            'fullText': f"{m['channel']} marketing spend in {m['region']} ({m['state']}) was "
                        f"${m['value']:.2f} the week of {m['week_start']}, z={m['z']:.2f} vs trailing "
                        f"baseline. Same-week co-occurrence with the sales anomaly; not established as causal.",
        })
    if r['same_day_event']:
        ev = r['same_day_event']
        evidence_list.append({
            'id': f"event_{ev['date']}", 'date': ev['date'], 'source': 'fact_sales_daily.event_name_1',
            'type': f"Calendar Event ({ev['event_type']})", 'title': ev['event_name'],
            'similarity': 1.0, 'similarityTier': 'high',
            'preview': f"{ev['event_name']} ({ev['event_type']}) fell on this exact date.",
            'fullText': f"{ev['event_name']} ({ev['event_type']}) occurred on {ev['date']}, the same day as this anomaly.",
        })
    if not evidence_list:
        evidence_list.append({
            'id': 'no-evidence', 'date': attrs['date'], 'source': 'none',
            'type': 'No Corroborating Evidence',
            'title': 'No supply, review, marketing, or event evidence found',
            'similarity': 0.0, 'similarityTier': 'low',
            'preview': 'This anomaly has no corroborating evidence in any other source for this item/state/period.',
            'fullText': 'No supply anomaly, review sentiment shift, marketing anomaly, or calendar event was '
                        'found for this item/state in the surrounding period. Recommend treating this as '
                        'unexplained pending manual review rather than assigning a cause.',
        })

    if drivers:
        rec_title = f"Investigate {driver_label} driver for {attrs['item']} in {attrs['state']}"
        rec_impact = (f"Revenue {'declined' if is_drop else 'grew'} ${abs(attrs['actual_delta']):,.2f} "
                      f"({abs(pct) * 100:.1f}%), attributed to {driver_label} at "
                      f"{drivers[0]['weight'] * 100:.0f}% weight.")
    else:
        rec_title = "Insufficient evidence for an automated recommendation"
        rec_impact = (f"Revenue {'declined' if is_drop else 'grew'} ${abs(attrs['actual_delta']):,.2f} but no "
                      f"driver anomaly could be confidently attributed -- flag for manual review.")

    # Multiple prescriptive steps, each conditioned on evidence that actually
    # exists -- never a fixed 3-step template regardless of what was found.
    action_steps = [rec_title]
    if r['supply_evidence']:
        s = r['supply_evidence'][0]
        action_steps.append(f"Coordinate with supply chain to restore fill rate at {s['warehouse_sku']} "
                             f"(currently {s['fill_rate']}, target >= 0.95).")
    if rs and rs['mean_sentiment'] < 0:
        action_steps.append(f"Review customer support tickets/feedback for {attrs['item']} in {attrs['state']} "
                             f"from {rs['month']} to confirm root cause.")
    if not drivers:
        action_steps.append("Escalate to manual analyst review -- no single driver could be confidently "
                             "attributed from available evidence.")
    if len(action_steps) < 2:
        action_steps.append("Monitor for recurrence over the next reporting period; no further action "
                             "required if the pattern doesn't repeat.")

    # Root-cause synthesis narrative -- same evidence as evidence_list, in
    # prose form for the "Automated Root Cause Reasoning" section.
    synthesis_title = (
        f"{'Supply disruption' if r['supply_evidence'] else driver_label.capitalize() + ' shift'} "
        f"drove {abs(pct) * 100:.0f}% revenue {'decline' if is_drop else 'growth'} for "
        f"{attrs['item']} in {attrs['state']}."
    )
    body_parts = [
        f"On {attrs['date']}, revenue moved {pct * 100:+.1f}% (${attrs['actual_delta']:+,.2f}), with the "
        f"PVM decomposition attributing {pct_of(volume_val)} of the change to volume and {pct_of(price_val)} to price."
    ]
    if r['supply_evidence']:
        s = r['supply_evidence'][0]
        body_parts.append(f"Warehouse {s['warehouse_sku']} reported a fill rate of {s['fill_rate']} with "
                           f"{s['stockout_days']} stockout days that month.")
    if rs:
        turned = rs['direction'].replace('turns_', 'turned ')
        body_parts.append(f"Customer sentiment {turned} that month (mean polarity "
                           f"{rs['mean_sentiment']:.1f} across {rs['review_count']} record(s)).")
    if r['marketing_evidence']:
        body_parts.append("Marketing spend was also elevated the same week, though this is correlational, "
                           "not established as causal.")
    if not drivers:
        body_parts.append("No individual driver (units or price) independently crossed its own anomaly "
                           "threshold, so this variance could not be confidently attributed to a single cause.")

    # Warehouse/logistics block -- status reflects reality: never claim a
    # supply disruption when no supply anomaly was actually found.
    if r['supply_evidence']:
        s = r['supply_evidence'][0]
        logistics = {
            'title': 'Supply Logistics & Warehouse Metrics',
            'status': 'Disrupted',
            'statusClass': 'critical',
            'desc': f"Warehouse {s['warehouse_sku']} in {attrs['state']} reported a fill rate of "
                    f"{s['fill_rate']} with {s['stockout_days']} stockout days in {s['month']}.",
            'metrics': [
                {'label': 'Fill Rate', 'val': f"{s['fill_rate']}", 'valClass': 'danger',
                 'sub': f"{s['stockout_days']} stockout days"},
                {'label': 'Warehouse', 'val': s['warehouse_sku'], 'valClass': '', 'sub': attrs['state']},
                {'label': 'Period', 'val': s['month'], 'valClass': '', 'sub': 'Flagged month'},
            ],
        }
    else:
        logistics = {
            'title': 'Supply Logistics & Warehouse Metrics',
            'status': 'Normal',
            'statusClass': 'active',
            'desc': f"No supply anomaly was detected for {attrs['item']} in {attrs['state']} around this "
                    f"date -- fill rate and stockout days were within normal range.",
            'metrics': [
                {'label': 'Fill Rate', 'val': 'Normal', 'valClass': '', 'sub': 'No anomaly flagged'},
                {'label': 'Stockout Days', 'val': 'Below threshold', 'valClass': '', 'sub': '< 2 days'},
                {'label': 'Warehouse', 'val': warehouse, 'valClass': '', 'sub': attrs['state']},
            ],
        }

    return {
        'id': node_id,
        'title': f"{attrs['item']} Revenue {'Drop' if is_drop else 'Spike'}",
        'category': f"{driver_label.title()}-Driven" if drivers else 'Unattributed Variance',
        'sku': attrs['item'],
        'region': region_label,
        'warehouse': warehouse,
        'date': attrs['date'],
        'zScore': round(attrs['score'], 2),
        'deviation': f"{pct * 100:+.1f}% revenue {direction_word}",
        'confidence': confidence,
        'status': status,
        'headline': f"{attrs['item']} revenue {direction_word} {abs(pct) * 100:.1f}% in {attrs['state']} on {attrs['date']}",
        'summary': rec_impact,
        'pvm': {
            'volume': {'val': round(volume_val, 2), 'pct': pct_of(volume_val),
                       'expl': 'Volume effect from the day-over-day PVM decomposition.'},
            'price': {'val': round(price_val, 2), 'pct': pct_of(price_val),
                      'expl': 'Price effect from the day-over-day PVM decomposition.'},
            'mix': {'val': 0, 'pct': '0%', 'expl': 'Not applicable at this grain (single item/state series).'},
            'other': {'val': round(interaction_val, 2), 'pct': pct_of(interaction_val),
                      'expl': 'Interaction effect (price change x volume change).'},
        },
        'products': [{
            'sku': attrs['item'], 'volumeDelta': pct_of(volume_val),
            'revenueImpact': f"${attrs['actual_delta']:+,.2f}",
            'status': driver_label.title() if drivers else 'Unattributed',
        }],
        'evidence': evidence_list,
        'recommendedAction': {'title': rec_title, 'expectedImpact': rec_impact, 'steps': action_steps},
        'synthesis': {'title': synthesis_title, 'body': " ".join(body_parts)},
        'logistics': logistics,
    }


COLD_START_ITEM_ID = 'HOUSEHOLD_1_020'


def build_cold_start_detail(item_id):
    """
    For an item with zero sales_anomaly nodes in the current window (e.g.
    HOUSEHOLD_1_020) -- there's no revenue anomaly to decompose, so this
    honestly reports that instead of fabricating one, while still surfacing
    whatever real review/supply signals exist via entity traversal
    (graph_query.anomalies_for_item).
    """
    if GRAPH is None:
        return None

    from src.analytics.graph_query import anomalies_for_item

    related = anomalies_for_item(GRAPH, item_id)
    review_nodes = [GRAPH.nodes[n] for n in related if GRAPH.nodes[n]['kind'] == 'review_shift']
    supply_nodes = [GRAPH.nodes[n] for n in related if GRAPH.nodes[n]['kind'] == 'supply_anomaly']
    warehouse_sku = next((GRAPH.nodes[n]['warehouse_sku'] for n in related
                          if GRAPH.nodes[n]['kind'] == 'warehouse_entity'), None)

    state_ids = sorted({r['state'] for r in review_nodes}) or ['CA', 'TX']
    region_map = {'CA': 'CA (West Region)', 'TX': 'TX (South Region)'}
    region_label = " / ".join(region_map.get(s, s) for s in state_ids)

    evidence_list = []
    for s in supply_nodes:
        evidence_list.append({
            'id': f"supply_anom_{s['warehouse_sku']}_{s['state']}_{s['month']}",
            'date': s['month'], 'source': 'source_supply_monthly',
            'type': 'Structured Supply Signal',
            'title': f"Fill rate {s['fill_rate']} at {s['warehouse_sku']}",
            'similarity': 0.9, 'similarityTier': 'high',
            'preview': f"Warehouse {s['warehouse_sku']} reported fill_rate={s['fill_rate']}, "
                       f"{s['stockout_days']} stockout days in {s['month']}.",
            'fullText': f"Warehouse {s['warehouse_sku']} ({s['state']}) reported fill_rate={s['fill_rate']} "
                        f"and {s['stockout_days']} stockout days for {s['month']}.",
        })
    for rs in sorted(review_nodes, key=lambda r: r['month']):
        evidence_list.append({
            'id': f"review_shift_{item_id}_{rs['state']}_{rs['month']}",
            'date': rs['month'], 'source': 'unstructured_feedback',
            'type': f"Review Sentiment Shift ({rs['direction']})",
            'title': f"Customer sentiment turned {'negative' if rs['mean_sentiment'] < 0 else 'positive'} "
                     f"in {rs['state']}, {rs['month']}",
            'similarity': 0.8, 'similarityTier': 'medium' if rs['review_count'] <= 1 else 'high',
            'preview': f"Mean sentiment {rs['mean_sentiment']:.1f} across {rs['review_count']} review(s) in {rs['state']}.",
            'fullText': f"Aggregated review sentiment for {item_id} in {rs['state']} during {rs['month']}: "
                        f"mean polarity {rs['mean_sentiment']:.1f} across {rs['review_count']} record(s) "
                        f"(z={rs['z']:.2f}, {rs['direction']}).",
        })
    if not evidence_list:
        evidence_list.append({
            'id': 'no-evidence', 'date': 'N/A', 'source': 'none',
            'type': 'No Corroborating Evidence', 'title': 'No supply or review evidence found for this item',
            'similarity': 0.0, 'similarityTier': 'low',
            'preview': 'No signals of any kind found for this item in the current window.',
            'fullText': 'No supply anomaly or review sentiment shift was found for this item in the current dataset window.',
        })

    synthesis_body = (
        f"{item_id} has zero sales-anomaly nodes in the current dataset window -- there is not enough "
        f"daily sales history for the trailing z-score detector to evaluate this item yet, so no revenue "
        f"anomaly exists to decompose. "
    )
    if review_nodes:
        synthesis_body += (
            f"{len(review_nodes)} review sentiment signal(s) exist for this item, but with no matching "
            f"sales data to corroborate them, they should be treated as a lead for manual investigation, "
            f"not a confirmed finding."
        )
    else:
        synthesis_body += "No other signals (supply or review) were found for this item either."

    return {
        'id': f"cold_start_{item_id}",
        'title': f"{item_id}: Insufficient Sales History",
        'category': 'Sparse History (Cannot Evaluate)',
        'sku': item_id,
        'region': region_label,
        'warehouse': warehouse_sku or 'N/A',
        'date': 'Current window',
        'zScore': 0,
        'deviation': 'No revenue anomaly -- insufficient history',
        'confidence': 0,
        'status': 'active',
        'headline': f"{item_id} has no sales anomalies detected -- insufficient history in this window",
        'summary': synthesis_body,
        'pvm': {
            'volume': {'val': 0, 'pct': '0%', 'expl': 'No revenue anomaly exists to decompose.'},
            'price': {'val': 0, 'pct': '0%', 'expl': 'No revenue anomaly exists to decompose.'},
            'mix': {'val': 0, 'pct': '0%', 'expl': 'Not applicable.'},
            'other': {'val': 0, 'pct': '0%', 'expl': 'Not applicable.'},
        },
        'products': [{'sku': item_id, 'volumeDelta': 'n/a', 'revenueImpact': 'n/a', 'status': 'Insufficient Data'}],
        'evidence': evidence_list,
        'recommendedAction': {
            'title': 'Bypass automated alerting until sufficient baseline history exists',
            'expectedImpact': 'Prevent false-positive/false-negative alerts on an item the detector cannot yet evaluate.',
            'steps': [
                'Bypass automated z-score alerting for this item until it has a full trailing window of sales history.',
                'Manually review the review-sentiment signals found, if any, since they are not yet corroborated by sales data.',
            ],
        },
        'synthesis': {
            'title': f"{item_id} cannot yet be evaluated for anomalies -- insufficient sales history in this window.",
            'body': synthesis_body,
        },
        'logistics': {
            'title': 'Supply Logistics & Warehouse Metrics',
            'status': 'Insufficient Data' if not supply_nodes else 'Disrupted',
            'statusClass': 'active' if not supply_nodes else 'critical',
            'desc': (f"No supply anomaly flagged for warehouse {warehouse_sku}." if not supply_nodes else
                     f"Warehouse {warehouse_sku} shows a real supply anomaly -- see evidence."),
            'metrics': [
                {'label': 'Warehouse', 'val': warehouse_sku or 'N/A', 'valClass': '', 'sub': region_label},
                {'label': 'Sales Anomalies', 'val': '0', 'valClass': '', 'sub': 'Insufficient history'},
                {'label': 'Review Signals', 'val': str(len(review_nodes)), 'valClass': '', 'sub': 'Uncorroborated'},
            ],
        },
    }


def _get_latest_anomaly_context():
    """
    Node id of the most recent anomaly the live stream has surfaced so far
    (tracked in LATEST_ANOMALY as /api/stream/next advances). Falls back to
    the chronologically last revenue anomaly for the live item/state if the
    stream hasn't reached one yet (e.g. right after server start).
    """
    if LATEST_ANOMALY['node_id']:
        return LATEST_ANOMALY['node_id']
    if GRAPH is None:
        return None
    candidates = sorted(
        (a['date'], n) for n, a in GRAPH.nodes(data=True)
        if a.get('kind') == 'sales_anomaly' and a.get('column') == 'revenue'
        and a.get('item') == LIVE_ITEM and a.get('state') == LIVE_STATE
    )
    return candidates[-1][1] if candidates else None


def _call_groq(messages):
    import socket
    import urllib.request as ur
    import urllib.error as ue

    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return None, "GROQ_API_KEY is not set on the server."

    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 500,
    }).encode('utf-8')
    req = ur.Request(GROQ_API_URL, data=body, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Default urllib User-Agent gets blocked by Cloudflare (error 1010) in front of Groq's API.
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    })

    # api.groq.com resolves to both IPv4 and IPv6, but this host has no default
    # IPv6 route -- urlopen picking the AAAA record first fails outright with
    # "Network is unreachable" instead of falling back to IPv4. Force IPv4-only
    # resolution for this call rather than relying on getaddrinfo's ordering.
    original_getaddrinfo = socket.getaddrinfo

    def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_only_getaddrinfo
    start = time.perf_counter()
    try:
        with ur.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            _record_telemetry('llm_latencies_s', time.perf_counter() - start)
            usage = data.get('usage', {})
            if usage.get('total_tokens'):
                _record_telemetry('llm_tokens', usage['total_tokens'])
            return data['choices'][0]['message']['content'], None
    except ue.HTTPError as e:
        return None, f"Groq API error {e.code}: {e.read().decode('utf-8', errors='ignore')[:300]}"
    except Exception as e:
        return None, f"Groq request failed: {e}"
    finally:
        socket.getaddrinfo = original_getaddrinfo


_CHAT_DATE_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')


def _extract_date_from_message(message):
    """
    Only matches ISO YYYY-MM-DD (the format used everywhere else in this
    dataset/UI, e.g. the date picker). Other formats ("Jan 4 2012",
    "01/04/2012") are not recognized -- falls through to the latest-anomaly
    default rather than guessing at an ambiguous format.
    """
    match = _CHAT_DATE_RE.search(message)
    return match.group(1) if match else None


def build_chat_response(user_message):
    """
    Answers a free-form question. If the question names a specific date
    (ISO format), resolves it via resolve_anomaly_or_stats():
      - that date was itself a flagged anomaly -> evidence is just that.
      - that date had no anomaly -> evidence is that day's raw stats PLUS
        the latest anomaly actually detected, so the answer can say "nothing
        happened that day, but here's what did happen recently".
      - no data at all for that date -> no evidence, said explicitly.
    If no date is mentioned, falls back to the latest anomaly the live
    stream has surfaced so far.
    """
    date_str = _extract_date_from_message(user_message)
    evidence = {}
    notes = []

    if date_str:
        queried = resolve_anomaly_or_stats(LIVE_ITEM, LIVE_STATE, date_str)
        if queried is None:
            notes.append(f"No data exists for {LIVE_ITEM} in {LIVE_STATE} on {date_str}.")
        else:
            evidence['queried_date'] = queried
            if queried.get('category') == 'No Anomaly Detected':
                notes.append(f"{date_str} was NOT itself flagged as an anomaly -- 'queried_date' "
                              f"below is just that day's actual figures.")
                latest_node_id = _get_latest_anomaly_context()
                latest = build_dynamic_anomaly_detail(latest_node_id) if latest_node_id else None
                if latest and latest['id'] != queried['id']:
                    evidence['latest_anomaly'] = latest
                    notes.append("Since the asked-about date had no anomaly, also mention the most "
                                  "recent anomaly that WAS actually detected ('latest_anomaly' below).")
            else:
                notes.append(f"{date_str} was itself a detected anomaly.")
    else:
        latest_node_id = _get_latest_anomaly_context()
        latest = build_dynamic_anomaly_detail(latest_node_id) if latest_node_id else None
        if latest:
            evidence['latest_anomaly'] = latest
            notes.append("No specific date was mentioned, so this uses the latest detected anomaly.")
        else:
            notes.append("No anomaly evidence is currently available (graph or live stream not ready).")

    context_note = " ".join(notes)
    evidence_json = json.dumps(evidence, indent=2) if evidence else "{}"
    resolved_id = (evidence.get('queried_date') or evidence.get('latest_anomaly') or {}).get('id')

    system_prompt = (
        "You are a KPI intelligence assistant talking directly to a business user, not a "
        "developer. Answer using ONLY the facts in the evidence JSON below, but explain them "
        "in plain, everyday business language -- as if summarizing findings to a colleague, "
        "not reading out a data structure. For example say 'the drop was almost entirely "
        "because fewer units sold, not a price change' rather than naming fields like "
        "'volume_effect' or 'zScore'. Do NOT reference JSON field names, node ids, or use "
        "citation-style brackets (no '[evidence...]', no 'node_id'). If there are two evidence "
        "sections (queried_date and latest_anomaly), address both clearly but naturally, e.g. "
        "'Nothing unusual happened on that day -- revenue was normal at $X. The most recent real "
        "issue we detected was on a different date, caused by...'. Do not invent numbers, dates, "
        "or causes that are not in the evidence. If the evidence doesn't support a confident "
        "answer, say so plainly. Keep it to 3-5 short sentences."
    )
    user_prompt = f"{context_note}\n\nEvidence JSON:\n{evidence_json}\n\nQuestion: {user_message}"

    reply, error = _call_groq([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])
    if error:
        return {"error": error, "anomaly_context": resolved_id}
    return {"reply": reply, "anomaly_context": resolved_id}


class ApiRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS for local development
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept')
        # This app is under active development -- static JS/CSS/HTML change frequently,
        # and browsers cache them aggressively by default, which has already caused a
        # real bug (a stale cached .js missing a newly-added function while the page's
        # .html loaded fresh). Disable caching for everything served here.
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
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

        # 2. Latest Anomalies -- the 4 real featured cases, built once at startup
        if path == '/api/anomalies/latest' or path == '/api/anomalies':
            self._send_json(FEATURED_ANOMALIES)
            return

        # 3. Anomaly Detail: /api/anomalies/{key}
        if path.startswith('/api/anomalies/'):
            parts = path.split('/')
            key = parts[3] if len(parts) > 3 else FEATURED_ANOMALY_KEYS[0][1]
            _t0 = time.perf_counter()
            detail = (build_cold_start_detail(COLD_START_ITEM_ID) if key.startswith('cold_start_')
                      else build_dynamic_anomaly_detail(key))
            _record_telemetry('sql_latencies_ms', (time.perf_counter() - _t0) * 1000)
            if detail:
                self._send_json(detail)
            elif FEATURED_ANOMALIES:
                self._send_json(FEATURED_ANOMALIES[0])
            else:
                self._send_json({"error": "anomaly not found and no fallback available"}, status_code=404)
            return

        # 5. Live stream: next record in the replayed daily series
        if path == '/api/stream/next':
            if not LIVE_SERIES:
                self._send_json({"error": "live backend unavailable"}, status_code=503)
                return
            i = LIVE_CURSOR['i']
            record = LIVE_SERIES[i]
            LIVE_CURSOR['i'] = (i + 1) % len(LIVE_SERIES)
            if record['is_anomaly']:
                LATEST_ANOMALY['node_id'] = record['node_id']
            self._send_json(record)
            return

        if path == '/api/stream/reset':
            LIVE_CURSOR['i'] = 0
            self._send_json({"success": True})
            return

        # Real historical series for the chart's year filter buttons -- replaces
        # the old hardcoded REVENUE_TIMELINE_DATA mock.
        if path == '/api/history':
            qs = parse_qs(parsed.query)
            item_id = qs.get('item', [LIVE_ITEM])[0]
            state_id = qs.get('state', [LIVE_STATE])[0]
            year = qs.get('year', ['all'])[0]
            series = build_history_series(item_id, state_id, year)
            if series is None:
                self._send_json({"error": "history unavailable"}, status_code=503)
            else:
                self._send_json(series)
            return

        # 6. Manual date query: exact anomaly if one exists, else nearest prior
        if path == '/api/query':
            qs = parse_qs(parsed.query)
            date_str = qs.get('date', [None])[0]
            item_id = qs.get('item', [LIVE_ITEM])[0]
            state_id = qs.get('state', [LIVE_STATE])[0]
            if not date_str:
                self._send_json({"error": "date parameter required"}, status_code=400)
                return

            _t0 = time.perf_counter()
            result = resolve_anomaly_or_stats(item_id, state_id, date_str)
            _record_telemetry('sql_latencies_ms', (time.perf_counter() - _t0) * 1000)

            if result:
                self._send_json(result)
            else:
                self._send_json({"error": "no data for this item/state/date"}, status_code=404)
            return

        # 4. Telemetry Metrics -- real measured values (see TELEMETRY / _record_telemetry),
        # not the old hardcoded 142ms/1.8s/$0.004/"Gemini Flash 2.5" mock.
        if path == '/api/telemetry':
            def _avg(lst):
                return round(sum(lst) / len(lst), 2) if lst else None

            active_anomalies_count = 0
            if GRAPH is not None:
                active_anomalies_count = sum(
                    1 for _, a in GRAPH.nodes(data=True)
                    if a.get('kind') in ('sales_anomaly', 'marketing_anomaly', 'supply_anomaly', 'review_shift')
                )

            data_freshness_days = None
            if LIVE_SERIES:
                import datetime
                last_date = datetime.datetime.strptime(LIVE_SERIES[-1]['date'], '%Y-%m-%d')
                data_freshness_days = (datetime.datetime.now() - last_date).days

            avg_tokens = _avg(TELEMETRY['llm_tokens'])
            # Rough order-of-magnitude estimate, not exact billing -- Groq's actual
            # per-token rate for this model isn't queried here.
            APPROX_COST_PER_TOKEN = 0.0000002
            token_cost_usd = round(avg_tokens * APPROX_COST_PER_TOKEN, 6) if avg_tokens else None

            self._send_json({
                "sql_latency_ms": _avg(TELEMETRY['sql_latencies_ms']),
                "llm_latency_s": _avg(TELEMETRY['llm_latencies_s']),
                "avg_tokens_per_call": avg_tokens,
                "token_cost_usd": token_cost_usd,
                "token_cost_is_estimate": True,
                "data_freshness_days": data_freshness_days,
                "active_anomalies_count": active_anomalies_count,
                "model": GROQ_MODEL,
                "sample_size": len(TELEMETRY['sql_latencies_ms']) + len(TELEMETRY['llm_latencies_s']),
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

        # 0. General chatbot query (Groq-backed, grounded in the latest anomaly's evidence)
        if path == '/api/chat':
            message = payload.get('message', '').strip()
            if not message:
                self._send_json({"error": "message required"}, status_code=400)
                return
            result = build_chat_response(message)
            self._send_json(result)
            return

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
    _load_live_backend()
    socketserver.TCPServer.allow_reuse_address = True
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
