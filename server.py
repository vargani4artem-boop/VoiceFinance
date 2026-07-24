import os
import sys
import json
import sqlite3
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

DB_FILE = os.path.join(os.path.dirname(__file__), "finance.db")
PORT = int(os.environ.get("PORT", 8000))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8875858432:AAEe6xbzBi82Om75WpP19AE_8J8y1LKGwqo").strip()

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,          -- 'expense' or 'income'
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
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
        elif parsed.path == '/api/analytics':
            self.get_analytics()
        elif parsed.path == '/api/bot-status':
            self.get_bot_status()
        else:
            super().do_GET()

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
        else:
            self.send_error(404, "Endpoint not found")

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

    def get_transactions(self):
        conn = sqlite3.connect(DB_FILE)
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
            self.send_json({'success': True, 'data': status_copy})
        except Exception as e:
            self.send_json({'success': False, 'error': f"Failed to get bot status: {e}"})

    def add_transaction(self, data):
        tx_type = data.get('type', 'expense')
        amount = float(data.get('amount', 0))
        currency = data.get('currency', 'USD')
        category = data.get('category', 'прочее').lower()
        description = data.get('description', '')
        raw_voice = data.get('raw_voice', '')
        date_str = data.get('date') or datetime.now().strftime('%Y-%m-%d')
        created_at = datetime.now().isoformat()

        if amount <= 0:
            self.send_json({'success': False, 'error': 'Amount must be positive'}, status=400)
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (type, amount, currency, category, description, raw_voice, date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tx_type, amount, currency, category, description, raw_voice, date_str, created_at))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()

        self.send_json({'success': True, 'data': {
            'id': new_id, 'type': tx_type, 'amount': amount, 'currency': currency,
            'category': category, 'description': description, 'raw_voice': raw_voice,
            'date': date_str, 'created_at': created_at
        }})

    def delete_transaction(self, tx_id):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM transactions WHERE id = ?', (tx_id,))
        conn.commit()
        conn.close()
        self.send_json({'success': True, 'message': 'Transaction deleted'})

    def get_categories(self):
        conn = sqlite3.connect(DB_FILE)
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

        conn = sqlite3.connect(DB_FILE)
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
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT type, SUM(amount) as total FROM transactions GROUP BY type")
        totals = {row['type']: row['total'] for row in cursor.fetchall()}
        
        income = totals.get('income', 0.0)
        expense = totals.get('expense', 0.0)
        balance = income - expense
        ratio = round(income / expense, 2) if expense > 0 else (income if income > 0 else 0)
        
        cursor.execute("""
            SELECT category, SUM(amount) as total 
            FROM transactions 
            WHERE type = 'expense' 
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


def run_server():
    init_db()
    os.chdir(os.path.dirname(__file__))
    
    # Start Telegram Bot in daemon thread
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
