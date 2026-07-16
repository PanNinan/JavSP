"""从JavMenu抓取数据"""
import logging

from javsp.web.base import Request, resp2html
from javsp.web.exceptions import *
from javsp.datatype import MovieInfo


request = Request()

logger = logging.getLogger(__name__)
base_url = 'https://mrzyx.xyz'


def _info_field(info, label):
    """在 card-body 中按 label 文本定位到紧随其后的兄弟节点，返回其合并文本（未找到返回 None）"""
    spans = info.xpath(f"div/span[contains(text(), '{label}')]")
    if not spans:
        return None
    nxt = spans[0].getnext()
    if nxt is None:
        return None
    return ''.join(nxt.xpath(".//text()")).strip()


def parse_data(movie: MovieInfo):
    """从网页抓取并解析指定番号的数据
    Args:
        movie (MovieInfo): 要解析的影片信息，解析后的信息直接更新到此变量内
    """
    # JavMenu网页做得很不走心，将就了
    url = f'{base_url}/{movie.dvdid}'
    r = request.get(url)
    if r.history:
        # 被重定向到主页说明找不到影片资源
        raise MovieNotFoundError(__name__, movie.dvdid)

    html = resp2html(r)
    # 站点改版后容器 class 由 'col-md-9 px-0' 变为 'col-md-9 px-1 px-md-0'，用 contains 匹配更稳健
    container = html.xpath("//div[contains(@class, 'col-md-9')]")
    if not container:
        raise MovieNotFoundError(__name__, movie.dvdid)
    container = container[0]
    title_tag = container.xpath("//h1[@class='display-5']/strong/text()")
    if not title_tag:
        raise MovieNotFoundError(__name__, movie.dvdid)
    # 标题里竟然还插广告，真的疯了。要不是我已经写了抓取器，才懒得维护这个破站
    title = title_tag[0]
    for ad in ['  | JAV目錄大全 | 每日更新', ' 免費在線看', ' 免費AV在線看',
               '| JAV目錄大全 | 每日更新', '免費在線看', '免費AV在線看']:
        title = title.replace(ad, '')
    # 封面：改版后 single-video 内由 <video> 变成了 <img>（data-poster 失效），直接取 img 的 src
    cover_tag = container.xpath("//div[@class='single-video']")
    cover = ''
    if cover_tag:
        img = cover_tag[0].xpath(".//img/@src")
        if img:
            cover = img[0].strip()
    if not cover:
        cover_img_tag = container.xpath("//img[@class='lazy rounded']/@data-src")
        if cover_img_tag:
            cover = cover_img_tag[0].strip()
    info = container.xpath("//div[@class='card-body']")
    if not info:
        raise MovieNotFoundError(__name__, movie.dvdid)
    info = info[0]
    # 信息区字段改为“标签 + 兄弟节点”结构（發佈於/時長/製作/女優/類別）
    publish_date = _info_field(info, '發佈於')
    duration = _info_field(info, '時長')
    if duration:
        duration = duration.replace('分鐘', '').strip()
    producer = _info_field(info, '製作')
    genre_tags = info.xpath("//a[@class='genre']")
    genre, genre_id = [], []
    for tag in genre_tags:
        items = tag.get('href').split('/')
        pre_id = items[-3] + '/' + items[-1]
        genre.append(tag.text.strip())
        genre_id.append(pre_id)
        # genre的链接中含有censored字段，但是无法用来判断影片是否有码，因为完全不可靠……
    actress = info.xpath("div/span[contains(text(), '女優:')]/following-sibling::*/a/text()") or None
    magnet_table = container.xpath("//table[contains(@class, 'magnet-table')]/tbody")
    if magnet_table:
        magnet_links = magnet_table[0].xpath("tr/td/a/@href")
        # 它的FC2数据是从JavDB抓的，JavDB更换图片服务器后它也跟上了，似乎数据更新频率还可以
        movie.magnet = [i.replace('[javdb.com]','') for i in magnet_links]
    preview_pics = container.xpath("//a[@data-fancybox='gallery']/@href")

    if (not cover) and preview_pics:
        cover = preview_pics[0]
    movie.url = url
    movie.cover = cover
    movie.title = title.replace(movie.dvdid, '').strip()
    movie.preview_pics = preview_pics
    movie.publish_date = publish_date
    movie.duration = duration
    movie.genre = genre
    movie.genre_id = genre_id
    movie.actress = actress
    if producer:
        movie.producer = producer


if __name__ == "__main__":
    import pretty_errors
    pretty_errors.configure(display_link=True)
    logger.root.handlers[1].level = logging.DEBUG

    movie = MovieInfo('FC2-718323')
    try:
        parse_data(movie)
        print(movie)
    except CrawlerError as e:
        logger.error(e, exc_info=1)
