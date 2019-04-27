import os
import app
import uuid
import requests
import redis_connect
from crawl_web import WebScraper
from crawl_file import FileScraper
from crawl_base import BaseScraper


ALLOWABLE_EXTENSIONS = [".pdf", ".doc", ".docx", ""]

class CrawlerJob(object):
    def __init__(self, base_url):
        self.base_url = base_url
        self.s3_uri = ''
        self.links = []

    def get_extension(self):
        return list(filter(lambda x: response.self.base_url.lower().endswith(x), ALLOWABLE_EXTENSIONS))[0]

    def is_cached(self):
        app.context.logger.info('connecting to redis')
        if app.cache.exists(self.base_url):
            cache_val = app.cache.get(self.base_url)
            if cache_val != None and 's3_uri' in cache_val and 'child_urls' in cache_val:
                self.s3_uri = cache_val['s3_uri']
                self.links = cache_val['child_urls']
                return True
            else:
                return False

    def execute(self):
        url = self.base_url
        app.context.logger.info('Starting crawl thread for %s', url)     
        try:
            if self.is_cached():
                app.context.logger.info('url %s is crawled before', url)    
                return

            key = 'crawl_pages/{}'.format(str(uuid.uuid4()))
            app.context.logger.info('Generated key: %s', key)

            # scraper object is decided (FileScraper, WebScraper, BaseScraper)
            scraper = WebScraper(url, key)
            # scrape the page
            self.data = scraper.do_scrape()
            app.context.logger.info(self.data)
            # store
            self.s3_uri = scraper.store_in_gcs(self.data)
            # get child urls
            self.links = scraper.get_links(self.data)
            # put in cache
            scraper.store_in_redis(self.s3_uri, self.links)
            # callback manager
            self.send_response_to_manager()

        except Exception as e:
            app.context.logger.info("exception: {}".format(str(e)))

        app.context.active_thread_count.decrement()
    
    def send_response_to_manager(self):
        links_api = os.path.join(app.CRAWLER_MANAGER_ENDPOINT, 'links')
        app.context.logger.info('Endpoint on Crawler manager: %s', links_api)
        try:
            app.context.logger.info('Sending response back to crawler manager...')
            response = requests.post(
                                        links_api,
                                        json={'main_url':self.base_url, 
                                              's3_uri': self.s3_uri, 
                                              'child_urls': self.links}
                                    )
            response.raise_for_status()
            app.context.logger.info('Response sent successfully!')
        except Exception as e:
            app.context.logger.error("Could not connect to crawler manager: %s", str(e))