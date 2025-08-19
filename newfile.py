import telebot as C,logging as A
from config import TOKEN
from handlers import register_handlers as D
A.basicConfig(level=A.INFO,format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',handlers=[A.FileHandler('bot.log'),A.StreamHandler()])
B=A.getLogger(__name__)
def E():
	try:A=C.TeleBot(TOKEN);D(A);B.info('Бот запускается...');A.remove_webhook();A.polling(none_stop=True,interval=0)
	except Exception as E:B.error(f"Ошибка при запуске бота: {E}")
if __name__=='__main__':E()