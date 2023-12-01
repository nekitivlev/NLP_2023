import json

from telethon import TelegramClient


class TelegramAuth:
    def __init__(self, api_id, api_hash, bot_token):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token


def create_user_client():
    auth = load_telegram_auth()
    return TelegramClient('anon', auth.api_id, auth.api_hash)


def load_telegram_auth():
    with open('token.json') as f:
        data = json.load(f)

    telegram_auth = TelegramAuth(
        api_id=data['api_id'],
        api_hash=data['api_hash'],
        bot_token=data['bot_token'],
    )

    return telegram_auth
