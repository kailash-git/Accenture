import sqlite3
import numpy as np
import pandas as pd

# source_marketing_weekly.region_name only ever takes these two values; there is
# no direct region -> state key in the data, per the handoff doc's section 1.
REGION_TO_STATE = {"West": "CA", "South": "TX"}


def get_item_state_daily(db_path):
    """
    Aggregates fact_sales_daily from item x store x date grain up to
    item_id x state_id x date, summing units and revenue across every
    store within a state. Derives an aggregate average selling price
    (ASP = revenue / units) per row, since sell_price itself is a
    per-store value and has no single aggregate at this grain.
    """
    conn = sqlite3.connect(db_path)
    query = """
    SELECT
        item_id,
        state_id,
        date,
        SUM(units) as units,
        SUM(revenue) as revenue
    FROM fact_sales_daily
    GROUP BY item_id, state_id, date
    ORDER BY item_id, state_id, date
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df['sell_price'] = np.where(df['units'] > 0, df['revenue'] / df['units'], 0.0)
    return df


def get_marketing_weekly(db_path):
    """
    Loads source_marketing_weekly at its native (week, region, channel) grain
    and maps region_name to state_id via the hardcoded REGION_TO_STATE table,
    since no direct key exists in the data.
    """
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT week_start_monday, region_name, channel, marketing_spend FROM source_marketing_weekly",
        conn
    )
    conn.close()

    df['week_start_monday'] = pd.to_datetime(df['week_start_monday'])
    df['state_id'] = df['region_name'].map(REGION_TO_STATE)
    return df


def get_supply_monthly(db_path):
    """
    Loads source_supply_monthly joined to sku_lookup to attach item_id,
    since supply is keyed by warehouse_sku/state_id, not item_id directly.
    """
    conn = sqlite3.connect(db_path)
    query = """
    SELECT
        ss.warehouse_sku,
        ss.state_id,
        ss.month,
        ss.fill_rate,
        ss.stockout_days,
        sl.item_id
    FROM source_supply_monthly ss
    JOIN sku_lookup sl ON ss.warehouse_sku = sl.warehouse_sku
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_events(db_path):
    """
    Loads every distinct (date, event_name_1) pair in fact_sales_daily.
    Confirmed empirically: no date in this dataset has more than one distinct
    event_name_1, so date alone is a safe, collision-free key for event nodes
    (unlike the anomaly types, which needed item/state added to their ids).
    """
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT DISTINCT date, event_name_1, event_type_1 "
        "FROM fact_sales_daily WHERE event_name_1 IS NOT NULL",
        conn
    )
    conn.close()
    return df
