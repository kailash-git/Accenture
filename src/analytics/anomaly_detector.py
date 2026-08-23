import sqlite3
import pandas as pd
import numpy as np

def get_weekly_series(db_path, item_id=None, state_id=None):
    """
    Queries fact_sales_daily, standardizing dates to Monday-start weeks,
    and aggregates revenue and units.
    """
    conn = sqlite3.connect(db_path)
    
    # We standardize the date to the preceding Monday in SQL
    # in SQLite: date(date, 'weekday 0', '-6 days') calculates the Monday of the week
    query = """
    SELECT 
        date(date, 'weekday 0', '-6 days') as week_start_monday,
        item_id,
        state_id,
        SUM(units) as units,
        SUM(revenue) as revenue
    FROM fact_sales_daily
    WHERE 1=1
    """
    params = []
    if item_id:
        query += " AND item_id = ?"
        params.append(item_id)
    if state_id:
        query += " AND state_id = ?"
        params.append(state_id)
        
    query += " GROUP BY week_start_monday, item_id, state_id ORDER BY week_start_monday ASC"
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    
    df['week_start_monday'] = pd.to_datetime(df['week_start_monday'])
    return df

def detect_anomalies(db_path, item_id=None, state_id=None, window_size=8, threshold=2.0):
    """
    Calculates rolling z-scores on weekly revenue to detect anomalies.
    Returns a list of dictionaries with anomaly alerts.
    """
    df = get_weekly_series(db_path, item_id, state_id)
    alerts = []
    
    # Process each series (item_id + state_id combination) separately
    for (item, state), group in df.groupby(['item_id', 'state_id']):
        group = group.sort_values('week_start_monday').copy()
        
        # Calculate rolling mean and std of PREVIOUS weeks (shifting by 1)
        rolling_mean = group['revenue'].shift(1).rolling(window=window_size, min_periods=4).mean()
        rolling_std = group['revenue'].shift(1).rolling(window=window_size, min_periods=4).std()
        
        # Avoid division by zero
        rolling_std = rolling_std.replace(0, np.nan)
        
        # Compute z-score
        z_scores = (group['revenue'] - rolling_mean) / rolling_std
        
        group['rolling_mean'] = rolling_mean
        group['rolling_std'] = rolling_std
        group['z_score'] = z_scores
        
        # Identify rows exceeding threshold
        anomalous_rows = group[group['z_score'].abs() > threshold]
        
        for idx, row in anomalous_rows.iterrows():
            z = row['z_score']
            baseline = row['rolling_mean']
            curr_val = row['revenue']
            dev_pct = ((curr_val - baseline) / baseline) if baseline > 0 else 0
            
            alerts.append({
                "week_start_monday": row['week_start_monday'].strftime('%Y-%m-%d'),
                "item_id": item,
                "state_id": state,
                "revenue": round(curr_val, 2),
                "baseline_revenue": round(baseline, 2),
                "z_score": round(z, 4),
                "direction": "spike" if z > 0 else "drop",
                "deviation_pct": round(dev_pct, 4)
            })
            
    return alerts
