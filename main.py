import os
import time
import logging
from flask import Flask, request, abort
import telebot

TOKEN = os.environ.get("BOT_TOKEN", "8303813448:AAFNgDIB7wrBDmq8ls0If_T1TnwzQqYr5q4")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://soodajiye-bot.onrender.com")
MEDIA_TO_TEXT_BOT = "https://t.me/MediaToTextBot"

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route("/", methods=["GET", "POST", "HEAD"])
def webhook():
    if request.method in ("GET", "HEAD"):
        return "OK", 200
    if request.method == "POST":
        ct = request.headers.get("Content-Type", "")
        if ct and ct.startswith("application/json"):
            update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
            bot.process_new_updates([update])
            return "", 200
    return abort(403)

@app.route("/set_webhook", methods=["GET", "POST"])
def set_webhook_route():
    try:
        bot.set_webhook(url=WEBHOOK_URL)
        return f"Webhook set to {WEBHOOK_URL}", 200
    except Exception as e:
        logging.error(f"Failed to set webhook: {e}")
        return f"Failed to set webhook: {e}", 500

@app.route("/delete_webhook", methods=["GET", "POST"])
def delete_webhook_route():
    try:
        bot.delete_webhook()
        return "Webhook deleted.", 200
    except Exception as e:
        logging.error(f"Failed to delete webhook: {e}")
        return f"Failed to delete webhook: {e}", 500

def set_webhook_on_startup():
    try:
        bot.delete_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Main bot webhook set successfully to {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"Failed to set main bot webhook on startup: {e}")

@bot.message_handler(content_types=["text", "photo", "audio", "voice", "video", "sticker", "document", "animation"])
def handle_all_messages(message):
    reply = (
        f"[use our new bot]({MEDIA_TO_TEXT_BOT})\n"
        f"[👇🏻👇🏻👇🏻👇🏻👇🏻👇🏻👇🏻]({MEDIA_TO_TEXT_BOT})"
    )
    
    bot.reply_to(message, reply, parse_mode="Markdown")

def set_bot_info_and_startup():
    set_webhook_on_startup()

if __name__ == "__main__":
    set_bot_info_and_startup()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
