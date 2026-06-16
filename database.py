import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kronos_broker.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Portfolio table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY,
                cash_balance REAL NOT NULL,
                total_equity REAL NOT NULL
            )
        """)
        
        # Initialize with 10,000 starting cash if empty
        cursor.execute("SELECT COUNT(*) FROM portfolio")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO portfolio (id, cash_balance, total_equity) VALUES (1, 10000.0, 10000.0)")

        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                category TEXT DEFAULT 'crypto_mid',
                sell_signal_count INTEGER DEFAULT 0,
                peak_price REAL
            )
        """)
        
        # Alter table for existing dbs (ignore if already exists)
        try:
            cursor.execute("ALTER TABLE positions ADD COLUMN category TEXT DEFAULT 'crypto_mid'")
            cursor.execute("ALTER TABLE positions ADD COLUMN sell_signal_count INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE positions ADD COLUMN peak_price REAL")
        except sqlite3.OperationalError:
            pass # Columns already exist

        # Trade history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                entry_time TEXT NOT NULL,
                exit_price REAL NOT NULL,
                exit_time TEXT NOT NULL,
                pnl REAL NOT NULL,
                pnl_percent REAL NOT NULL,
                category TEXT DEFAULT 'crypto_mid'
            )
        """)
        
        # Alter table for existing dbs (ignore if already exists)
        try:
            cursor.execute("ALTER TABLE trade_history ADD COLUMN category TEXT DEFAULT 'crypto_mid'")
        except sqlite3.OperationalError:
            pass # Columns already exist
        
        # Settings table (for daemon toggle)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('daemon_enabled', 'false')")
        
        conn.commit()

def get_setting(key: str) -> str:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

def set_setting(key: str, value: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

def get_portfolio() -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT cash_balance, total_equity FROM portfolio WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return {"cash_balance": row[0], "total_equity": row[1]}
        return {"cash_balance": 0.0, "total_equity": 0.0}

def update_portfolio(cash_delta: float):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE portfolio SET cash_balance = cash_balance + ? WHERE id = 1", (cash_delta,))
        conn.commit()

def get_open_positions() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, symbol, side, quantity, entry_price, entry_time, category, sell_signal_count, peak_price FROM positions")
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "symbol": row[1],
                "side": row[2],
                "quantity": row[3],
                "entry_price": row[4],
                "entry_time": row[5],
                "category": row[6],
                "sell_signal_count": row[7],
                "peak_price": row[8]
            } for row in rows
        ]

def get_position_by_symbol(symbol: str) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, symbol, side, quantity, entry_price, entry_time, category, sell_signal_count, peak_price FROM positions WHERE symbol = ?", (symbol,))
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "symbol": row[1],
                "side": row[2],
                "quantity": row[3],
                "entry_price": row[4],
                "entry_time": row[5],
                "category": row[6],
                "sell_signal_count": row[7],
                "peak_price": row[8]
            }
        return None

def open_position(symbol: str, side: str, quantity: float, price: float, timestamp: str, category: str = "crypto_mid"):
    cost = quantity * price
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO positions (symbol, side, quantity, entry_price, entry_time, category, peak_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol, side, quantity, price, timestamp, category, price))
        
        # Deduct cash for BUY
        # For a simplified model, both BUY and SELL (short) lock cash margin, but let's assume we just deduct cash for the position value
        cursor.execute("UPDATE portfolio SET cash_balance = cash_balance - ? WHERE id = 1", (cost,))
        conn.commit()

def close_position(position_id: int, exit_price: float, exit_timestamp: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, side, quantity, entry_price, entry_time, category FROM positions WHERE id = ?", (position_id,))
        pos = cursor.fetchone()
        if not pos:
            return
        
        symbol, side, quantity, entry_price, entry_time, category = pos
        
        # Calculate PnL
        if side == "BUY":
            pnl = (exit_price - entry_price) * quantity
            pnl_percent = ((exit_price - entry_price) / entry_price) * 100.0
        else: # SELL (Short)
            pnl = (entry_price - exit_price) * quantity
            pnl_percent = ((entry_price - exit_price) / entry_price) * 100.0
            
        # Return cash + pnl
        returned_cash = (quantity * entry_price) + pnl
        
        # Log to history
        cursor.execute("""
            INSERT INTO trade_history (symbol, side, quantity, entry_price, entry_time, exit_price, exit_time, pnl, pnl_percent, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (symbol, side, quantity, entry_price, entry_time, exit_price, exit_timestamp, pnl, pnl_percent, category))
        
        # Delete position
        cursor.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        
        # Update portfolio
        cursor.execute("UPDATE portfolio SET cash_balance = cash_balance + ? WHERE id = 1", (returned_cash,))
        conn.commit()

def update_position_peak_price(position_id: int, new_peak: float):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE positions SET peak_price = ? WHERE id = ?", (new_peak, position_id))
        conn.commit()

def update_sell_signal_count(position_id: int, new_count: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE positions SET sell_signal_count = ? WHERE id = ?", (new_count, position_id))
        conn.commit()

def get_trade_history(limit: int = 50) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, symbol, side, quantity, entry_price, entry_time, exit_price, exit_time, pnl, pnl_percent, category
            FROM trade_history
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "symbol": row[1],
                "side": row[2],
                "quantity": row[3],
                "entry_price": row[4],
                "entry_time": row[5],
                "exit_price": row[6],
                "exit_time": row[7],
                "pnl": row[8],
                "pnl_percent": row[9],
                "category": row[10]
            } for row in rows
        ]

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
