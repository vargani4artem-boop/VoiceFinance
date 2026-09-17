import os
import sys
import json
import sqlite3
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# Redirect stdout and stderr to app.log
class TeeLogger:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8", buffering=1)

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

LOG_FILE = os.path.join(os.path.dirname(__file__), "app.log")
sys.stdout = TeeLogger(LOG_FILE)
sys.stderr = TeeLogger(LOG_FILE)

DB_FILE = os.path.join(os.path.dirname(__file__), "finance.db")
PORT = int(os.environ.get("PORT", 8000))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8875858432:AAEe6xbzBi82Om75WpP19AE_8J8y1LKGwqo").strip()

def normalize_category(cat):
    if not cat:
        return "прочее"
    return cat.strip().lower()

def init_db():
    try:
        import persistence
        persistence.restore_db()
    except Exception as e:
        print(f"[Init DB Restore Error] {e}")
        
    conn = sqlite3.connect(DB_FILE, timeout=30)
    cursor = conn.cursor()
    
    # Transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,          -- 'expense' or 'income'
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'CAD',
            category TEXT NOT NULL,
            description TEXT,
            raw_voice TEXT,
            date TEXT NOT NULL,          -- YYYY-MM-DD
            created_at TEXT NOT NULL     -- ISO timestamp
        )
    ''')
    
    # Categories table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,          -- 'expense', 'income', or 'both'
            icon TEXT DEFAULT 'folder',
            color TEXT DEFAULT '#4F46E5'
        )
    ''')
    
    # Insert default categories if empty
    cursor.execute('SELECT COUNT(*) FROM categories')
    if cursor.fetchone()[0] == 0:
        default_cats = [
            ('продукты', 'expense', 'shopping-bag', '#10B981'),
            ('бензин', 'expense', 'fuel', '#F59E0B'),
            ('транспорт', 'expense', 'bus', '#3B82F6'),
            ('коммунальные', 'expense', 'home', '#6366F1'),
            ('кредиты', 'expense', 'credit-card', '#EF4444'),
            ('развлечения', 'expense', 'film', '#EC4899'),
            ('бизнес', 'expense', 'briefcase', '#8B5CF6'),
            ('кафе и рестораны', 'expense', 'utensils', '#F97316'),
            ('здоровье', 'expense', 'heart-pulse', '#06B6D4'),
            ('зарплата', 'income', 'wallet', '#10B981'),
            ('фриланс', 'income', 'laptop', '#3B82F6'),
            ('инвестиции', 'income', 'trending-up', '#8B5CF6'),
            ('подарок', 'income', 'gift', '#F43F5E')
        ]
        cursor.executemany('INSERT INTO categories (name, type, icon, color) VALUES (?, ?, ?, ?)', default_cats)
        
    # Accounts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,             -- 'asset' or 'debt'
            currency TEXT NOT NULL,         -- 'UAH', 'CAD', 'USD'
            balance REAL NOT NULL,          -- current balance (positive for asset, debt amount for debt)
            credit_limit REAL DEFAULT 0,    -- total credit limit
            credit_remaining REAL DEFAULT 0,-- remaining credit limit
            updated_at TEXT NOT NULL
        )
    ''')
    
    # Pre-populate accounts if empty
    cursor.execute('SELECT COUNT(*) FROM accounts')
    if cursor.fetchone()[0] == 0:
        import datetime
        now_str = datetime.datetime.now().isoformat()
        initial_accounts = [
            ('Гривневая карта 1', 'debt', 'UAH', 229759.0, 0.0, 0.0, now_str),
            ('Гривневая карта 2', 'debt', 'UAH', 115694.0, 0.0, 0.0, now_str),
            ('Канадская карта 1', 'debt', 'CAD', 5262.0, 7500.0, 2238.0, now_str),
            ('Канадская карта 2', 'debt', 'CAD', 8312.0, 25000.0, 16688.0, now_str),
            ('Канадская карта 3', 'debt', 'CAD', 4733.0, 7500.0, 2767.0, now_str),
            ('Сберегательный счет', 'asset', 'CAD', 300.0, 0.0, 0.0, now_str),
            ('Личный аккаунт', 'asset', 'CAD', 0.0, 0.0, 0.0, now_str),
            ('Interactive Brokers', 'asset', 'CAD', 863.0, 0.0, 0.0, now_str)
        ]
        cursor.executemany('''
            INSERT INTO accounts (name, type, currency, balance, credit_limit, credit_remaining, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', initial_accounts)

    # Migrate UAH accounts to debt if they exist as assets
    cursor.execute("UPDATE accounts SET type = 'debt' WHERE name IN ('Гривневая карта 1', 'Гривневая карта 2')")

    # Migrate USD database records to CAD
    cursor.execute("UPDATE transactions SET currency = 'CAD' WHERE currency = 'USD'")
    cursor.execute("UPDATE accounts SET currency = 'CAD' WHERE currency = 'USD'")

    # Clean up old transactions (keep only August 2026 and later)
    cursor.execute("DELETE FROM transactions WHERE date < '2026-08-01'")

    # Trigger fallback sheet import and Telegram backup if transactions are empty
    cursor.execute('SELECT COUNT(*) FROM transactions')
    if cursor.fetchone()[0] == 0:
        import threading
        def background_auto_import():
            try:
                import bot
                print("[Auto-Import] Transactions table empty. Running fallback Google Sheet import...")
                bot.import_google_sheet("1K7icTbNknhsP7bT0QK1eoK6VY22U0NJ9_lwKZMqtSpE", 0)
                print("[Auto-Import] Fallback Google Sheet import completed. Backing up to Telegram...")
                import persistence
                persistence.backup_db()
            except Exception as e:
                print(f"[Auto-Import Error] Fallback import failed: {e}")
        threading.Thread(target=background_auto_import, daemon=True).start()
    # TEMPORARY CODE: Force reset database with the user's correct chat transactions
    force_reset = False
    if force_reset:
        cursor.execute("DELETE FROM transactions")
        cursor.execute("DELETE FROM accounts")
        import datetime
        now_str = datetime.datetime.now().isoformat()
        initial_accounts = [
            ('Гривневая карта 1', 'debt', 'UAH', 229759.0, 0.0, 0.0, now_str),
            ('Гривневая карта 2', 'debt', 'UAH', 115694.0, 0.0, 0.0, now_str),
            ('Канадская карта 1', 'debt', 'CAD', 5262.0, 7500.0, 2238.0, now_str),
            ('Канадская карта 2', 'debt', 'CAD', 8312.0, 25000.0, 16688.0, now_str),
            ('Канадская карта 3', 'debt', 'CAD', 4733.0, 7500.0, 2767.0, now_str),
            ('Сберегательный счет', 'asset', 'CAD', 300.0, 0.0, 0.0, now_str),
            ('Личный аккаунт', 'asset', 'CAD', 0.0, 0.0, 0.0, now_str),
            ('Interactive Brokers', 'asset', 'CAD', 863.0, 0.0, 0.0, now_str)
        ]
        cursor.executemany('''
            INSERT INTO accounts (name, type, currency, balance, credit_limit, credit_remaining, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', initial_accounts)
        import datetime
        now_str = datetime.datetime.now().isoformat()
        real_txs = [
            # Incomes
            ('income', 1786.0, 'CAD', 'зарплата', 'Зарплата', 'Зарплата', '2026-08-21', now_str),
            
            # Expenses
            ('expense', 70.0, 'CAD', 'кафе', '70 дол кафе', '70 дол кафе', '2026-08-14', now_str),
            ('expense', 75.0, 'CAD', 'бензин', '75 бенз', '75 бенз', '2026-08-15', now_str),
            ('expense', 17.0, 'CAD', 'кафе', '17 кафе', '17 кафе', '2026-08-15', now_str),
            ('expense', 22.0, 'CAD', 'витамины', '- 22 витамины', '- 22 витамины', '2026-08-16', now_str),
            ('expense', 529.0, 'CAD', 'травориум', 'Зарегистрирую 529 долларов на членство в Травориум.', 'Зарегистрирую 529 долларов на членство в Травориум.', '2026-08-16', now_str),
            ('expense', 67.0, 'CAD', 'кафе', '67, не сем', '67, не сем', '2026-08-16', now_str),
            ('expense', 112.0, 'CAD', 'бензин', '112 дол бенз запиши', '112 дол бенз запиши', '2026-08-16', now_str),
            ('expense', 21.0, 'CAD', 'прочее', 'Да нет, 21 dollar расходы на мороженное', 'Да нет, 21 dollar расходы на мороженное', '2026-08-16', now_str),
            ('expense', 14.0, 'CAD', 'кафе', '14 дол кафе', '14 дол кафе', '2026-08-17', now_str),
            ('expense', 25.0, 'CAD', 'продукты', 'Продукты', 'Продукты', '2026-08-17', now_str),
            ('expense', 25.0, 'CAD', 'прочее', 'Занеси расход 25', 'Занеси расход 25', '2026-08-17', now_str),
            ('expense', 125.0, 'CAD', 'бензин', '125 долларов на бензин', '125 долларов на бензин и 100 долларов на консультацию бухгалтера', '2026-08-17', now_str),
            ('expense', 100.0, 'CAD', 'бухгалтер', '100 долларов на консультацию бухгалтера', '125 долларов на бензин и 100 долларов на консультацию бухгалтера', '2026-08-17', now_str),
            ('expense', 31.0, 'CAD', 'витамины', '31 дол витамины', '31 дол витамины', '2026-08-18', now_str),
            ('expense', 82.0, 'CAD', 'продукты', '82 продукты', '82 продукты', '2026-08-18', now_str),
            ('expense', 20.0, 'CAD', 'кафе', '20 кафе', '20 кафе', '2026-08-19', now_str),
            ('income', 500.0, 'CAD', 'погашение', 'Отправил за кредит 500 дол', 'Отправил за кредит 500 дол и 550 дол алименты', '2026-08-21', now_str),
            ('expense', 550.0, 'CAD', 'алименты', '550 дол алименты', 'Отправил за кредит 500 дол и 550 дол алименты', '2026-08-21', now_str),
            ('income', 600.0, 'CAD', 'погашение', 'По 600 дол на кредитки', 'По 600 дол на кредитки', '2026-08-21', now_str),
            ('expense', 22.0, 'CAD', 'продукты', '22 продукти', '22 продукти', '2026-08-22', now_str),
            ('expense', 55.0, 'CAD', 'продукты', '55 на продукты', '55 на продукты', '2026-08-22', now_str)
        ]
        cursor.executemany('''
            INSERT INTO transactions (type, amount, currency, category, description, raw_voice, date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', real_txs)
        
        import threading
        def do_backup():
            import time
            time.sleep(3)
            import persistence
            persistence.backup_db()
        threading.Thread(target=do_backup, daemon=True).start()

    conn.commit()
    conn.close()

class VoiceFinanceHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/transactions':
            self.get_transactions()
        elif parsed.path == '/api/categories':
            self.get_categories()
        elif parsed.path == '/api/accounts':
            self.get_accounts()
        elif parsed.path == '/api/analytics':
            self.get_analytics()
        elif parsed.path == '/api/bot-status':
            self.get_bot_status()
        elif parsed.path == '/api/sync-july':
            conn = None
            try:
                conn = sqlite3.connect(DB_FILE, timeout=60.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=60000")
                cursor = conn.cursor()
                
                # 1. Delete old July records if any
                cursor.execute("DELETE FROM transactions WHERE date LIKE '2026-07-%'")
                
                # 2. Insert July income
                cursor.execute(
                    "INSERT INTO transactions (date, type, amount, category, description, currency, created_at) "
                    "VALUES ('2026-07-15', 'income', 3900.00, 'зарплата', 'Доход за июль (по данным банка)', 'CAD', '2026-07-15T12:00:00')"
                )
                
                # 3. Insert all July expenses
                july_list = [('2026-07-31', 20.79, 'кафе', 'Village Ice Cream'), ('2026-07-31', 18.02, 'покупки', 'Amazon'), ('2026-07-31', 50.0, 'инвестиции', 'Internet Interactive Brokers Canad'), ('2026-07-31', 12.6, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-30', 26.24, 'подписки', 'Apple'), ('2026-07-30', 320.0, 'услуги', 'E-Transfer Zoran Stiralki'), ('2026-07-30', 20.0, 'переводы', 'E-Transfer Alya'), ('2026-07-30', 5.76, 'бензин', 'Calgary Co-Op Gas'), ('2026-07-30', 100.13, 'покупки', 'Canadian Tire'), ('2026-07-30', 7.34, 'кафе', 'Tim Hortons'), ('2026-07-28', 18.01, 'бензин', 'Chevron'), ('2026-07-28', 4.08, 'кафе', 'Circle K'), ('2026-07-28', 50.0, 'бензин', 'Calgary Co-Op Gas'), ('2026-07-28', 7.35, 'кафе', 'Tim Hortons'), ('2026-07-27', 115.12, 'продукты', 'Sobeys'), ('2026-07-27', 11.76, 'кафе', 'Village Ice Cream'), ('2026-07-27', 162.75, 'покупки', 'Browns Southcentre'), ('2026-07-27', 49.35, 'покупки', 'Capz'), ('2026-07-27', 0.89, 'покупки', 'Dollarama'), ('2026-07-27', 28.11, 'покупки', 'Shawnessy'), ('2026-07-27', 9.96, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-27', 65.19, 'проценты', 'Finance Charge'), ('2026-07-26', 45.82, 'продукты', 'Sobeys'), ('2026-07-26', 11.55, 'продукты', 'Italian Centre Shop'), ('2026-07-26', 14.49, 'связь', 'Twilio'), ('2026-07-26', 164.07, 'связь', 'Fido'), ('2026-07-25', 37.22, 'продукты', 'Sobeys'), ('2026-07-25', 100.0, 'бензин', 'Shell'), ('2026-07-25', 24.74, 'кафе', 'Tim Hortons'), ('2026-07-25', 11.63, 'кафе', 'Dairy Queen'), ('2026-07-25', 23.34, 'кафе', 'Tim Hortons'), ('2026-07-25', 16.76, 'кафе', 'Tim Hortons'), ('2026-07-25', 20.0, 'переводы', 'E-Transfer Alya'), ('2026-07-25', 52.49, 'авто', 'Mint Smartwash'), ('2026-07-24', 20.07, 'кафе', 'Tim Hortons'), ('2026-07-24', 54.39, 'покупки', 'Amazon'), ('2026-07-24', 15.51, 'кафе', 'Tim Hortons'), ('2026-07-24', 69.94, 'финансы', 'Affirm'), ('2026-07-24', 50.0, 'инвестиции', 'Internet Interactive Brokers Canad'), ('2026-07-23', 71.15, 'продукты', 'FreshCo'), ('2026-07-23', 5.59, 'бензин', 'Circle K'), ('2026-07-23', 9.8, 'кафе', 'Tim Hortons'), ('2026-07-22', 132.05, 'бензин', 'Petro-Canada'), ('2026-07-22', 5.24, 'бензин', 'Chevron'), ('2026-07-22', 419.71, 'погашение укр', 'Intl Visa Monobank Eur'), ('2026-07-22', 12.06, 'кафе', 'Tim Hortons'), ('2026-07-22', 7.79, 'кафе', 'Tim Hortons'), ('2026-07-22', 95.95, 'проценты', 'Finance Charge'), ('2026-07-22', 82.85, 'продукты', 'Sobeys'), ('2026-07-21', 2.09, 'бензин', 'Chevron'), ('2026-07-21', 15.92, 'бензин', 'Chevron'), ('2026-07-21', 25.13, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-20', 24.15, 'покупки', 'Dollarama'), ('2026-07-20', 2.1, 'кафе', "McDonald's"), ('2026-07-20', 31.49, 'покупки', 'Amazon'), ('2026-07-19', 88.16, 'покупки', 'Winners'), ('2026-07-19', 8.37, 'кафе', 'Analog Southcentre'), ('2026-07-19', 71.66, 'покупки', 'Dollarama'), ('2026-07-19', 32.62, 'покупки', 'Dollarama'), ('2026-07-19', 31.49, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-19', 93.42, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-19', 67.31, 'покупки', 'Bath & Body Works'), ('2026-07-18', 12.13, 'продукты', 'Sobeys'), ('2026-07-18', 334.51, 'продукты', 'Sobeys'), ('2026-07-18', 31.49, 'спорт', 'Calgary Gym'), ('2026-07-17', 24.13, 'продукты', 'Sobeys'), ('2026-07-17', 100.99, 'продукты', 'Sobeys'), ('2026-07-17', 5.87, 'кафе', 'Dairy Queen'), ('2026-07-16', 15.0, 'авто', 'Ahs Parking Lots'), ('2026-07-16', 23.09, 'покупки', 'Amazon'), ('2026-07-16', 11.53, 'кафе', 'Tim Hortons'), ('2026-07-16', 17.28, 'бензин', '7-Eleven Gas'), ('2026-07-16', 13.64, 'бензин', '7-Eleven Gas'), ('2026-07-15', 30.44, 'покупки', 'Amazon'), ('2026-07-15', 159.9, 'путешествия', 'Easyjetkd'), ('2026-07-15', 998.7, 'путешествия', 'WestJet Airlines'), ('2026-07-14', 10.59, 'покупки', 'Amazon'), ('2026-07-13', 11.32, 'покупки', 'Amazon'), ('2026-07-13', 434.57, 'продукты', 'Sobeys'), ('2026-07-13', 84.73, 'бензин', 'Petro-Canada Gas'), ('2026-07-12', 8.36, 'бензин', 'Shell Gas'), ('2026-07-12', 18.89, 'кафе', 'W Glacier Sweet Treats'), ('2026-07-12', 17.26, 'продукты', 'Big Fork Harvest Fo'), ('2026-07-12', 29.77, 'продукты', 'Big Fork Harvest Fo'), ('2026-07-12', 43.54, 'продукты', 'Big Fork Harvest Fo'), ('2026-07-12', 10.49, 'подписки', 'Amazon Prime Membership'), ('2026-07-12', 11.62, 'отдых', 'Montanastateparks'), ('2026-07-12', 18.15, 'бензин', 'Conoco Gas'), ('2026-07-12', 85.43, 'бензин', 'Cenex Gas'), ('2026-07-12', 96.99, 'жилье', 'West Glacier Koa Stor'), ('2026-07-12', 4.49, 'жилье', 'West Glacier Koa Stor'), ('2026-07-12', 7.48, 'жилье', 'West Glacier Koa Stor'), ('2026-07-12', 15.75, 'кафе', 'Sweet Peaks Whitefish'), ('2026-07-11', 30.22, 'отдых', 'West Glacier'), ('2026-07-11', 58.51, 'кафе', 'W Glacier Sweet Treats'), ('2026-07-11', 87.2, 'кафе', 'Del'), ('2026-07-10', 162.99, 'продукты', 'Sobeys'), ('2026-07-10', 66.46, 'бензин', 'Petro-Canada Gas'), ('2026-07-10', 68.75, 'услуги', 'Vitalii Vashchenko'), ('2026-07-10', 26.76, 'покупки', 'Amazon'), ('2026-07-10', 50.0, 'инвестиции', 'Internet Interactive Brokers Canad'), ('2026-07-10', 15.09, 'кафе', 'Tim Hortons'), ('2026-07-09', 20.0, 'переводы', 'E-Transfer Alya'), ('2026-07-09', 50.99, 'прочее', 'Intl Assoc Scientologists'), ('2026-07-09', 4.19, 'подписки', 'Apple'), ('2026-07-09', 12.06, 'кафе', 'Tim Hortons'), ('2026-07-09', 43.71, 'услуги', 'Flag Services'), ('2026-07-08', 38.26, 'продукты', "Lina's Italian Mercato"), ('2026-07-08', 26.32, 'покупки', 'Amazon'), ('2026-07-08', 21.0, 'кафе', 'Village Ice Cream'), ('2026-07-06', 55.53, 'продукты', 'Sobeys'), ('2026-07-06', 14.69, 'кафе', '7-Eleven'), ('2026-07-06', 17.35, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-05', 9.3, 'кафе', 'Starbucks'), ('2026-07-05', 27.92, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-05', 17.6, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-04', 136.5, 'кафе', 'Nastin Sweet'), ('2026-07-04', 96.0, 'бензин', 'Circle K Gas'), ('2026-07-04', 13.21, 'кафе', 'Lovely Ice Cream'), ('2026-07-04', 21.97, 'продукты', 'Sobeys'), ('2026-07-04', 22.5, 'бензин', 'Petro-Canada Gas'), ('2026-07-03', 10.5, 'кафе', "Brian's Cafe"), ('2026-07-03', 3.68, 'кафе', "Brian's Cafe"), ('2026-07-03', 27.27, 'здоровье', 'Shoppers Drug Mart'), ('2026-07-03', 16.06, 'кафе', 'Tim Hortons'), ('2026-07-03', 16.95, 'банк', 'Service Charge'), ('2026-07-03', 16.95, 'банк', 'Service Charge'), ('2026-07-03', 39.26, 'кафе', '7-Eleven'), ('2026-07-03', 99.0, 'банк', 'Annual Fee'), ('2026-07-03', 7.5, 'банк', 'Cash Advance Fee'), ('2026-07-03', 0.04, 'проценты', 'Finance Charge'), ('2026-07-02', 20.76, 'кафе', 'Tim Hortons'), ('2026-07-02', 4.19, 'бензин', 'Calgary Co-Op Gas'), ('2026-07-02', 21.59, 'наличные', 'Cash Advance'), ('2026-07-02', 60.65, 'покупки', 'Shawnessy'), ('2026-07-02', 124.88, 'бензин', 'Esso Gas Station'), ('2026-07-01', 14.61, 'связь', 'Twilio'), ('2026-07-01', 200.0, 'переводы', 'Global Money'), ('2026-07-01', 100.0, 'переводы', 'E-Transfer Andriy Stiklo'), ('2026-07-01', 50.0, 'инвестиции', 'Internet Interactive Brokers Canad'), ('2026-07-01', 175.71, 'погашение укр', 'Intl Visa Monobank Uah'), ('2026-07-01', 20.0, 'переводы', 'E-Transfer Alya'), ('2026-07-01', 331.53, 'погашение укр', 'Intl Visa Monobank Uah'), ('2026-07-01', 25.13, 'покупки', 'Amazon')]
                rows = [(d, 'expense', amt, 'CAD', cat, desc, d + 'T12:00:00') for d, amt, cat, desc in july_list]
                cursor.executemany(
                    "INSERT INTO transactions (date, type, amount, currency, category, description, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows
                )
                conn.commit()
                conn.close()
                conn = None
                
                import persistence
                persistence.backup_db()
                self.send_json({"success": True, "message": "July fully synchronized with bank statement."})
            except Exception as e:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                self.send_json({"success": False, "error": str(e)}, status=500)
            return
        elif parsed.path == '/api/logs':
            self.get_logs()
        else:
            super().do_GET()

    def get_logs(self):
        try:
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                log_content = "".join(lines[-150:])
            else:
                log_content = "Log file not found."
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(log_content.encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"Failed to read logs: {e}".encode('utf-8'))

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        
        try:
            data = json.loads(body.decode('utf-8'))
        except Exception:
            data = {}

        if parsed.path == '/api/transactions':
            self.add_transaction(data)
        elif parsed.path == '/api/categories':
            self.add_category(data)
        elif parsed.path == '/api/accounts':
            self.update_account(data)
        elif parsed.path == '/api/telegram-webhook':
            self.handle_telegram_webhook(data)
        else:
            self.send_error(404, "Endpoint not found")

    def handle_telegram_webhook(self, update):
        global BOT_STATUS
        try:
            import bot
            telegram_bot = bot.TelegramBot(bot.TOKEN)
            
            # Track update details
            msg = update.get('message', {})
            BOT_STATUS["last_update_received"] = datetime.now().isoformat()
            BOT_STATUS["last_update_id"] = update.get('update_id')
            BOT_STATUS["last_chat_id"] = msg.get('chat', {}).get('id') if msg else None
            BOT_STATUS["last_text_received"] = msg.get('text') or ("Voice message" if msg.get('voice') else None) if msg else None
            
            # Process update asynchronously in a daemon thread so we can reply 200 OK to Telegram immediately
            threading.Thread(target=telegram_bot.handle_update, args=(update,), daemon=True).start()
            
            self.send_json({'success': True})
        except Exception as e:
            print(f"[Webhook Error] {e}")
            self.send_json({'success': False, 'error': str(e)}, status=500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/transactions/'):
            tx_id = parsed.path.split('/')[-1]
            self.delete_transaction(tx_id)
        else:
            self.send_error(404, "Endpoint not found")

    def send_json(self, response_data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))

    def get_accounts(self):
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM accounts ORDER BY type ASC, id ASC')
            rows = cursor.fetchall()
            accounts = [dict(r) for r in rows]
            conn.close()
            self.send_json({'success': True, 'data': accounts})
        except Exception as e:
            self.send_json({'success': False, 'error': str(e)}, status=500)

    def update_account(self, data):
        account_id = data.get('id')
        balance = data.get('balance')
        credit_limit = data.get('credit_limit')
        credit_remaining = data.get('credit_remaining')
        
        if not account_id:
            self.send_json({'success': False, 'error': 'Account ID is required'}, status=400)
            return
            
        try:
            conn = sqlite3.connect(DB_FILE, timeout=30)
            cursor = conn.cursor()
            
            cursor.execute('SELECT type FROM accounts WHERE id = ?', (account_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                self.send_json({'success': False, 'error': 'Account not found'}, status=404)
                return
                
            acct_type = row[0]
            now_str = datetime.now().isoformat()
            
            if acct_type == 'debt' and credit_limit is not None and credit_remaining is not None:
                credit_limit = float(credit_limit)
                credit_remaining = float(credit_remaining)
                balance = max(0.0, credit_limit - credit_remaining)
                cursor.execute('''
                    UPDATE accounts 
                    SET balance = ?, credit_limit = ?, credit_remaining = ?, updated_at = ?
                    WHERE id = ?
                ''', (balance, credit_limit, credit_remaining, now_str, account_id))
            else:
                balance = float(balance)
                cursor.execute('''
                    UPDATE accounts 
                    SET balance = ?, updated_at = ?
                    WHERE id = ?
                ''', (balance, now_str, account_id))
                
            conn.commit()
            conn.close()
            
            try:
                import persistence
                persistence.async_backup()
            except Exception as e:
                print(f"[Backup Trigger Error] {e}")
                
            self.send_json({'success': True})
        except Exception as e:
            self.send_json({'success': False, 'error': str(e)}, status=500)

    def get_transactions(self):
        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM transactions ORDER BY created_at DESC')
        rows = cursor.fetchall()
        txs = [dict(r) for r in rows]
        conn.close()
        self.send_json({'success': True, 'data': txs})

    def get_bot_status(self):
        try:
            import bot
            status_copy = BOT_STATUS.copy()
            status_copy["has_genai_client"] = bot.genai_client is not None
            status_copy["gemini_key_prefix"] = bot.GEMINI_KEY[:6] if bot.GEMINI_KEY else None
            status_copy["gemini_key_length"] = len(bot.GEMINI_KEY) if bot.GEMINI_KEY else 0
            status_copy["gemini_errors"] = getattr(bot, "GEMINI_ERRORS", [])
            self.send_json({'success': True, 'data': status_copy})
        except Exception as e:
            self.send_json({'success': False, 'error': f"Failed to get bot status: {e}"})
    def add_transaction(self, data):
        tx_type = data.get('type', 'expense')
        amount = float(data.get('amount', 0))
        currency = data.get('currency', 'CAD')
        category = normalize_category(data.get('category', 'прочее'))
        description = data.get('description', '')
        raw_voice = data.get('raw_voice', '')
        date_str = data.get('date') or datetime.now().strftime('%Y-%m-%d')
        created_at = datetime.now().isoformat()

        if amount <= 0:
            self.send_json({'success': False, 'error': 'Amount must be positive'}, status=400)
            return

        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (type, amount, currency, category, description, raw_voice, date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tx_type, amount, currency, category, description, raw_voice, date_str, created_at))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()

        try:
            import persistence
            persistence.async_backup()
        except Exception as e:
            print(f"[Backup Trigger Error] {e}")

        self.send_json({'success': True, 'data': {
            'id': new_id, 'type': tx_type, 'amount': amount, 'currency': currency,
            'category': category, 'description': description, 'raw_voice': raw_voice,
            'date': date_str, 'created_at': created_at
        }})

    def delete_transaction(self, tx_id):
        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM transactions WHERE id = ?', (tx_id,))
        conn.commit()
        conn.close()
        
        try:
            import persistence
            persistence.async_backup()
        except Exception as e:
            print(f"[Backup Trigger Error] {e}")
            
        self.send_json({'success': True, 'message': 'Transaction deleted'})

    def get_categories(self):
        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM categories ORDER BY name ASC')
        rows = cursor.fetchall()
        cats = [dict(r) for r in rows]
        conn.close()
        self.send_json({'success': True, 'data': cats})

    def add_category(self, data):
        name = data.get('name', '').strip().lower()
        cat_type = data.get('type', 'expense')
        icon = data.get('icon', 'tag')
        color = data.get('color', '#6366F1')

        if not name:
            self.send_json({'success': False, 'error': 'Category name is required'}, status=400)
            return

        conn = sqlite3.connect(DB_FILE, timeout=30)
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO categories (name, type, icon, color) VALUES (?, ?, ?, ?)',
                           (name, cat_type, icon, color))
            conn.commit()
            new_id = cursor.lastrowid
            conn.close()
            self.send_json({'success': True, 'data': {'id': new_id, 'name': name, 'type': cat_type, 'icon': icon, 'color': color}})
        except sqlite3.IntegrityError:
            conn.close()
            self.send_json({'success': False, 'error': 'Category already exists'}, status=400)

    def get_analytics(self):
        conn = sqlite3.connect(DB_FILE, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT type, SUM(amount) as total 
            FROM transactions 
            WHERE category NOT IN ('погашение', 'погашение долга', 'погашение укр', 'сбережения', 'сейвинг', 'инвестиции', 'инвестирование')
            GROUP BY type
        """)
        totals = {row['type']: row['total'] for row in cursor.fetchall()}
        
        income = totals.get('income', 0.0)
        expense = totals.get('expense', 0.0)
        balance = income - expense
        ratio = round(income / expense, 2) if expense > 0 else (income if income > 0 else 0)
        
        cursor.execute("""
            SELECT category, SUM(amount) as total 
            FROM transactions 
            WHERE type = 'expense' 
              AND category NOT IN ('погашение', 'погашение долга', 'погашение укр', 'сбережения', 'сейвинг', 'инвестиции', 'инвестирование')
            GROUP BY category 
            ORDER BY total DESC 
            LIMIT 5
        """)
        top_expenses = [dict(r) for r in cursor.fetchall()]
        
        conn.close()
        self.send_json({
            'success': True,
            'data': {
                'income': income,
                'expense': expense,
                'balance': balance,
                'ratio': ratio,
                'top_expenses': top_expenses
            }
        })

BOT_STATUS = {
    "status": "not_started",
    "error": None,
    "last_poll": None,
    "last_update_received": None,
    "last_update_id": None,
    "last_chat_id": None,
    "last_text_received": None,
    "token_prefix": TOKEN[:10] if TOKEN else None
}

def start_telegram_bot():
    global BOT_STATUS
    BOT_STATUS["status"] = "starting"
    try:
        import bot
        print("[Server] Initializing Telegram Bot in background thread...")
        telegram_bot = bot.TelegramBot(bot.TOKEN)
        BOT_STATUS["status"] = "polling"
        
        # Override start_polling to update last_poll timestamp
        def polling_with_status():
            while True:
                BOT_STATUS["last_poll"] = datetime.now().isoformat()
                try:
                    res = telegram_bot.send_request('getUpdates', {'offset': telegram_bot.offset, 'timeout': 30})
                    if res and res.get('ok'):
                        for update in res.get('result', []):
                            telegram_bot.offset = update['update_id'] + 1
                            
                            # Track last update details
                            msg = update.get('message', {})
                            BOT_STATUS["last_update_received"] = datetime.now().isoformat()
                            BOT_STATUS["last_update_id"] = update.get('update_id')
                            BOT_STATUS["last_chat_id"] = msg.get('chat', {}).get('id') if msg else None
                            BOT_STATUS["last_text_received"] = msg.get('text') or ("Voice message" if msg.get('voice') else None) if msg else None
                            
                            telegram_bot.handle_update(update)
                except Exception as ex:
                    print(f"[Bot Polling Error] {ex}")
                    BOT_STATUS["error"] = f"Polling error: {ex}"
                    time.sleep(3)
                time.sleep(0.5)
        
        polling_with_status()
    except Exception as e:
        print(f"[Server] Telegram Bot background thread error: {e}")
        BOT_STATUS["status"] = "failed"
        BOT_STATUS["error"] = str(e)


def setup_webhook():
    webhook_url = "https://voicefinance.onrender.com/api/telegram-webhook"
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}"
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            print("[Webhook] setWebhook response:", res)
    except Exception as e:
        print("[Webhook] Failed to set webhook:", e)


def run_server():
    init_db()
    os.chdir(os.path.dirname(__file__))
    
    # Use Webhook in production (Render has RENDER or PORT != 8000), otherwise Polling
    if os.environ.get("RENDER") or PORT != 8000:
        print("[Server] Production environment detected. Setting up Telegram Webhook...")
        setup_webhook()
        BOT_STATUS["status"] = "webhook_active"
    else:
        print("[Server] Local environment detected. Starting polling thread...")
        bot_thread = threading.Thread(target=start_telegram_bot, daemon=True)
        bot_thread.start()

    server_address = ('', PORT)
    httpd = HTTPServer(server_address, VoiceFinanceHandler)
    print(f"VoiceFinance Web & Bot server running at port {PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == '__main__':
    run_server()
