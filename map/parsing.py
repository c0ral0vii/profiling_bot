import aiohttp

from bs4 import BeautifulSoup


async def get_page(url: str):
    '''Получение страницы'''

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                page = await response.text()

    return page


async def get_imgs(url: str, user: str):
    '''Получение фотографий с файлообменника'''

    try:
        page = await get_page(url=url)
        soup = BeautifulSoup(page, 'lxml')

    except Exception as ex:
        print(f'Ошибка: {ex}')
        return

    img_urls = []

    if url.find('files.fm'):
        img_names = soup.find_all('div', class_='image-item')

        for img_name in img_names:
            finally_link = f'https://files.fm/thumb_show.php?i={img_name.get("file_hash")}'
            img_urls.append(finally_link)

        return img_urls

    if url.find('postimg.cc'):
        # postimg
        img_links = soup.find_all('a', class_='img')

        for text in img_links:

            img_page = await get_page(url=text.get('href'))
            img_soup = BeautifulSoup(img_page, 'lxml')

            finally_link = img_soup.find('img', class_='zoom').get('src')
            img_urls.append(finally_link)

        return img_urls