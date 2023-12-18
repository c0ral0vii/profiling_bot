import aiohttp
import os
import time

from selenium import webdriver
from webdriver_manager.chrome import ChromeDriver
from selenium.webdriver.chromium.service import Service
from bs4 import BeautifulSoup
from config.config import generate_path
from .files import delete_imgs, unzip_imgs, rename_imgs


def download_photos(url: str, user: int) -> bool:
    '''Скачивание zip архива с фотографиями'''

    chrome_options = webdriver.ChromeOptions()

    prefs = {
        'prefs': {
            'download.default_directory': f'{os.getcwd()}/generate_map/{user}/temp/imgs/',
        }
    }

    chrome_options.add_experimental_option('prefs', prefs)
    chrome_options.headless = True
    service = Service(executable_path=ChromeDriver().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)

        time.sleep(5)

        download_click = driver.find_element('xpath', '//a[@class="head_download__button"]').click()
        time.sleep(0.5)
        download_zip = driver.find_element('xpath', '//a[@id="head_download_zip_button"]').click()

        time.sleep(12)
        
    except Exception as ex:
        print(ex)
    finally:
        driver.close()
        driver.quit()
        return True


async def get_page(url: str):
    '''Получение страницы, функция чтобы избежать DRY'''

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                page = await response.text()

    return page


async def get_imgs(url: str, user: str):
    '''Получение фотографий с файлообменника'''

    delete_imgs(user=user)
    try:
        page = await get_page(url=url)

        soup = BeautifulSoup(page, 'lxml')
    except Exception as ex:
        print(ex)
        return

    if url.find('files.fm'):
        # files.fm
        download = download_photos(url=url, user=user)

        if not download:
            return 'Ошибка с селениумом'

        unzip = unzip_imgs(user=user)
        
        all_links = soup.find_all()
            
    if url.find('postimg.cc'):
        # postimg
        img_links = soup.find_all('a', class_='img')

        
        for text in img_links:

            link = text.get('href')

            # Получение ссылки для скачивания
            img_page = await get_page(url=link)
            img_soup = BeautifulSoup(img_page, 'lxml')
            tag = img_soup.find('a', id='download')

            img = img_soup.find('img', id='main-image')
            img_link = img.get('src').replace('/', "'")

            finally_link = tag.get('href')

            await postimg_download_image(img_url=finally_link, name=img_link, user=user)



async def postimg_download_image(img_url: str, name: str, user: str):
    '''Загрузка фотографий с postimg в папку temp'''

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url) as resp:
                img_data = await resp.read()

    except Exception as e:
        print(f"An error occurred: {e}")
    
    filename = name
    imgs_dir = generate_path(user=user)
    file_path = os.path.join(imgs_dir, filename)

    with open(file_path, 'wb') as img:
        img.write(img_data)
    
    return