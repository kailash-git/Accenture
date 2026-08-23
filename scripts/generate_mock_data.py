"""
generate_mock_data.py
Seeding script to load Parquet sources, compute costs/margins, generate unstructured text reviews,
and initialize the SQLite database (business_bi.db).
"""
import os
import sqlite3
import pandas as pd

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
            "text_content": "WARNING: There is a pricing billing bug for FOODS_3_586. The shelf price was labeled $1.68 but the self-checkout register charged my card double ($3.36). Please fix this price checker error!",
            "date": "2013-05-15"
        },
        {
            "item_id": "FOODS_3_586",
            "state_id": "TX",
            "source": "support ticket",
            "text_content": "Customer support hotline received 12 complaints today regarding pricing discrepancies for FOODS_3_586. Register is overcharging by exactly $1.68. It shows high dollar revenue in our logs but customers are demanding refunds.",
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

def main():
    if not os.path.exists(SALES_PARQUET):
        raise FileNotFoundError(f"Parquet files not found in {DATA_DIR}. Please copy them from KPI-data first.")
        
    init_database()
    seed_sku_lookup()
    seed_sales()
    seed_marketing()
    seed_supply()
    seed_unstructured_feedback()
    print("\nDatabase seeding completed successfully. Verification ready!")

if __name__ == '__main__':
    main()
