#!/usr/bin/python
# -*- coding: utf-8 -*-

'''
 - Captcha Overseer:
   - Tracks incoming new captcha tokens
   - Monitors the captcha'd accounts queue
   - Launches captcha_solver threads
 - Captcha Solver Threads each:
   - Have a unique captcha token
   - Attempts to verifyChallenge
   - Puts account back in active queue
   - Pushes webhook messages with captcha status
'''

import logging
import time
import requests

from threading import Thread

from pgoapi import PGoApi
from .fakePogoApi import FakePogoApi

from .models import Token
from .transform import jitter_location
from .account import check_login
from .proxy import get_new_proxy
from .utils import now


log = logging.getLogger(__name__)


def captcha_overseer_thread(args, account_queue, captcha_queue, key_scheduler,
                            wh_queue):
    solverId = 0
    while True:
        # Run once every 15 seconds.
        sleep_timer = 15

        tokens_needed = captcha_queue.qsize()
        if tokens_needed > 0:
            tokens = Token.get_valid(tokens_needed)
            tokens_available = len(tokens)
            solvers = min(tokens_needed, tokens_available)
            log.debug('Captcha overseer running. Captchas: %d - Tokens: %d',
                      tokens_needed, tokens_available)
            for i in range(0, solvers):
                hash_key = None
                if args.hash_key:
                    hash_key = key_scheduler.next()

                t = Thread(target=captcha_solver_thread,
                           name='captcha-solver-{}'.format(solverId),
                           args=(args, account_queue, captcha_queue, hash_key,
                                 tokens[i], wh_queue))
                t.daemon = True
                t.start()

                solverId += 1
                if solverId > 999:
                    solverId = 0
                # Wait a bit before launching next captcha-solver thread
                time.sleep(1)

            # Adjust captcha-overseer sleep timer
            sleep_timer -= 1 * solvers
        time.sleep(sleep_timer)


def captcha_solver_thread(args, account_queue, captcha_queue, hash_key, token,
                          wh_queue):
    status, account, location, captcha_url = (captcha_queue.get())
    time_start = now()

    status['message'] = 'Waking up account {} to verify captcha token.'.format(
                         account['username'])
    log.info(status['message'])

    if args.mock != '':
        api = FakePogoApi(args.mock)
    else:
        api = PGoApi()

    if hash_key:
        log.debug('Using key {} for solving this captcha.'.format(hash_key))
        api.activate_hash_server(hash_key)

    proxy_url = False
    if args.proxy:
        # Try to fetch a new proxy
        proxy_num, proxy_url = get_new_proxy(args)

        if proxy_url:
            log.debug('Using proxy %s', proxy_url)
            api.set_proxy({'http': proxy_url, 'https': proxy_url})

    if not args.no_jitter:
        # Jitter location before uncaptcha attempt
        location = jitter_location(location)

    api.set_position(*location)
    status['message'] = 'Logging in...'
    check_login(args, account, api, location, proxy_url)

    response = api.verify_challenge(token=token)

    captcha_queue.task_done()
    time_elapsed = now() - time_start
    wh_message = {'status_name': args.status_name,
                  'status': 'error',
                  'account': status['username'],
                  'captcha': status['captcha'],
                  'time': time_elapsed}

    if 'success' in response['responses']['VERIFY_CHALLENGE']:
        status['message'] = (
            "Account {} successfully uncaptcha'd, returning to " +
            'active duty.').format(account['username'])
        log.info(status['message'])
        account_queue.put(account)
        wh_message['status'] = 'success'
    else:
        status['message'] = (
            'Account {} failed verifyChallenge, putting back ' +
            'in captcha queue.').format(account['username'])
        log.warning(status['message'])
        captcha_queue.put((status, account, location, captcha_url))
        wh_message['status'] = 'failure'

    if args.webhooks:
        wh_queue.put(('captcha', wh_message))


# Return captcha_url if captcha is encountered
def check_captcha(response_dict):
    try:
        captcha_url = response_dict['responses'][
            'CHECK_CHALLENGE']['challenge_url']
        if len(captcha_url) > 1:
            return captcha_url
    except KeyError, e:
        log.error('Unable to check captcha: {}'.format(e))

    return None


# Return True if captcha was succesfully solved
def automatic_captcha_solve(args, status, api, captcha_url, account,
                            account_failures, wh_queue):
    if not args.captcha_solving:
        return False
    elif not args.captcha_key:
        return False

    status['message'] = (
        'Account {} is encountering a captcha, starting 2captcha ' +
        'sequence.').format(account['username'])
    log.warning(status['message'])

    if args.webhooks:
        wh_message = {'status_name': args.status_name,
                      'status': 'encounter',
                      'account': status['username'],
                      'captcha': status['captcha'],
                      'time': 0}
        wh_queue.put(('captcha', wh_message))

    time_start = now()
    captcha_token = token_request(args, status, captcha_url)
    time_elapsed = now() - time_start

    if 'ERROR' in captcha_token:
        log.warning('Unable to resolve captcha, please check your ' +
                    '2captcha API key and/or wallet balance.')
        account_failures.append({
            'account': account,
            'last_fail_time': now(),
            'reason': 'captcha failed to verify'})
        if args.webhooks:
            wh_message['status'] = 'error'
            wh_message['time'] = time_elapsed
            wh_queue.put(('captcha', wh_message))

        return False
    else:
        status['message'] = (
            'Retrieved captcha token, attempting to verify challenge ' +
            'for {}.').format(account['username'])
        log.info(status['message'])

        response = api.verify_challenge(token=captcha_token)
        time_elapsed = now() - time_start
        if 'success' in response['responses']['VERIFY_CHALLENGE']:
            status['message'] = "Account {} successfully uncaptcha'd.".format(
                account['username'])
            log.info(status['message'])
            if args.webhooks:
                wh_message['status'] = 'success'
                wh_message['time'] = time_elapsed
                wh_queue.put(('captcha', wh_message))

            return True
        else:
            status['message'] = (
                'Account {} failed verifyChallenge, putting away ' +
                'account for now.').format(account['username'])
            log.info(status['message'])
            account_failures.append({
                'account': account,
                'last_fail_time': now(),
                'reason': 'captcha failed to verify'})
            if args.webhooks:
                wh_message['status'] = 'failure'
                wh_message['time'] = time_elapsed
                wh_queue.put(('captcha', wh_message))

            return False


def token_request(args, status, url):
    s = requests.Session()
    # Fetch the CAPTCHA_ID from 2captcha.
    try:
        request_url = (
            'http://2captcha.com/in.php?key={}&method=userrecaptcha' +
            '&googlekey={}&pageurl={}').format(args.captcha_key,
                                               args.captcha_dsk, url)
        captcha_id = s.post(request_url).text.split('|')[1]
        captcha_id = str(captcha_id)
    # IndexError implies that the retuned response was a 2captcha error.
    except IndexError:
        return 'ERROR'
    status['message'] = (
        'Retrieved captcha ID: {}; now retrieving token.').format(captcha_id)
    log.info(status['message'])
    # Get the response, retry every 5 seconds if it's not ready.
    recaptcha_response = s.get(
        'http://2captcha.com/res.php?key={}&action=get&id={}'.format(
            args.captcha_key, captcha_id)).text
    while 'CAPCHA_NOT_READY' in recaptcha_response:
        log.info('Captcha token is not ready, retrying in 5 seconds...')
        time.sleep(5)
        recaptcha_response = s.get(
            'http://2captcha.com/res.php?key={}&action=get&id={}'.format(
                args.captcha_key, captcha_id)).text
    token = str(recaptcha_response.split('|')[1])
    return token
