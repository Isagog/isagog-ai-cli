# pylint: disable=W,C,R
"""
 Terminological module (box)
 Defines ontology and related classes

"""
from io import StringIO
from typing import Dict, Optional, Union, TextIO, List

from pydantic import BaseModel, Field, PrivateAttr
from rdflib import OWL, RDF, RDFS, Graph
from rdflib.term import Literal, URIRef

from isagog.model.kg_model import ID, Concept, Relation, Attribute, DataType, Predicate, validate_predicate_hierarchy

from typing import Set, Dict
from pydantic import ValidationError


class Ontology(BaseModel):
    """
        In-memory representation of an ontology.
    """
    namespace: Dict[str, str] = Field(default_factory=dict)
    source: Optional[Union[str, TextIO, StringIO]] = Field(default=None)
    publicIRI: Optional[str] = Field(default=None)  # Consider using AnyUrl from pydantic
    source_format: Optional[str] = Field(default=None)  # Consider using Enum
    concepts: Dict[ID, Concept] = Field(default_factory=dict)
    relations: Dict[ID, Relation] = Field(default_factory=dict)
    attributes: Dict[ID, Attribute] = Field(default_factory=dict)
    languages: List[str] = Field(default_factory=lambda: ["en", "it"])

    model_config = {
        "arbitrary_types_allowed": True
    }



    def get_concept(self, id: ID) -> Concept | None:
        return self.concepts.get(id)


    def get_relation(self, id: ID) -> Relation | None:
        return self.relations.get(id)

    def get_attribute(self, id: ID) -> Attribute | None:
        return self.attributes.get(id)


    def add_concept(self, concept: Concept, validate=True) -> 'Ontology':
        if concept.id not in self.concepts:
            if validate and not validate_predicate_hierarchy(concept, self.concepts):
                raise Exception(f"Inconsistent concept: {concept.id}")
            self.concepts[concept.id] = concept
        else:
            raise ValueError(f"Concept {concept} already in ontology")
        return self


    def add_relation(self, relation: Relation, validate=True) -> 'Ontology':
        if relation.id not in self.relations:
            if validate and not validate_predicate_hierarchy(relation, self.concepts | self.relations):
                raise Exception(f"Inconsistent relation: {relation.id}")
            self.relations[relation.id] = relation
        else:
            raise ValueError(f"Relation {relation} already in ontology")


    def add_attribute(self, attribute: Attribute, validate=True) -> 'Ontology':
        if attribute.id not in self.attributes:
            if validate and not validate_predicate_hierarchy(attribute, self.concepts | self.attributes):
                raise Exception(f"Inconsistent attribute: {attribute.id}")
            self.attributes[attribute.id] = attribute
        else:
            raise ValueError(f"Attribute {attribute} already in ontology")
        return self



class OWLOntology(Ontology):
    """
    OWL ontology representation.
    """

    _graph: Graph = PrivateAttr(default=None)

    model_config = {
        "arbitrary_types_allowed": True
    }

    def _get_literal_values(self, subject: URIRef, predicate: URIRef) -> list[str]:
        """Helper function to get literal values with language tag preference."""
        # First try with language tag
        values = []
        for obj in self._graph.objects(subject, predicate):
            if isinstance(obj, Literal) and obj.language in self.languages:
                values.append(str(obj))

        # If not found, try without language tag
        if not values:
            for obj in self._graph.objects(subject, predicate):
                if isinstance(obj, Literal):
                    values.append(str(obj))

        return values


    def _load_concepts_from_graph(self) -> Dict[str, Concept]:
        """
        Load concepts from an RDF graph.

        Returns:
            A dictionary mapping concept URIs to Concept objects
        """
        concepts: Dict[str, Concept] = {}

        # First pass: Create all concepts
        for subject in self._graph.subjects(RDF.type, OWL.Class):
            if isinstance(subject, URIRef):
                concept = Concept(id=ID(str(subject)))
                concepts[str(subject)] = concept

        # Second pass: Add relationships
        for subject, predicate, obj in self._graph:
            if not isinstance(subject, URIRef) or str(subject) not in concepts:
                continue

            concept = concepts[str(subject)]

            # Handle subclass relationships (parents)
            if predicate == RDFS.subClassOf and isinstance(obj, URIRef):
                concept.add_parent(str(obj))

            # Handle disjoint relationships
            elif predicate == OWL.disjointWith and isinstance(obj, URIRef):
                concept.add_disjoint(str(obj))

            labels = self._get_literal_values(subject, RDFS.label)
            if labels:
                concept.labels = labels

            # Get comment (try RDFS comment)
            comments = self._get_literal_values(subject, RDFS.comment)
            if comments:
                concept.comments = comments

        return concepts


    def _load_attributes_from_graph(self) -> Dict[str, Attribute]:
        """
        Load attributes (data properties) from an RDF graph.

        Returns:
            Dictionary mapping attribute URIs to Attribute objects
        """
        attributes: Dict[str, Attribute] = {}

        # Find all data properties
        for subject in self._graph.subjects(RDF.type, OWL.DatatypeProperty):
            if not isinstance(subject, URIRef):
                continue

            uri = str(subject)
            attribute = Attribute(id=ID(uri))
            # Get domain
            for domain in self._graph.objects(subject, RDFS.domain):
                if isinstance(domain, URIRef) and str(domain) in self.concepts:
                    attribute.set_domain(ID(str(domain)))
                    break

            # Get range (data type)
            for range_type in self._graph.objects(subject, RDFS.range):
                if isinstance(range_type, URIRef):
                    data_type = DataType.from_uri(str(range_type))
                    if data_type:
                        attribute.set_range(data_type)
                        break

            # Get parent properties
            for parent in self._graph.objects(subject, RDFS.subPropertyOf):
                if isinstance(parent, URIRef):
                    attribute.add_parent(str(parent))

            labels = self._get_literal_values(subject, RDFS.label)
            if labels:
                attribute.labels = labels

            # Get comment (try RDFS comment)
            comments = self._get_literal_values(subject, RDFS.comment)
            if comments:
                attribute.comments = comments


            attributes[uri] = attribute

        return attributes

    def _load_relations_from_graph(self) -> Dict[str, Relation]:
        """
        Load relations (object properties) from an RDF graph.

        Returns:
            Dictionary mapping relation URIs to Relation objects
        """
        relations: Dict[str, Relation] = {}

        # First pass: Create all relations
        for subject in self._graph.subjects(RDF.type, OWL.ObjectProperty):
            if not isinstance(subject, URIRef):
                continue

            uri = str(subject)
            relation = Relation(id=ID(uri))
            relations[uri] = relation

        # Second pass: Set properties and handle inverse relationships
        for uri, relation in relations.items():
            subject = URIRef(uri)

            # Get domain
            for domain in self._graph.objects(subject, RDFS.domain):
                if isinstance(domain, URIRef) and str(domain) in self.concepts:
                    relation.set_domain(ID(str(domain)))
                    break

            # Get range
            for range_val in self._graph.objects(subject, RDFS.range):
                if isinstance(range_val, URIRef) and str(range_val) in self.concepts:
                    relation.range = ID(str(range_val))
                    break

            # Get parent properties
            for parent in self._graph.objects(subject, RDFS.subPropertyOf):
                if isinstance(parent, URIRef):
                    relation.add_parent(str(parent))

            # Get inverse relationship
            for inverse in self._graph.objects(subject, OWL.inverseOf):
                if isinstance(inverse, URIRef):
                    relation.inverse = ID(str(inverse))
                    break

            labels = self._get_literal_values(subject, RDFS.label)
            if labels:
                relation.labels = labels

            # Get comment (try RDFS comment)
            comments = self._get_literal_values(subject, RDFS.comment)
            if comments:
                relation.comments = comments


        return relations


    def model_post_init(self, __context) -> None:
        if not self._graph:
            if not self.source:
                raise ValueError("No source provided")
            if not self.publicIRI:
                raise ValueError("No public IRI provided")
            if not self.source_format:
                self.source_format = "turtle"
            self._graph = Graph()
            self._graph.parse(source=self.source, publicID=self.publicIRI, format=self.source_format)

        # Load concepts, attributes, and relations, keeping the order
        self.concepts = self._load_concepts_from_graph()
        self.attributes = self._load_attributes_from_graph()
        self.relations = self._load_relations_from_graph()






VOID_ONTOLOGY = """
    @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    <http://isagog.com/ontologies/void> rdf:type owl:Ontology .
    """

VoidOntology = OWLOntology(
    source=StringIO(VOID_ONTOLOGY),
    publicIRI="http://isagog.com/ontologies/void",
)
