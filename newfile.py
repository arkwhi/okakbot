import telebot

# вставь сюда свой токен от BotFather
TOKEN = "8381916674:AAF35FVmUDtRhUsSZCxmDxfPUJMGTPe02t8"

bot = telebot.TeleBot(TOKEN)

# реакция на команду /start
@bot.message_handler(commands=['ogo'])
def start_message(message):
    bot.send_message(message.chat.id, "Привет!")
    
@bot.message_handler(func=lambda message: message.text and message.text.lower() == "окак")
def reply_to_okak(message):
    bot.reply_to(message, f"@{message.from_user.username} тру окак фан")
    
@bot.message_handler(commands=['hello'])
def hello_user(message):
    bot.reply_to(message, f"Привет, {message.from_user.first_name}!")
    
@bot.message_handler(commands=['bye'])
def hello_user(message):
    bot.reply_to(message, f"Пока, {message.from_user.first_name}:(")

# запуск бота
bot.remove_webhook()
bot.polling()