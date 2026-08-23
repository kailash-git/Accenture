import sqlite3
import pandas as pd
import numpy as np

def get_pvm_data(db_path, start_date_0, end_date_0, start_date_1, end_date_1, state_id=None, cat_id=None):
    """
    Retrieves aggregated sales data for two comparison windows:
    - Period 0: Baseline (start_date_0 to end_date_0)
    - Period 1: Anomaly/Test (start_date_1 to end_date_1)
    
    Filters by state_id or product cat_id if provided.
    """
    conn = sqlite3.connect(db_path)
    
    query = """
    SELECT 
        item_id,
        cat_id,
        state_id,
        CASE 
            WHEN date >= ? AND date <= ? THEN 0
            WHEN date >= ? AND date <= ? THEN 1
            ELSE -1
        END as period,
        SUM(units) as total_units,
        SUM(revenue) as total_revenue
    FROM fact_sales_daily
    WHERE (date >= ? AND date <= ?) OR (date >= ? AND date <= ?)
    """
    params = [
        start_date_0, end_date_0,
        start_date_1, end_date_1,
        start_date_0, end_date_0,
        start_date_1, end_date_1
    ]
    
    if state_id:
        query += " AND state_id = ?"
        params.append(state_id)
    if cat_id:
        query += " AND cat_id = ?"
        params.append(cat_id)
        
    query += " GROUP BY item_id, cat_id, state_id, period"
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    
    # Filter out any rows that fall outside the two periods
    df = df[df['period'] != -1].copy()
    return df

def calculate_pvm(db_path, start_date_0, end_date_0, start_date_1, end_date_1, state_id=None, cat_id=None):
    """
    Calculates the Price-Volume-Mix decomposition between Period 0 and Period 1.
    
    Returns a dictionary containing:
    - baseline_revenue
    - anomaly_revenue
    - revenue_variance
    - price_effect
    - volume_effect
    - mix_effect
    - product_breakdown (list of detailed items)
    """
    df = get_pvm_data(db_path, start_date_0, end_date_0, start_date_1, end_date_1, state_id, cat_id)
    
    if df.empty:
        return {
            "baseline_revenue": 0.0, "anomaly_revenue": 0.0, "revenue_variance": 0.0,
            "price_effect": 0.0, "volume_effect": 0.0, "mix_effect": 0.0,
            "product_breakdown": []
        }
        
    # Pivot to get Period 0 and Period 1 side by side per item_id
    pivoted = df.pivot(index=['item_id', 'cat_id', 'state_id'], columns='period', 
                       values=['total_units', 'total_revenue']).fillna(0.0)
    
    # Flatten columns
    pivoted.columns = [f"{col[0]}_{col[1]}" for col in pivoted.columns]
    pivoted = pivoted.reset_index()
    
    # Rename for convenience
    pivoted = pivoted.rename(columns={
        'total_units_0': 'v0', 'total_revenue_0': 'r0',
        'total_units_1': 'v1', 'total_revenue_1': 'r1'
    })
    
    # If no data exists for either baseline or test, return zeros
    if pivoted.empty:
        return {
            "baseline_revenue": 0.0, "anomaly_revenue": 0.0, "revenue_variance": 0.0,
            "price_effect": 0.0, "volume_effect": 0.0, "mix_effect": 0.0,
            "product_breakdown": []
        }
    
    # Calculate Average Selling Prices (ASP) per item
    pivoted['p0'] = np.where(pivoted['v0'] > 0, pivoted['r0'] / pivoted['v0'], 0.0)
    pivoted['p1'] = np.where(pivoted['v1'] > 0, pivoted['r1'] / pivoted['v1'], 0.0)
    
    # Handle launch/discontinuations:
    # If item is new in Period 1 (v0 = 0), set p0 = p1 so price effect is 0
    pivoted['p0'] = np.where(pivoted['v0'] == 0, pivoted['p1'], pivoted['p0'])
    # If item is discontinued in Period 1 (v1 = 0), set p1 = p0 so price effect is 0
    pivoted['p1'] = np.where(pivoted['v1'] == 0, pivoted['p0'], pivoted['p1'])
    
    # Total Volumes
    v0_total = pivoted['v0'].sum()
    v1_total = pivoted['v1'].sum()
    
    # Shares of volume per product
    pivoted['s0'] = np.where(v0_total > 0, pivoted['v0'] / v0_total, 0.0)
    pivoted['s1'] = np.where(v1_total > 0, pivoted['v1'] / v1_total, 0.0)
    
    # Price Effect (per item): (P1 - P0) * V1
    pivoted['price_effect'] = (pivoted['p1'] - pivoted['p0']) * pivoted['v1']
    
    # For Volume and Mix, we need the weighted baseline price
    # Volume Effect (per item): (V1_total - V0_total) * P0 * S0
    pivoted['volume_effect'] = (v1_total - v0_total) * pivoted['p0'] * pivoted['s0']
    
    # Mix Effect (per item): V1_total * P0 * (S1 - S0)
    pivoted['mix_effect'] = v1_total * pivoted['p0'] * (pivoted['s1'] - pivoted['s0'])
    
    # Total calculations
    baseline_revenue = pivoted['r0'].sum()
    anomaly_revenue = pivoted['r1'].sum()
    revenue_variance = anomaly_revenue - baseline_revenue
    
    price_effect = pivoted['price_effect'].sum()
    volume_effect = pivoted['volume_effect'].sum()
    mix_effect = pivoted['mix_effect'].sum()
    
    # Build product-level breakdown list
    breakdown = []
    for _, row in pivoted.iterrows():
        breakdown.append({
            "item_id": row['item_id'],
            "cat_id": row['cat_id'],
            "state_id": row['state_id'],
            "v0": int(row['v0']),
            "v1": int(row['v1']),
            "r0": round(row['r0'], 2),
            "r1": round(row['r1'], 2),
            "p0": round(row['p0'], 4),
            "p1": round(row['p1'], 4),
            "price_effect": round(row['price_effect'], 2),
            "volume_effect": round(row['volume_effect'], 2),
            "mix_effect": round(row['mix_effect'], 2),
            "variance": round(row['r1'] - row['r0'], 2)
        })
        
    return {
        "baseline_revenue": round(baseline_revenue, 2),
        "anomaly_revenue": round(anomaly_revenue, 2),
        "revenue_variance": round(revenue_variance, 2),
        "price_effect": round(price_effect, 2),
        "volume_effect": round(volume_effect, 2),
        "mix_effect": round(mix_effect, 2),
        "product_breakdown": breakdown
    }
