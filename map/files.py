import os

from config.config import imgs_dir


async def check_files() -> list:
    '''Получение всех фотографий из temp'''

    all_imgs = []

    for file in os.listdir(imgs_dir):
        all_imgs.append(os.path.join(imgs_dir, file))
    
    return all_imgs


async def delete_imgs() -> None:
    '''Удаление фотографий из папки temp'''

    for file in os.listdir(imgs_dir):
        os.remove(os.path.join(imgs_dir, file))