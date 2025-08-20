_A=False
import sqlite3,logging
from config import DATABASE_PATH
class Database:
	def __init__(self):self.db_path=DATABASE_PATH;self.init_database()
	def get_connection(self):return sqlite3.connect(self.db_path)
	def init_database(self):
		try:
			with self.get_connection()as conn:conn.execute('\n                    CREATE TABLE IF NOT EXISTS users (\n                        user_id INTEGER PRIMARY KEY,\n                        username TEXT,\n                        first_name TEXT,\n                        last_name TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                    )\n                ');conn.execute('\n                    CREATE TABLE IF NOT EXISTS personal_messages (\n                        id INTEGER PRIMARY KEY AUTOINCREMENT,\n                        user_id INTEGER,\n                        message_type TEXT,\n                        message_text TEXT,\n                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n                        FOREIGN KEY (user_id) REFERENCES users (user_id)\n                    )\n                ');conn.commit();logging.info('База данных инициализирована успешно')
		except Exception as e:logging.error(f"Ошибка при инициализации базы данных: {e}")
	def add_user(self,user_id,username,first_name,last_name):
		try:
			with self.get_connection()as conn:conn.execute('\n                    INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)\n                    VALUES (?, ?, ?, ?)\n                ',(user_id,username,first_name,last_name));conn.commit();return True
		except Exception as e:logging.error(f"Ошибка при добавлении пользователя: {e}");return _A
	def save_personal_message(self,user_id,message_type,message_text):
		try:
			with self.get_connection()as conn:conn.execute('\n                    DELETE FROM personal_messages \n                    WHERE user_id = ? AND message_type = ?\n                ',(user_id,message_type));conn.execute('\n                    INSERT INTO personal_messages (user_id, message_type, message_text)\n                    VALUES (?, ?, ?)\n                ',(user_id,message_type,message_text));conn.commit();return True
		except Exception as e:logging.error(f"Ошибка при сохранении персонального сообщения: {e}");return _A
	def get_personal_message(self,user_id,message_type):
		try:
			with self.get_connection()as conn:result=conn.execute('\n                    SELECT message_text FROM personal_messages \n                    WHERE user_id = ? AND message_type = ?\n                    ORDER BY created_at DESC LIMIT 1\n                ',(user_id,message_type)).fetchone();return result[0]if result else None
		except Exception as e:logging.error(f"Ошибка при получении персонального сообщения: {e}");return
	def user_exists(self,user_id):
		try:
			with self.get_connection()as conn:result=conn.execute('\n                    SELECT 1 FROM users WHERE user_id = ?\n                ',(user_id,)).fetchone();return result is not None
		except Exception as e:logging.error(f"Ошибка при проверке пользователя: {e}");return _A
		
#деньги
def init_database(self):
    try:
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS personal_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_type TEXT,
                    message_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            # новая таблица для валюты
            conn.execute("""
                CREATE TABLE IF NOT EXISTS balances (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            conn.commit()
            logging.info("База данных инициализирована успешно")
    except Exception as e:
        logging.error(f"Ошибка при инициализации базы данных: {e}")

def get_balance(self, user_id):
    try:
        with self.get_connection() as conn:
            result = conn.execute("SELECT balance FROM balances WHERE user_id = ?", (user_id,)).fetchone()
            return result[0] if result else 0
    except Exception as e:
        logging.error(f"Ошибка при получении баланса: {e}")
        return 0

def update_balance(self, user_id, amount):
    try:
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO balances (user_id, balance)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance
            """, (user_id, amount))
            conn.commit()
            return True
    except Exception as e:
        logging.error(f"Ошибка при обновлении баланса: {e}")
        return False