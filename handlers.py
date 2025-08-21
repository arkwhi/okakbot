_A='spok'
import telebot,logging
from database import Database
db=Database()
def register_user(message):user=message.from_user;db.add_user(user_id=user.id,username=user.username,first_name=user.first_name,last_name=user.last_name)
def start_handler(bot,message):register_user(message);bot.send_message(message.chat.id,f"""Привет, {message.from_user.first_name}! 🤖

Доступные команды:
📋 /help - показать все команды""")
def help_handler(bot,message):
	help_text="😳Ну вот, все команды бота: \n\n 🍎/help - Показать все команды \n🪙/bomj - Бомжуй и получай деньги! \n🤵/pocket - Возьми с собой чуть-чуть денег, и попробуй своровать с карманов чужаков. \n🎰/casino - Самое жестокое испытание каждого человека \n😵‍💫/loto - До последних денег покупай билеты, ведь ты выиграешь! \n🪤/balance - Посмотри в свою шляпу, бомж \n💰/topbubl - Посмотри топ богачей. \n🪩Дать <@ник> <количество> - Подари денег кому-нибудь \n🛖🏢/buy_hut и /buy_communal - Покупай недвижку за 20к и 95к чтобы открыть новые работы. \n 🥷🧽/mafia и /clean - Работы по недвижимости \n🌚/whoami, /id, /osebe - Кто ты? Твой айди. О тебе \n🌝Окак ник <ник> - Поставь себе ник!\n\n💖Ждите новых Окак обновлений!\n ";bot.send_message(message.chat.id,help_text)
def set_spok_handler(bot,message):
	register_user(message);command_text=message.text.split('/set_spok',1)
	if len(command_text)>1 and command_text[1].strip():
		spok_message=command_text[1].strip()
		if db.save_personal_message(message.from_user.id,_A,spok_message):bot.reply_to(message,f"✅ Ваше пожелание спокойной ночи сохранено!\n\n💬 Текст: {spok_message}\n\nТеперь используйте /spok чтобы отправить его!")
		else:bot.reply_to(message,'❌ Произошла ошибка при сохранении сообщения.')
	else:bot.reply_to(message,'❗ Пожалуйста, укажите текст сообщения после команды.\n\nПример: /set_spok Спокойной ночи, сладких снов! 🌙✨')
def spok_handler(bot,message):
	register_user(message);spok_message=db.get_personal_message(message.from_user.id,_A)
	if spok_message:
		if message.reply_to_message and message.reply_to_message.from_user.username:response_text=f"@{message.from_user.username}", f"говорит всем (или не всем): 🌙 {spok_message}"
		else:response_text=f"🌙 {spok_message}"
		bot.reply_to(message,response_text)
	else:bot.reply_to(message,'❗ У вас нет сохранённого пожелания спокойной ночи!\n\nИспользуйте /set_spok [текст] чтобы сохранить своё пожелание.')
def hello_handler(bot,message):register_user(message);bot.reply_to(message,f"Привет, {message.from_user.first_name}! 👋")
def bye_handler(bot,message):register_user(message);bot.reply_to(message,f"Пока, {message.from_user.first_name}! 😢")
def okak_handler(bot,message):register_user(message);bot.reply_to(message,f"@{message.from_user.username} тру окак фан 🔥")
def ogo_handler(bot,message):register_user(message);bot.send_message(message.chat.id,'Привет! 🎉')
def register_handlers(bot):
	@bot.message_handler(commands=['start'])
	def handle_start(message):start_handler(bot,message)
	@bot.message_handler(commands=['help'])
	def handle_help(message):help_handler(bot,message)
	@bot.message_handler(commands=['set_spok'])
	def handle_set_spok(message):set_spok_handler(bot,message)
	@bot.message_handler(commands=[_A])
	def handle_spok(message):spok_handler(bot,message)
	@bot.message_handler(commands=['hello'])
	def handle_hello(message):hello_handler(bot,message)
	@bot.message_handler(commands=['bye'])
	def handle_bye(message):bye_handler(bot,message)
	@bot.message_handler(commands=['ogo'])
	def handle_ogo(message):ogo_handler(bot,message)
	@bot.message_handler(func=lambda message:message.text and message.text.lower()=='окак')
	def handle_okak(message):okak_handler(bot,message)
