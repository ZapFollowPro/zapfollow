import telebot
import os
import time
import threading
from datetime import datetime, timedelta

TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

reminders = []

@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg,
        "🚀 ZapFollow Pro\n\n"
        "Use:\n"
        "/lembrar telefone nome dias\n\n"
        "Ex: /lembrar 551199999999 João 2"
    )

@bot.message_handler(commands=['lembrar'])
def lembrar(msg):
    try:
        parts = msg.text.split()
        phone = parts[1]
        name = parts[2]
        days = int(parts[3])

        due = datetime.now() + timedelta(days=days)

        reminders.append({
            "chat_id": msg.chat.id,
            "phone": phone,
            "name": name,
            "due": due
        })

        bot.reply_to(msg, f"✅ Follow-up com {name} agendado!")

    except:
        bot.reply_to(msg, "❌ Use: /lembrar 551199999999 Nome 2")

def check_reminders():
    while True:
        now = datetime.now()

        for r in reminders[:]:
            if now >= r["due"]:
                link = f"https://wa.me/{r['phone']}?text=Fala {r['name']}, estou retomando nosso contato."

                bot.send_message(r["chat_id"],
                    f"🔔 Hora do follow-up com {r['name']}!\n👉 {link}")

                reminders.remove(r)

        time.sleep(60)

threading.Thread(target=check_reminders).start()

print("Rodando...")
bot.infinity_polling()