import datetime
import json

import logging
import os
import pytz
import requests

# env variables
crucible_base_url = os.getenv('crucible_base_url')
crucible_user_token = os.getenv('crucible_user_token')
slack_webhook_url = os.getenv('slack_webhook_url')
slack_token = os.getenv('slack_token')
# end variables

crucible_open_reviews_endpoint = f'{crucible_base_url}/rest-service/reviews-v1/filter/'
slack_headers = {'Content-type': 'application/json',
                 'Authorization': f'Bearer {slack_token}'}
slack_user_lookup_endpoint = 'https://slack.com/api/users.lookupByEmail'


def lambda_handler(event, context):

    logging.info('Checking due reviews from crucible.')

    # get reviews from crucible
    r = requests.get(url=crucible_open_reviews_endpoint,
                     headers={'Accept': 'application/json'},
                     params={'FEAUTH': crucible_user_token, 'states': 'Review'})

    if r.status_code != 200:
        logging.error(f'Got status {r.status_code} while trying to fetch reviews from crucible.')
        exit(1)

    data = r.json()
    if not data:
        logging.debug('No reviews were found in crucible.')
        exit(0)

    review_list = ''
    authors = {}

    for review in data['reviewData']:

        due_date_str = review['dueDate'] if 'dueDate' in review else ''

        if due_date_str:

            # due date comes in ISO-8601 format
            due_date = datetime.datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M:%S.%f%z')

            # convert it to UTC
            due_date_utc = due_date.replace(tzinfo=pytz.UTC) - due_date.utcoffset()

            # get timestamps for due date and current time
            due_date_utc_timestamp = due_date_utc.timestamp()
            now_utc_timestamp = datetime.datetime.utcnow().timestamp()

            # check if the review is due
            if now_utc_timestamp > due_date_utc_timestamp:

                # try to get author info from slack so we can properly mention the user
                if review['creator']['userName'] not in authors:
                    r = requests.get(url=slack_user_lookup_endpoint,
                                     headers=slack_headers,
                                     params={'email': review['creator']['userName']})
                    if r.status_code == 200:
                        data = r.json()
                        # if the user is not found then use the username from crucible
                        authors[review['creator']['userName']] = f"<@{data['user']['id']}>" if data['ok'] else \
                            review['creator']['userName']
                    else:
                        logging.warning(f'Got status {r.status_code} while calling {slack_user_lookup_endpoint} .')

                review_list += (f"{crucible_base_url}/cru/{review['permaId']['id']} "
                                f"author: {authors[review['creator']['userName']]}\n")

    if review_list:
        r = requests.post(url=slack_webhook_url,
                          headers=slack_headers,
                          data=json.dumps({'text': f'The following reviews are due:\n {review_list}'}))

        if r.status_code != 200:
            logging.error(f'Got status {r.status_code} while trying to post to the slack webhook url.')

    return review_list
