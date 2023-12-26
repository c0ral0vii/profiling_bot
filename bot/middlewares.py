from aiogram import BaseMiddleware
from aiogram.types import Message


class ValidAccounts(BaseMiddleware):
    def __init__(self, allowed_users: list | int, message: Message) -> None:
        self.allowed_users = allowed_users
        self.message = message

    async def on_pre_process_message(self):
        if self.message.from_user.id not in self.allowed_users:
            await self.message.answer(f'У вас нет доступа для использования бота')
            return