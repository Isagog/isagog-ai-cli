"""
Client for Isagog NLP service
(c) Isagog S.r.l. 2024, MIT License
"""
import logging
import os
import time
import httpx

from dotenv import load_dotenv

from isagog.model.nlp_model import Word, NamedEntity

load_dotenv()

NLP_DEFAULT_TIMEOUT = int(os.getenv('NLP_DEFAULT_TIMEOUT', 60))

DEFAULT_LEXICAL_POS = ["NOUN", "VERB", "ADJ", "ADV"]
DEFAULT_SEARCH_POS = ["NOUN", "VERB", "PROPN"]

AUTH_TOKEN_KEY = os.getenv('ISAGOG_AUTH_TOKEN_KEY', 'X-Isagog-API-Token')
AUTH_TOKEN_VALUE = os.getenv('ISAGOG_AUTH_TOKEN_VALUE')


def truncate(s: str, n=10):
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
                 version: str = None,
                 logger=logging.getLogger()):
        self.route = route
        self.version = version
        self.logger = logger
        self.logger.info("Isagog NLP client (%s) initialized on route %s", hex(id(self)), route)

    def similarity_ranking(self,
                           target: str,
                           candidates: list[str],
                           timeout=NLP_DEFAULT_TIMEOUT) -> list[(int, float)]:

        """
        Ranks the candidates based on their similarity with the supplied text
        :param timeout:
        :param target:
        :param candidates:
        :return:
        """
        start = time.time()
        req = {
            "target": target,
            "candidates": candidates,
        }

        res = httpx.post(
            url=self.route + "/rank",
            json=req,
            timeout=timeout
        )

        if res.status_code == 200:
            self.logger.debug("Ranked %s in %d seconds", truncate(target), time.time() - start)
            return [(rank[0], rank[1]) for rank in res.json()]
        else:
            self.logger.error("similarity ranking failed: code=%d, reason=%s", res.status_code, res.text)
            return []

    def extract_keywords_from(self,
                              text: str,
                              number=5,
                              timeout=NLP_DEFAULT_TIMEOUT) -> list[str]:
        """
        Extract the main N words (keywords) from the supplied text
        :param timeout:
        :param text:
        :param number:
        :return:
        """
        self.logger.debug("Extracting %d keywords from %s", number, truncate(text))

        headers = {"Accept": "application/json"}

        if AUTH_TOKEN_VALUE:
            headers[AUTH_TOKEN_KEY] = AUTH_TOKEN_VALUE
        try:
            res = httpx.post(
                url=self.route + "/analyze",
                json={
                    "text": text,
                    "tasks": ["keyword"],
                    "keyword_number": number
                },
                headers=headers,
                timeout=timeout
            )
            if res.status_code == 200:
                res_dict = res.json()
                words = [kwr[0] for kwr in res_dict["keyword"]]
                return words
            else:
                self.logger.error("fail to extract from '%s': code=%d, reason=%s", text, res.status_code, res.text)
                return []
        except httpx.ConnectError:
            self.logger.error("Failed to connect to the host %s.", self.route)
            return []
        except httpx.RequestError as exc:
            self.logger.error(f"An error occurred while requesting {exc.request.url!r}.")
            return []
        except httpx.TimeoutException:
            self.logger.error("The request timed out from %s.", self.route)
            return []
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                f"HTTP error from occurred from {self.route}: {exc.response.status_code} - {exc.response.text}")
            return []
        except Exception as exc:
            self.logger.error(f"An unexpected error occurred on {self.route}: {exc}")
            return []

    def extract_words(self,
                      text: str,
                      filter_pos=None,
                      timeout=NLP_DEFAULT_TIMEOUT) -> list[str]:
        """
        Extract all the word token with the given part-of-speech
        :param timeout:
        :param text:
        :param filter_pos: part of speech list
        :return:
        """
        self.logger.debug("Extracting words from %s", truncate(text))
        if not filter_pos:
            filter_pos = DEFAULT_LEXICAL_POS

        headers = {"Accept": "application/json"}

        if AUTH_TOKEN_VALUE:
            headers[AUTH_TOKEN_KEY] = AUTH_TOKEN_VALUE

        try:
            res = httpx.post(
                url=self.route + "/analyze",
                json={
                    "text": text,
                    "tasks": ["word"]
                },
                headers=headers,
                timeout=timeout
            )
            if res.status_code == 200:
                res_dict = res.json()
                words = [Word(**{k: v for k, v in r.items() if k in Word._fields}) for r in res_dict["words"]]
                return [w.text for w in words if w.pos in filter_pos]
            else:
                self.logger.error("fail to extract from '%s': code=%d, reason=%s", text, res.status_code, res.text)
                return []
        except httpx.ConnectError:
            self.logger.error("Failed to connect to the host %s.", self.route)
            return []
        except httpx.RequestError as exc:
            self.logger.error(f"An error occurred while requesting {exc.request.url!r}.")
            return []
        except httpx.TimeoutException:
            self.logger.error("The request timed out from %s.", self.route)
            return []
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                f"HTTP error from occurred from {self.route}: {exc.response.status_code} - {exc.response.text}")
            return []
        except Exception as exc:
            self.logger.error(f"An unexpected error occurred on {self.route}: {exc}")
            return []

    def extract_words_entities(self,
                               text: str,
                               filter_pos=None,
                               timeout=NLP_DEFAULT_TIMEOUT) -> (list[Word], list[NamedEntity]):
        """
        Extract words and entities from the supplied text
        :param text:
        :param filter_pos:
        :param timeout:
        :return:
        """
        self.logger.debug("Extracting words and entities from %s", truncate(text))
        if not filter_pos:
            filter_pos = DEFAULT_LEXICAL_POS

        headers = {"Accept": "application/json"}

        if AUTH_TOKEN_VALUE:
            headers[AUTH_TOKEN_KEY] = AUTH_TOKEN_VALUE

        try:
            res = httpx.post(
                url=self.route + "/analyze",
                json={
                    "text": text,
                    "tasks": ["word", "entity"]
                },
                headers=headers,
                timeout=timeout
            )

            if res.status_code == 200:
                res_dict = res.json()
                words = list(filter(lambda w: w.pos in filter_pos,
                                    [Word(**{k: v for k, v in r.items() if k in Word._fields}) for r in res_dict["words"]]))
                entities = [NamedEntity(**{k: v for k, v in r.items() if k in NamedEntity._fields}) for r in
                            res_dict["entities"]]
                return words, entities

            else:
                self.logger.error("fail to extract from '%s': code=%d, reason=%s", text, res.status_code, res.text)
                return [], []
        except httpx.ConnectError:
            self.logger.error("Failed to connect to the host %s.", self.route)
            return [], []
        except httpx.RequestError as exc:
            self.logger.error(f"An error occurred while requesting {exc.request.url!r}.")
            return [], []
        except httpx.TimeoutException:
            self.logger.error("The request timed out from %s.", self.route)
            return [], []
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                f"HTTP error from occurred from {self.route}: {exc.response.status_code} - {exc.response.text}")
            return [], []
        except Exception as exc:
            self.logger.error(f"An unexpected error occurred on {self.route}: {exc}")
            return [], []

