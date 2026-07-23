import os
import sys
import time
import json
import sqlite3
import re
import urllib.request
import urllib.parse
from datetime import datetime

# ReportLab PDF & Pie Chart imports
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.charts.legends import Legend

    CYR_FONT = 'Helvetica'
    font_candidates = [
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/segoeui.ttf',
        'C:/Windows/Fonts/calibri.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    ]
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('CyrillicFont', font_path))
                CYR_FONT = 'CyrillicFont'
                break
            except Exception:
                pass
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    CYR_FONT = 'Helvetica'

# Import google.genai SDK
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

DB_FILE = os.path.join(os.path.dirname(__file__), "finance.db")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8875858432:AAEe6xbzBi82Om75WpP19AE_8J8y1LKGwqo").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

genai_client = None
if HAS_GENAI and GEMINI_KEY:
    try:
        genai_client = genai.Client(api_key=GEMINI_KEY)
        print("[Bot] google.genai SDK Client initialized successfully!")
    except Exception as e:
        print(f"[Bot] Client init error: {e}")

# Per-user conversational memory
USER_CHAT_HISTORY = {}

def clean_json_string(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def ask_gemini_brain(user_text=None, chat_id=None, audio_bytes=None):
    if not genai_client:
        return None

    history = USER_CHAT_HISTORY.get(chat_id, [])
    history_str = json.dumps(history[-6:], ensure_ascii=False)

    income, expense, balance = get_analytics()

    prompt_instructions = f"""
Ты — VoiceFinance AI: универсальный ИИ-ассистент, финансовый эксперт и живой собеседник с неограниченным кругом знаний.
Ты должен помогать пользователю во всем: отвечать на любые вопросы обо всем на свете (например, давать подробные инструкции как подняться на Эверест, писать рецепты, программировать, давать советы), поддерживать беседу И одновременно управлять его финансами.

Твоя задача:
1. Если пользователь задает общий вопрос (о науке, жизни, Эвересте, спорте, коде), поставь intent="CHAT", а в поле "ai_reply" напиши максимально подробный, развернутый, интересный и структурированный ответ со всеми деталями. Ответ не должен быть сухим или коротким!
2. Если в реплике есть финансовое действие (расход, доход, исправление, отчет), извлеки параметры в соответствующие поля JSON, а в "ai_reply" дай теплый дружеский комментарий.

Текущее состояние счета: Доходы=${income}, Расходы=${expense}, Чистый остаток=${balance}
История реплик: {history_str}
Ввод пользователя: {"ГОЛОСОВОЕ СООБЩЕНИЕ (прослушай аудио)" if audio_bytes else f'"{user_text}"'}

Верни СТРОГО чистый JSON формата:
{{
  "transcribed_text": "Точная расшифровка реплики пользователя",
  "intent": "ADD_TX" | "CORRECT_LAST" | "DELETE_LAST" | "QUERY_BALANCE" | "EXPORT_PDF" | "CHAT",
  "type": "expense" | "income",
  "amount": number_or_null,
  "category": "продукты" | "бензин" | "транспорт" | "коммунальные" | "кредиты" | "развлечения" | "бизнес" | "кафе и рестораны" | "здоровье" | "зарплата" | "фриланс" | "прочее",
  "new_amount": number_or_null,
  "new_category": string_or_null,
  "ai_reply": "Твой ответ. Если вопрос сложный или просветительский — распиши его подробно, по шагам, с эмодзи!"
}}

Важные правила намерения (intent):
1. Если просит показать график, диаграмму, процентное соотношение, выгрузить отчет, прислать документ -> intent = "EXPORT_PDF".
2. Если добавляет расход или доход ("купил продукты 500", "заправился на 2000") -> intent = "ADD_TX".
3. Если исправляет прошлую сумму/категорию ("ой не 2000 а 1500") -> intent = "CORRECT_LAST".
4. Если просит отменить/удалить -> intent = "DELETE_LAST".
5. Если просто беседует, здоровается, задает вопросы -> intent = "CHAT".
"""

    contents = []
    if audio_bytes:
        contents.append(types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"))
    contents.append(prompt_instructions)

    models_to_try = ['gemini-3.5-flash', 'gemini-2.0-flash-lite', 'gemini-2.0-flash']
    
    for m in models_to_try:
        try:
            res = genai_client.models.generate_content(
                model=m,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            cleaned = clean_json_string(res.text)
            data = json.loads(cleaned)
            return data
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                time.sleep(1)
                continue
            elif "404" in err_str:
                continue
            else:
                print(f"[Gemini Error on {m}] {e}")
                continue

    return None

# PDF Generator Function with Percentage Pie Chart
def generate_pdf_report(filename="voicefinance_report.pdf"):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions ORDER BY created_at DESC")
    txs = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT category, SUM(amount) as total FROM transactions WHERE type='expense' GROUP BY category ORDER BY total DESC")
    cat_rows = [(r['category'], r['total']) for r in cursor.fetchall()]
    conn.close()

    income, expense, balance = get_analytics()
    ratio = round(income / expense, 2) if expense > 0 else (income if income > 0 else 0)

    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', fontName=CYR_FONT, fontSize=18, leading=22, textColor=colors.HexColor('#6366F1'))
    heading_style = ParagraphStyle('HeadStyle', fontName=CYR_FONT, fontSize=13, leading=16, textColor=colors.HexColor('#1E293B'))
    meta_style = ParagraphStyle('MetaStyle', fontName=CYR_FONT, fontSize=9, textColor=colors.HexColor('#64748B'))
    cell_style = ParagraphStyle('CellStyle', fontName=CYR_FONT, fontSize=9, leading=11, textColor=colors.HexColor('#1E293B'))
    cell_header_style = ParagraphStyle('CellHeadStyle', fontName=CYR_FONT, fontSize=9, leading=11, textColor=colors.white)

    story = []
    story.append(Paragraph("<b>VoiceFinance AI — Анализ Расходов и Диаграмма</b>", title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Дата формирования: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Всего операций: {len(txs)}", meta_style))
    story.append(Spacer(1, 15))

    # Summary table
    summary_data = [
        [
            Paragraph("<b>Общий Доход</b>", cell_style),
            Paragraph("<b>Общий Расход</b>", cell_style),
            Paragraph("<b>Чистый Баланс</b>", cell_style),
            Paragraph("<b>Коэффициент</b>", cell_style)
        ],
        [
            Paragraph(f"<b>${income:,.2f}</b>", cell_style),
            Paragraph(f"<b>${expense:,.2f}</b>", cell_style),
            Paragraph(f"<b>${balance:,.2f}</b>", cell_style),
            Paragraph(f"<b>{ratio}x</b>", cell_style)
        ]
    ]
    sum_table = Table(summary_data, colWidths=[130, 130, 130, 130])
    sum_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
    ]))
    story.append(sum_table)
    story.append(Spacer(1, 15))

    # Pie Chart Section
    if cat_rows and expense > 0:
        story.append(Paragraph("<b>Распределение расходов по категориям (%):</b>", heading_style))
        story.append(Spacer(1, 8))

        d = Drawing(400, 180)
        pc = Pie()
        pc.x = 20
        pc.y = 15
        pc.width = 150
        pc.height = 150
        pc.data = [amt for cat, amt in cat_rows]
        pc.labels = [f"{round((amt/expense)*100, 1)}%" for cat, amt in cat_rows]
        
        palette = [
            colors.HexColor('#6366F1'), colors.HexColor('#EC4899'),
            colors.HexColor('#10B981'), colors.HexColor('#F59E0B'),
            colors.HexColor('#3B82F6'), colors.HexColor('#8B5CF6')
        ]
        for i in range(len(cat_rows)):
            pc.slices[i].fillColor = palette[i % len(palette)]
            pc.slices[i].strokeColor = colors.white
            pc.slices[i].strokeWidth = 1.5

        d.add(pc)

        leg = Legend()
        leg.x = 200
        leg.y = 140
        leg.dx = 10
        leg.dy = 10
        leg.fontName = CYR_FONT
        leg.fontSize = 9
        leg.boxAnchor = 'nw'
        leg.colorNamePairs = [(palette[i % len(palette)], f"{cat_rows[i][0]}: ${cat_rows[i][1]} ({round((cat_rows[i][1]/expense)*100, 1)}%)") for i in range(len(cat_rows))]
        d.add(leg)

        story.append(d)
        story.append(Spacer(1, 15))

        # Category Breakdown Table
        story.append(Paragraph("<b>Детализация долей по категориям:</b>", heading_style))
        story.append(Spacer(1, 8))

        cat_table_data = [[
            Paragraph("<b>Категория</b>", cell_header_style),
            Paragraph("<b>Сумма</b>", cell_header_style),
            Paragraph("<b>Доля от всех трат</b>", cell_header_style)
        ]]

        for cat, amt in cat_rows:
            pct = round((amt / expense) * 100, 1) if expense > 0 else 0
            cat_table_data.append([
                Paragraph(str(cat), cell_style),
                Paragraph(f"${amt:,.2f}", cell_style),
                Paragraph(f"<b>{pct}%</b> (от общего объёма ${expense:,.2f})", cell_style)
            ])

        cat_table = Table(cat_table_data, colWidths=[150, 130, 240])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366F1')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        story.append(cat_table)
        story.append(Spacer(1, 15))

    # Transactions List
    story.append(Paragraph("<b>История всех операций:</b>", heading_style))
    story.append(Spacer(1, 8))

    tx_table_data = [[
        Paragraph("<b>Дата</b>", cell_header_style),
        Paragraph("<b>Тип</b>", cell_header_style),
        Paragraph("<b>Сумма</b>", cell_header_style),
        Paragraph("<b>Категория</b>", cell_header_style),
        Paragraph("<b>Описание / Голос</b>", cell_header_style)
    ]]

    for t in txs:
        tx_type_str = "Доход" if t['type'] == 'income' else "Расход"
        tx_table_data.append([
            Paragraph(str(t['date']), cell_style),
            Paragraph(tx_type_str, cell_style),
            Paragraph(f"${t['amount']}", cell_style),
            Paragraph(str(t['category']), cell_style),
            Paragraph(str(t['description'] or t['raw_voice'] or '-'), cell_style)
        ])

    if len(txs) == 0:
        tx_table_data.append([
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("$0", cell_style),
            Paragraph("Нет операций", cell_style), Paragraph("-", cell_style)
        ])

    tx_table = Table(tx_table_data, colWidths=[75, 65, 75, 115, 190])
    tx_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#475569')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
    ]))
    story.append(tx_table)

    doc.build(story)
    return filename

# Database helper functions
def save_transaction(tx_type, amount, category, raw):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    date_str = datetime.now().strftime('%Y-%m-%d')
    created_at = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO transactions (type, amount, currency, category, description, raw_voice, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (tx_type, amount, 'USD', category, raw, raw, date_str, created_at))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def correct_last_transaction(new_amount=None, new_category=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, amount, category FROM transactions ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        tx_id, old_amt, old_cat = row
        updated_amt = new_amount if new_amount is not None else old_amt
        updated_cat = new_category if new_category is not None else old_cat
        cursor.execute("UPDATE transactions SET amount = ?, category = ? WHERE id = ?", (updated_amt, updated_cat, tx_id))
        conn.commit()
        conn.close()
        return updated_amt, updated_cat
    conn.close()
    return None, None

def delete_last_transaction():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, category, amount FROM transactions ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM transactions WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return row[1], row[2]
    conn.close()
    return None, None

def get_analytics():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT type, SUM(amount) FROM transactions GROUP BY type")
    rows = dict(cursor.fetchall())
    conn.close()
    
    income = rows.get('income', 0.0) or 0.0
    expense = rows.get('expense', 0.0) or 0.0
    balance = income - expense
    return income, expense, balance

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}/"
        self.file_api_url = f"https://api.telegram.org/file/bot{token}/"
        self.offset = 0
        
    def send_request(self, method, data=None):
        url = self.api_url + method
        headers = {'Content-Type': 'application/json'}
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8') if data else None, headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"[Bot Error] {method}: {e}")
            return None

    def send_document(self, chat_id, file_path, caption=""):
        url = self.api_url + "sendDocument"
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        body = []
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode("utf-8"))
        if caption:
            body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"; parse_mode=\"HTML\"\r\n\r\n{caption}\r\n".encode("utf-8"))
        
        filename = os.path.basename(file_path)
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: application/pdf\r\n\r\n".encode("utf-8"))
        body.append(file_bytes)
        body.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        payload = b"".join(body)
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[sendDocument Error] {e}")
            return None

    def download_file(self, file_path):
        url = self.file_api_url + file_path
        try:
            with urllib.request.urlopen(url) as resp:
                return resp.read()
        except Exception as e:
            print(f"[Download Error] {e}")
            return None

    def send_message(self, chat_id, text, reply_markup=None):
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
        if reply_markup:
            payload['reply_markup'] = reply_markup
        return self.send_request('sendMessage', payload)

    def process_ai_result(self, chat_id, gemini_res, raw_input="сообщение"):
        lower_input = (raw_input or "").lower()
        is_chart_request = any(kw in lower_input for kw in ['пдф', 'pdf', 'отчет', 'отчёт', 'график', 'диаграмм', 'кругов', 'процент', 'соотношен', 'съел', 'объем'])

        if is_chart_request or (gemini_res and gemini_res.get('intent') == 'EXPORT_PDF'):
            income, expense, balance = get_analytics()
            pdf_path = generate_pdf_report("voicefinance_report.pdf")
            caption_msg = (
                f"📊 <b>Ваша круговая диаграмма и процентный отчёт готовы!</b>\n\n"
                f"💰 Общий объём трат: <b>${expense:,.2f}</b> из заработанных <b>${income:,.2f}</b>\n"
                f"📄 Файл PDF со встроенной круговой диаграммой прикреплён ниже."
            )
            self.send_document(chat_id, pdf_path, caption=caption_msg)
            return

        if not gemini_res:
            income, expense, balance = get_analytics()
            self.send_message(chat_id, f"🎙️ Понял вашу запись!\n💳 Текущий баланс: <b>${balance:,.2f}</b>\nНажмите кнопку ниже для интерактивного UI с графиками.")
            return

        intent = gemini_res.get('intent', 'CHAT')
        ai_reply = gemini_res.get('ai_reply', '')
        transcribed = gemini_res.get('transcribed_text', '')

        if not chat_id in USER_CHAT_HISTORY:
            USER_CHAT_HISTORY[chat_id] = []
        USER_CHAT_HISTORY[chat_id].append({'ai': ai_reply})

        prefix = f"🎤 <i>«{transcribed}»</i>\n\n" if transcribed else ""

        if intent == 'ADD_TX' and gemini_res.get('amount'):
            tx_type = gemini_res.get('type', 'expense')
            amt = gemini_res.get('amount')
            cat = gemini_res.get('category', 'прочее')
            save_transaction(tx_type, amt, cat, transcribed or raw_input)
            income, expense, balance = get_analytics()
            
            full_reply = f"{prefix}✨ {ai_reply}\n\n💳 <b>Текущий баланс: ${balance:,.2f}</b>"
            self.send_message(chat_id, full_reply)

        elif intent == 'CORRECT_LAST':
            new_amt = gemini_res.get('new_amount') or gemini_res.get('amount')
            new_cat = gemini_res.get('new_category') or gemini_res.get('category')
            correct_last_transaction(new_amt, new_cat)
            income, expense, balance = get_analytics()
            
            full_reply = f"{prefix}🔄 {ai_reply}\n\n💳 <b>Обновленный баланс: ${balance:,.2f}</b>"
            self.send_message(chat_id, full_reply)

        elif intent == 'DELETE_LAST':
            cat, amt = delete_last_transaction()
            income, expense, balance = get_analytics()
            full_reply = f"{prefix}🗑️ {ai_reply}\n\n💳 <b>Баланс: ${balance:,.2f}</b>"
            self.send_message(chat_id, full_reply)

        else:
            full_reply = f"{prefix}{ai_reply}" if prefix else ai_reply
            self.send_message(chat_id, full_reply)

    def handle_update(self, update):
        msg = update.get('message')
        if not msg:
            return
        
        chat_id = msg['chat']['id']
        text = msg.get('text', '')
        voice = msg.get('voice')
        
        # Start command
        if text.startswith('/start') or text.startswith('/help'):
            welcome = (
                "<b>🎙️ Привет! Я твой голосовой AI-ассистент VoiceFinance.</b>\n\n"
                "Отправляй любые голосовые сообщения или текст на любые темы! Я воспринимаю всё: вопросы, разговоры, заметки, расходы, самоисправления и запросы круговых диаграмм/отчётов.\n\n"
                "<b>Например:</b>\n"
                "• 🎤 <i>«Покажи диаграмму расходов в процентах»</i>\n"
                "• 🎤 <i>«Запиши 1500 рублей на продукты»</i>\n"
                "• 🎤 <i>«Ой, смени последнюю категорию на бензин»</i>\n\n"
                "Нажмите кнопку ниже для перехода в визуальный UI!"
            )
            web_url = os.environ.get("WEB_APP_URL", "https://voicefinance.onrender.com")
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "📱 Открыть VoiceFinance UI", "web_app": {"url": web_url}}
                ]]
            }
            self.send_message(chat_id, welcome, reply_markup)
            return

        # Voice Message handling with Multimodal Gemini Speech-to-Text
        if voice:
            file_id = voice['file_id']
            file_info = self.send_request('getFile', {'file_id': file_id})
            
            if file_info and file_info.get('ok'):
                file_path = file_info['result']['file_path']
                audio_bytes = self.download_file(file_path)
                
                if audio_bytes:
                    gemini_res = ask_gemini_brain(chat_id=chat_id, audio_bytes=audio_bytes)
                    self.process_ai_result(chat_id, gemini_res, raw_input="голосовая заметка")
                else:
                    self.send_message(chat_id, "❌ Не удалось загрузить аудиозапись.")
            else:
                self.send_message(chat_id, "❌ Ошибка получения звукового файла от Telegram.")
            return

        # Text Message handling
        if text:
            if not chat_id in USER_CHAT_HISTORY:
                USER_CHAT_HISTORY[chat_id] = []
            USER_CHAT_HISTORY[chat_id].append({'user': text})

            gemini_res = ask_gemini_brain(user_text=text, chat_id=chat_id)
            self.process_ai_result(chat_id, gemini_res, raw_input=text)

    def start_polling(self):
        print(f"[Bot] Multimodal Voice & Percentage Pie Chart Gemini Bot is polling...")
        while True:
            try:
                res = self.send_request('getUpdates', {'offset': self.offset, 'timeout': 30})
                if res and res.get('ok'):
                    for update in res.get('result', []):
                        self.offset = update['update_id'] + 1
                        self.handle_update(update)
            except Exception as e:
                print(f"[Bot Polling Error] {e}")
                time.sleep(3)
            time.sleep(0.5)

if __name__ == '__main__':
    bot = TelegramBot(TOKEN)
    bot.start_polling()
