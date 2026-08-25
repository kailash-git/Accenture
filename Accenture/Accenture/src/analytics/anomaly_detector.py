"""
src/analytics/anomaly_detector.py
Statistical Anomaly Detector for tracking KPI movements (Revenue, Gross Margin %, Inventory Turnover).
"""

import sqlite3
import numpy as np
import pandas as pd

class AnomalyDetector:
    def __init__(self, db_path):
        self.db_path = db_path

    def run_detection(self, kpi_name="Revenue", time_grain="monthly", window_periods=8, threshold=2.0):
        """
        Run statistical z-score detection on the specified KPI and grain.
        """
        conn = sqlite3.connect(self.db_path)
        
        # 1. Fetch sales and inventory data to compute metrics
        if kpi_name == "Revenue" or kpi_name == "GrossMarginPercent":
            query = """
            SELECT date, item_id, state_id, revenue, cost_of_goods_sold 
            FROM fact_sales_daily
            """
            df = pd.read_sql_query(query, conn)
            df['date'] = pd.to_datetime(df['date'])
            
            # Map grains
            if time_grain == "monthly":
                df['period'] = df['date'].dt.to_period('M')
            elif time_grain == "weekly":
                df['period'] = df['date'].dt.to_period('W-MON')
            else:
                df['period'] = df['date'].dt.to_period('D')
                
            # Aggregate KPIs at the grain
            grouped = df.groupby(['period', 'item_id', 'state_id']).agg({
                'revenue': 'sum',
                'cost_of_goods_sold': 'sum'
            }).reset_index()
            
            # Formulate Gross Margin % at period level (not average of daily percentages)
            grouped['gross_margin_percent'] = (grouped['revenue'] - grouped['cost_of_goods_sold']) / grouped['revenue']
            grouped['gross_margin_percent'] = grouped['gross_margin_percent'].fillna(0.0)
            
            # KPI select
            if kpi_name == "Revenue":
                grouped['kpi_value'] = grouped['revenue']
            else:
                grouped['kpi_value'] = grouped['gross_margin_percent']
                
        elif kpi_name == "InventoryTurnover":
            query = """
            SELECT il.date, il.item_id, il.state_id, il.inventory_on_hand, sl.supplier_raw_cost, 
                   COALESCE(fs.cost_of_goods_sold, 0.0) as cost_of_goods_sold
            FROM inventory_logs il
            JOIN sku_lookup sl ON il.item_id = sl.item_id
            LEFT JOIN fact_sales_daily fs ON il.date = fs.date AND il.item_id = fs.item_id
            """
            df = pd.read_sql_query(query, conn)
            df['date'] = pd.to_datetime(df['date'])
            df['inventory_value'] = df['inventory_on_hand'] * df['supplier_raw_cost']
            
            if time_grain == "monthly":
                df['period'] = df['date'].dt.to_period('M')
            else:
                df['period'] = df['date'].dt.to_period('W-MON')
                
            grouped = df.groupby(['period', 'item_id', 'state_id']).agg({
                'cost_of_goods_sold': 'sum',
                'inventory_value': 'mean'
            }).reset_index()
            
            # Avoid division by zero
            grouped['kpi_value'] = grouped['cost_of_goods_sold'] / grouped['inventory_value']
            grouped['kpi_value'] = grouped['kpi_value'].fillna(0.0)
            
        else:
            conn.close()
            raise ValueError(f"Unknown KPI: {kpi_name}")
            
        conn.close()
        
        # Sort values
        grouped = grouped.sort_values(by=['item_id', 'state_id', 'period']).reset_index(drop=True)
        
        # 2. Run statistical rolling z-score detection
        anomalies_detected = []
        
        for (item_id, state_id), group in grouped.groupby(['item_id', 'state_id']):
            group = group.reset_index(drop=True)
            n_rows = len(group)
            
            for i in range(n_rows):
                current_period = group.loc[i, 'period']
                current_val = group.loc[i, 'kpi_value']
                
                # Baseline window: previous window_periods observations
                start_idx = max(0, i - window_periods)
                end_idx = i # exclusive of current
                
                # Seasonal awareness: If we have the same period last year, we prioritize it
                has_seasonal = False
                if time_grain == "monthly" and i >= 12:
                    last_year_val = group.loc[i - 12, 'kpi_value']
                    # Calculate seasonal z-score based on historical deviations if possible
                    # E.g. we look at previous observations but compare deviations from seasonal value
                    has_seasonal = True
                
                if end_idx - start_idx < 3:
                    # Insufficient history for statistical detection
                    z_score = 0.0
                    mean_val = current_val
                    std_val = 0.0
                    confidence = 50.0
                else:
                    baseline_vals = group.loc[start_idx:end_idx-1, 'kpi_value'].values
                    mean_val = np.mean(baseline_vals)
                    std_val = np.std(baseline_vals)
                    
                    if std_val < 1e-5:
                        z_score = 0.0
                    else:
                        z_score = (current_val - mean_val) / std_val
                    confidence = 90.0
                    
                    # Apply seasonal index scaling if we have it
                    if has_seasonal:
                        # Seasonal adjustment: scale z-score to incorporate last year's deviation
                        # Let's adjust z-score if it matches the seasonal trend
                        seasonal_diff = current_val - group.loc[i - 12, 'kpi_value']
                        # E.g., if YoY difference is small, z-score is tempered (it's expected seasonal movement)
                        # We temper the z-score by incorporating the YoY variance
                        yoy_baseline = [group.loc[j, 'kpi_value'] - group.loc[j-12, 'kpi_value'] for j in range(12, i) if j >= 12]
                        if len(yoy_baseline) >= 3:
                            yoy_mean = np.mean(yoy_baseline)
                            yoy_std = np.std(yoy_baseline)
                            if yoy_std > 1e-5:
                                yoy_z = (seasonal_diff - yoy_mean) / yoy_std
                                # Combine z-score with seasonal z-score
                                z_score = 0.7 * yoy_z + 0.3 * z_score
                                confidence = 95.0
                
                # Check threshold
                if abs(z_score) >= threshold:
                    direction = "UP" if current_val > mean_val else "DOWN"
                    deviation_pct = (current_val - mean_val) / mean_val if mean_val > 0 else 0.0
                    
                    # Severity mapping
                    if abs(z_score) > 3.0:
                        severity = "CRITICAL"
                    elif abs(z_score) > 2.0:
                        severity = "WARNING"
                    else:
                        severity = "ACTIVE"
                        
                    anomalies_detected.append({
                        "kpi_name": kpi_name,
                        "item_id": item_id,
                        "state_id": state_id,
                        "period": str(current_period),
                        "actual_value": float(current_val),
                        "baseline_value": float(mean_val),
                        "deviation_pct": float(deviation_pct),
                        "z_score": float(z_score),
                        "direction": direction,
                        "severity": severity,
                        "confidence": float(confidence),
                        "time_grain": time_grain
                    })
                    
        return anomalies_detected
