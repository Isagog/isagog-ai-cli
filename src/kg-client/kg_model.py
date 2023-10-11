"""
Isagog KG model
"""
import logging
from typing import Any


log = logging.getLogger("isagog-cli")


def _uri_label(uri: str) -> str:
    if "#" in uri:
        return uri.split("#")[-1]
    elif "/" in uri:
        return uri.split("/")[-1]
    else:
        return uri


class Attribute(object):
    """
    Attribute instance, as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        self.id = data.get('id', KeyError("attribute missing id"))
        self.type = data.get('type', "string")
        self.values = data.get('values', [])
        self.label = data.get('label', _uri_label(self.id))
        # self.comment = data['comment'] if 'comment' in data else ""

    def to_dict(self) -> dict:
        return _todict(self)

    def all_values_as_string(self) -> str:
        match len(self.values):
            case 0:
                return ""
            case 1:
                return self.values[0]
            case _:
                return "\n".join(self.values)

    def all_values(self) -> list:
        return self.values

    def first_value(self, default=None) -> Any | None:
        if len(self.values) > 0:
            return self.values[0]
        else:
            return default

    def is_empty(self) -> bool:
        return len(self.values) == 0 or self.values[0] == "None"


VoidAttribute = Attribute({'id': 'http://attribute#void'})


class Reference(object):
    """
    Reference instance as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        self.id = data.get('id', KeyError("reference missing id"))
        self.kinds = data.get('kinds', [])
        self.label = data.get('label', _uri_label(self.id))

    # self.comment = data['comment'] if 'comment' in data else ""

    def to_dict(self) -> dict:
        return _todict(self)


class Relation(object):
    """
    Relation as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        try:
            self.id = data['id']
            self.label = data['label'] if 'label' in data and data['label'] != "" else _uri_label(self.id)
            self.values = [Reference(r_data) for r_data in data['values']] if 'values' in data else []
        except Exception as e:
            raise ValueError(f"Deserialization error {e}")

    def to_dict(self) -> dict:
        return _todict(self)

    def all_values(self) -> list:
        return self.values

    def first_value(self, default=None) -> Any | None:
        if len(self.values) > 0:
            return self.values[0]
        else:
            return default

    def is_empty(self) -> bool:
        return len(self.values) == 0


VoidRelation = Relation({'id': 'http://relation#void'})


class Individual(object):
    """
    Individual entity as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    (Individual)
    """

    def __init__(self, data: dict):
        try:
            self.id = data['id']
            self.kinds = data['kinds']
            self.label = data['label'] if 'label' in data and data['label'] != "" else _uri_label(self.id)
            self.comment = data['comment'] if 'comment' in data else ''
            self.attributes = [Attribute(a_data) for a_data in data['attributes']] if 'attributes' in data \
                else list[Attribute]()
            self.relations = [Relation(r_data) for r_data in data['relations']] if 'relations' in data \
                else list[Relation]()
            self.score = float(data.get('score', 0.0))
        except Exception as e:
            raise ValueError(f"Deserialization error {e}")

    def get_attribute(self, attribute_id: str) -> Attribute | Any:
        # match_id = f"<{attribute_id}>" if not attribute_id.startswith('<') else attribute_id
        found = next(filter(lambda x: x.id.strip('<>') == attribute_id, self.attributes), None)
        if found and not found.is_empty():
            return found
        else:
            log.warning("%s not valued in %s", attribute_id, self.id)
            return VoidAttribute

    def get_relation(self, relation_id: str) -> Relation | Any:
        #   match_id = f"<{relation_id}>" if not relation_id.startswith('<') else relation_id
        found = next(filter(lambda x: x.id.strip('<>') == relation_id, self.relations), None)
        if found and not found.is_empty():
            return found
        else:
            log.warning("%s not valued %s", relation_id, self.id)
            return VoidRelation

    def to_dict(self) -> dict:
        return _todict(self)

    def set_score(self, score: float):
        self.score = score

    def get_score(self) -> float | None:
        return self.score

    def has_score(self) -> bool:
        return self.score is not None


def _todict(obj, classkey=None):
    """
     Recursive object to dict converter
    """
    if isinstance(obj, dict):
        data = {}
        for (k, v) in obj.items():
            data[k] = _todict(v, classkey)
        return data
    elif hasattr(obj, "_ast"):
        return _todict(obj._ast())
    elif hasattr(obj, "__iter__") and not isinstance(obj, str):
        return [_todict(v, classkey) for v in obj]
    elif hasattr(obj, "__dict__"):
        data = dict([(key, _todict(value, classkey))
                     for key, value in obj.__dict__.items()
                     if not callable(value) and not key.startswith('_')])
        if classkey is not None and hasattr(obj, "__class__"):
            data[classkey] = obj.__class__.__name__
        return data
    else:
        return obj
