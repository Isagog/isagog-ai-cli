# pylint: disable=W,C,R
"""
 Terminological module (box)
 Defines ontology and related classes

"""
from io import StringIO
from typing import IO, Optional, TextIO

from rdflib import OWL, RDF, RDFS, Graph
from rdflib.term import Literal

from isagog.model.kg_model import ID, Concept, Relation, Attribute


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
            category_annotation=ID(
                "https://isagog.com/ontologies/top#meta"
            ),
    ):
        """
        :param source:  Path to the ontology source file.
        :param publicIRI:  Base IRI for the ontology.
        :param source_format:  Format of the ontology.
        :param category_annotation:  Annotation marker for categories.
        """
        Graph.__init__(self, identifier=publicIRI)
        self.parse(source=source, publicID=publicIRI, format=source_format)
        self.categories = [
            Concept(id=cls)
            for cls in self.subjects(
                predicate=category_annotation, object=Literal("CATEGORY")
            )
            if isinstance(cls, ID)
        ]

        self.concepts = [
            Concept(id=cls)
            for cls in self.subjects(predicate=RDF.type, object=OWL.Class)
            if isinstance(cls, ID)
        ]
        self.relations = [
            Relation(id=rl)
            for rl in self.subjects(
                predicate=RDF.type, object=OWL.ObjectProperty
            )
            if isinstance(rl, ID)
        ]
        self.attributes = [
            Attribute(id=att)
            for att in self.subjects(
                predicate=RDF.type, object=OWL.DatatypeProperty
            )
            if isinstance(att, ID)
        ]
        for ann in self.subjects(
                predicate=RDF.type, object=OWL.AnnotationProperty
        ):
            if isinstance(ann, ID):
                self.attributes.append(Attribute(id=ann))

        self._submap = dict[Concept, list[Concept]]()

    def subclasses(self, sup: Concept) -> list[Concept]:
        """
        Gets direct subclasses of a given concept.
        """
        if sup not in self._submap:
            self._submap[sup] = [
                Concept(id=sc)
                for sc in self.subjects(predicate=RDFS.subClassOf, object=sup.id)
                if isinstance(sc, ID)
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

    def categorize(self, classes: list[Concept]) -> Optional[Concept]:
        """
        Finds the category for the given concept.
        :param classes: the classes to categorize
        :return:
        """
        for cls in classes:
            for _c in self.categories:
                if self.is_subclass(cls, _c):
                    return _c
        return None

    def get_concept(self, candidate: str) -> Concept | None:
        return next((item for item in self.concepts if str(item.id) == candidate), None)

    def get_relation(self, candidate: str) -> Relation | None:
        return next((item for item in self.relations if str(item.id) == candidate), None)

    def get_attribute(self, candidate: str) -> Attribute | None:
        return next((item for item in self.attributes if str(item.id) == candidate), None)


VOID_ONTOLOGY = """
    @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    <http://isagog.com/ontologies/void> rdf:type owl:Ontology .
    """

VoidOntology = Ontology(
    source=StringIO(VOID_ONTOLOGY),
    publicIRI="http://isagog.com/ontologies/void",
)
