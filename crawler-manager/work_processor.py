import json
import logging
import os
import redis_connect
import requests
import time

import helpers


class SimpleValidator:
    def __init__(self, action=True):
        self.action = action
    
    def allowed(self, url, agent):
        return self.action


class Processor():
    def __init__(self, context, robots_txt_fetcher):
        self.context = context
        self.robots_txt_fetcher = robots_txt_fetcher
        self.robot_validators = {}

    def run(self):
        self.context.logger.info('Waiting for crawlers...')
        while self.context.crawlers.size() == 0:
            time.sleep(10)
        
        self.context.logger.info('Entering processor loop')
        while self.context.queued_urls.size() > 0 or self.context.in_process_urls.size() > 0:
            self.context.logger.info('%d urls queued, %d in process',
                                     self.context.queued_urls.size(), self.context.in_process_urls.size())
            self.context.logger.info('Entered processor loop')
            crawlers = self.context.crawlers.get()
            self.context.logger.info('Iterating through crawlers: %s', str(crawlers))
            for crawler in crawlers:
                (url_count, url) = self.context.queued_urls.poll()
                self.context.logger.info('Pulled %s from queue', url)
                self.context.logger.info('It has a count of %s', url_count)
                # If no urls's in queue
                if url is None:
                    break
                
                # add a robot validator for the domain if necessary
                domain = helpers.get_domain_name(url)
                root = helpers.get_root_url(url)
                if domain not in self.robot_validators:
                    try:
                        self.robot_validators[domain] = self.robots_txt_fetcher.fetch(
                            os.path.join(root, 'robots.txt'))
                    except:
                        self.robot_validators[domain] = SimpleValidator()
                
                # If this url is disallowed, then skip it
                if not self.robot_validators[domain].allowed(url, 'Googlebot'):
                    self.context.logger.info('Skipping %s because disallowed by robots.txt', url)
                    continue
                
                crawl_api = os.path.join(crawler, "crawl")
                try:
                    self.context.logger.info("Sending crawl request for %s to %s", url, crawler)
                    response = requests.post(crawl_api, json={'url': url})
                    response.raise_for_status()
                except Exception as e:
                    self.context.logger.error('Unable to send crawl request to crawler %s: %s', crawler, str(e))
                else:
                    if json.loads(response.text)['accepted']:
                        self.context.logger.info('Crawler %s accepted request', crawler)
                        self.context.in_process_urls.add(url)
                    else:
                        self.context.logger.warning('Crawler %s rejected request', crawler)
                        self.context.queued_urls.add(url, count=url_count)
            
            # TODO: eliminate this. This is completely arbitrary
            sleep_time = 0.1
            self.context.logger.info('Work processor sleeping %f seconds', sleep_time)
            time.sleep(sleep_time)