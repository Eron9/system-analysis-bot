from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
import psycopg2
import os
import json
import logging
import random
import datetime
import asyncio

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("BOT_TOKEN не найден!")
else:
    print("BOT_TOKEN загружен успешно.")

DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Загрузка вопросов
with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

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

def update_score(user_id, score):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, score) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET score = %s',
                   (user_id, score, score))
    conn.commit()
    conn.close()

def save_answer(user_id, question_id, answer, correct):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO user_answers (user_id, question_id, answer, correct, date)
                      VALUES (%s, %s, %s, %s, %s)''',
                   (user_id, question_id, answer, correct, datetime.datetime.now()))
    conn.commit()
    conn.close()

def get_top_users():
    conn = get_db_connection()
    cursor = conn.cursor()
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

async def send_quiz_to_user(user_id):
    selected_questions = random.sample(questions, 3)
    for q in selected_questions:
        keyboard = types.InlineKeyboardMarkup()
        for i, option in enumerate(q["options"]):
            callback_data = f"{q['id']}:{i}"
            keyboard.add(types.InlineKeyboardButton(text=option, callback_data=callback_data))
        await bot.send_message(user_id, q["question"], reply_markup=keyboard)

timezone = pytz.timezone('Europe/Moscow')
scheduler = AsyncIOScheduler(timezone=timezone)

@scheduler.scheduled_job('cron', hour=9, minute=0)
async def send_daily_quiz():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    conn.close()

    for user in users:
        user_id = user[0]
        await send_quiz_to_user(user_id)

@scheduler.scheduled_job('cron', day=1, hour=0, minute=0)
async def send_top_users():
    top_users = get_top_users()
    for user in top_users:
        user_id, total_score = user
        await bot.send_message(user_id, f"Поздравляем! Вы в топ-3 за последний месяц с {total_score} баллами!")

@dp.callback_query(F.data)
async def process_answer(callback_query: types.CallbackQuery):
    question_id, selected = callback_query.data.split(":")
    question = next((q for q in questions if q["id"] == question_id), None)
    correct = question["answer"]

    user_id = str(callback_query.from_user.id)
    correct_answer = int(selected) == correct
    text = "✅ Верно!" if correct_answer else f"❌ Неверно. Правильный ответ: {question['options'][correct]}"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT score FROM users WHERE user_id = %s', (user_id,))
    result = cursor.fetchone()
    current_score = result[0] if result else 0

    if correct_answer:
        current_score += 1

    update_score(user_id, current_score)
    save_answer(user_id, question_id, selected, correct_answer)

    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, text)

@dp.message(Command("start"))
async def send_welcome(message: Message):
    await message.reply("Привет! Это новый проект, который поможет тебе проверить знания по системному анализу. Готов ли ты пройти тест? Я начну задавать вопросы!")

    # Регистрация пользователя
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, score) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING',
                   (str(message.from_user.id), 0))
    conn.commit()
    conn.close()

    await send_quiz_to_user(message.from_user.id)

async def main():
    create_db()
    await bot.delete_webhook(drop_pending_updates=True)  # <--- Эта строка отключает webhook
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
    
@dp.message()
async def ignore_all_messages(message: types.Message):
    pass  # просто игнорирует любое сообщение