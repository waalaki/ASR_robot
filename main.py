import os
import subprocess
import requests
from flask import Flask, request, abort
import telebot
from telebot.types import Update

BOT_TOKEN = "7188814271:AAFfuo2kc3n17fUd0hbikzdL22atM2ft3CM"
WEBHOOK_URL = "https://asr-robot-b0mm.onrender.com"
WEBHOOK_PATH = "/webhook"

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

@bot.message_handler(content_types=['voice'])
def voice_handler(message):
    file_info = bot.get_file(message.voice.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

    with requests.get(file_url, stream=True) as r:
        with open("voice.ogg", "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", "voice.ogg",
        "-ar", "16000",
        "-ac", "1",
        "voice.flac"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    url = "https://www.google.com/speech-api/v2/recognize?client=chromium&lang=en-US"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "audio/x-flac; rate=16000"
    }

    with open("voice.flac", "rb") as f:
        r = requests.post(url, headers=headers, data=f)

    bot.reply_to(message, r.text or "No text")

@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_data = request.get_data().decode("utf-8")
        update = Update.de_json(json_data)
        bot.process_new_updates([update])
        return "", 200
    abort(403)

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)
    app.run(host="0.0.0.0", port=8080)
