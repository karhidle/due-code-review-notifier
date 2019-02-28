import datetime
import json
import logging
import os

import pytz
import requests

# env variables
crucible_base_url = os.getenv('CRUCIBLE_BASE_URL')
crucible_user_token = os.getenv('CRUCIBLE_USER_TOKEN')
slack_webhook_url = os.getenv('SLACK_WEBHOOK_URL')
slack_token = os.getenv('SLACK_TOKEN')
# end variables

crucible_open_reviews_endpoint = f'{crucible_base_url}/rest-service/reviews-v1/filter/'
slack_headers = {'Content-type': 'application/json',
                 'Authorization': f'Bearer {slack_token}'}
slack_user_lookup_endpoint = 'https://slack.com/api/users.lookupByEmail'


def check_due_reviews(event: dict, context) -> dict:

    logging.info('Checking due reviews from crucible.')

    # get reviews from crucible, there's no way to filter due reviews in their API.
    r = requests.get(url=crucible_open_reviews_endpoint,
                     headers={'Accept': 'application/json'},
                     params={'FEAUTH': crucible_user_token, 'states': 'Review'})

    if r.status_code != 200:
        logging.error(f'Got status {r.status_code} while trying to fetch reviews from crucible.')
        return

    data = r.json()
    if not data:
        logging.debug('No reviews were found in crucible.')
        return

    review_list = ''
    authors = {}

    for review in data['reviewData']:

        due_date_str = review['dueDate'] if 'dueDate' in review else ''

        if due_date_str:

            # due date comes in ISO-8601 format
            due_date = datetime.datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M:%S.%f%z')

            # convert it to UTC
            due_date_utc = due_date.replace(tzinfo=pytz.UTC) - due_date.utcoffset()

            now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)

            # check if the review is due
            if now_utc > due_date_utc:

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

                time_diff = (now_utc - due_date_utc)
                if time_diff.days:
                    due_info = f'{time_diff.days} days'
                else:
                    due_hours = int(time_diff.seconds / 3600)
                    due_info = f'{due_hours} hours' if due_hours else f'{int(time_diff.seconds / 60)} minutes'

                review_list += (f"{crucible_base_url}/cru/{review['permaId']['id']} "
                                f"author: {authors[review['creator']['userName']]} "
                                f"- due {due_info} ago\n")

    if review_list:
        r = requests.post(url=slack_webhook_url,
                          headers=slack_headers,
                          data=json.dumps({'text': f'The following reviews are due:\n {review_list}'}))

        if r.status_code != 200:
            logging.error(f'Got status {r.status_code} while trying to post to the slack webhook url.')

    return review_list
