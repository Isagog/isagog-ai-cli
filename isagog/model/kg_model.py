"""
    A model for Knowledge Graph entities and relations
    (c) Isagog S.r.l. 2024, MIT License
"""
import logging
import uuid
from typing import IO, TextIO, Any, Callable, Dict

from rdflib import OWL, Graph, RDF, URIRef, RDFS

import re

from pydantic import BaseModel
from typing_extensions import deprecated

Value = str | int | float | bool


class Identifier(str):
    def __new__(cls, _id):
        if not cls.is_valid_id(_id):
            raise ValueError(f"Invalid identifier: {_id}")
        return str.__new__(cls, _id)

    @staticmethod
    def is_valid_id(_id):
        pattern = re.compile(
            r'^[a-zA-Z][a-zA-Z0-9+.-]*:'  # Scheme: Any valid URI scheme
            r'[a-zA-Z0-9-._~:/?#\[\]@!$&\'()*+,;=%]*$'  # Path: Any valid URI character
        )
        return re.match(pattern, _id)

    def n3(self):
        return f"<{self}>"


Reference = URIRef | Identifier

OWL_ENTITY_TYPES = [OWL.Class, OWL.NamedIndividual, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty]

PROFILE_ATTRIBUTE = Identifier("http://isagog.com/ontology#profile")


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


class Entity(BaseModel):
    id: Reference
    meta: str = None

    def __init__(self, _id, **kwargs):
        super().__init__(**kwargs)
        self.id = _id
        self.meta = kwargs.get('meta', None)

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

    @deprecated
    def to_dict(self, **kwargs) -> dict:
        """
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
        elif 'format' in kwargs:
            if kwargs.get('format') == 'api':
                rt = {
                    "id": self.id,
                }
                if hasattr(self, '__meta__'):
                    rt['meta'] = self.__meta__
                return rt
            else:
                serializer = _todict
        else:
            serializer = _todict
        return serializer(self)


class Concept(Entity):
    """
    Unary predicate
    """
    comment: str | None = None
    ontology: str | None = None
    parents: list[Reference] = [OWL.Thing]

    def __init__(self, _id: Reference, **kwargs):
        super().__init__(_id, **kwargs)
        self.comment = kwargs.get('comment', None)
        self.ontology = kwargs.get('ontology', None)
        self.parents = kwargs.get('parents', [OWL.Thing])


class Attribute(Entity):
    """
    Class of assertions ranging on concrete domains
    owl:DatatypeProperties
    """

    domain: Reference = OWL.Thing
    parents: list[Reference] = [OWL.topDataProperty]

    def __init__(self, _id: Reference, **kwargs):
        super().__init__(_id, **kwargs)
        self.domain = kwargs.get('domain', OWL.Thing)
        self.parents = kwargs.get('parents', [OWL.topDataProperty])


class Relation(Entity):
    """
    Class of assertions ranging on individuals
    owl:ObjectProperty
    """
    domain: Reference = OWL.Thing
    range: Reference = OWL.Thing
    inverse: Reference = None
    parents: list[Reference] = [OWL.topObjectProperty]

    def __init__(self,
                 _id: Reference,
                 domain: Reference = OWL.Thing,
                 range: Reference = OWL.Thing,
                 inverse: Reference = None,
                 parents=None,
                 **kwargs):
        super().__init__(_id, **kwargs)
        self.domain = domain
        self.range = range
        self.inverse = inverse
        if parents is None:
            parents = [OWL.topObjectProperty]
        self.parents = parents


class Assertion(BaseModel):
    """
    Assertion axiom of the form: property(subject, values)
    """

    predicate: Reference
    subject: Reference
    values: list[Reference | Value]
    id: str = None

    def __init__(self,
                 predicate: Reference,
                 subject: Reference,
                 values: list[Reference | Value] = None,
                 reify: bool = False,
                 **kwargs):
        super().__init__(**kwargs)
        self.predicate = predicate
        self.subject = subject
        self.values = values if values else []
        if reify:
            self.id = kwargs.get('id', uuid.uuid4())

    def is_empty(self) -> bool:
        return not self.values

    @deprecated
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
                serializer = _todict
        else:
            serializer = _todict
        return serializer(self)


class Ontology(Graph):
    """
    In-memory, read-only RDF representation of an ontology.
    Manages basic reasoning on declared inclusion dependencies (RDFS.subClassOf).
    Also, it manages classes annotated as 'category' in the ontology. Categories
    are 'rigid' concepts,
    i.e. they (should) hold for an individual in every 'possible world'.
    Categories should be (a) disjoint from their siblings, (b) maximal, i.e.
    for any category,
    no super-categories allowed.
    """

    def __init__(
            self,
            source: IO[bytes] | TextIO | str,
            publicIRI: str,
            source_format="turtle"
    ):
        """
        :param source:  Path to the ontology source file.
        :param publicIRI:  Base IRI for the ontology.
        :param source_format:  Format of the ontology.

        """
        Graph.__init__(self, identifier=publicIRI)
        self.parse(source=source, publicID=publicIRI, format=source_format)

        self.concepts = [
            Concept(cls)
            for cls in self.subjects(predicate=RDF.type, object=OWL.Class)
            if isinstance(cls, URIRef)
        ]
        self.relations = [
            Relation(rl)
            for rl in self.subjects(
                predicate=RDF.type, object=OWL.ObjectProperty
            )
            if isinstance(rl, URIRef)
        ]
        self.attributes = [
            Attribute(att)
            for att in self.subjects(
                predicate=RDF.type, object=OWL.DatatypeProperty
            )
            if isinstance(att, URIRef)
        ]
        for ann in self.subjects(
                predicate=RDF.type, object=OWL.AnnotationProperty
        ):
            if isinstance(ann, URIRef):
                self.attributes.append(Attribute(ann))

        self._submap = dict[Concept, list[Concept]]()

    def subclasses(self, sup: Concept) -> list[Concept]:
        """
        Gets direct subclasses of a given concept
        """
        if sup not in self._submap:
            self._submap[sup] = [
                Concept(sc)
                for sc in self.subjects(RDFS.subClassOf, sup.id)
                if isinstance(sc, URIRef)
            ]
        return self._submap[sup]

    def is_subclass(self, sub: Concept, sup: Concept) -> bool:
        """
        Tells if a given concept implies another given concept (i.e. is a subclass)
        :param sub:  Subconcept
        :param sup:  Superconcept
        """

        if sub == sup:
            return True
        subcls = self.subclasses(sup)
        found = False
        while not found:
            if sub in subcls:
                found = True
            else:
                for _sc in subcls:
                    if self.is_subclass(sub, _sc):
                        found = True
                        break
                break
        return found


class AttributeInstance(Assertion):
    """
    Attributive assertion
    """
    value_type: str = None

    def __init__(self,
                 predicate: Reference = None,
                 subject: Reference = None,
                 values: list[Value] = None,
                 type: str = None,
                 **kwargs):
        """
        :param subject: the asserted subject
        :param predicate: the asserted property
        :param values: the asserted values, they can be strings, integers, floats or booleans
        :param kwargs:
        """
        self.value_type = type
        if values:
            specimen = values[0]
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
        super().__init__(predicate=predicate,
                         subject=subject,
                         values=values,
                         **kwargs)

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

    def first_value(self, default=None) -> str | int | float | bool | None:
        if len(self.values) > 0:
            return self.values[0]
        else:
            return default

    @deprecated
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
        else:
            return super().to_dict()
        return rt


VOID_ATTRIBUTE = AttributeInstance(predicate='http://isagog.com/attribute#void')


class RelationInstance(Assertion):
    """
    Relational assertion
    """

    def __init__(self,
                 predicate: Reference = None,
                 subject: Reference = None,
                 values: list[Any | Reference | dict] = None,
                 **kwargs):
        """

        :param property: the asserted property
        :param subject: the assertion's subject
        :param values: the asserted values, they can be individuals, references or dictionaries
        :param kwargs:
        """
        if values:
            specimen = values[0]
            if isinstance(specimen, Individual):
                pass
            elif isinstance(specimen, Reference):
                # values are references, convert them to Individuals
                inst_values = [Individual(_id=r_data) for r_data in values]
                values = inst_values
            elif isinstance(specimen, dict):
                # if values are dictionaries, then convert them to Individuals
                inst_values = [Individual(_id=r_data.get('id'), **r_data) for r_data in values]
                values = inst_values
            else:
                raise ValueError("bad values for relational assertion")

        super().__init__(predicate=predicate,
                         subject=subject,
                         values=values,
                         **kwargs)

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

    @deprecated
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

    def __init__(self,
                 _id: Reference,
                 kind: Reference | list[Reference] = None,
                 label: str = None,
                 comment: str = None,
                 attributes: list[AttributeInstance | dict] = None,
                 relations: list[RelationInstance | dict] = None,
                 **kwargs
                 ):
        """

        :param _id: the individual identifier
        :param kind: the individual kind(s)
        :param label: the distinguished attribute 'label'
        :param comment: the distinguished attribute 'comment'
        :param attributes: the individual attributes
        :param relations: the individual relations
        :param kwargs:
        """
        super().__init__(_id, owl=OWL.NamedIndividual, **kwargs)
        self.kind = list(kind) if kind else [OWL.Thing]
        self.label = label if label else _uri_label(_id)
        self.comment = comment if comment else None
        self.attributes = list()
        self.relations = list()
        if attributes:
            for attribute in attributes:
                if isinstance(attribute, dict):
                    attribute = AttributeInstance(**attribute)
                self.add_attribute(instance=attribute)

        if relations:
            for relation in relations:
                if isinstance(relation, dict):
                    relation = RelationInstance(**relation)
                self.add_relation(instance=relation)
        if 'score' in kwargs and kwargs.get('score'):
            self.score = float(kwargs.get('score'))
        if self.has_attribute(PROFILE_ATTRIBUTE):
            self.profile = {
                profile_value.split("=")[0]: int(profile_value.split("=")[1])
                for profile_value in self.get_attribute(PROFILE_ATTRIBUTE).values
            }
        else:
            self.profile = {}
        self._refresh = True

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
        self.score = score

    def get_score(self) -> float | None:
        """
        Gets the individual score, i.e. the relevance of the individual in a given context (e.g. a search result)
        :return:
        """
        if hasattr(self, 'score'):
            return self.score
        else:
            return None

    def has_score(self) -> bool:
        """
        Tells if the individual has a score
        :return:
        """
        return hasattr(self, 'score')

    def add_attribute(self,
                      instance: AttributeInstance = None,
                      predicate: Reference = None,
                      values: list[str | int | float | bool] = None):
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
        self._refresh = True

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
            self._refresh = True
        else:
            if not predicate:
                raise ValueError("missing property")
            if not isinstance(predicate, Reference):
                predicate = Identifier(predicate)
            self.add_relation(instance=RelationInstance(predicate=predicate, values=values))

    def need_update(self):
        return self._refresh

    def updated(self):
        self._refresh = False

    @deprecated
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
