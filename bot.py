import telebot
import os
import sqlite3
import time
import threading
from datetime import datetime, timedelta

TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# 🔒 COLOQUE SEU ID AQUI (IMPORTANTE)
ADMIN_ID = 8449316389  # <-- TROQUE PELO SEU ID

# Banco de dados
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

# Criar ou buscar usuário
def get_user(chat_id):
    cursor.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        return (chat_id, 0, 0)
    return user

# START
@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.chat.id)
    bot.reply_to(msg,
        "🚀 ZapFollow Pro\n\n"
        "Use:\n"
        "/lembrar telefone nome dias\n\n"
        "Ex: /lembrar 551199999999 João 2"
    )

# VER ID
@bot.message_handler(commands=['id'])
def id_user(msg):
    bot.reply_to(msg, f"🆔 Seu ID: {msg.chat.id}")

# LEMBRETE
@bot.message_handler(commands=['lembrar'])
def lembrar(msg):
    user = get_user(msg.chat.id)

    # Limite grátis
    if user[1] == 0 and user[2] >= 5:
        bot.send_message(msg.chat.id,
            "🚫 Limite grátis atingido\n\n"
            "💎 Libere ilimitado com /assinar")
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

        # Gatilho de venda
        bot.send_message(msg.chat.id,
            "💡 Se isso te ajudar a fechar 1 venda, já se pagou.\n"
            "Use /assinar para liberar ilimitado.")

    except:
        bot.reply_to(msg, "❌ Use: /lembrar 551199999999 Nome 2")

# ASSINAR
@bot.message_handler(commands=['assinar'])
def assinar(msg):
    bot.send_message(msg.chat.id,
        "💎 ZapFollow Premium\n\n"
        "✔ Lembretes ilimitados\n"
        "✔ Nunca mais perca vendas\n\n"
        "💰 R$19,90/mês\n\n"
        "💳 Pix: 44999648254\n\n"
        "Após pagamento, envie o comprovante.")

# LIBERAR PREMIUM (SÓ ADMIN)
@bot.message_handler(commands=['liberar'])
def liberar(msg):
    if msg.chat.id != ADMIN_ID:
        return

    try:
        parts = msg.text.split()
        user_id = int(parts[1])

        cursor.execute(
            "UPDATE users SET premium=1 WHERE chat_id=?",
            (user_id,)
        )
        conn.commit()

        bot.send_message(user_id, "💎 Premium ativado!")

        bot.reply_to(msg, "✅ Usuário liberado com sucesso!")

    except:
        bot.reply_to(msg, "❌ Use: /liberar ID_DO_USUARIO")

# CHECK DE LEMBRETES
def check_reminders():
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute("SELECT * FROM reminders WHERE due <= ?", (now,))
        rows = cursor.fetchall()

        for r in rows:
            chat_id, phone, name = r[1], r[2], r[3]

            link = f"https://wa.me/{phone}?text=Fala {name}, estou retomando nosso contato."

            bot.send_message(chat_id,
                f"🔔 Hora do follow-up!\n👉 {link}")

            cursor.execute("DELETE FROM reminders WHERE id=?", (r[0],))
            conn.commit()

        time.sleep(60)

threading.Thread(target=check_reminders).start()

print("🚀 Bot rodando...")
bot.infinity_polling()