import logging
import sys

import requests
from dotenv import load_dotenv
import os

from isagog.model.nlp_model import Word, NamedEntity

load_dotenv()

log = logging.getLogger("isagog-cli")

log.setLevel(os.getenv("ISAGOG_AI_LOG_LEVEL", logging.INFO))

handler = logging.StreamHandler(sys.stdout)

# Create a formatter and set the format for the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Add the handler to the logger
log.addHandler(handler)

DEFAULT_LEXICAL_POS = ["NOUN", "VERB", "ADJ", "ADV"]
DEFAULT_SEARCH_POS = ["NOUN", "VERB", "PROPN"]

def truncate(s: str, n = 10):
    """
    Truncate a string to the first N characters, adding '...' if the string is longer.

    :param s: The string to be truncated.
    :param n: The maximum length of the truncated string.
    :return: The truncated string.
    """
    # Check if the string is longer than N characters
    if len(s) > n:
        return s[:n] + '...'
    else:
        return s


class LanguageProcessor(object):
    """
    Interface to Language service
    """

    def __init__(self,
                 route: str,
                 version: str = None):
        self.route = route
        self.version = version
        log.debug("LanguageProcessor initialized with route %s", route)

    def similarity_ranking(self, target: str,
                           candidates: list[str]) -> list[(int, float)]:

        """
        Ranks the candidates based on their similarity with the supplied text
        :param target:
        :param candidates:
        :return:
        """
        log.debug("Ranking for %s", target)
        req = {
            "target": target,
            "candidates": candidates,
        }

        res = requests.post(
            url=self.route + "/rank",
            json=req,
            timeout=30
        )

        if res.ok:
            return [(rank[0], rank[1]) for rank in res.json()]
        else:
            log.error("similarity ranking failed: code=%d, reason=%s", res.status_code, res.reason)
            return []

    def extract_keywords_from(self, text: str, number=5) -> list[str]:
        """
        Extract the main N words (keywords) from the supplied text
        :param text:
        :param number:
        :return:
        """
        log.debug("Extracting %d keywords from %s", number, truncate(text))
        res = requests.post(
            url=self.route + "/analyze",
            json={
                "text": text,
                "tasks": ["keyword"],
                "keyword_number": number
            },
            headers={"Accept": "application/json"},
            timeout=20
        )
        if res.ok:
            res_dict = res.json()
            words = [kwr[0] for kwr in res_dict["keyword"]]
            return words
        else:
            log.error("fail to extract from '%s': code=%d, reason=%s", text, res.status_code, res.reason)
            return []

    def extract_words(self, text: str, filter_pos=None) -> list[str]:
        """
        Extract all the word token with the given part-of-speech
        :param text:
        :param filter_pos: part of speech list
        :return:
        """
        log.debug("Extracting words from %s", truncate(text))
        if not filter_pos:
            filter_pos = DEFAULT_LEXICAL_POS

        res = requests.post(
            url=self.route + "/analyze",
            json={
                "text": text,
                "tasks": ["word"]
            },
            headers={"Accept": "application/json"},
            timeout=20
        )
        if res.ok:
            res_dict = res.json()
            words = [Word(**{k: v for k, v in r.items() if k in Word._fields}) for r in res_dict["words"]]
            return [w.text for w in words if w.pos in filter_pos]
        else:
            log.error("fail to extract from '%s': code=%d, reason=%s", text, res.status_code, res.reason)
            return []

    def extract_words_entities(self, text: str, filter_pos=None) -> (list[Word], list[NamedEntity]):
        log.debug("Extracting words and entities from %s", truncate(text))
        if not filter_pos:
            filter_pos = DEFAULT_LEXICAL_POS

        res = requests.post(
            url=self.route + "/analyze",
            json={
                "text": text,
                "tasks": ["word", "entity"]
            },
            headers={"Accept": "application/json"},
            timeout=20
        )

        if res.ok:
            res_dict = res.json()
            words = list(filter(lambda w: w.pos in filter_pos,
                                [Word(**{k: v for k, v in r.items() if k in Word._fields}) for r in res_dict["words"]]))
            entities = [NamedEntity(**{k: v for k, v in r.items() if k in NamedEntity._fields}) for r in
                        res_dict["entities"]]
            return words, entities

        else:
            log.error("fail to extract from '%s': code=%d, reason=%s", text, res.status_code, res.reason)
            return [], []
