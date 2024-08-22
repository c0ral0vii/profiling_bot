from aiogram.fsm.state import StatesGroup, State


class AuthUser(StatesGroup):
    user = State()
    password = State()


class Auth(StatesGroup):
    auth = State()