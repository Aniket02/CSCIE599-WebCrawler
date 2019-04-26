from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from main_app.models import CrawlRequest, Profile
from main_app.views import launch_crawler_manager
from main_app.views import get_google_cloud_manifest_contents
from main_app.views import JOB_ID
from main_app.views import URLS

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import BasePermission, IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework_jwt.utils import jwt_payload_handler
from django.conf import settings
from django.contrib.auth.signals import user_logged_in

from django.http import JsonResponse
from django.http import HttpRequest
from django.http import HttpResponse
from io import BytesIO
from google.cloud import storage

import requests, jwt, json, os, zipfile, time, sys

# import the logging library
import logging
logging.basicConfig(level=logging.INFO)
# Get an instance of a logger
logger = logging.getLogger(__name__)

# when the container is running in docker compose, set IMAGE_TAG = 0
# when running on Kubernetes, it is the Pipeline Id, which is used for naming the Docker images in the registry.
NAMESPACE = os.environ.get('NAMESPACE', 'default')
IMAGE_TAG = os.environ.get('IMAGE_TAG', '0')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'local')
CRAWLER_MANAGER_USER_PREFIX = 'admin'

def check_user_password(current_password, incoming_password):
    salt = current_password.split('$')[2]
    hashed_password = make_password(incoming_password, salt)


@api_view(['POST'])
@permission_classes([AllowAny, ])
def get_api_job_status(request):
    try:
        job = CrawlRequest.objects.get(pk=request.data['job_id'])
        job_info = {
            "name": job.name,
            "type": job.type,
            "domain": job.domain,
            "urls": job.urls,
            "status": job.status
        }
    except CrawlRequest.DoesNotExist:
        raise Http404("Job does not exist.")

    return JsonResponse(job_info)

@api_view(['POST'])
@permission_classes([AllowAny, ])
def authenticate_user(request):
    try:
        username = request.data['username']
        password = request.data['password']
        user = User.objects.get(username=username)
        if user:# and check_user_password(user.password, password):
            try:
                payload = jwt_payload_handler(user)
                token = jwt.encode(payload, settings.SECRET_KEY)
                user_details = {}
                user_details['name'] = "%s %s" % (user.first_name, user.last_name)
                user_details['token'] = token
                user_logged_in.send(sender=user.__class__, request=request, user=user)
                return Response(user_details, status=status.HTTP_200_OK)

            except Exception as e:
                raise e
        else:
            res = {
                'error': 'can not authenticate with the given credentials or the account has been deactivated'}
            return Response(res, status=status.HTTP_403_FORBIDDEN)
    except KeyError:
        res = {'error': 'please provide a email and a password'}
        return Response(res)

@api_view(['POST'])
@permission_classes((IsAuthenticated, ))
#@permission_classes([AllowAny, ])
def api_create_crawl(request):
    logger.info('In api new job')
    global JOB_ID
    global URLS
    username = request.data['username']
    user_obj = User.objects.get(username=username)
    crawl_request = CrawlRequest(user=user_obj)
    crawl_request.name = request.data['name']
    crawl_request.domain = request.data['domain']
    crawl_request.urls = request.data['urls']
    crawl_request.save()
    JOB_ID = crawl_request.id
    if crawl_request.urls != "":
        URLS = crawl_request.urls
    logger.info('NewJob created: %s', crawl_request.id)
    logger.info('Received urls: %s', crawl_request.urls)
    launch_crawler_manager(crawl_request, JOB_ID)
    payload = {}
    payload['jobId'] = crawl_request.id
    return Response(payload, status=status.HTTP_200_OK)


def get_google_cloud_crawl_pages(manifest):
    client = storage.Client()
    bucket = client.get_bucket(os.environ['GCS_BUCKET'])
    content = {}
    links = manifest.decode().split('\n')
    for link in links:
        logger.info('link: %s', link)
        link_arr = link.split(',')
        if (len(link_arr) <= 1):
            continue
        url = link_arr[0]
        file_location = link_arr[1]
        logger.info('url: %s, file_location: %s', url, file_location)
        file_location_arr = file_location.split('/')
        file_name = file_location_arr[-2] + "/" + file_location_arr[-1][:-1]
        logger.info('file_name: %s', file_name)
        blob = storage.Blob(file_name, bucket)
        content[url] = blob.download_as_string()
    return content

@api_view(['GET'])
@permission_classes([AllowAny, ])
def api_crawl_contents(request):
    jobId = request.query_params.get('JOB_ID')
    content = ""
    payload = {}
    complete_crawl = request.query_params.get('complete_crawl')
    job = CrawlRequest.objects.get(pk=jobId)
    manifest = job.s3_location.split('/')[-1]
    payload['jobId'] = jobId
    if complete_crawl == "1":
        content = get_google_cloud_crawl_pages(content)
    else:
        try:
            content = get_google_cloud_manifest_contents(manifest)
        except Exception as e:
            logger.info('Unable to read manifest contents: %s', str(e))
            content = 'Unable to read manifest contents'
    payload['crawl_contents'] = content
    return Response(payload, status=status.HTTP_200_OK)