import telebot
import os

TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "🚀 ZapFollow Pro ativo!\nUse /lembrar")

@bot.message_handler(commands=['lembrar'])
def lembrar(msg):
    bot.reply_to(msg, "🔥 Lembrete criado (versão inicial)")

print("Bot rodando...")
bot.infinity_polling()
