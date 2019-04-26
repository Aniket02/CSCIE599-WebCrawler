import json
import logging
import redis
import os

logging.basicConfig(level=logging.INFO)

redis_db = redis.StrictRedis(host=os.environ.get('REDIS_HOST','crawler-redis'), port=6379, db=0)


def get(key):
    return json.loads(redis_db.get(key))


def put(key, value):
    return redis_db.set(key, json.dumps(value))


def exists(key):
    return bool(redis_db.exists(key))


def dump():
    for key in redis_db.scan_iter("*"):
        logging.info('redis value %s --- %s', key, redis_db.get(key))


def test_redis_connection():
    try:
        logging.info("Connecting to Redis: %s", os.environ.get('REDIS_HOST','crawler-redis'))
        redis_db.ping()
        return 'Connection successful (Redis)'
    except redis.ConnectionError as e:
        logging.error("Error connecting to redis: %s", str(e))