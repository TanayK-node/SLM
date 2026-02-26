import sqlite3
import os

def create_complex_db():
    # Ensure we are saving it in the root directory
    db_path = os.path.join(os.path.dirname(__file__), "company_data.db")
    
    # Delete the old flat database if it exists
    if os.path.exists(db_path):
        os.remove(db_path)
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # TABLE 1: Users (The Quants and Analysts)
    cursor.execute("""
    CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        role TEXT
    )
    """)
    
    # TABLE 2: Algorithms (Linked to Users)
    cursor.execute("""
    CREATE TABLE algorithms (
        algo_id INTEGER PRIMARY KEY,
        algo_name TEXT,
        status TEXT,
        creator_id INTEGER,
        FOREIGN KEY(creator_id) REFERENCES users(user_id)
    )
    """)
    
    # TABLE 3: Trades (Linked to Algorithms)
    cursor.execute("""
    CREATE TABLE trades (
        trade_id INTEGER PRIMARY KEY,
        algo_id INTEGER,
        symbol TEXT,
        trade_type TEXT,
        profit_loss REAL,
        FOREIGN KEY(algo_id) REFERENCES algorithms(algo_id)
    )
    """)
    
    # Insert Users
    cursor.executemany("INSERT INTO users (name, role) VALUES (?, ?)", [
        ("Alice", "Senior Quant"),
        ("Bob", "Junior Analyst")
    ])
    
    # Insert Algorithms
    cursor.executemany("INSERT INTO algorithms (algo_name, status, creator_id) VALUES (?, ?, ?)", [
        ("Momentum_v1", "Active", 1),       # Alice's bot
        ("Arb_Bot_v4", "Active", 1),        # Alice's bot
        ("Mean_Reversion_v2", "Inactive", 2) # Bob's bot
    ])
    
    # Insert Trades (Profits and Losses)
    cursor.executemany("INSERT INTO trades (algo_id, symbol, trade_type, profit_loss) VALUES (?, ?, ?, ?)", [
        (1, "AAPL", "BUY", 1500.00),
        (1, "TSLA", "SELL", -300.50),
        (2, "BTC", "BUY", 5000.00),
        (2, "ETH", "BUY", 1200.00),
        (3, "MSFT", "SELL", -800.00),
        (3, "GOOGL", "BUY", 200.00)
    ])
    
    conn.commit()
    conn.close()
    print("✅ Complex relational database 'company_data.db' created successfully.")

if __name__ == "__main__":
    create_complex_db()