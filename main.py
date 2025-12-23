import os
import threading
import subprocess
import requests
import logging
import time
from flask import Flask, request, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
import wave
import json
from vosk import Model, KaldiRecognizer
import gc

BOT_TOKEN = os.environ.get("BOT_TOKEN", "7920977306:AAHhFpv2ImMsiowjpm288ebRdxAjoJZwWec")
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL_BASE", "https://asr-robot-1.onrender.com")
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
("🇬🇧 English","en-us","https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"),
("🇪🇸 Español","es","https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"),
("🇫🇷 Français","fr","https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"),
("🇩🇪 Deutsch","de","https://alphacephei.com/vosk/models/vosk-model-small-de-0.15.zip"),
("🇷🇺 Русский","ru","https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"),
("🇦🇪 العربية","ar","https://alphacephei.com/vosk/models/vosk-model-small-ar-0.4.zip"),
("🇨🇳 中文","cn","https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"),
("🇯🇵 日本語","ja","https://alphacephei.com/vosk/models/vosk-model-small-ja-0.22.zip"),
("🇵🇹 Português","pt","https://alphacephei.com/vosk/models/vosk-model-small-pt-0.22.zip"),
("🇮🇹 Italiano","it","https://alphacephei.com/vosk/models/vosk-model-small-it-0.22.zip")
]

user_mode = {}
user_transcriptions = {}
user_selected_lang = {}
pending_files = {}
vosk_models = {}
current_model = None

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
flask_app = Flask(__name__)

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

def get_user_mode(uid):
    return user_mode.get(uid, "📄 Text File")

def convert_to_wav(input_path):
    output_path = input_path + ".wav"
    subprocess.run(['ffmpeg', '-i', input_path, output_path, '-y', '-loglevel', 'error'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path

def download_model(lang_code, url):
    model_path = os.path.join(MODELS_DIR, f"vosk-model-small-{lang_code}")
    if os.path.exists(model_path):
        return model_path
    zip_path = model_path + ".zip"
    r = requests.get(url, stream=True)
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    subprocess.run(['unzip', '-o', zip_path, '-d', MODELS_DIR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(zip_path)
    return model_path

def load_vosk_model(lang_code, url):
    global current_model
    if lang_code not in vosk_models:
        if current_model:
            del current_model
            gc.collect()
        model_path = download_model(lang_code, url)
        vosk_models[lang_code] = Model(model_path, log_level=0, mmap=True)
        current_model = vosk_models[lang_code]
    return vosk_models[lang_code]

def transcribe_audio_vosk(file_path, lang_code):
    model_entry = next((l for l in LANGS if l[1]==lang_code), None)
    if not model_entry:
        return "Language model not found"
    model = load_vosk_model(lang_code, model_entry[2])
    wav_path = convert_to_wav(file_path)
    wf = wave.open(wav_path, "rb")
    rec = KaldiRecognizer(model, wf.getframerate())
    result_text = ""
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            res = json.loads(rec.Result())
            result_text += res.get("text", "") + " "
    final_res = json.loads(rec.FinalResult())
    result_text += final_res.get("text", "")
    wf.close()
    if os.path.exists(wav_path):
        os.remove(wav_path)
    return result_text.strip()

def build_lang_keyboard(origin):
    btns, row = [], []
    for i, (lbl, code, url) in enumerate(LANGS, 1):
        row.append(InlineKeyboardButton(lbl, callback_data=f"lang|{code}|{lbl}|{origin}"))
        if i % 3 == 0:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    return InlineKeyboardMarkup(btns)

def send_long_text(chat_id, text, reply_id, uid, action="Transcript"):
    mode = get_user_mode(uid)
    if len(text) > MAX_MESSAGE_CHUNK:
        if mode == "Split messages":
            sent = None
            for i in range(0, len(text), MAX_MESSAGE_CHUNK):
                sent = bot.send_message(chat_id, text[i:i+MAX_MESSAGE_CHUNK], reply_to_message_id=reply_id)
            return sent
        else:
            fname = os.path.join(DOWNLOADS_DIR, f"{action}.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(text)
            sent = bot.send_document(chat_id, open(fname, 'rb'), caption="Transcript file", reply_to_message_id=reply_id)
            os.remove(fname)
            return sent
    return bot.send_message(chat_id, text, reply_to_message_id=reply_id)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if ensure_joined(message):
        kb = build_lang_keyboard("file")
        bot.reply_to(message, "👋 Salaam!\nSend me voice/audio/video to transcribe.\nSelect the language:", reply_markup=kb, parse_mode="Markdown")

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
    pending = pending_files.pop(chat_id, None)
    if not pending:
        return
    file_path = pending.get("path")
    orig_msg = pending.get("message")
    bot.send_chat_action(chat_id, 'typing')
    try:
        text = transcribe_audio_vosk(file_path, code)
        if not text:
            raise ValueError("Empty transcription")
        sent = send_long_text(chat_id, text, orig_msg.id, orig_msg.from_user.id)
        if sent:
            user_transcriptions.setdefault(chat_id, {})[sent.message_id] = {"text": text, "origin": orig_msg.id}
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@bot.message_handler(content_types=['voice', 'audio', 'video', 'document'])
def handle_media(message):
    if not ensure_joined(message):
        return
    media = message.voice or message.audio or message.video or message.document
    if not media:
        return
    if getattr(media, 'file_size', 0) > MAX_UPLOAD_SIZE:
        bot.reply_to(message, f"Send a file less than {MAX_UPLOAD_MB}MB 🤓")
        return
    bot.send_chat_action(message.chat.id, 'typing')
    file_path = os.path.join(DOWNLOADS_DIR, f"temp_{message.id}_{media.file_unique_id}")
    try:
        file_info = bot.get_file(media.file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        with requests.get(file_url, stream=True) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        lang = user_selected_lang.get(message.chat.id)
        if not lang:
            pending_files[message.chat.id] = {"path": file_path, "message": message}
            kb = build_lang_keyboard("file")
            bot.reply_to(message, "Select language:", reply_markup=kb)
            return
        text = transcribe_audio_vosk(file_path, lang)
        if not text:
            raise ValueError("Empty response")
        sent = send_long_text(message.chat.id, text, message.id, message.from_user.id)
        if sent:
            user_transcriptions.setdefault(message.chat.id, {})[sent.message_id] = {"text": text, "origin": message.id}
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)

@flask_app.route("/", methods=["GET"])
def index():
    return "waxaan ku ordayaa render 😤", 200

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
