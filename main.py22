import os
import threading
import json
import requests
import logging
import time
import tempfile
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
import speech_recognition as sr

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE", "")
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook/")
WEBHOOK_URL = WEBHOOK_URL_BASE.rstrip('/') + WEBHOOK_PATH if WEBHOOK_URL_BASE else ""
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "300"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "20"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_MB * 1024 * 1024
MAX_MESSAGE_CHUNK = 4095
REQUIRED_CHANNEL = os.environ.get("REQUIRED_CHANNEL", "")
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "./downloads")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
GEMINI_KEYS = os.environ.get("GEMINI_KEYS", GEMINI_KEY)
GEMINI_MODEL = "gemini-2.0-flash"

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LANGS = [
("🇬🇧 English","en"), ("🇸🇦 العربية","ar"), ("🇪🇸 Español","es"), ("🇫🇷 Français","fr"),
("🇷🇺 Русский","ru"), ("🇩🇪 Deutsch","de"), ("🇮🇳 हिन्दी","hi"), ("🇮🇷 فارسی","fa"),
("🇮🇩 Indonesia","id"), ("🇺🇦 Українська","uk"), ("🇦🇿 Azərbaycan","az"), ("🇮🇹 Italiano","it"),
("🇹🇷 Türkçe","tr"), ("🇧🇬 Български","bg"), ("🇷🇸 Srpski","sr"), ("🇵🇰 اردو","ur"),
("🇹🇭 ไทย","th"), ("🇻🇳 Tiếng Việt","vi"), ("🇯🇵 日本語","ja"), ("🇰🇷 한국어","ko"),
("🇨🇳 中文","zh"), ("🇳🇱 Nederlands:nl", "nl"), ("🇸🇪 Svenska","sv"), ("🇳🇴 Norsk","no"),
("🇮🇱 עברית","he"), ("🇩🇰 Dansk","da"), ("🇪🇹 አማርኛ","am"), ("🇫🇮 Suomi","fi"),
("🇧🇩 বাংলা","bn"), ("🇰🇪 Kiswahili","sw"), ("🇪🇹 Oromo","om"), ("🇳🇵 नेपाली","ne"),
("🇵🇱 Polski","pl"), ("🇬🇷 Ελληνικά","el"), ("🇨🇿 Čeština","cs"), ("🇮🇸 Íslenska","is"),
("🇱🇹 Lietuvių","lt"), ("🇱🇻 Latviešu","lv"), ("🇭🇷 Hrvatski","hr"), ("🇷🇸 Bosanski","bs"),
("🇭🇺 Magyar","hu"), ("🇷🇴 Română","ro"), ("🇸🇴 Somali","so"), ("🇲🇾 Melayu","ms"),
("🇺🇿 O'zbekcha","uz"), ("🇵🇭 Tagalog","tl"), ("🇵🇹 Português","pt")
]

user_mode = {}
user_transcriptions = {}
user_selected_lang = {}
pending_files = {}

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
flask_app = Flask(__name__)

def get_user_mode(uid):
    return user_mode.get(uid, "📄 Text File")

def gemini_api_call(endpoint, payload, key):
    url = f"https://generativelanguage.googleapis.com/v1beta/{endpoint}?key={key}"
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()

class KeyRotator:
    def __init__(self, keys):
        self.keys = [k.strip() for k in keys.split(",") if k.strip()] if isinstance(keys, str) else list(keys or [])
        self.pos = 0
        self.lock = threading.Lock()
    def get_key(self):
        with self.lock:
            if not self.keys: return None
            key = self.keys[self.pos]
            self.pos = (self.pos + 1) % len(self.keys)
            return key
    def mark_success(self, key):
        with self.lock:
            try:
                i = self.keys.index(key)
                self.pos = (i + 1) % len(self.keys)
            except ValueError: pass
    def mark_failure(self, key):
        self.mark_success(key)

gemini_rotator = KeyRotator(GEMINI_KEYS)

def execute_gemini_action(action_callback):
    last_exc = None
    total = len(gemini_rotator.keys) or 1
    for _ in range(total + 1):
        key = gemini_rotator.get_key()
        if not key: raise RuntimeError("No Gemini keys available")
        try:
            result = action_callback(key)
            gemini_rotator.mark_success(key)
            return result
        except Exception as e:
            last_exc = e
            gemini_rotator.mark_failure(key)
    raise RuntimeError(f"Gemini failed: {last_exc}")

def ask_gemini(text, instruction):
    def perform(key):
        payload = {"contents": [{"parts": [{"text": f"{instruction}\n\n{text}"}]}]}
        data = gemini_api_call(f"models/{GEMINI_MODEL}:generateContent", payload, key)
        return data["candidates"][0]["content"]["parts"][0]["text"]
    return execute_gemini_action(perform)

def build_action_keyboard(text_len):
    btns = []
    if text_len > 1000:
        btns.append([InlineKeyboardButton("Get Summarize", callback_data="summarize_menu|")])
    return InlineKeyboardMarkup(btns)

def build_lang_keyboard(origin):
    btns, row = [], []
    for i, (lbl, code) in enumerate(LANGS, 1):
        row.append(InlineKeyboardButton(lbl, callback_data=f"lang|{code}|{lbl}|{origin}"))
        if i % 3 == 0:
            btns.append(row)
            row = []
    if row: btns.append(row)
    return InlineKeyboardMarkup(btns)

def build_summarize_keyboard(origin):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Short", callback_data=f"summopt|Short|{origin}")],
        [InlineKeyboardButton("Detailed", callback_data=f"summopt|Detailed|{origin}")],
        [InlineKeyboardButton("Bulleted", callback_data=f"summopt|Bulleted|{origin}")]
    ])

def ensure_joined(message):
    if not REQUIRED_CHANNEL: return True
    try:
        status = bot.get_chat_member(REQUIRED_CHANNEL, message.from_user.id).status
        if status in ['member', 'administrator', 'creator']: return True
    except: pass
    clean = REQUIRED_CHANNEL.replace("@", "")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Join", url=f"https://t.me/{clean}")]])
    bot.reply_to(message, "First, join my channel and come back 👍", reply_markup=kb)
    return False

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if ensure_joined(message):
        welcome_text = "👋 Salaam!\n• Send me voice, audio or video to transcribe.\n\nSelect language:"
        bot.reply_to(message, welcome_text, reply_markup=build_lang_keyboard("file"), parse_mode="Markdown")

@bot.message_handler(commands=['mode'])
def choose_mode(message):
    if ensure_joined(message):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Split messages", callback_data="mode|Split messages")],
            [InlineKeyboardButton("📄 Text File", callback_data="mode|Text File")]
        ])
        bot.reply_to(message, "How do I send you long transcripts?:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('mode|'))
def mode_cb(call):
    mode = call.data.split("|")[1]
    user_mode[call.from_user.id] = mode
    bot.edit_message_text(f"Mode set to: {mode} ☑️", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('lang|'))
def lang_cb(call):
    _, code, lbl, origin = call.data.split("|")
    chat_id = call.message.chat.id
    if origin != "file":
        process_text_action(call, origin, f"Translate to {lbl}", f"Translate to {lbl}. Return ONLY translation.")
        return
    bot.delete_message(chat_id, call.message.message_id)
    user_selected_lang[chat_id] = code
    pending = pending_files.pop(chat_id, None)
    if not pending: return
    
    file_path, orig_msg = pending["path"], pending["message"]
    bot.send_chat_action(chat_id, 'typing')
    try:
        text = transcribe_file(file_path, language=code)
        sent = send_long_text(chat_id, text, orig_msg.id, orig_msg.from_user.id)
        if sent:
            user_transcriptions.setdefault(chat_id, {})[sent.message_id] = {"text": text, "origin": orig_msg.id}
            bot.edit_message_reply_markup(chat_id, sent.message_id, reply_markup=build_action_keyboard(len(text)))
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")
    finally:
        if os.path.exists(file_path): os.remove(file_path)

@bot.callback_query_handler(func=lambda c: c.data.startswith('summarize_menu|'))
def action_cb(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=build_summarize_keyboard(call.message.id))

@bot.callback_query_handler(func=lambda c: c.data.startswith('summopt|'))
def summopt_cb(call):
    _, style, origin = call.data.split("|")
    prompt = f"Summarize this as {style}. Return ONLY the summary."
    process_text_action(call, origin, f"Summarize ({style})", prompt)

def process_text_action(call, origin_msg_id, log_action, prompt_instr):
    chat_id = call.message.chat.id
    data = user_transcriptions.get(chat_id, {}).get(int(origin_msg_id))
    if not data: return
    bot.send_chat_action(chat_id, 'typing')
    try:
        res = ask_gemini(data["text"], prompt_instr)
        send_long_text(chat_id, res, data["origin"], call.from_user.id, log_action)
    except Exception as e:
        bot.send_message(chat_id, f"Error: {e}")

def get_audio_duration(file_path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
    return float(subprocess.run(cmd, stdout=subprocess.PIPE).stdout)

def process_chunk(idx, start, chunk_sec, file_path, lang, r):
    with tempfile.NamedTemporaryFile(delete=False, suffix=f'_{idx}.flac', dir=DOWNLOADS_DIR) as tf:
        tmp = tf.name
    cmd = ['ffmpeg', '-y', '-ss', str(start), '-t', str(chunk_sec), '-i', file_path, '-vn', '-ar', '12000', '-ac', '1', tmp]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    text = ""
    if os.path.exists(tmp) and os.path.getsize(tmp) > 100:
        try:
            with sr.AudioFile(tmp) as source:
                audio = r.record(source)
                text = r.recognize_google(audio, language=lang)
        except: pass
        finally: os.remove(tmp)
    return idx, text

def transcribe_file(file_path, language=None):
    r, duration, chunk_sec = sr.Recognizer(), get_audio_duration(file_path), 60
    total = int((duration + chunk_sec - 1) // chunk_sec)
    results = [None] * total
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(process_chunk, i, i*chunk_sec, chunk_sec, file_path, language, r) for i in range(total)]
        for f in futures:
            idx, txt = f.result()
            results[idx] = txt
    return " ".join([t for t in results if t])

@bot.message_handler(content_types=['voice', 'audio', 'video', 'document'])
def handle_media(message):
    if not ensure_joined(message): return
    media = message.voice or message.audio or message.video or message.document
    if not media or getattr(media, 'file_size', 0) > MAX_UPLOAD_SIZE:
        bot.reply_to(message, "File too large!")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    file_info = bot.get_file(media.file_id)
    ext = os.path.splitext(file_info.file_path)[1]
    dest = os.path.join(DOWNLOADS_DIR, f"{message.id}{ext}")
    with open(dest, 'wb') as f:
        f.write(requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}").content)
    
    lang = user_selected_lang.get(message.chat.id)
    if not lang:
        pending_files[message.chat.id] = {"path": dest, "message": message}
        bot.reply_to(message, "Select language:", reply_markup=build_lang_keyboard("file"))
        return
    
    try:
        text = transcribe_file(dest, language=lang)
        sent = send_long_text(message.chat.id, text, message.id, message.from_user.id)
        if sent:
            user_transcriptions.setdefault(message.chat.id, {})[sent.message_id] = {"text": text, "origin": message.id}
            bot.edit_message_reply_markup(message.chat.id, sent.message_id, reply_markup=build_action_keyboard(len(text)))
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
    finally:
        if os.path.exists(dest): os.remove(dest)

def send_long_text(chat_id, text, reply_id, uid, action="Transcript"):
    mode = get_user_mode(uid)
    if len(text) > MAX_MESSAGE_CHUNK:
        if mode == "Split messages":
            s = None
            for i in range(0, len(text), MAX_MESSAGE_CHUNK):
                s = bot.send_message(chat_id, text[i:i+MAX_MESSAGE_CHUNK], reply_to_message_id=reply_id)
            return s
        else:
            path = os.path.join(DOWNLOADS_DIR, f"{action}.txt")
            with open(path, "w", encoding="utf-8") as f: f.write(text)
            with open(path, 'rb') as f:
                s = bot.send_document(chat_id, f, caption="Transcript file 👍", reply_to_message_id=reply_id)
            os.remove(path)
            return s
    return bot.send_message(chat_id, text, reply_to_message_id=reply_id)

@flask_app.route("/", methods=["GET"])
def index(): return "Bot Running", 200

@flask_app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([Update.de_json(request.get_data().decode('utf-8'))])
        return '', 200
    abort(403)

if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        flask_app.run(host="0.0.0.0", port=PORT)
