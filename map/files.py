import os


def create_new_user(user: int):
    """Создание папки для пользователя"""

    try:
        os.mkdir(f"map/generate_map/{user}")
    except Exception as ex:
        return
