import csv
import logging
import os
import re
import sys

import gensim
from nltk.stem import SnowballStemmer

from login import create_user_client, create_openai_client


def main():
    if len(sys.argv) >= 3:
        chat_name = sys.argv[1]
        language = sys.argv[2]
    else:
        chat_name = input('Please input a Telegram chat name: ')
        language = input('Please input the language of the chat: ')

    model = TelegramSearchModel(chat_name, language.lower())
    while True:
        query = input('Please input a search query: ')
        for result in model.query(query):
            similarity_percent = int(result.similarity * 100)
            print(f'{similarity_percent}%: {result.message_text}')


class MessageSearchResult:
    def __init__(self, message_id, message_text, similarity, message_link):
        self.message_text = message_text
        self.message_id = message_id
        self.similarity = similarity
        self.message_link = message_link


class TelegramSearchModel:
    def __init__(self, chat_name, language, use_chat_gpt=True):
        chat_filename = get_chat_filename(chat_name)
        chat_id_filename = get_chat_id_filename(chat_name)
        model_filename = get_model_filename(chat_name)

        download_chat(chat_name, chat_filename, chat_id_filename)
        self.chat_id = read_chat_id(chat_id_filename)
        chat_messages = list(read_chat_messages(chat_filename))
        self.chat_message_by_id = {message_id: message_text for message_id, message_text in chat_messages}

        self.stemmer = create_stemmer(language)

        train_model(chat_messages, self.stemmer, model_filename)
        self.model = load_model(model_filename)

        self.use_chat_gpt = use_chat_gpt
        if use_chat_gpt:
            self.openai_client = create_openai_client()

    def query(self, query):
        query_tokens = preprocess_message_text(query, self.stemmer)
        query_vector = self.model.infer_vector(query_tokens)

        results = []
        if self.use_chat_gpt:
            max_results = 20
        else:
            max_results = 5
        for message_id, similarity in self.model.docvecs.most_similar([query_vector], topn=200):
            chat_message = self.chat_message_by_id.get(message_id)
            if not chat_message:
                continue
            chat_message_tokens = preprocess_message_text(chat_message, self.stemmer)
            if len(chat_message_tokens) < 4:
                continue

            message_link = f"https://t.me/c/{str(self.chat_id)[4:]}/{message_id}"
            results.append(MessageSearchResult(message_id, chat_message, similarity, message_link))
            if len(results) >= max_results:
                break

        if self.use_chat_gpt:
            results = filter_search_results_with_chat_gpt(self.openai_client, results, query)

        return results


def get_chat_filename(chat_name):
    out_directory = 'messages'
    os.makedirs(out_directory, exist_ok=True)
    return f'{out_directory}/{chat_name}.csv'


def get_chat_id_filename(chat_name):
    out_directory = 'messages'
    os.makedirs(out_directory, exist_ok=True)
    return f'{out_directory}/{chat_name}.id.txt'


def get_model_filename(chat_name):
    out_directory = 'models'
    os.makedirs(out_directory, exist_ok=True)
    return f'{out_directory}/{chat_name}.bin'


def download_chat(chat_name, chat_filename, chat_id_filename):
    if os.path.exists(chat_filename) and os.path.exists(chat_id_filename):
        print('Already downloaded.')
        return

    with create_user_client() as client:
        client.loop.run_until_complete(async_download_chat(client, chat_name, chat_filename, chat_id_filename))


async def async_download_chat(client, chat_name, chat_filename, chat_id_filename):
    chat_id = await get_chat_id(client, chat_name)
    with open(chat_id_filename, 'w') as f:
        f.write(str(chat_id))
    print(f'Chat "{chat_name}" found, id={chat_id}.')

    with open(chat_filename, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['id', 'text'])  # Write header

        messages_saved = 0
        async for message in client.iter_messages(chat_id):
            writer.writerow([message.id, message.text])

            messages_saved += 1
            if messages_saved % 100 == 0:
                f.flush()
                print(f'Saved {messages_saved} messages')

    print(f'Messages from chat {chat_name} have been written to {chat_filename}.')


async def get_chat_id(client, chat_name):
    async for dialog in client.iter_dialogs():
        if dialog.name == chat_name:
            return dialog.id
    raise ValueError(f'Chat with name "{chat_name}" was not found!')


def train_model(chat_messages, stemmer, model_filename):
    if os.path.exists(model_filename):
        print('Already trained the model.')
        return

    train_corpus = list(preprocess_training_corpus(chat_messages, stemmer))

    logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)
    model = gensim.models.doc2vec.Doc2Vec(vector_size=350, epochs=200, min_count=2, dm=0)
    model.build_vocab(train_corpus)
    model.train(train_corpus, total_examples=model.corpus_count, epochs=model.epochs)
    model.save(model_filename)
    print(f'The trained model has been written to {model_filename}')


def read_chat_id(chat_id_filename):
    with open(chat_id_filename) as f:
        return int(f.readline().strip())


def read_chat_messages(chat_filename):
    with open(chat_filename, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)

        # Skip the header
        next(reader, None)

        for row in reader:
            message_id, message_text = row
            message_id = int(message_id)
            yield message_id, message_text


def create_stemmer(language):
    return SnowballStemmer(language=language)


def preprocess_training_corpus(chat_messages, stemmer):
    for message_id, message_text in chat_messages:
        tokens = preprocess_message_text(message_text, stemmer)
        yield gensim.models.doc2vec.TaggedDocument(tokens, [message_id])


def preprocess_message_text(message_text, stemmer):
    tokens = gensim.utils.simple_preprocess(message_text)
    tokens = [stemmer.stem(token) for token in tokens]
    return tokens


def load_model(model_filename):
    return gensim.models.doc2vec.Doc2Vec.load(model_filename)


def filter_search_results_with_chat_gpt(openai_client, search_results, query):
    chatgpt_query = 'Hello! I want you to help me find similar messages in a chat. Here is a message. Remember it:\n'
    chatgpt_query += f'{escape_for_chat_gpt(query)}\n\n'
    chatgpt_query += ("And here are some of the found messages, some of which may be irrelevant. "
                      "Please choose several (around 5) of messages that are the most relevant to the original message. "
                      "Print their ids in the same format (id=123). Print more relevant messages first. "
                      "Don't write anything else.\n")
    for i, search_result in enumerate(search_results):
        chatgpt_query += f"id={i}\n{escape_for_chat_gpt(search_result.message_text)}\n\n"

    response = openai_client.chat.completions.create(
      model="gpt-3.5-turbo",
      messages=[
        {"role": "system", "content": "You follow instructions precisely."},
        {"role": "user", "content": chatgpt_query}
      ]
    )
    response_message = response.choices[0].message.content
    message_indices = [int(match.group(1)) for match in re.finditer(r'id=(\d+)', response_message)]
    return [search_results[message_index] for message_index in message_indices]


def escape_for_chat_gpt(text):
    return text.replace('\n', '')


if __name__ == '__main__':
    main()
