"""
Isagog KG model
"""
import io
import logging
from typing import IO, Optional, TextIO, Any

from rdflib import OWL, Graph, Literal, RDF, URIRef, RDFS

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


class KnowledgeObject:
    """Base class for all knowledge objects"""

    def __init__(self, uri: URIRef | str) -> None:
        self.uri = URIRef(uri) if isinstance(uri, str) else uri

    def n3(
            self, namespace_manager: Optional["NamespaceManager"] = None
    ) -> str:
        """Convert to n3"""
        return self.uri.n3(namespace_manager=namespace_manager)

    # def to_json(self) -> str:
    #     """ Convert to JSON """
    #     return json.dumps(
    #         {"uri": str(self.uri)}
    #     )

    def __str__(self):
        return str(self.uri)

    def __eq__(self, other):
        return (
                (isinstance(other, KnowledgeObject) and self.uri == other.uri)
                or (isinstance(other, URIRef) and self.uri == other)
                or (isinstance(other, str) and str(self.uri) == other)
        )

    def __hash__(self):
        return self.uri.__hash__()


def _uri(ref: KnowledgeObject) -> URIRef:
    return ref.uri





class Annotation(KnowledgeObject):
    """
    References to owl:AnnotationProperty
    """

    def __init__(self, uri: URIRef | str):
        KnowledgeObject.__init__(self, uri)


class Entity(KnowledgeObject):
    """
    Any identified knowledge entity, either predicative or individual
    """
    ALLOWED_TYPES = [OWL.Axiom, OWL.NamedIndividual, OWL.ObjectProperty, OWL.DatatypeProperty]

    def __init__(self, data: dict, _type: str = None):
        assert (data and _type)
        assert _type in Entity.ALLOWED_TYPES
        super().__init__(data.get('id', KeyError("invalid entity data")))
        self.type = _type

    def to_dict(self) -> dict:
        return _todict(self)


class Concept(Entity):
    """
    Concept
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        super().__init__(data, OWL.Class)
        self.comment = data.get('comment', "")
        self.ontology = data.get('ontology', "")
        self.parents = data.get('parents', [])

class Attribute(KnowledgeObject):
    """
    References to owl:DatatypeProperty
    """

    def __init__(self, uri: URIRef | str, domain: Optional[Concept] = None):
        KnowledgeObject.__init__(self, uri)
        self.domain = domain if domain is not None else Concept(OWL.Thing)

class Relation(KnowledgeObject):
    """
    Refs to owl:ObjectProperty
    """

    def __init__(
            self,
            uri: URIRef | str,
            inverse: Optional[URIRef] = None,
            label: str = None,
            domain: Optional[Concept] = None,
            range: Optional[Concept] = None,
    ):
        KnowledgeObject.__init__(self, uri)
        self.inverse = inverse
        self.domain = domain if domain is not None else Concept(OWL.Thing)
        self.range = range if range is not None else Concept(OWL.Thing)
        self.label = label if label is not None else _uri_label(uri)

    def __str__(self):
        return self.uri if isinstance(self.uri, str) else str(self.uri)


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
            source_format="turtle",
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
        Gets direct subclasses of a given concept.
        """
        if sup not in self._submap:
            self._submap[sup] = [
                Concept(sc)
                for sc in self.subjects(RDFS.subClassOf, _uri(sup))
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


class Reference(Entity):
    """
    Reference instance as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
        super().__init__(data, OWL.Axiom)
        self.kinds = data.get('kinds', [])


class RelationInstance(Assertion):
    """
    Relation instance as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, data: dict):
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


VOID_RELATION = RelationInstance({'id': 'http://isagog.com/relation#void'})


class Individual(Entity):
    """
    Individual entity as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    (Individual)
    """

    def __init__(self, data: dict):
        super().__init__(data, OWL.NamedIndividual)
        self.label = data.get('label', _uri_label(self.id))
        self.kinds = data.get('kinds', [OWL.Thing])
        self.comment = data.get('comment', '')
        self.attributes = [AttributeInstance(a_data) for a_data in data['attributes']] if 'attributes' in data \
            else list[AttributeInstance]()
        self.relations = [RelationInstance(r_data) for r_data in data['relations']] if 'relations' in data \
            else list[RelationInstance]()
        self.score = float(data.get('score', 0.0))

    def get_attribute(self, attribute_id: str) -> AttributeInstance | Any:
        found = next(filter(lambda x: x.id.strip('<>') == attribute_id, self.attributes), None)
        if found and not found.is_empty():
            return found
        else:
            log.warning("%s not valued in %s", attribute_id, self.id)
            return VOID_ATTRIBUTE

    def get_relation(self, relation_id: str) -> RelationInstance | Any:
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
