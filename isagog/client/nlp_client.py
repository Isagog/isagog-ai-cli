import logging

import requests
import toml
import os

from nlp_model import Word, NamedEntity

log = logging.getLogger("isagog-cli")

config = toml.load(f"{os.environ.get('APPROOT', '../..')}/config/config.toml")

nlp_endpoint = os.environ.get("ISAGOG_AI_NLP_ROUTE", "https://ai.isagog.com/api/nlp")

log.debug(f"nlp endpoint: {nlp_endpoint}")

search_pos = config["nlp"]["search_pos"]
lexical_pos = config["nlp"]["lexical_pos"]


def similarity_ranking(target: str,
                       candidates: list[str]) -> list[(int, float)]:
    req = {
        "target": target,
        "candidates": candidates,
    }

    res = requests.post(
        url=nlp_endpoint + "/rank",
        json=req,
        timeout=30
    )

    if res.ok:
        return [(rank[0], rank[1]) for rank in res.json()]
    else:
        log.error("similarity ranking failed: code=%d, reason=%s", res.status_code, res.reason)
        return []


def extract_keywords_from(text: str, number=5) -> list[str]:
    res = requests.post(
        url=nlp_endpoint + "/analyze",
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


def extract_words(text: str, filter_pos=search_pos) -> list[str]:
    res = requests.post(
        url=nlp_endpoint + "/analyze",
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


def extract_words_entities(text: str, filter_pos=lexical_pos) -> (list[Word], list[NamedEntity]):
    res = requests.post(
        url=nlp_endpoint + "/analyze",
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
