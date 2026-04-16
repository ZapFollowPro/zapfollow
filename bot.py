import telebot
import os
import sqlite3
import time
import threading
import urllib.parse  # Para tratar o link do WhatsApp
from datetime import datetime, timedelta

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN não encontrado nas variáveis de ambiente!")

bot = telebot.TeleBot(TOKEN)
ADMIN_ID = 8449316389  

# --- BANCO DE DADOS (Dica: No Railway, use volumes ou PostgreSQL) ---
def get_db_connection():
    conn = sqlite3.connect("bot.db", check_same_thread=False)
    return conn

conn = get_db_connection()
cursor = conn.cursor()

# Tabelas com suporte a texto de mensagem personalizado
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    premium INTEGER DEFAULT 0,
    reminders_count INTEGER DEFAULT 0,
    join_date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    phone TEXT,
    name TEXT,
    due TEXT,
    custom_msg TEXT
)
""")
conn.commit()

def get_user(chat_id):
    cursor.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,))
    user = cursor.fetchone()
    if not user:
        now = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("INSERT INTO users (chat_id, join_date) VALUES (?, ?)", (chat_id, now))
        conn.commit()
        return (chat_id, 0, 0, now)
    return user

# --- COMANDOS ---

@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.chat.id)
    text = (
        "🚀 *ZapFollow Pro*\n\n"
        "Sua máquina de recuperação de vendas no WhatsApp.\n\n"
        "📌 *Como usar:*\n"
        "`/lembrar telefone Nome Dias` ou\n"
        "`/lembrar 551199999999 João 2`"
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['lembrar'])
def lembrar(msg):
    user = get_user(msg.chat.id)
    is_premium = user[1]
    count = user[2]

    if not is_premium and count >= 5:
        bot.send_message(msg.chat.id, "❌ *Limite atingido!*\n\nLibere envios ilimitados agora.", 
                         reply_markup=telebot.types.InlineKeyboardMarkup().add(
                             telebot.types.InlineKeyboardButton("💎 Virar Premium", callback_data="pay")
                         ), parse_mode="Markdown")
        return

    try:
        parts = msg.text.split(maxsplit=3)
        phone = parts[1].replace("+", "").replace("-", "") # Limpa o número
        name = parts[2]
        days = int(parts[3])
        due = datetime.now() + timedelta(days=days)

        cursor.execute(
            "INSERT INTO reminders (chat_id, phone, name, due) VALUES (?, ?, ?, ?)",
            (msg.chat.id, phone, name, due.strftime("%Y-%m-%d %H:%M"))
        )
        cursor.execute("UPDATE users SET reminders_count = reminders_count + 1 WHERE chat_id=?", (msg.chat.id,))
        conn.commit()

        bot.reply_to(msg, f"✅ *Agendado!*\n\nNo dia {due.strftime('%d/%m')}, eu te avisarei para falar com *{name}*.", parse_mode="Markdown")

    except:
        bot.reply_to(msg, "❌ *Erro no formato!*\nUse: `/lembrar 551199999999 Nome 1`", parse_mode="Markdown")

@bot.message_handler(commands=['assinar'])
def assinar(msg):
    text = (
        "💎 *ZapFollow Premium*\n\n"
        "• Lembretes ilimitados\n"
        "• Suporte prioritário\n\n"
        "💰 *Apenas R$ 19,90/mês*\n\n"
        "🔑 *Pix:* `44999648254` (Toque para copiar)\n\n"
        "Após o Pix, envie o comprovante para o suporte."
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['liberar'])
def liberar(msg):
    if msg.chat.id != ADMIN_ID: return
    try:
        user_id = int(msg.text.split()[1])
        cursor.execute("UPDATE users SET premium=1 WHERE chat_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "✨ *Sua conta foi atualizada para PREMIUM!*\nAproveite os lembretes ilimitados.", parse_mode="Markdown")
        bot.reply_to(msg, "✅ Sucesso!")
    except:
        bot.reply_to(msg, "Use: /liberar ID")

# --- MOTOR DE BUSCA (Thread) ---

def check_reminders():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("SELECT * FROM reminders WHERE due <= ?", (now,))
            rows = cursor.fetchall()

            for r in rows:
                rid, chat_id, phone, name = r[0], r[1], r[2], r[3]
                
                # Texto personalizado para o WhatsApp
                msg_whatsapp = f"Olá {name}, estou retomando nosso contato referente ao seu interesse. Como podemos prosseguir?"
                encoded_msg = urllib.parse.quote(msg_whatsapp)
                link = f"https://wa.me/{phone}?text={encoded_msg}"

                text = (
                    f"🔔 *HORA DO FOLLOW-UP!*\n\n"
                    f"👤 *Cliente:* {name}\n"
                    f"📱 *Zap:* `{phone}`\n\n"
                    f"👉 [CLIQUE AQUI PARA FALAR COM ELE]({link})"
                )
                
                bot.send_message(chat_id, text, parse_mode="Markdown", disable_web_page_preview=True)
                cursor.execute("DELETE FROM reminders WHERE id=?", (rid,))
                conn.commit()
        except Exception as e:
            print(f"Erro no loop: {e}")
        
        time.sleep(30) # Checa a cada 30 segundos

# Iniciar thread
threading.Thread(target=check_reminders, daemon=True).start()

print("🚀 Bot iniciado com sucesso!")
bot.infinity_polling()
