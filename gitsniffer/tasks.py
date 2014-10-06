from celery import Celery
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import rethinkdb as r


app = Celery('gitsniffer_tasks', broker='redis://localhost/1')


"""
rethinkdb document format

{
    "url": "full url",
    "base": "netloc",
    "last_scraped": r.now(),
    "found_git": bool,
    "last_tested": r.now()
}
"""


def URLExists(rdb, url):
    return not r.table('urldata').filter({'url': url}).is_empty().run(rdb)


def needs_scraping(rdb, url):
    def filter_func(doc):
        now = r.now()
        prev = doc['last_scraped']
        diff = now - prev
        return doc['url'] == url and diff.hours >= 5

    return not r.table('urldata').filter(filter_func).is_empty().run(rdb)


def InsertURL(rdb, url):
    r.table('urldata').insert({
        'url': url,
        'base': urlparse(url).netloc,
        'last_scraped': r.now(),
        'found_git': False}).run(rdb)


def UpdateURL(rdb, url):
    r.table('urldata').filter({'url': url}).update({
        'last_scraped': r.now()})


@app.task
def Crawl(url, db_info):
    rdb = r.Connection(**db_info)
    parsed_url = urlparse(url)
    resp = requests.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text)
    for item in soup.find_all('a'):
        new_url = item['href']
        new_parsed = urlparse(new_url)
        exists = URLExists(rdb, url)
        if needs_scraping(rdb, new_url) or exists:
            if new_parsed.netloc == parsed_url.netloc:
                Crawl.delay(new_url, db_info)
                Test.delay(new_url, db_info)
                if exists:
                    rdb.UpdateURL(rdb, new_url)
                else:
                    rdb.InsertURL(rdb, new_url)


@app.task
def Test(url, db_info):
    rdb = r.Connection(**db_info)
    resp = requests.get(urljoin(url, ".git/index"))
    try:
        resp.raise_for_status()
        Download.delay(url, db_info)
        r.table('urldata').filter({'url': url}).update(
            {'found_git': True, 'last_tested': r.now()}).run(rdb)
    except:
        r.table('urldata').filter({'url': url}).update(
            {'found_git': False, 'last_tested': r.now()}).run(rdb)


@app.task
def Download(url, db_info):
    pass