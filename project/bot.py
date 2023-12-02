import sys

from telethon.sync import events

from login import create_bot_client
from model import TelegramSearchModel


def main():
    if len(sys.argv) >= 3:
        chat_name = sys.argv[1]
        language = sys.argv[2]
    else:
        chat_name = input('Please input a Telegram chat name: ')
        language = input('Please input the language of the chat: ')

    model = TelegramSearchModel(chat_name, language)
    bot = create_bot_client()
    allowed_chats = get_allowed_chats()

    with bot:
        @bot.on(events.NewMessage(pattern=r"\/search"))
        async def handler(event):
            message = event.message.message
            if allowed_chats and event.chat_id not in allowed_chats:
                return

            search_query = message.split(maxsplit=1)[1].strip()
            if not search_query:
                return

            response = ""
            for i, result in enumerate(model.query(search_query)):
                message_text = result.message_text
                message_text = message_text.replace('[', '\\[')
                message_text = message_text.replace(']', '\\]')
                response += f'{i + 1}) [{message_text}]({result.message_link})\n'

            await event.reply(response)
        bot.run_until_disconnected()


def get_allowed_chats():
    with open("allowed_chats.txt") as f:
        return [int(allowed_chat) for allowed_chat in f.readlines()]


if __name__ == '__main__':
    main()
