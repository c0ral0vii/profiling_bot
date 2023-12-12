import os

from config.config import imgs_dir


def check_files() -> list:
    '''Получение всех фотографий из temp'''

    all_imgs = []

    for file in os.listdir(imgs_dir):
        all_imgs.append(os.path.join(imgs_dir, file))
    
    return all_imgs


def delete_imgs() -> None:
    '''Удаление фотографий из папки temp'''

    for file in os.listdir(imgs_dir):
        os.remove(os.path.join(imgs_dir, file))


def create_coordinate_file(cords: dict) -> True:
    filename = 'coordinates.txt'
    map_folder = 'map/temp'
    filepath = os.path.join(map_folder, filename)

    with open(filepath, 'w') as f:
        for path, coord in cords.items():
            f.write(f'\n{coord}')


def change_img_name(ready_coords: dict) -> None:
    '''Изменение названий файлов в координаты.jpg'''
    
    for img_path, coords in ready_coords.items():
        new_name = f'{coords}.jpg'
        os.replace(img_path, os.path.join(imgs_dir, new_name))