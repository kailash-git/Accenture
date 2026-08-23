-- SQLite Database Initialization Schema
-- Track: BusinessIntelligence.ai
-- Mapped by Sivasubramanian S & Thirukailash K A

PRAGMA foreign_keys = ON;

-- 1. Product Metadata Table
CREATE TABLE IF NOT EXISTS product_details (
    sku_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL
);

-- 2. Structured Sales Transactions Table
CREATE TABLE IF NOT EXISTS sales_transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,          -- Format: YYYY-MM-DD
    region TEXT NOT NULL,        -- East, West, North, South
    sku_id TEXT NOT NULL,
    sales_volume INTEGER NOT NULL CHECK (sales_volume >= 0),
    average_selling_price REAL NOT NULL CHECK (average_selling_price >= 0),
    FOREIGN KEY (sku_id) REFERENCES product_details (sku_id)
);

-- 3. Structured Inventory Records Table
CREATE TABLE IF NOT EXISTS inventory_records (
    inventory_id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,          -- Format: YYYY-MM-DD
    region TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    inventory_on_hand INTEGER NOT NULL CHECK (inventory_on_hand >= 0),
    reorder_point INTEGER NOT NULL CHECK (reorder_point >= 0),
    warehouse_bay_number TEXT NOT NULL,
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days >= 0),
    average_inventory_cost REAL NOT NULL CHECK (average_inventory_cost >= 0),
    FOREIGN KEY (sku_id) REFERENCES product_details (sku_id)
);

-- 4. Unstructured Customer Reviews Table
CREATE TABLE IF NOT EXISTS customer_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,          -- Format: YYYY-MM-DD
    region TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    review_text TEXT NOT NULL,
    sentiment_score REAL NOT NULL CHECK (sentiment_score BETWEEN -1.0 AND 1.0),
    FOREIGN KEY (sku_id) REFERENCES product_details (sku_id)
);

-- 5. Unstructured Support Tickets Table
CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,          -- Format: YYYY-MM-DD
    region TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    issue_description TEXT NOT NULL,
    urgency_level TEXT CHECK(urgency_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    FOREIGN KEY (sku_id) REFERENCES product_details (sku_id)
);

-- 6. User Feedback Loops Table
CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_id TEXT NOT NULL,
    rating INTEGER CHECK(rating IN (-1, 1)), -- -1 for thumbs down, 1 for thumbs up
    user_comments TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);
