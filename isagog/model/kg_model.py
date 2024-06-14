"""
    A model for Knowledge Graph entities and relations
    (c) Isagog S.r.l. 2024, MIT License
"""
import logging
import re
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field, model_validator
from rdflib import OWL, URIRef

# class Identifier(str):
#     def __new__(cls, _id):
#         if not cls.is_valid_id(_id):
#             raise ValueError(f"Invalid identifier: {_id}")
#         return str.__new__(cls, _id)
#
#     @staticmethod
#     def is_valid_id(_id):
#         pattern = re.compile(
#             r'^[a-zA-Z][a-zA-Z0-9+.-]*:'  # Scheme: Any valid URI scheme
#             r'[a-zA-Z0-9-._~:/?#\[\]@!$&\'()*+,;=%]*$'  # Path: Any valid URI character
#         )
#         return re.match(pattern, _id)
#
#     def n3(self):
#         return f"<{self}>"

Identifier = str | URIRef

Value = str | int | float | bool

OWL_ENTITY_TYPES = [OWL.Class, OWL.NamedIndividual, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty]

PROFILE_ATTRIBUTE = URIRef("http://isagog.com/ontology#profile")


def _uri_label(uri: str) -> str:
    """
    Extracts a label from a URI
    :param uri:
    :return:
    """
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
        if not data:
            return str(obj)
        if classkey is not None and hasattr(obj, "__class__"):
            data[classkey] = obj.__class__.__name__
        return data
    else:
        # can't convert to dict
        return obj


class Types(Enum):
    """
    Types of entities
    """
    CONCEPT = "concept"
    ATTRIBUTE = "attribute"
    RELATION = "relation"
    INDIVIDUAL = "individual"
    INSTANCE = "instance"
    VALUE = "value"
    ASSERTION = "assertion"
    ATTRIBUTE_INSTANCE = "attribute_instance"
    RELATION_INSTANCE = "relation_instance"


class TypedReference(BaseModel):
    id: Identifier
    type: Types | None = None

    class Config:
        arbitrary_types_allowed = True

    def __str__(self):
        return str(self.id)

    def __repr__(self):
        return str(self.id)


Reference = Identifier | TypedReference


class Entity(BaseModel):
    id: Identifier

    class Config:
        arbitrary_types_allowed = True

    def __eq__(self, other):
        return (
                (isinstance(other, Entity) and self.id == other.id)
                or (isinstance(other, URIRef) and self.id == str(other).strip("<>"))
                or (isinstance(other, str) and str(self.id) == other)
        )

    def __hash__(self):
        return self.id.__hash__()

    def to_dict(self, **kwargs) -> dict:
        """
        Custom serialization of the entity.
        Converts the entity to a json serializable dictionary.
        :param kwargs: format (a string to specify the output format, 'api' for API output,
                               default: object to dict conversion)
                       serializer (a custom function to use for serialization, overrides format if present)
        :return: a serializable dictionary representation of the entity
        """
        if 'serializer' in kwargs:
            serializer = kwargs.get('serializer')
            if not isinstance(serializer, Callable):
                raise ValueError("bad serializer")
            return serializer(self)
        elif 'format' in kwargs:
            match kwargs.get('format', ''):
                case 'api':
                    rt = {
                        "id": self.id,
                    }
                    if hasattr(self, '__meta__'):
                        rt['meta'] = self.__meta__
                    return rt
                case _:
                    return _todict(self)
        else:
            return self.model_dump(exclude_none=True)


class Predicate(Entity):
    """
    Predicate
    """
    label: str | None = None
    comment: str | None = None
    arity: int | None = 0
    implied: list[Reference | Entity] | None = []
    disjoint: list[Reference | Entity] | None = []

    @model_validator(mode='after')
    def validate(self):
        if self.implied or self.disjoint:
            for ref in self.implied + self.disjoint:
                if isinstance(ref, Reference):
                    pass
                elif isinstance(ref, Predicate):
                    if self.arity != ref.arity:
                        raise ValueError("bad implied")


class Concept(Predicate):
    """
    Unary predicate
    """
    arity: int = 1


class Attribute(Predicate):
    """
    Class of assertions ranging on concrete domains
    owl:DatatypeProperties
    """
    arity: int = 2
    domain: Reference | None


class Relation(Predicate):
    """
    Class of assertions ranging on individuals
    owl:ObjectProperty
    """
    arity: int = 2
    domain: Reference | Entity | None = None
    range: Reference | Entity | None = None
    inverse: Reference | None = None


class Assertion(BaseModel):
    """
    Assertion axiom of the form: property(subject, values)
    """

    predicate: Reference | Identifier
    subject: Reference | Identifier | None = None
    values: list[Any] | None = []
    id: str | None = None

    class Config:
        arbitrary_types_allowed = True

    def is_empty(self) -> bool:
        return not self.values

    def to_dict(self, **kwargs) -> dict:
        if 'serializer' in kwargs:
            serializer = kwargs.get('serializer')
            if not isinstance(serializer, Callable):
                raise ValueError("bad serializer")
        elif 'format' in kwargs:
            if kwargs.get('format') == 'api':
                rt = {
                    "id": self.predicate,
                    "subject": self.subject,
                    "values": self.values
                }
                if hasattr(self, 'label'):
                    rt['label'] = self.label
                if hasattr(self, 'comment'):
                    rt['comment'] = self.comment
                return rt
            else:
                return _todict(self)
        else:
            return super().to_dict()


class AttributeInstance(Assertion):
    """
    Attributive assertion
    """
    values: list[Value] | None = []
    value_type: str | None = None

    def __post_init__(self):
        if self.values:
            specimen = self.values[0]
            if isinstance(specimen, str):
                if self.value_type:
                    if self.value_type == "string":
                        pass
                    else:
                        raise ValueError("bad values for string attribute")
                else:
                    self.value_type = "string"

            elif isinstance(specimen, int):
                if self.value_type:
                    if self.value_type == "int":
                        pass
                    else:
                        raise ValueError("bad values for int attribute")
                else:
                    self.value_type = "int"
                raise ValueError("bad values for int attribute")

            elif isinstance(specimen, float):
                if self.value_type:
                    if self.value_type == "float":
                        pass
                    else:
                        raise ValueError("bad values for float attribute")
                else:
                    self.value_type = "float"

            elif isinstance(specimen, bool):
                if self.value_type:
                    if self.value_type == "bool":
                        pass
                    else:
                        raise ValueError("bad values for bool attribute")
                else:
                    self.value_type = "bool"
            else:
                raise ValueError("bad values for attribute")

    def all_values_as_string(self) -> str:
        match len(self.values):
            case 0:
                return ""
            case 1:
                return str(self.values[0])
            case _:
                return "\n".join([str(v) for v in self.values])

    def all_values(self) -> list:
        return self.values

    def first_value(self, default=None) -> Value | None:
        if len(self.values) > 0:
            return self.values[0]
        else:
            return default

    def to_dict(self, **kwargs) -> dict:
        if 'serializer' in kwargs:
            return super().to_dict(serializer=kwargs.get('serializer'))
        rt = {}
        if 'format' in kwargs and kwargs.get('format') == 'api':
            rt["id"] = self.predicate
            if hasattr(self, 'label'):
                rt['label'] = self.label
            if hasattr(self, 'type'):
                rt['type'] = self.type
            rt['values'] = self.values
            return rt
        else:
            return super().to_dict()


VOID_ATTRIBUTE = AttributeInstance(predicate='http://isagog.com/attribute#void')


class RelationInstance(Assertion):
    """
    Relational assertion
    """
    values: list[Reference | Entity] | None = []

    def __post_init__(self):
        if self.values:
            specimen = self.values[0]
            if isinstance(specimen, Individual):
                pass
            elif isinstance(specimen, Reference):
                # values are references, convert them to Individuals
                inst_values = [Individual(_id=r_data) for r_data in self.values]
                self.values = inst_values
            elif isinstance(specimen, dict):
                # if values are dictionaries, then convert them to Individuals
                inst_values = [Individual(_id=r_data.get('id'), **r_data) for r_data in self.values]
                self.values = inst_values
            else:
                raise ValueError("bad values for relational assertion")

    def all_values(self, only_id=True) -> list:
        """
        Returns all values of the relation instance
        :param only_id:
        :return:
        """
        if only_id:
            return [ind.id for ind in self.values]
        else:
            return self.values

    def first_value(self, only_id=True, default=None) -> Any | None:
        if len(self.values) > 0:
            if only_id:
                return self.values[0].id
            else:
                return self.values[0]
        else:
            return default

    def kind_map(self) -> dict:
        """
        Returns a map of individuals by kind
        :return: a map of kind : individuals
        """
        kind_map = {}
        for individual in self.values:
            for kind in individual.kind:
                if kind not in kind_map:
                    kind_map[kind] = []
                kind_map[kind].append(individual)
        return kind_map

    def to_dict(self, **kwargs) -> dict:
        if 'serializer' in kwargs:
            return super().to_dict(serializer=kwargs.get('serializer'))
        rt = {}
        if 'format' in kwargs:
            if kwargs.get('format') == 'api':
                rt["id"] = str(self.predicate)
                if hasattr(self, 'label'):
                    rt['label'] = str(self.label)
                if hasattr(self, 'type'):
                    rt['type'] = str(self.type)
                rt['values'] = [ind.to_dict(format='api') for ind in self.values]
            else:
                logging.warning("unknown format %s", kwargs.get('format'))
                rt = super().to_dict()
        else:
            rt = super().to_dict()
        return rt


VOID_RELATION = RelationInstance(predicate='http://isagog.com/relation#void')


class Individual(Entity):
    """
    Individual entity

    """

    kind: list[Reference] = []
    label: str | None = None
    comment: str | None = None
    attributes: list[AttributeInstance] | None = []
    relations: list[RelationInstance] | None = []
    ephemeral: dict[str, Value] | None = Field(default_factory=dict, exclude=True)

    def has_attribute(self, attribute_id: Reference) -> bool:
        """
        Checks if the individual has a given ontology defined attribute
        :param attribute_id:
        :return:
        """
        found = next(filter(lambda x: x.predicate == attribute_id, self.attributes), None)
        return found and not found.is_empty()

    def get_attribute(self, attribute_id: Reference) -> AttributeInstance | None:
        """
        Gets the ontology defined attribute instance of the individual
        :param attribute_id:
        :return:
        """
        found = next(filter(lambda x: x.predicate == attribute_id, self.attributes), None)
        if found and not found.is_empty():
            return found
        else:
            return VOID_ATTRIBUTE

    def has_relation(self, relation_id: Reference) -> bool:
        """
        Checks if the individual has a given ontology defined relation
        :param relation_id:
        :return:
        """
        found = next(filter(lambda x: x.predicate == relation_id, self.relations), None)
        return found and not found.is_empty()

    def get_relation(self, relation_id: Reference) -> RelationInstance | None:
        """
        Gets the ontology defined relation instance of the individual
        :param relation_id:
        :return:
        """
        found = next(filter(lambda x: x.predicate == relation_id, self.relations), None)
        if found and not found.is_empty():
            return found
        else:
            return VOID_RELATION

    def get_assertions(self) -> list[Assertion]:
        """
        Gets all assertions about the individual
        :return:
        """
        return self.attributes + self.relations

    def set_score(self, score: float):
        """
        Sets the individual score, i.e. the relevance of the individual in a given context (e.g. a search result)
        :param score:
        :return:
        """
        self.ephemeral['score'] = score

    def get_score(self) -> float | None:
        """
        Gets the individual score, i.e. the relevance of the individual in a given context (e.g. a search result)
        :return:
        """
        return self.ephemeral.get('score')

    def has_score(self) -> bool:
        """
        Tells if the individual has a score
        :return:
        """
        return 'score' in self.ephemeral

    def add_attribute(self,
                      instance: AttributeInstance = None,
                      predicate: Reference = None,
                      values: list[Value] = None):
        """
        Adds an attribute to the individual
        One of predicate or instance must be provided (but not both: in that case, instance is preferred)
        :param values:
        :param predicate:
        :param instance:
        """
        if instance:
            if not isinstance(instance, AttributeInstance):
                raise ValueError("bad instance")
            if instance.subject and instance.subject != self.id:
                logging.warning("attribute for %s redeclared for %s", instance.subject, self.id)
            instance.subject = self.id
            existing = self.get_attribute(instance.predicate)
            if not existing or existing.is_empty():
                self.attributes.append(instance)
            else:
                existing.values.extend([value for value in instance.values if value not in existing.values])
        else:
            if not predicate:
                raise ValueError("missing predicate")
            if not isinstance(predicate, Reference):
                predicate = Identifier(predicate)
            self.add_attribute(instance=AttributeInstance(predicate=predicate, values=values))
        self.ephemeral['refresh'] = True

    def add_relation(self,
                     instance: RelationInstance = None,
                     predicate: Reference = None,
                     values: list[Reference] = None):
        """
        Adds a relation to the individual
        One of predicate or instance must be provided (but not both: in that case, instance is preferred)
        :param instance:
        :param values:
        :param predicate:
        :return:
        """
        if instance:
            if not isinstance(instance, RelationInstance):
                raise ValueError("bad instance")
            if instance.subject and instance.subject != self.id:
                logging.warning("relation for %s redeclared for %s", instance.subject, self.id)
            instance.subject = self.id
            existing = self.get_relation(instance.predicate)
            if not existing or existing.is_empty():
                self.relations.append(instance)
            else:
                existing.values.extend([value for value in instance.values if value not in existing.values])
            self.ephemeral['refresh'] = True
        else:
            if not predicate:
                raise ValueError("missing property")
            if not isinstance(predicate, Reference):
                predicate = Identifier(predicate)
            self.add_relation(instance=RelationInstance(predicate=predicate, values=values))

    def need_update(self):
        return self.ephemeral.get('refresh', False)

    def updated(self):
        self.ephemeral['refresh'] = False

    def to_dict(self, **kwargs) -> dict:
        if 'serializer' in kwargs:
            return super().to_dict(serializer=kwargs.get('serializer'))
        rt = {}
        if 'format' in kwargs:
            if kwargs.get('format') == 'api':
                rt['id'] = str(self.id)
                if self.kind:
                    rt['kind'] = [str(k) for k in self.kind],  # [str(c.id) for c in self.get_kind()],
                if self.label:
                    rt['label'] = self.label
                if self.comment:
                    rt['comment'] = self.comment
                if self.attributes:
                    rt['attributes'] = [att.to_dict(format='api') for att in self.attributes]
                if self.relations:
                    rt['relations'] = [rel.to_dict(format='api') for rel in self.relations]
                if hasattr(self, 'score'):
                    rt['score'] = self.score
            else:
                logging.warning("unknown format %s", kwargs.get('format'))
                rt = super().to_dict()
        else:
            rt = super().to_dict()
        return rt
