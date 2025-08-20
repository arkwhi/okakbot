import telebot as C,logging as A
from config import TOKEN
from handlers import register_handlers as D
from extra_handlers import register_extra_handlers as F
A.basicConfig(level=A.INFO,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',handlers=[A.FileHandler('bot.log'),A.StreamHandler()])
B=A.getLogger(__name__)
def E():
	try:A=C.TeleBot(TOKEN);D(A);F(A);commands = [
    types.BotCommand("start", "Начать работу с ботом"),
    types.BotCommand("help", "Если вам нужна помощь"),
    types.BotCommand("set_spok", "Сделать своё сообщение спокойной ночи"),
    types.BotCommand("spok", "Отправить своё сообщение спокойной(?) ночи"),
    types.BotCommand("hello", "Сказать привет Окаку"),
    types.BotCommand("bye", "Попрощаться ему("),
    types.BotCommand("ogo", "Прикол"),
    types.BotCommand("id", "Показать свой Telegram ID"),
    types.BotCommand("whoami", "Информация о пользователе"),
    types.BotCommand("quote", "Показать сохранённую цитату"),
    types.BotCommand("set_quote", "Сохранить свою цитату"),
]
A.set_my_commands(commands);B.info('Бот запускается...');A.remove_webhook();A.polling(none_stop=True,interval=0)
	except Exception as E:B.error(f"Ошибка при запуске бота: {E}")
if __name__=='__main__':E()
