import os
import threading
import subprocess
import requests
import logging
import time
import zipfile
import uuid
import shutil
import wave
from flask import Flask, request, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
from vosk import Model, KaldiRecognizer

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
MODELS_DIR = os.environ.get("MODELS_DIR", "./models")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LANGS = [
("🇬🇧 English","en-US"), ("🇸🇦 العربية","ar-SA"), ("🇪🇸 Español","es-ES"), ("🇫🇷 Français","fr-FR"),
("🇷🇺 Русский","ru-RU"), ("🇩🇪 Deutsch","de-DE"), ("🇮🇹 Italiano","it-IT"), ("🇵🇹 Português","pt-PT"),
("🇳🇱 Nederlands","nl-NL"), ("🇹🇷 Türkçe","tr-TR"), ("🇸🇪 Svenska","sv-SE")
]

VOSK_MODEL_MAP = {
"en-US":"vosk-model-small-en-us-0.15",
"es-ES":"vosk-model-small-es-0.42",
"fr-FR":"vosk-model-small-fr-0.22",
"de-DE":"vosk-model-small-de-0.15",
"ru-RU":"vosk-model-small-ru-0.22",
"it-IT":"vosk-model-small-it-0.22",
"pt-PT":"vosk-model-small-pt-0.3",
"nl-NL":"vosk-model-small-nl-0.22",
"tr-TR":"vosk-model-small-tr-0.3",
"sv-SE":"vosk-model-small-sv-0.4"
}

MODEL_DOWNLOAD_BASE = "https://alphacephei.com/vosk/models/"

model_lock = threading.Lock()
loaded_model = None
loaded_model_name = None

user_mode = {}
user_transcriptions = {}
user_selected_lang = {}
pending_files = {}

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

def get_user_mode(uid):
    return user_mode.get(uid, "📄 Text File")

def download_and_extract_model(model_id):
    target_dir = os.path.join(MODELS_DIR, model_id)
    if os.path.isdir(target_dir):
        return target_dir
    zip_name = f"{model_id}.zip"
    zip_path = os.path.join(MODELS_DIR, zip_name)
    url = MODEL_DOWNLOAD_BASE + zip_name
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(MODELS_DIR)
    os.remove(zip_path)
    if os.path.isdir(target_dir):
        return target_dir
    for name in os.listdir(MODELS_DIR):
        path = os.path.join(MODELS_DIR, name)
        if os.path.isdir(path) and model_id in name:
            return path
    return target_dir

def ensure_model_for_lang(lang_code):
    global loaded_model, loaded_model_name
    model_id = VOSK_MODEL_MAP.get(lang_code)
    if not model_id:
        model_id = VOSK_MODEL_MAP.get("en-US")
    with model_lock:
        if loaded_model_name == model_id and loaded_model is not None:
            return loaded_model
        model_path = os.path.join(MODELS_DIR, model_id)
        if not os.path.isdir(model_path):
            download_and_extract_model(model_id)
        try:
            model = Model(model_path)
        except Exception:
            model = None
        loaded_model = model
        loaded_model_name = model_id
        return loaded_model

def convert_to_wav_16k_mono(src_path):
    dst_path = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4().hex}.wav")
    cmd = [
        "ffmpeg", "-i", src_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", dst_path, "-y", "-loglevel", "error"
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dst_path

def transcribe_with_vosk(wav_path, lang_code):
    model = ensure_model_for_lang(lang_code)
    if model is None:
        raise RuntimeError("Vosk model failed to load")
    wf = wave.open(wav_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(False)
    parts = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            res = rec.Result()
            try:
                j = __import__("json").loads(res)
                if j.get("text"):
                    parts.append(j["text"])
            except:
                pass
    final = rec.FinalResult()
    try:
        jf = __import__("json").loads(final)
        if jf.get("text"):
            parts.append(jf["text"])
    except:
        pass
    wf.close()
    return " ".join(parts).strip()

def build_lang_keyboard(origin):
    btns, row = [], []
    for i, (lbl, code) in enumerate(LANGS, 1):
        row.append(InlineKeyboardButton(lbl, callback_data=f"lang|{code}|{lbl}|{origin}"))
        if i % 3 == 0:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    return InlineKeyboardMarkup(btns)

def ensure_joined(message):
    if not REQUIRED_CHANNEL:
        return True
    try:
        if bot.get_chat_member(REQUIRED_CHANNEL, message.from_user.id).status in ['member', 'administrator', 'creator']:
            return True
    except:
        pass
    clean = REQUIRED_CHANNEL.replace("@", "")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Join", url=f"https://t.me/{clean}")]])
    bot.reply_to(message, "First, join my channel and come back 👍", reply_markup=kb)
    return False

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if ensure_joined(message):
        welcome_text = (
            "👋 Salaam!\n"
            "• Send voice, audio, video or document to transcribe with Vosk offline models\n\n"
            "Select the language spoken in your audio or video:"
        )
        kb = build_lang_keyboard("file")
        bot.reply_to(message, welcome_text, reply_markup=kb, parse_mode="Markdown")

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
    if not ensure_joined(call.message):
        return
    mode = call.data.split("|")[1]
    user_mode[call.from_user.id] = mode
    try:
        bot.edit_message_text(f"you choosed: {mode}", call.message.chat.id, call.message.message_id, reply_markup=None)
    except:
        pass
    bot.answer_callback_query(call.id, f"Mode set to: {mode} ☑️")

@bot.message_handler(commands=['lang'])
def lang_command(message):
    if ensure_joined(message):
        kb = build_lang_keyboard("file")
        bot.reply_to(message, "Select the language spoken in your audio or video:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('lang|'))
def lang_cb(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
    _, code, lbl, origin = call.data.split("|")
    chat_id = call.message.chat.id
    user_selected_lang[chat_id] = code
    bot.answer_callback_query(call.id, f"Language set: {lbl} ☑️")
    if origin == "file":
        pending = pending_files.pop(chat_id, None)
        if not pending:
            return
        file_path = pending.get("path")
        orig_msg = pending.get("message")
        bot.send_chat_action(chat_id, 'typing')
        try:
            wav = convert_to_wav_16k_mono(file_path)
            text = transcribe_with_vosk(wav, code)
            if not text:
                raise ValueError("Empty transcription")
            sent = send_long_text(chat_id, text, orig_msg.id, orig_msg.from_user.id)
            if sent:
                user_transcriptions.setdefault(chat_id, {})[sent.message_id] = {"text": text, "origin": orig_msg.id}
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: {e}")
        finally:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except:
                pass
            try:
                if wav and os.path.exists(wav):
                    os.remove(wav)
            except:
                pass

@bot.message_handler(content_types=['voice', 'audio', 'video', 'document'])
def handle_media(message):
    if not ensure_joined(message):
        return
    media = message.voice or message.audio or message.video or message.document
    if not media:
        return
    if getattr(media, 'file_size', 0) > MAX_UPLOAD_SIZE:
        bot.reply_to(message, f"Just send me a file less than {MAX_UPLOAD_MB}MB 😎")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    file_path = os.path.join(DOWNLOADS_DIR, f"temp_{message.id}_{media.file_unique_id}")
    try:
        file_info = bot.get_file(media.file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        with requests.get(file_url, stream=True, timeout=REQUEST_TIMEOUT) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        lang = user_selected_lang.get(message.chat.id)
        if not lang:
            pending_files[message.chat.id] = {"path": file_path, "message": message}
            kb = build_lang_keyboard("file")
            bot.reply_to(message, "Select the language spoken in your audio or video:", reply_markup=kb)
            return
        wav = convert_to_wav_16k_mono(file_path)
        text = transcribe_with_vosk(wav, lang)
        if not text:
            raise ValueError("Empty response")
        sent = send_long_text(message.chat.id, text, message.id, message.from_user.id)
        if sent:
            user_transcriptions.setdefault(message.chat.id, {})[sent.message_id] = {"text": text, "origin": message.id}
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass
    finally:
        try:
            if 'wav' in locals() and os.path.exists(wav):
                os.remove(wav)
        except:
            pass

def send_long_text(chat_id, text, reply_id, uid, action="Transcript"):
    mode = get_user_mode(uid)
    if len(text) > MAX_MESSAGE_CHUNK:
        if mode == "Split messages":
            sent = None
            for i in range(0, len(text), MAX_MESSAGE_CHUNK):
                sent = bot.send_message(chat_id, text[i:i+MAX_MESSAGE_CHUNK], reply_to_message_id=reply_id)
            return sent
        else:
            fname = os.path.join(DOWNLOADS_DIR, f"{action}_{uuid.uuid4().hex}.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(text)
            sent = bot.send_document(chat_id, open(fname, 'rb'), caption="Transcript file", reply_to_message_id=reply_id)
            os.remove(fname)
            return sent
    return bot.send_message(chat_id, text, reply_to_message_id=reply_id)

@flask_app.route("/", methods=["GET"])
def index():
    return "waxaan ku ordayaa render wali online ahay😤", 200

@flask_app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = Update.de_json(request.get_data().decode('utf-8'))
        threading.Thread(target=bot.process_new_updates, args=([update],)).start()
        return '', 200
    abort(403)

if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL)
        flask_app.run(host="0.0.0.0", port=PORT)
    else:
        print("Webhook URL not set, exiting.")
