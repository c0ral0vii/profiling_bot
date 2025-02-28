import aiofiles
from config.config import PASSWORD


async def check_password(password: str, user: int) -> str:
    if PASSWORD == password:
        return True
    return False


async def auth_user(user: int):
    with aiofiles.open("users.txt", "a") as f:
        await f.write(user)


async def check_auth(user: int):
    with aiofiles.open("users.txt", "r") as f:
        all_users = await f.read()
        if user in all_users:
            return True
        return False
