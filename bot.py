from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz  # импортируем pytz для работы с часовыми поясами
import psycopg2
import os
import json
import logging
import random
import datetime

# Загружаем токен бота из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # URL для подключения к PostgreSQL

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot=bot)

# Загружаем вопросы из файла
with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

# Функция для подключения к базе данных PostgreSQL
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# Функция для создания таблиц в базе данных
def create_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id TEXT PRIMARY KEY,
                        score INTEGER)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_answers (
                        user_id TEXT,
                        question_id TEXT,
                        answer INTEGER,
                        correct BOOLEAN,
                        date TIMESTAMP)''')
    conn.commit()
    conn.close()

# Функция для обновления баллов пользователя
def update_score(user_id, score):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, score) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET score = %s', 
                   (user_id, score, score))
    conn.commit()
    conn.close()

# Функция для сохранения ответа пользователя в базе данных
def save_answer(user_id, question_id, answer, correct):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO user_answers (user_id, question_id, answer, correct, date) 
                      VALUES (%s, %s, %s, %s, %s)''', 
                   (user_id, question_id, answer, correct, datetime.datetime.now()))
    conn.commit()
    conn.close()

# Функция для получения топ-3 пользователей за месяц
def get_top_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Считаем баллы за последний месяц
    one_month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
    cursor.execute('''
        SELECT user_id, SUM(CASE WHEN correct THEN 1 ELSE 0 END) AS total_score
        FROM user_answers
        WHERE date > %s
        GROUP BY user_id
        ORDER BY total_score DESC
        LIMIT 3
    ''', (one_month_ago,))
    
    top_users = cursor.fetchall()
    conn.close()
    return top_users

# Функция для отправки вопросов пользователю
async def send_quiz_to_user(user_id):
    selected_questions = random.sample(questions, 3)  # выбираем 3 случайных вопроса
    for q in selected_questions:
        keyboard = types.InlineKeyboardMarkup()
        for i, option in enumerate(q["options"]):
            callback_data = f"{q['id']}:{i}"
            keyboard.add(types.InlineKeyboardButton(option, callback_data=callback_data))
        # Отправляем вопрос без дополнительного обращения
        await bot.send_message(user_id, q["question"], reply_markup=keyboard)

# Создаём объект часового пояса
timezone = pytz.timezone('Europe/Moscow')  # Используйте нужный вам часовой пояс
scheduler = AsyncIOScheduler(timezone=timezone)

# Ежедневная задача для отправки вопросов
@scheduler.scheduled_job('cron', hour=9, minute=0)  # каждый день в 9 утра
async def send_daily_quiz():
    now = datetime.datetime.now()
    
    # Получаем список всех пользователей
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    conn.close()
    
    # Отправка вопросов всем пользователям
    for user in users:
        user_id = user[0]
        await send_quiz_to_user(user_id)

# Ежемесячная задача для вычисления топ-3 пользователей
@scheduler.scheduled_job('cron', day=1, hour=0, minute=0)  # 1-го числа каждого месяца
async def send_top_users():
    top_users = get_top_users()
    for user in top_users:
        user_id, total_score = user
        await bot.send_message(user_id, f"Поздравляем! Вы в топ-3 за последний месяц с {total_score} баллами!")

scheduler.start()

# Обработчик нажатия на кнопки с ответами
@dp.callback_query_handler(lambda c: True)
async def process_answer(callback_query: types.CallbackQuery):
    question_id, selected = callback_query.data.split(":")
    question = next((q for q in questions if q["id"] == question_id), None)
    correct = question["answer"]

    user_id = str(callback_query.from_user.id)
    correct_answer = int(selected) == correct
    text = "✅ Верно!" if correct_answer else f"❌ Неверно. Правильный ответ: {question['options'][correct]}"
    
    # Получаем текущий балл пользователя из базы данных
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT score FROM users WHERE user_id = %s', (user_id,))
    result = cursor.fetchone()
    current_score = result[0] if result else 0
    
    if correct_answer:
        current_score += 1
    
    # Обновляем баллы пользователя в базе данных
    update_score(user_id, current_score)
    
    # Сохраняем ответ в базе данных
    save_answer(user_id, question_id, selected, correct_answer)
    
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, text)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_db()  # Создаем базу данных, если еще не существует
    executor.start_polling(dp, skip_updates=True)