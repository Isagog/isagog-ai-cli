from typing import IO, TextIO

from rdflib import OWL, Graph, RDF, URIRef, RDFS

from isagog.model.kg_model import Relation, Concept, Attribute


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
            Concept(id=cls)
            for cls in self.subjects(predicate=RDF.type, object=OWL.Class)
            if isinstance(cls, URIRef)
        ]
        self.relations = [
            Relation(id=rl)
            for rl in self.subjects(
                predicate=RDF.type, object=OWL.ObjectProperty
            )
            if isinstance(rl, URIRef)
        ]
        self.attributes = [
            Attribute(id=att)
            for att in self.subjects(
                predicate=RDF.type, object=OWL.DatatypeProperty
            )
            if isinstance(att, URIRef)
        ]
        for ann in self.subjects(
                predicate=RDF.type, object=OWL.AnnotationProperty
        ):
            if isinstance(ann, URIRef):
                self.attributes.append(Attribute(id=ann))

        self._submap = dict[Concept, list[Concept]]()

    def subclasses(self, sup: Concept) -> list[Concept]:
        """
        Gets direct subclasses of a given concept
        """
        if sup not in self._submap:
            self._submap[sup] = [
                Concept(id=sc)
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
