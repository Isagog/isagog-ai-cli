"""
Isagog KG model
"""
import logging
from typing import Any

from rdflib import OWL

log = logging.getLogger("isagog-cli")


def _uri_label(uri: str) -> str:
    if "#" in uri:
        return uri.split("#")[-1]
    elif "/" in uri:
        return uri.split("/")[-1]
    else:
        return uri


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


class Entity(object):
    """
    Any identified knowledge entity, either predicative or individual
    """
    ALLOWED_TYPES = [OWL.Axiom, OWL.NamedIndividual, OWL.ObjectProperty, OWL.DatatypeProperty]

    def __init__(self, _id: str, _type: str):
        assert (_id and _type)
        assert _type in Entity.ALLOWED_TYPES
        self.id = _id
        self.type = _type

    def to_dict(self) -> dict:
        return _todict(self)


class Assertion(object):
    """
    Any assertion
    """

    def __init__(self, predicate: str, subject='@', values=None):
        assert predicate
        self.predicate = predicate
        self.subject = subject
        self.values = values if values else []


class AttributeInstance(Assertion):
    """
    Attribute instance, as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        super().__init__(predicate=data.get('id', KeyError("missing attribute id")),
                         values=data.get('values', []))
        self.value_type = data.get('type', "string")

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


VOID_ATTRIBUTE = AttributeInstance({'id': 'http://isagog.com/attribute#void'})


class Concept(Entity):
    """
    Concept
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        super().__init__(data.get('id'), OWL.Class)
        self.comment = data.get('comment', "")
        self.ontology = data.get('ontology', "")
        self.parents = data.get('parents', [])


class Reference(Entity):
    """
    Reference instance as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        super().__init__(data.get('id'), OWL.Axiom)
        self.kinds = data.get('kinds', [])


class Relationship(Assertion):
    """
    Relation instance as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict, predicate: str):
        super().__init__(predicate=data.get('id', KeyError("missing relation id")),
                         values=[Reference(r_data) for r_data in data['values']] if 'values' in data else [])

    def all_values(self) -> list:
        return self.values

    def first_value(self, default=None) -> Any | None:
        if len(self.values) > 0:
            return self.values[0]
        else:
            return default

    def is_empty(self) -> bool:
        return len(self.values) == 0


VOID_RELATION = Relationship({'id': 'http://isagog.com/relation#void'})


class Individual(Entity):
    """
    Individual entity as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    (Individual)
    """

    def __init__(self, data: dict):
        super().__init__(data.get('id'), OWL.NamedIndividual)
        self.label = data.get('label', _uri_label(self.id))
        self.kinds = data.get('kinds', [OWL.Thing])
        self.comment = data.get('comment', '')
        self.attributes = [AttributeInstance(a_data) for a_data in data['attributes']] if 'attributes' in data \
            else list[AttributeInstance]()
        self.relations = [Relationship(r_data) for r_data in data['relations']] if 'relations' in data \
            else list[Relationship]()
        self.score = float(data.get('score', 0.0))

    def get_attribute(self, attribute_id: str) -> AttributeInstance | Any:
        found = next(filter(lambda x: x.id.strip('<>') == attribute_id, self.attributes), None)
        if found and not found.is_empty():
            return found
        else:
            log.warning("%s not valued in %s", attribute_id, self.id)
            return VOID_ATTRIBUTE

    def get_relation(self, relation_id: str) -> Relationship | Any:
        found = next(filter(lambda x: x.id.strip('<>') == relation_id, self.relations), None)
        if found and not found.is_empty():
            return found
        else:
            log.warning("%s not valued %s", relation_id, self.id)
            return VOID_RELATION

    def set_score(self, score: float):
        self.score = score

    def get_score(self) -> float | None:
        return self.score

    def has_score(self) -> bool:
        return self.score is not None
