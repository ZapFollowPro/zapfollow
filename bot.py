import telebot
import os
import sqlite3
import time
import threading
from datetime import datetime, timedelta

TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    premium INTEGER DEFAULT 0,
    reminders_count INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    phone TEXT,
    name TEXT,
    due TEXT
)
""")

conn.commit()

def get_user(chat_id):
    cursor.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        return (chat_id, 0, 0)
    return user

@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.chat.id)
    bot.reply_to(msg, "🚀 ZapFollow Pro ativo!\nUse /lembrar")

@bot.message_handler(commands=['lembrar'])
def lembrar(msg):
    user = get_user(msg.chat.id)

    if user[1] == 0 and user[2] >= 5:
        bot.send_message(msg.chat.id,
            "🚫 Limite grátis atingido\n💎 Use /assinar")
        return

    try:
        parts = msg.text.split()
        phone = parts[1]
        name = parts[2]
        days = int(parts[3])

        due = datetime.now() + timedelta(days=days)

        cursor.execute(
            "INSERT INTO reminders (chat_id, phone, name, due) VALUES (?, ?, ?, ?)",
            (msg.chat.id, phone, name, due.strftime("%Y-%m-%d %H:%M"))
        )

        cursor.execute(
            "UPDATE users SET reminders_count = reminders_count + 1 WHERE chat_id=?",
            (msg.chat.id,)
        )

        conn.commit()

        bot.reply_to(msg, f"✅ Follow-up com {name} agendado!")

    except:
        bot.reply_to(msg, "❌ Use: /lembrar 551199999999 Nome 2")

@bot.message_handler(commands=['assinar'])
def assinar(msg):
    bot.send_message(msg.chat.id,
        "💎 Premium R$19,90/mês\n\nPix: SEU_PIX\nEnvie comprovante")

def check_reminders():
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("SELECT * FROM reminders WHERE due <= ?", (now,))
        rows = cursor.fetchall()

        for r in rows:
            chat_id, phone, name = r[1], r[2], r[3]

            link = f"https://wa.me/{phone}?text=Fala {name}, retomando contato."

            bot.send_message(chat_id,
                f"🔔 Hora do follow-up!\n👉 {link}")

            cursor.execute("DELETE FROM reminders WHERE id=?", (r[0],))
            conn.commit()

        time.sleep(60)

threading.Thread(target=check_reminders).start()

bot.infinity_polling()