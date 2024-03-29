"""
KG model
"""

from typing import IO, TextIO, Any

from rdflib import OWL, Graph, RDF, URIRef, RDFS

# Type definitions

ID = URIRef | str  # Identifier type

ALLOWED_TYPES = [OWL.Axiom, OWL.NamedIndividual, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.Class]


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
        return obj


class Entity(object):
    """
    Any identified knowledge entity, either predicative (property) or individual
    """

    def __init__(self, _id: ID, **kwargs):
        assert _id
        self.id = str(_id).strip("<>") if isinstance(_id, URIRef) else _id
        owl_type = kwargs.get('owl')
        self.__owl__ = owl_type if owl_type and owl_type in ALLOWED_TYPES else None

    def n3(self) -> str:
        """Convert to n3"""
        return f"<{self.id}>"

    def __eq__(self, other):
        return (
                (isinstance(other, Entity) and self.id == other.id)
                or (isinstance(other, URIRef) and self.id == str(other).strip("<>"))
                or (isinstance(other, str) and str(self.id) == other)
        )

    def __hash__(self):
        return self.id.__hash__()

    def to_dict(self) -> dict:
        return _todict(self)


class Annotation(Entity):
    """
    References to owl:AnnotationProperty
    """

    def __init__(self, _id: ID):
        super().__init__(self, _id=_id)


class Concept(Entity):
    """
    Unary predicate
    """

    def __init__(self, _id: ID, **kwargs):
        """

        :param _id: the concept identifier
        :param kwargs:
        """
        kwargs['owl'] = OWL.Class
        super().__init__(_id, **kwargs)
        self.comment = kwargs.get('comment', "")
        self.ontology = kwargs.get('ontology', "")
        self.parents = kwargs.get('parents', [OWL.Thing])


class Attribute(Entity):
    """
    Assertions ranging on concrete domains
    owl:DatatypeProperties
    """

    def __init__(self, _id: ID, **kwargs):
        """

        :param _id:
        :param kwargs: domain
        """
        kwargs['owl'] = OWL.DatatypeProperty
        super().__init__(_id, **kwargs)
        self.domain = kwargs.get('domain', OWL.Thing)


class Relation(Entity):
    """
    Assertions ranging on individuals
    owl:ObjectProperty
    """

    def __init__(
            self,
            _id: ID,
            **kwargs
    ):
        """

        :param _id:
        :param kwargs: inverse, domain, range, label
        """
        kwargs['owl'] = OWL.ObjectProperty
        super().__init__(_id, **kwargs)
        self.inverse = kwargs.get('inverse')
        self.domain = kwargs.get('domain', Concept(OWL.Thing))
        self.range = kwargs.get('range', Concept(OWL.Thing))
        self.label = kwargs.get('label', _uri_label(_id))


class Assertion(object):
    """
    Logical assertion of the form: property(subject, values)
    """

    def __init__(self,
                 predicate: ID,
                 subject: ID = None,
                 values: list = None):
        """

        :param predicate:
        :param subject:
        :param values:
        """
        assert predicate
        self.property = str(predicate).strip("<>")
        self.subject = str(subject).strip("<>") if subject else None
        self.values = values if values else []


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
    Attribute instance, as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, **kwargs):
        predicate = kwargs.get('property', kwargs.get('id', KeyError("missing relation property")))
        values = kwargs.get('values', [])
        super().__init__(predicate=predicate,
                         values=values)
        self.value_type = kwargs.get('type', "string")

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


VOID_ATTRIBUTE = AttributeInstance(id='http://isagog.com/attribute#void')


class RelationInstance(Assertion):
    """
    Relational assertion, as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    """

    def __init__(self, **kwargs):
        predicate = kwargs.get('property', kwargs.get('id', KeyError("missing relation property")))
        values = kwargs.get('values', [])
        if values:
            specimen = values[0]
            if isinstance(specimen, Individual):
                pass
            elif isinstance(specimen, dict):
                inst_values = [Individual(_id=r_data.get('id'), **r_data) for r_data in values]
                values = inst_values
            else:
                raise ValueError("bad values for relation instance")
        super().__init__(predicate=predicate,
                         values=values)

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

    def is_empty(self) -> bool:
        return len(self.values) == 0

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


VOID_RELATION = RelationInstance(predicate='http://isagog.com/relation#void')


class Individual(Entity):
    """
    Individual entity as defined in
    isagog_api/openapi/isagog_kg.openapi.yaml
    (Individual)
    """

    def __init__(self, _id: ID, **kwargs):
        super().__init__(_id, **kwargs)
        self.__owl__ = OWL.NamedIndividual
        self.label = kwargs.get('label', _uri_label(self.id))
        self.kind = kwargs.get('kind', kwargs.get('kinds', [OWL.Thing]))  # back compatibility w 0.7
        self.comment = kwargs.get('comment', '')
        self.attributes = [AttributeInstance(**a_data) for a_data in
                           kwargs.get('attributes', list[AttributeInstance]())]
        self.relations = [RelationInstance(**r_data) for r_data in kwargs.get('relations', list[RelationInstance]())]
        if 'score' in kwargs:
            self.score = float(kwargs.get('score'))
        if self.has_attribute("https://isagog.com/ontology#profile"):
            self.profile = {
                profile_value.split("=")[0]: int(profile_value.split("=")[1])
                for profile_value in self.get_attribute("https://isagog.com/ontology#profile").values
            }
        else:
            self.profile = {}

    def has_attribute(self, attribute_id: ID) -> bool:
        """
        Checks if the individual has a given ontology defined attribute
        :param attribute_id:
        :return:
        """
        found = next(filter(lambda x: x.property == attribute_id, self.attributes), None)
        return found and not found.is_empty()

    def get_attribute(self, attribute_id: ID) -> AttributeInstance | Any:
        """
        Gets the ontology defined attribute instance of the individual
        :param attribute_id:
        :return:
        """
        found = next(filter(lambda x: x.property == attribute_id, self.attributes), None)
        if found and not found.is_empty():
            return found
        else:
            return VOID_ATTRIBUTE

    def has_relation(self, relation_id: ID) -> bool:
        """
        Checks if the individual has a given ontology defined relation
        :param relation_id:
        :return:
        """
        found = next(filter(lambda x: x.property == relation_id, self.relations), None)
        return found and not found.is_empty()

    def get_relation(self, relation_id: ID) -> RelationInstance | Any:
        """
        Gets the ontology defined relation instance of the individual
        :param relation_id:
        :return:
        """
        found = next(filter(lambda x: x.property == relation_id, self.relations), None)
        if found and not found.is_empty():
            return found
        else:
            return VOID_RELATION

    def set_score(self, score: float):
        self.score = score

    def get_score(self) -> float | None:
        if hasattr(self, 'score'):
            return self.score
        else:
            return None

    def has_score(self) -> bool:
        return hasattr(self, 'score')
