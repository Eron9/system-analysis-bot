import os
import json
import logging
from aiogram import Bot, Dispatcher, types, executor

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

with open("questions.json", "r", encoding="utf-8") as f:
    questions = json.load(f)

user_scores = {}

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    await message.answer("Привет! Я бот по системному анализу. Каждый день я буду присылать тебе 3 вопроса.
Готов начать? Напиши /quiz")

@dp.message_handler(commands=["quiz"])
async def quiz_handler(message: types.Message):
    user_id = str(message.from_user.id)
    user_scores.setdefault(user_id, 0)
    
    for q in questions:
        keyboard = types.InlineKeyboardMarkup()
        for i, option in enumerate(q["options"]):
            callback_data = f"{q['id']}:{i}"
            keyboard.add(types.InlineKeyboardButton(option, callback_data=callback_data))
        await message.answer(q["question"], reply_markup=keyboard)

@dp.callback_query_handler(lambda c: True)
async def process_answer(callback_query: types.CallbackQuery):
    question_id, selected = callback_query.data.split(":")
    question = next((q for q in questions if q["id"] == question_id), None)
    correct = question["answer"]

    user_id = str(callback_query.from_user.id)
    if int(selected) == correct:
        user_scores[user_id] += 1
        text = "✅ Верно!"
    else:
        text = f"❌ Неверно. Правильный ответ: {question['options'][correct]}"
    
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, text)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    executor.start_polling(dp, skip_updates=True)
