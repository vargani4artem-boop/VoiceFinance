import os
import shutil
import sqlite3
import urllib.request
import urllib.parse
import json
import threading
from datetime import datetime

TOKEN = "8875858432:AAEe6xbzBi82Om75WpP19AE_8J8y1LKGwqo"
DEFAULT_CHAT_ID = "408397367"
DB_FILE = os.path.join(os.path.dirname(__file__), "finance.db")

def send_request(method, payload=None, files=None):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if files:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = []
        for k, v in payload.items():
            body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
        for k, filepath in files.items():
            filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                file_bytes = f.read()
            body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
            body.append(file_bytes)
            body.append(b"\r\n")
        body.append(f"--{boundary}--\r\n".encode("utf-8"))
        req = urllib.request.Request(url, data=b"".join(body), headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'User-Agent': 'Mozilla/5.0'
        }, method='POST')
    else:
        headers = {'User-Agent': 'Mozilla/5.0'}
        data = None
        if payload:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST' if payload else 'GET')
        
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"[Persistence Telegram API Error] {method}: {e}")
        return None

def backup_db(chat_id=DEFAULT_CHAT_ID):
    if not os.path.exists(DB_FILE):
        return False
        
    backup_temp = os.path.join(os.path.dirname(__file__), "finance_backup.db")
    try:
        shutil.copyfile(DB_FILE, backup_temp)
    except Exception as e:
        print(f"[Backup Error] Failed to copy SQLite file: {e}")
        return False
        
    caption = f"📦 Auto-Backup VoiceFinance DB\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    res = send_request("sendDocument", payload={"chat_id": chat_id, "caption": caption, "disable_notification": "true"}, files={"document": backup_temp})
    
    if os.path.exists(backup_temp):
        os.remove(backup_temp)
        
    if res and res.get("ok"):
        new_msg_id = res["result"]["message_id"]
        
        # Fetch current chat info to find and delete the old pinned backup message
        chat_info = send_request("getChat", payload={"chat_id": chat_id})
        old_msg_id = None
        if chat_info and chat_info.get("ok"):
            pinned = chat_info["result"].get("pinned_message")
            if pinned:
                old_msg_id = pinned.get("message_id")
        
        # Pin the new backup
        send_request("pinChatMessage", payload={"chat_id": chat_id, "message_id": new_msg_id, "disable_notification": "true"})
        
        # Delete the old backup message if found to keep the chat clean
        if old_msg_id:
            send_request("deleteMessage", payload={"chat_id": chat_id, "message_id": old_msg_id})
            
        print(f"[Backup Success] Database pinned and old backup deleted in chat {chat_id}")
        return True
    else:
        print(f"[Backup Failed] Failed to send document to chat {chat_id}")
        return False

def async_backup(chat_id=DEFAULT_CHAT_ID):
    threading.Thread(target=backup_db, args=(chat_id,), daemon=True).start()

def restore_db(chat_id=DEFAULT_CHAT_ID):
    print(f"[Restore] Attempting to restore database from chat {chat_id}...")
    res = send_request("getChat", payload={"chat_id": chat_id})
    if not res or not res.get("ok"):
        print("[Restore Failed] Failed to fetch chat info")
        return False
        
    chat_info = res.get("result", {})
    pinned = chat_info.get("pinned_message")
    if not pinned:
        print("[Restore] No pinned message found in chat")
        return False
        
    doc = pinned.get("document")
    if not doc:
        print("[Restore] Pinned message is not a document")
        return False
        
    file_id = doc.get("file_id")
    file_res = send_request("getFile", payload={"file_id": file_id})
    if not file_res or not file_res.get("ok"):
        print("[Restore Failed] Failed to get file details")
        return False
        
    file_path = file_res["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    
    try:
        req = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            db_bytes = resp.read()
        
        with open(DB_FILE, "wb") as f:
            f.write(db_bytes)
        print(f"[Restore Success] Database successfully restored from Telegram! File size: {len(db_bytes)} bytes")
        return True
    except Exception as e:
        print(f"[Restore Failed] Failed to download or write database: {e}")
        return False
