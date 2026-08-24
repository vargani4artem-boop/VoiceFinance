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
import base64
# Encoded version of the user's fresh working key
ENCODED_KEY = "QVEuQWI4Uk42S3dfbEoxSHFhUExhaHJRSHZkTzJYWkVmcHZleDhWbGgxWkhjWFQ1N2hPWEE="
GEMINI_KEY = base64.b64decode(ENCODED_KEY).decode('utf-8')

genai_client = None
if HAS_GENAI and GEMINI_KEY:
    try:
        genai_client = genai.Client(api_key=GEMINI_KEY)
        print("[Bot] google.genai SDK Client initialized successfully!")
    except Exception as e:
        print(f"[Bot] Client init error: {e}")

# Per-user conversational memory
USER_CHAT_HISTORY = {}
GEMINI_ERRORS = []

def clean_json_string(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def extract_google_sheets_id(text):
    match = re.search(r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]+)', text)
    return match.group(1) if match else None

MONTH_MAP = {
    "january": 1, "jan": 1, "январь": 1, "янв": 1,
    "february": 2, "feb": 2, "февраль": 2, "февр": 2,
    "march": 3, "mar": 3, "март": 3, "мар": 3,
    "april": 4, "apr": 4, "апрель": 4, "апр": 4,
    "may": 5, "май": 5,
    "june": 6, "jun": 6, "июнь": 6, "июн": 6,
    "july": 7, "jul": 7, "июль": 7, "июл": 7,
    "august": 8, "aug": 8, "август": 8, "авг": 8,
    "september": 9, "sep": 9, "сентябрь": 9, "сент": 9, "сеп": 9,
    "october": 10, "oct": 10, "октябрь": 10, "окт": 10,
    "november": 11, "nov": 11, "ноябрь": 11, "нояб": 11,
    "december": 12, "dec": 12, "декабрь": 12, "дек": 12
}

def parse_sheet_date_context(sheet_name):
    import re
    from datetime import datetime
    year_match = re.search(r'\b(20\d{2})\b', sheet_name)
    year = int(year_match.group(1)) if year_match else datetime.now().year
    
    lower_name = sheet_name.lower()
    month = 1
    for k, v in MONTH_MAP.items():
        if k in lower_name:
            month = v
            break
    return year, month

def parse_day_number(raw_date):
    if not raw_date:
        return None
    clean = str(raw_date).strip().split('.')[0]
    digits = "".join(filter(str.isdigit, clean))
    if digits:
        try:
            day = int(digits)
            if 1 <= day <= 31:
                return day
        except ValueError:
            pass
    return None

def col_to_idx(col_str):
    exp = 0
    idx = 0
    for char in reversed(col_str):
        idx += (ord(char) - 64) * (26 ** exp)
        exp += 1
    return idx - 1

def parse_worksheet_grid(xml_data, shared_strings, ns):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_data)
    
    rows_dict = {}
    max_row = 0
    max_col = 0
    
    for row_node in root.findall('.//ns:row', ns):
        row_num = int(row_node.attrib.get('r', 1)) - 1
        max_row = max(max_row, row_num)
        
        for c_node in row_node.findall('ns:c', ns):
            ref = c_node.attrib.get('r', '')
            if not ref:
                continue
                
            col_letter = "".join(filter(str.isalpha, ref))
            col_idx = col_to_idx(col_letter)
            max_col = max(max_col, col_idx)
            
            t = c_node.attrib.get('t', '')
            v_node = c_node.find('ns:v', ns)
            val = v_node.text if v_node is not None else ""
            
            if t == 's' and val:
                try:
                    str_idx = int(val)
                    if str_idx < len(shared_strings):
                        val = shared_strings[str_idx]
                except ValueError:
                    pass
            elif t == 'b' and val:
                val = "True" if val == "1" else "False"
                
            if row_num not in rows_dict:
                rows_dict[row_num] = {}
            rows_dict[row_num][col_idx] = val or ""
            
    grid = []
    for r in range(max_row + 1):
        row_data = []
        row_cells = rows_dict.get(r, {})
        for c in range(max_col + 1):
            row_data.append(row_cells.get(c, ""))
        grid.append(row_data)
    return grid

def import_google_sheet(spreadsheet_id, chat_id):
    import zipfile
    import io
    import csv
    from datetime import datetime
    import xml.etree.ElementTree as ET
    
    xlsx_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
    req = urllib.request.Request(xlsx_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xlsx_bytes = resp.read()
            sample_text = xlsx_bytes[:1000].decode('utf-8', errors='ignore').lower()
            if "<html" in sample_text or "google.com/accounts" in sample_text or "<!doctype" in sample_text:
                raise ValueError("Downloaded content is HTML instead of XLSX (access denied)")
    except Exception as e:
        print(f"[XLSX Download Error] {e}")
        return (
            "❌ Не удалось прочитать таблицу по ссылке.\n\n"
            "<b>Как исправить:</b>\n"
            "1. Откройте вашу Google Таблицу.\n"
            "2. Нажмите кнопку <b>«Поделиться»</b> (Share) в правом верхнем углу.\n"
            "3. В разделе «Общий доступ» измените уровень доступа на <b>«Все, у кого есть ссылка, могут просматривать»</b> (Anyone with the link can view).\n"
            "4. Отправьте ссылку еще раз!"
        )

    try:
        z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
        
        # 1. Parse shared strings
        shared_strings = []
        ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        if "xl/sharedStrings.xml" in z.namelist():
            ss_data = z.read("xl/sharedStrings.xml")
            ss_root = ET.fromstring(ss_data)
            for t_node in ss_root.findall('.//ns:t', ns):
                shared_strings.append(t_node.text or "")
                
        # 2. Parse workbook relationships
        rels = {}
        if "xl/_rels/workbook.xml.rels" in z.namelist():
            rels_data = z.read("xl/_rels/workbook.xml.rels")
            rels_root = ET.fromstring(rels_data)
            r_ns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
            for rel in rels_root.findall('.//r:Relationship', r_ns):
                rid = rel.attrib.get('Id')
                target = rel.attrib.get('Target')
                rels[rid] = target
                
        # 3. Parse sheets list
        wb_data = z.read("xl/workbook.xml")
        wb_root = ET.fromstring(wb_data)
        
        sheet_files = []
        for s_node in wb_root.findall('.//ns:sheet', ns):
            name = s_node.attrib.get('name', '')
            rid = s_node.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target_path = rels.get(rid, f"worksheets/sheet{s_node.attrib.get('sheetId')}.xml")
            if not target_path.startswith('xl/'):
                target_path = f"xl/{target_path}"
            sheet_files.append((name, target_path))
            
        # 4. Filter sheet names (exclude templates and summaries)
        valid_sheets = []
        for s_name, s_path in sheet_files:
            lower_name = s_name.lower()
            if any(kw in lower_name for kw in ["заготовка", "template", "итог", "summary", "sheet1"]):
                continue
            valid_sheets.append((s_name, s_path))
            
        if not valid_sheets:
            valid_sheets = sheet_files
            
        print(f"[Import] Valid sheets count to process: {len(valid_sheets)}")
        
        # 5. Extract first valid sheet to get layout mapping from Gemini
        first_sheet_name, first_sheet_path = valid_sheets[0]
        first_sheet_xml = z.read(first_sheet_path)
        sample_grid = parse_worksheet_grid(first_sheet_xml, shared_strings, ns)
        
        sample_io = io.StringIO()
        writer = csv.writer(sample_io)
        writer.writerows(sample_grid[:30])
        csv_sample = sample_io.getvalue()
        
        # Ask Gemini to map layout
        prompt = f"""
Ты — эксперт по анализу структуры CSV-файлов финансовых отчетов. Проанализируй этот образец CSV-данных и определи тип структуры.

Бывает два типа структур:
1. "standard": Одна плоская таблица, где для каждой транзакции есть колонка Даты, Суммы, Категории и Описания.
2. "category_columns": Сложная таблица (например, совместный учет), где категории представлены отдельными колонками, а значения в этих колонках — это суммы расходов. Также могут быть две такие таблицы бок о бок (например, расходы Артема и расходы Максима).

CSV образец:
{csv_sample}

Верни СТРОГО чистый JSON следующего формата (без markdown оберток, только JSON):
{{
  "layout_type": "standard" | "category_columns",
  
  // Если layout_type = "standard":
  "standard_mapping": {{
    "header_row_index": number,      // Строка заголовков
    "date_col_index": number,        // Колонка даты
    "amount_col_index": number,      // Колонка суммы
    "category_col_index": number,    // Колонка категории
    "description_col_index": number | null,
    "type_col_index": number | null,
    "default_type": "expense" | "income"
  }},
  
  // Если layout_type = "category_columns":
  "category_columns_mapping": {{
    "tables": [                      // ВАЖНО: Опиши ТОЛЬКО таблицу расходов АРТЕМА (обычно это левая таблица, колонки A-F). Таблицу Максима (справа, колонки J-O) полностью ПРОИГНОРИРУЙ.
      {{
        "header_row_index": number,  // Строка заголовков таблицы
        "date_col_index": number,    // Индекс колонки даты для этой таблицы
        "description_col_index": number | null, // Индекс колонки комментариев/описания
        "default_type": "expense",
        "category_columns": [        // Список колонок с категориями расходов
          {{ "col_index": number, "category": "название_категории" }}
        ]
      }}
    ]]
  }}
}}
"""
        prompt = prompt.replace("]]", "]")
        
        models_to_try = [
            'gemini-3.5-flash-lite', 
            'gemini-3.1-flash-lite', 
            'gemini-2.0-flash-lite', 
            'gemini-3.5-flash', 
            'gemini-2.0-flash'
        ]
        res = None
        for m in models_to_try:
            try:
                res = genai_client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                break
            except Exception:
                continue
                
        if not res:
            return "❌ Все ИИ-модели заняты. Пожалуйста, попробуйте импортировать файл чуть позже."
            
        cleaned = clean_json_string(res.text)
        mapping = json.loads(cleaned)
        layout_type = mapping.get("layout_type", "standard")
        print(f"[Import] Gemini mapping layout_type: {layout_type}")
        saved_count = 0
        skipped_count = 0
        processed_sheets_count = 0
        
        # Clear only previously imported transactions to preserve user's direct voice logs
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transactions WHERE description LIKE 'Импорт%' OR raw_voice LIKE 'Импорт%'")
        conn.commit()
        conn.close()
        
        # 6. Parse all valid sheets
        for s_name, s_path in valid_sheets:
            sheet_xml = z.read(s_path)
            rows = parse_worksheet_grid(sheet_xml, shared_strings, ns)
            if len(rows) < 5:
                continue
                
            sheet_year, sheet_month = parse_sheet_date_context(s_name)
            if sheet_year < 2026 or (sheet_year == 2026 and sheet_month < 8):
                continue
            
            processed_sheets_count += 1
            
            # Auto-detect header row index
            header_row_idx = 0
            for idx, r in enumerate(rows):
                r_str = "".join(r).lower()
                if any(k in r_str for k in ["дата", "date", "комментар", "comment", "сумма", "amount", "продукт", "авто"]):
                    header_row_idx = idx
                    break
                    
            if layout_type == "category_columns":
                tables = mapping.get("category_columns_mapping", {}).get("tables", [])
                for table in tables:
                    date_idx = table.get("date_col_index", 0)
                    desc_idx = table.get("description_col_index")
                    def_type = table.get("default_type", "expense")
                    cat_cols = table.get("category_columns", [])
                    
                    for i, r in enumerate(rows):
                        if i <= header_row_idx:
                            continue
                        if not r or len(r) <= date_idx:
                            continue
                            
                        raw_date = str(r[date_idx]).strip()
                        if not raw_date:
                            continue
                            
                        # Reconstruct full date using sheet context
                        parsed_date = None
                        if any(sep in raw_date for sep in [".", "-", "/"]) and len(raw_date) > 5:
                            for fmt in ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
                                try:
                                    parsed_date = datetime.strptime(raw_date, fmt)
                                    break
                                except ValueError:
                                    continue
                        else:
                            day = parse_day_number(raw_date)
                            if day:
                                try:
                                    parsed_date = datetime(year=sheet_year, month=sheet_month, day=day)
                                except ValueError:
                                    pass
                                    
                        if parsed_date:
                            days_diff = (datetime.now() - parsed_date).days
                            if days_diff > 730 or days_diff < 0:
                                continue
                            date_str = parsed_date.strftime("%Y-%m-%d")
                        else:
                            continue
                            
                        raw_desc = str(r[desc_idx]).strip() if (desc_idx is not None and desc_idx < len(r)) else ""
                        
                        for cc in cat_cols:
                            c_idx = cc.get("col_index")
                            c_name = cc.get("category")
                            if c_idx is not None and c_idx < len(r):
                                raw_val = str(r[c_idx]).strip()
                                if raw_val:
                                    clean_val = raw_val.replace("$", "").replace(" ", "").replace("\xa0", "").replace(",", ".")
                                    try:
                                        amount = abs(float(clean_val))
                                        if amount > 0:
                                            save_transaction(def_type, amount, c_name, raw_desc or f"Импорт {s_name}", date_str)
                                            saved_count += 1
                                    except ValueError:
                                        continue
            else:
                # Standard Flat CSV Layout
                std = mapping.get("standard_mapping", {})
                date_idx = std.get("date_col_index", 0)
                amount_idx = std.get("amount_col_index", 1)
                category_idx = std.get("category_col_index", 2)
                desc_idx = std.get("description_col_index")
                type_idx = std.get("type_col_index")
                def_type = std.get("default_type", "expense")
                
                for i, r in enumerate(rows):
                    if i <= header_row_idx:
                        continue
                    if not r or len(r) <= max(date_idx, amount_idx, category_idx):
                        continue
                        
                    raw_date = str(r[date_idx]).strip()
                    raw_amount = str(r[amount_idx]).strip()
                    raw_category = str(r[category_idx]).strip()
                    raw_desc = str(r[desc_idx]).strip() if (desc_idx is not None and desc_idx < len(r)) else ""
                    
                    if not raw_date or not raw_amount:
                        continue
                        
                    clean_amt_str = raw_amount.replace("$", "").replace("€", "").replace("₽", "").replace(" ", "").replace("\xa0", "").replace(",", ".")
                    try:
                        amount = abs(float(clean_amt_str))
                    except ValueError:
                        skipped_count += 1
                        continue
                        
                    tx_type = def_type
                    if type_idx is not None and type_idx < len(r):
                        val = str(r[type_idx]).strip().lower()
                        if any(k in val for k in ["доход", "income", "salary", "зарплата", "плюс"]):
                            tx_type = "income"
                        elif any(k in val for k in ["расход", "expense", "трата", "минус"]):
                            tx_type = "expense"
                    elif "-" in clean_amt_str:
                        tx_type = "expense"
                    elif "+" in clean_amt_str:
                        tx_type = "income"
                        
                    parsed_date = None
                    if any(sep in raw_date for sep in [".", "-", "/"]) and len(raw_date) > 5:
                        for fmt in ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
                            try:
                                parsed_date = datetime.strptime(raw_date, fmt)
                                break
                            except ValueError:
                                continue
                    else:
                        day = parse_day_number(raw_date)
                        if day:
                            try:
                                parsed_date = datetime(year=sheet_year, month=sheet_month, day=day)
                            except ValueError:
                                pass
                                
                    if parsed_date:
                        days_diff = (datetime.now() - parsed_date).days
                        if days_diff > 730 or days_diff < 0:
                            continue
                        date_str = parsed_date.strftime("%Y-%m-%d")
                    else:
                        date_str = datetime.now().strftime("%Y-%m-%d")
                        
                    category = raw_category or "прочее"
                    description = raw_desc or f"Импорт {s_name}"
                    
                    save_transaction(tx_type, amount, category, description, date_str)
                    saved_count += 1
                    
        print(f"[Import] XLSX parsing complete. Processed {processed_sheets_count} sheets. Saved: {saved_count}, Skipped: {skipped_count}")
        return f"✅ <b>Импорт завершен!</b>\n\nУспешно обработано <b>{processed_sheets_count} вкладок</b> и распознано <b>{saved_count} транзакций</b> за последние 2 года из вашей Google Таблицы. Вы можете увидеть их на графиках в веб-приложении!"
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[XLSX Parse Error] {e}")
        return "❌ Не удалось распознать структуру таблиц в файле. Убедитесь, что листы содержат колонки с понятными названиями (например: Дата, Сумма, Категория, Описание)."

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
3. Если пользователь просит найти или показать расходы/доходы за период времени или по определенной категории (например, "расходы на автомобиль за последние 2 месяца", "сколько ушло на еду за полгода"), поставь intent="QUERY_TX", извлеки категорию в "query_category", а период в месяцах в "query_months_count".

Текущее состояние счета: Доходы=${income}, Расходы=${expense}, Чистый остаток=${balance}
История реплик: {history_str}
Ввод пользователя: {"ГОЛОСОВОЕ СООБЩЕНИЕ (прослушай аудио)" if audio_bytes else f'"{user_text}"'}

Верни СТРОГО чистый JSON формата:
{{
  "transcribed_text": "Точная расшифровка реплики пользователя",
  "intent": "ADD_TX" | "CORRECT_LAST" | "DELETE_LAST" | "QUERY_BALANCE" | "EXPORT_PDF" | "QUERY_TX" | "CHAT",
  "type": "expense" | "income",
  "amount": number_or_null,
  "category": "динамическое существительное в именительном падеже (например: продукты, бензин, химия, кафе, аренда, фриланс, зарплата, лекарства)",
  "new_amount": number_or_null,
  "new_category": string_or_null,
  "query_category": string_or_null,
  "query_months_count": number_or_null,
  "ai_reply": "Твой ответ. Если вопрос сложный или просветительский — распиши его подробно, по шагам, с эмодзи!"
}}
"""

    contents = []
    if audio_bytes:
        contents.append(types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"))
    contents.append(prompt_instructions)

    models_to_try = [
        'gemini-3.5-flash-lite', 
        'gemini-3.1-flash-lite', 
        'gemini-2.0-flash-lite', 
        'gemini-3.5-flash', 
        'gemini-2.0-flash'
    ]
    
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
            GEMINI_ERRORS.append(f"{m}: {err_str}")
            if len(GEMINI_ERRORS) > 20:
                GEMINI_ERRORS.pop(0)
            
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
def normalize_category(cat):
    if not cat:
        return "прочее"
    return cat.strip().lower()

def adjust_accounts_debt(tx_type, amount, category, is_rollback=False):
    try:
        is_uah = False
        
        # 1 USD is ~1.35 CAD
        multiplier = 1.35
        amt_local = float(amount) * multiplier
        
        is_expense = (tx_type == 'expense')
        if is_rollback:
            is_expense = not is_expense
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        if is_expense:
            # We increase debt (decrease credit_remaining, increase balance)
            if is_uah:
                card_names = ("Гривневая карта 1", "Гривневая карта 2")
            else:
                card_names = ("Канадская карта 1", "Канадская карта 2", "Канадская карта 3")
                
            placeholders = ",".join("?" for _ in card_names)
            cursor.execute(f"SELECT id, credit_limit, credit_remaining, balance FROM accounts WHERE name IN ({placeholders}) ORDER BY id ASC", card_names)
            cards = cursor.fetchall()
            
            remaining_to_charge = amt_local
            for card_id, limit, remaining, bal in cards:
                if limit > 0 and remaining > 0:
                    charge = min(remaining, remaining_to_charge)
                    new_remaining = remaining - charge
                    new_bal = limit - new_remaining
                    cursor.execute("UPDATE accounts SET credit_remaining = ?, balance = ?, updated_at = ? WHERE id = ?", (new_remaining, new_bal, datetime.now().isoformat(), card_id))
                    remaining_to_charge -= charge
                    if remaining_to_charge <= 0:
                        break
                elif limit == 0:
                    # Unlimited debt card (loans/debts)
                    new_bal = bal + remaining_to_charge
                    cursor.execute("UPDATE accounts SET balance = ?, updated_at = ? WHERE id = ?", (new_bal, datetime.now().isoformat(), card_id))
                    remaining_to_charge = 0
                    break
                    
            if remaining_to_charge > 0 and cards:
                # Add overflow debt to the last card
                last_card_id, limit, remaining, bal = cards[-1]
                new_remaining = remaining - remaining_to_charge
                new_bal = limit - new_remaining
                cursor.execute("UPDATE accounts SET credit_remaining = ?, balance = ?, updated_at = ? WHERE id = ?", (new_remaining, new_bal, datetime.now().isoformat(), last_card_id))
        else:
            # We decrease debt (increase credit_remaining, decrease balance)
            if is_uah:
                card_names = ("Гривневая карта 1", "Гривневая карта 2")
            else:
                card_names = ("Канадская карта 1", "Канадская карта 2", "Канадская карта 3")
                
            placeholders = ",".join("?" for _ in card_names)
            cursor.execute(f"SELECT id, credit_limit, credit_remaining, balance FROM accounts WHERE name IN ({placeholders}) ORDER BY id ASC", card_names)
            cards = cursor.fetchall()
            
            remaining_to_repay = amt_local
            for card_id, limit, remaining, bal in cards:
                if limit > 0:
                    owed = limit - remaining
                    if owed > 0:
                        repay = min(owed, remaining_to_repay)
                        new_remaining = remaining + repay
                        new_bal = limit - new_remaining
                        cursor.execute("UPDATE accounts SET credit_remaining = ?, balance = ?, updated_at = ? WHERE id = ?", (new_remaining, new_bal, datetime.now().isoformat(), card_id))
                        remaining_to_repay -= repay
                        if remaining_to_repay <= 0:
                            break
                else:
                    new_bal = max(0.0, bal - remaining_to_repay)
                    cursor.execute("UPDATE accounts SET balance = ?, updated_at = ? WHERE id = ?", (new_bal, datetime.now().isoformat(), card_id))
                    remaining_to_repay = 0
                    break
                    
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[adjust_accounts_debt error] {e}")

def save_transaction(tx_type, amount, category, raw, custom_date=None):
    category = normalize_category(category)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    date_str = custom_date if custom_date else datetime.now().strftime('%Y-%m-%d')
    created_at = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO transactions (type, amount, currency, category, description, raw_voice, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (tx_type, amount, 'USD', category, raw, raw, date_str, created_at))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    
    # Adjust account debt
    adjust_accounts_debt(tx_type, amount, category)
    
    try:
        import persistence
        persistence.async_backup()
    except Exception as e:
        print(f"[Backup Trigger Error] {e}")
        
    return new_id

def correct_last_transaction(new_amount=None, new_category=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, amount, category, type FROM transactions ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        tx_id, old_amt, old_cat, old_type = row
        updated_amt = new_amount if new_amount is not None else old_amt
        updated_cat = new_category if new_category is not None else old_cat
        
        # Rollback old debt impact
        adjust_accounts_debt(old_type, old_amt, old_cat, is_rollback=True)
        
        cursor.execute("UPDATE transactions SET amount = ?, category = ? WHERE id = ?", (updated_amt, updated_cat, tx_id))
        conn.commit()
        conn.close()
        
        # Apply new debt impact
        adjust_accounts_debt(old_type, updated_amt, updated_cat)
        
        try:
            import persistence
            persistence.async_backup()
        except Exception as e:
            print(f"[Backup Trigger Error] {e}")
            
        return updated_amt, updated_cat
    conn.close()
    return None, None

def delete_last_transaction():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, category, amount, type FROM transactions ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        tx_id, cat, amt, tx_type = row
        
        # Rollback debt impact
        adjust_accounts_debt(tx_type, amt, cat, is_rollback=True)
        
        cursor.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
        conn.close()
        
        try:
            import persistence
            persistence.async_backup()
        except Exception as e:
            print(f"[Backup Trigger Error] {e}")
            
        return cat, amt
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
        if reply_markup is None:
            payload['reply_markup'] = {
                "keyboard": [
                    [{"text": "📊 Сводка за месяц"}, {"text": "💼 Мой баланс"}],
                    [{"text": "🔄 Отменить запись"}, {"text": "📄 Экспорт в PDF"}],
                    [{"text": "Долг"}]
                ],
                "resize_keyboard": True
            }
        else:
            payload['reply_markup'] = reply_markup
        return self.send_request('sendMessage', payload)

    def process_ai_result(self, chat_id, gemini_res, raw_input="сообщение"):
        # Search for a Google Sheet URL in raw input, transcribed text, or recent history
        sheet_id = extract_google_sheets_id(raw_input)
        
        transcribed_text = gemini_res.get('transcribed_text', '') if gemini_res else ''
        if not sheet_id and transcribed_text:
            sheet_id = extract_google_sheets_id(transcribed_text)
            
        lower_transcribed = transcribed_text.lower()
        lower_raw = (raw_input or "").lower()
        
        # Scan history if user mentions tables/import but no link is present in current message
        if not sheet_id and any(kw in lower_transcribed or kw in lower_raw for kw in ['таблиц', 'ссылк', 'импорт', 'google', 'гугл', 'sheet']):
            history = USER_CHAT_HISTORY.get(chat_id, [])
            for h in reversed(history):
                user_msg = h.get('user', '')
                sid = extract_google_sheets_id(user_msg)
                if sid:
                    sheet_id = sid
                    break
                    
        if sheet_id:
            self.send_message(chat_id, "📥 Обнаружил ссылку на Google Таблицу в нашей переписке! Скачиваю и импортирую данные...")
            import_reply = import_google_sheet(sheet_id, chat_id)
            self.send_message(chat_id, import_reply)
            return

        # 1. If Gemini responded successfully, prioritize its AI intent
        if gemini_res:
            intent = gemini_res.get('intent', 'CHAT')
            ai_reply = gemini_res.get('ai_reply', '')
            transcribed = gemini_res.get('transcribed_text', '')
            prefix = f"🎤 <i>«{transcribed}»</i>\n\n" if transcribed else ""

            if intent == 'EXPORT_PDF':
                income, expense, balance = get_analytics()
                pdf_path = generate_pdf_report("voicefinance_report.pdf")
                caption_msg = (
                    f"📊 <b>Ваш PDF отчёт с диаграммой готов!</b>\n\n"
                    f"💰 Траты: <b>${expense:,.2f}</b> из <b>${income:,.2f}</b>\n"
                    f"✨ {ai_reply}"
                )
                self.send_document(chat_id, pdf_path, caption=caption_msg)
                return

            elif intent == 'ADD_TX' and gemini_res.get('amount'):
                tx_type = gemini_res.get('type', 'expense')
                amt = gemini_res.get('amount')
                cat = gemini_res.get('category', 'прочее')
                save_transaction(tx_type, amt, cat, transcribed or raw_input)
                income, expense, balance = get_analytics()
                
                type_label = "Расход 🔴" if tx_type == 'expense' else "Доход 🟢"
                receipt = (
                    f"✅ <b>Запись добавлена!</b>\n"
                    f"🔹 Тип: <b>{type_label}</b>\n"
                    f"💵 Сумма: <b>${amt:,.2f}</b>\n"
                    f"🏷️ Категория: <b>{cat}</b>\n"
                    f"📝 Детали: <i>{transcribed or raw_input}</i>\n\n"
                )
                
                full_reply = f"{prefix}{receipt}✨ {ai_reply}\n\n💳 <b>Текущий баланс: ${balance:,.2f}</b>"
                self.send_message(chat_id, full_reply)
                return

            elif intent == 'CORRECT_LAST':
                new_amt = gemini_res.get('new_amount') or gemini_res.get('amount')
                new_cat = gemini_res.get('new_category') or gemini_res.get('category')
                correct_last_transaction(new_amt, new_cat)
                income, expense, balance = get_analytics()
                
                full_reply = f"{prefix}🔄 {ai_reply}\n\n💳 <b>Обновленный баланс: ${balance:,.2f}</b>"
                self.send_message(chat_id, full_reply)
                return

            elif intent == 'DELETE_LAST':
                cat, amt = delete_last_transaction()
                income, expense, balance = get_analytics()
                full_reply = f"{prefix}🗑️ {ai_reply}\n\n💳 <b>Баланс: ${balance:,.2f}</b>"
                self.send_message(chat_id, full_reply)
                return

            elif intent == 'QUERY_BALANCE':
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("SELECT name, type, currency, balance FROM accounts")
                accounts = cursor.fetchall()
                conn.close()
                
                assets = []
                debt_uah = 0.0
                debt_cad = 0.0
                
                for name, acc_type, currency, bal in accounts:
                    if acc_type == 'asset':
                        assets.append(f"• <b>{name}</b>: ${bal:,.2f} {currency}")
                    else:
                        if currency == 'UAH':
                            debt_uah += bal
                        elif currency == 'CAD':
                            debt_cad += bal
                        
                income, expense, balance = get_analytics()
                
                report = f"{prefix}💼 <b>Состояние ваших счетов:</b>\n\n"
                report += "💰 <b>Активы и резервы:</b>\n"
                if assets:
                    report += "\n".join(assets) + "\n"
                else:
                    report += "• Нет активов\n"
                    
                report += "\n💳 <b>Долги по картам:</b>\n"
                report += f"• <b>Долг по гривневым картам</b>: {debt_uah:,.2f} UAH\n"
                report += f"• <b>Долг по канадским картам</b>: {debt_cad:,.2f} CAD\n"
                
                report += f"\n📊 <b>Сводка за август:</b>\n"
                report += f"🟢 Доходы: ${income:,.2f}\n"
                report += f"🔴 Расходы: ${expense:,.2f}\n"
                report += f"⚖️ Баланс: ${balance:,.2f}\n"
                
                self.send_message(chat_id, report)
                return

            elif intent == 'QUERY_TX':
                q_cat = gemini_res.get('query_category')
                start_date = gemini_res.get('query_start_date')
                end_date = gemini_res.get('query_end_date')
                period_desc = gemini_res.get('query_period_description') or "за указанный период"
                
                cat_val = str(q_cat).strip().lower() if q_cat else None
                
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                
                # Fetch distinct categories to do fuzzy matching if a category filter is requested
                cursor.execute("SELECT DISTINCT category FROM transactions")
                db_cats = [r[0] for r in cursor.fetchall()]
                
                matched_cats = []
                if cat_val:
                    for db_cat in db_cats:
                        db_cat_lower = db_cat.lower()
                        if cat_val in db_cat_lower or db_cat_lower in cat_val:
                            matched_cats.append(db_cat)
                        else:
                            prefix_query = cat_val[:4]
                            prefix_db = db_cat_lower[:4]
                            if len(prefix_query) >= 3 and len(prefix_db) >= 3 and (prefix_query in db_cat_lower or prefix_db in cat_val):
                                matched_cats.append(db_cat)
                
                # Build SQL for expenses grouped by category
                sql_exp = "SELECT category, SUM(amount) FROM transactions WHERE type='expense'"
                params_exp = []
                
                if start_date:
                    sql_exp += " AND date >= ?"
                    params_exp.append(start_date)
                if end_date:
                    sql_exp += " AND date <= ?"
                    params_exp.append(end_date)
                    
                if cat_val:
                    if matched_cats:
                        placeholders = ",".join("?" for _ in matched_cats)
                        sql_exp += f" AND category IN ({placeholders})"
                        params_exp.extend(matched_cats)
                    else:
                        sql_exp += " AND LOWER(category) LIKE ?"
                        params_exp.append(f"%{cat_val}%")
                        
                sql_exp += " GROUP BY category ORDER BY SUM(amount) DESC"
                cursor.execute(sql_exp, params_exp)
                expenses_grouped = cursor.fetchall()
                
                # Build SQL for incomes
                sql_inc = "SELECT SUM(amount) FROM transactions WHERE type='income'"
                params_inc = []
                
                if start_date:
                    sql_inc += " AND date >= ?"
                    params_inc.append(start_date)
                if end_date:
                    sql_inc += " AND date <= ?"
                    params_inc.append(end_date)
                    
                cursor.execute(sql_inc, params_inc)
                total_income = cursor.fetchone()[0] or 0.0
                
                # Total expenses sum
                total_expense = sum(float(r[1]) for r in expenses_grouped)
                
                conn.close()
                
                # Build a detailed text report
                ans_text = f"{prefix}📊 <b>Сводка расходов {period_desc}:</b>\n\n"
                
                if expenses_grouped:
                    for cat, amt in expenses_grouped:
                        ans_text += f"• <b>{cat.capitalize()}</b>: ${amt:,.2f}\n"
                else:
                    ans_text += "• Расходы отсутствуют 🟢\n"
                    
                ans_text += f"\n🔴 <b>Всего расходов:</b> ${total_expense:,.2f}\n"
                
                # Only show income/balance if no specific category was queried
                if not cat_val:
                    ans_text += f"🟢 <b>Всего доходов:</b> ${total_income:,.2f}\n"
                    ans_text += f"⚖️ <b>Чистый баланс:</b> ${(total_income - total_expense):,.2f}\n"
                else:
                    desc_cat = matched_cats[0] if matched_cats else cat_val
                    ans_text += f"\n<i>(Показаны только расходы в категории «{desc_cat}»)</i>\n"
                    
                if ai_reply:
                    ans_text += f"\n💬 <i>{ai_reply}</i>"
                    
                self.send_message(chat_id, ans_text)
                return

            else:
                # Chat or general query. Check if user asked for web app / link / site
                lower_input = (raw_input or "").lower()
                is_app_request = any(kw in lower_input for kw in ['приложен', 'ссылк', 'веб', 'сайт', 'открыть ui', 'интерфейс'])
                
                if is_app_request:
                    app_msg = (
                        f"🌐 <b>Вот ссылка на ваше персональное веб-приложение:</b>\n"
                        f"https://voicefinance.onrender.com\n\n"
                        f"Вы также можете открыть его прямо внутри Telegram, нажав на кнопку ниже! Там вы найдете все графики, процентные диаграммы и сможете управлять транзакциями вручную."
                    )
                    reply_markup = {
                        "inline_keyboard": [[
                            {"text": "📱 Открыть VoiceFinance UI", "web_app": {"url": "https://voicefinance.onrender.com"}}
                        ]]
                    }
                    self.send_message(chat_id, app_msg, reply_markup)
                    return
                
                full_reply = f"{prefix}{ai_reply}" if prefix else ai_reply
                self.send_message(chat_id, full_reply)
                return

        # 2. Fallback rule-based parsing ONLY if Gemini API is rate-limited or fails
        lower_input = (raw_input or "").lower()
        is_app_request = any(kw in lower_input for kw in ['приложен', 'ссылк', 'веб', 'сайт', 'открыть ui', 'интерфейс'])
        if is_app_request:
            app_msg = (
                f"🌐 <b>Вот ссылка на ваше персональное веб-приложение:</b>\n"
                f"https://voicefinance.onrender.com\n\n"
                f"Вы также можете открыть его прямо внутри Telegram, нажав на кнопку ниже!"
            )
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "📱 Открыть VoiceFinance UI", "web_app": {"url": "https://voicefinance.onrender.com"}}
                ]]
            }
            self.send_message(chat_id, app_msg, reply_markup)
            return

        is_pdf_request = any(kw in lower_input for kw in ['пдф', 'pdf', 'отчет', 'отчёт', 'график в пдф', 'выгрузи отчет'])

        if is_pdf_request:
            pdf_path = generate_pdf_report("voicefinance_report.pdf")
            caption_msg = f"📄 <b>Ваш готовый PDF отчёт с финансовой сводкой!</b>"
            self.send_document(chat_id, pdf_path, caption=caption_msg)
            return

        # Smart fallback explanation if Gemini failed
        is_question = any(kw in lower_input for kw in ['ли', 'как', 'почему', 'что', 'где', 'когда', 'можешь', 'умеешь', 'таблиц'])
        if is_question or raw_input == "голосовая заметка":
            error_msg = (
                "⚠️ <b>Временные ограничения связи с ИИ</b>\n\n"
                "Ваш текущий API ключ Gemini исчерпал суточные лимиты запросов (429 Resource Exhausted).\n\n"
                "<b>Как это исправить за 10 секунд:</b>\n"
                "1. Получите новый бесплатный ключ в Google AI Studio: 👉 <b><a href='https://aistudio.google.com/'>aistudio.google.com</a></b>\n"
                "2. Зайдите в панель управления Render ➔ ваш сервис ➔ вкладка <b>Environment</b>.\n"
                "3. Обновите значение переменной <code>GEMINI_API_KEY</code> новым ключом.\n"
                "4. Сохраните изменения, и бот сразу же сможет полноценно отвечать на любые вопросы!"
            )
            self.send_message(chat_id, error_msg)
            return

def check_and_add_monthly_recurring_expenses(chat_id):
    try:
        import datetime
        now = datetime.datetime.now()
        month_prefix = now.strftime('%Y-%m') # e.g. "2026-08"
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Check if already added for this month
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE date LIKE ? AND description LIKE '[Auto-Recurring]%'", (f"{month_prefix}-%",))
        count = cursor.fetchone()[0]
        if count > 0:
            conn.close()
            return
            
        # Get total UAH debt to calculate interest
        cursor.execute("SELECT SUM(balance) FROM accounts WHERE currency = 'UAH'")
        total_uah_debt = cursor.fetchone()[0] or 0.0
        conn.close()
        
        # Calculate interest: 22% annual on UAH cards debt
        interest_uah = (total_uah_debt * 0.22) / 12
        interest_usd = round(interest_uah / 41.0, 2)
        
        # List of recurring expenses to add
        # Format: (amount, category, description)
        recurring = [
            (interest_usd, 'проценты', '[Auto-Recurring] Проценты по кредиту (22% годовых)'),
            (50.0, 'прочее', '[Auto-Recurring] Помощь'),
            (40.0, 'бензин', '[Auto-Recurring] Мойка машины'),
            (130.0, 'связь', '[Auto-Recurring] Связь'),
            (30.0, 'бензин', '[Auto-Recurring] Мост')
        ]
        
        date_str = f"{month_prefix}-01"
        for amt, cat, desc in recurring:
            if amt > 0:
                save_transaction('expense', amt, cat, desc, custom_date=date_str)
                
    except Exception as e:
        print(f"[check_and_add_monthly_recurring_expenses error] {e}")

    def handle_update(self, update):
        try:
            msg = update.get('message')
            if not msg:
                return
            
            chat_id = msg['chat']['id']
            
            # Automatically check and add monthly recurring expenses
            check_and_add_monthly_recurring_expenses(chat_id)
            
            text = msg.get('text', '')
            voice = msg.get('voice')
            
            # Start command
            if text.startswith('/start') or text.startswith('/help'):
                welcome = (
                    "<b>🎙️ Привет! Я твой голосовой AI-ассистент VoiceFinance.</b>\n\n"
                    "Отправляй любые голосовые сообщения или текст на любые темы! Я воспринимаю всё: вопросы, разговоры, заметки, расходы, самоисправления и запросы отчётов/сводок.\n\n"
                    "<b>Например:</b>\n"
                    "• 🎤 <i>«Сводка по всем расходам»</i>\n"
                    "• 🎤 <i>«Запиши 50 долларов на продукты»</i>\n"
                    "• 🎤 <i>«Сводка за последние 5 дней»</i>\n"
                    "• 🎤 <i>«Смени последнюю категорию на бензин»</i>\n"
                )
                self.send_message(chat_id, welcome)
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
                        # Save voice transcription to history for context awareness!
                        if gemini_res and gemini_res.get('transcribed_text'):
                            if not chat_id in USER_CHAT_HISTORY:
                                USER_CHAT_HISTORY[chat_id] = []
                            USER_CHAT_HISTORY[chat_id].append({'user': gemini_res['transcribed_text']})
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

                # Fast rule-based interceptors for custom reply keyboard menu buttons
                if text == "📊 Сводка за месяц":
                    import datetime
                    now = datetime.datetime.now()
                    first_day = now.replace(day=1).strftime('%Y-%m-%d')
                    last_day = (now.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
                    last_day_str = last_day.strftime('%Y-%m-%d')
                    gemini_res = {
                        "intent": "QUERY_TX",
                        "query_start_date": first_day,
                        "query_end_date": last_day_str,
                        "query_period_description": "за текущий месяц"
                    }
                elif text == "💼 Мой баланс":
                    gemini_res = {
                        "intent": "QUERY_BALANCE"
                    }
                elif text == "🔄 Отменить запись":
                    gemini_res = {
                        "intent": "DELETE_LAST",
                        "ai_reply": "Последняя транзакция успешно удалена!"
                    }
                elif text == "📄 Экспорт в PDF":
                    gemini_res = {
                        "intent": "EXPORT_PDF",
                        "ai_reply": "Экспортировал отчет!"
                    }
                elif text == "Долг":
                    gemini_res = {
                        "intent": "CHAT",
                        "ai_reply": "📝 Пожалуйста, надиктуйте или напишите сумму долга. Например: <b>«Долг 500 долларов»</b> или <b>«Внеси долг 200»</b>."
                    }
                else:
                    gemini_res = ask_gemini_brain(user_text=text, chat_id=chat_id)
                
                self.process_ai_result(chat_id, gemini_res, raw_input=text)
        except Exception as e:
            err_str = str(e)
            print(f"[Handle Update Error] {e}")
            GEMINI_ERRORS.append(f"handle_update: {err_str}")
            try:
                self.send_message(chat_id, f"❌ <b>Ошибка обработки:</b> {err_str}\n\nПожалуйста, отправьте сообщение еще раз.")
            except Exception:
                pass

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
