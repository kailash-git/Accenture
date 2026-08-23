-- db_init.sql
-- Relational database structure for BusinessIntelligence.ai KPI Engine
PRAGMA foreign_keys = ON;

-- 1. Product SKU Lookup & Supplier Cost Table
CREATE TABLE IF NOT EXISTS sku_lookup (
    item_id TEXT PRIMARY KEY,
    warehouse_sku TEXT NOT NULL,
    supplier_raw_cost REAL NOT NULL
);

-- 2. Daily Sales Fact Table
CREATE TABLE IF NOT EXISTS fact_sales_daily (
    date TEXT NOT NULL,
    item_id TEXT NOT NULL,
    dept_id TEXT NOT NULL,
    cat_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    state_id TEXT NOT NULL,
    d TEXT NOT NULL,
    units INTEGER NOT NULL,
    wm_yr_wk INTEGER NOT NULL,
    event_name_1 TEXT,
    event_type_1 TEXT,
    snap_CA INTEGER,
    snap_TX INTEGER,
    snap_WI INTEGER,
    sell_price REAL NOT NULL,
    price_source_grain TEXT NOT NULL,
    price_is_imputed INTEGER NOT NULL,
    revenue REAL NOT NULL,
    cost_of_goods_sold REAL NOT NULL,
    gross_margin_percent REAL NOT NULL,
    PRIMARY KEY (date, item_id, store_id),
    FOREIGN KEY(item_id) REFERENCES sku_lookup(item_id)
);

-- 3. Weekly Marketing Spend Table
CREATE TABLE IF NOT EXISTS source_marketing_weekly (
    week_start_monday TEXT NOT NULL,
    region_name TEXT NOT NULL,
    channel TEXT NOT NULL,
    marketing_spend REAL NOT NULL,
    PRIMARY KEY (week_start_monday, region_name, channel)
);

-- 4. Monthly Supply Metrics Table
CREATE TABLE IF NOT EXISTS source_supply_monthly (
    warehouse_sku TEXT NOT NULL,
    state_id TEXT NOT NULL,
    month TEXT NOT NULL, -- Format: YYYY-MM
    fill_rate REAL NOT NULL,
    stockout_days INTEGER NOT NULL,
    PRIMARY KEY (warehouse_sku, state_id, month),
    FOREIGN KEY(warehouse_sku) REFERENCES sku_lookup(warehouse_sku)
);

-- 5. Unstructured Customer Feedback & Support Tickets Table
CREATE TABLE IF NOT EXISTS unstructured_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    state_id TEXT NOT NULL,
    source TEXT NOT NULL, -- 'customer review', 'support ticket', 'carrier email'
    text_content TEXT NOT NULL,
    date TEXT NOT NULL, -- YYYY-MM-DD
    FOREIGN KEY(item_id) REFERENCES sku_lookup(item_id)
);

-- 6. User Feedback Loop Table
CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_id TEXT NOT NULL,
    rating INTEGER NOT NULL, -- 1 for Thumbs Up, -1 for Thumbs Down
    user_comments TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);
