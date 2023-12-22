import os
import zipfile

from config.config import generate_path


def create_new_user(user: str):
    '''Создание папки для пользователя'''

    try:
        os.mkdir(f'map/generate_map/{user}')
        os.mkdir(f'map/generate_map/{user}/temp')
        os.mkdir(f'map/generate_map/{user}/temp/imgs')
    except Exception as ex:
        print(ex)


def check_files(user: str) -> list:
    '''Получение всех фотографий из temp'''

    all_imgs = []

    imgs_dir = generate_path(user=user)

    for file in os.listdir(imgs_dir):
        all_imgs.append(os.path.join(imgs_dir, file))
    
    return all_imgs


def delete_imgs(user: int) -> None:
    '''Удаление фотографий из папки temp'''

    imgs_dir = generate_path(user=user)

    for file in os.listdir(imgs_dir):
        os.remove(os.path.join(imgs_dir, file))


def unzip_imgs(user: int) -> bool:
    '''Распаковка изображений из zip архива'''

    zip = os.listdir(f'generate_map/{user}/temp/img')

    for zip_name in zip:
        try:
            with zipfile.ZipFile(zip_name, 'r') as f:
                f.extractall()
        except Exception as ex:
            print(ex)

    return True


async def rename_imgs(user: int, rename_to: str, rename_from: str):
    '''Переназвать фотографии в ссылку, для использования на карте'''

    os.rename(f'map/generate_map/{user}/temp/imgs/{rename_from}',
              f'map/generate_map/{user}/temp/imgs/{rename_to}')