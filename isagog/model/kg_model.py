"""
 Isagog Knowledge Graph Model
 (c) 2024 Isagog Srl
"""
import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Dict, Any, Set


from pydantic import BaseModel, Field
from pydantic_core import core_schema
from rdflib import Literal, OWL, RDFS


class N3Serializable(ABC):

    @abstractmethod
    def n3(self, **kwargs) -> str:
        pass

class N3String(str, N3Serializable):
    """
    A string class that supports N3 serialization.
    """

    class Config:
        arbitrary_types_allowed = True

    def __new__(cls, content: Any):
        # Ensure the content is converted to a string
        return super().__new__(cls, str(content))

    def n3(self) -> str:
        """
        Return the N3 serialization of the string.
        """
        # Escape special characters
        # Check if the string is a valid URI
        uri_pattern = re.compile(r'^https?://[\w\-]+(\.[\w\-]+)+[/#?]?.*$')
        if uri_pattern.match(self):
            return f"<{self}>"

        # Escape special characters
        s = self.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')

        # Check if the string contains any characters outside the ASCII range
        if any(ord(c) > 127 for c in s):
            return f'"""{s}"""'
        else:
            return f'"{s}"'

    def __repr__(self) -> str:
        return f'N3String({super().__repr__()})'

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type, handler
    ) -> core_schema.CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema([
                core_schema.is_instance_schema(cls),
                core_schema.chain_schema([
                    core_schema.str_schema(),
                    core_schema.no_info_plain_validator_function(cls)
                ])
            ]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: str(instance)
            )
        )


ID = N3String


class DataType(str, Enum):
    STRING = "xsd:string"
    INTEGER = "xsd:integer"
    FLOAT = "xsd:float"
    BOOLEAN = "xsd:boolean"
    DATE = "xsd:date"
    DATETIME = "xsd:dateTime"

    def n3(self) -> str:
        return str(self.value)

    @classmethod
    def from_uri(cls, uri: str) -> Optional['DataType']:
        uri = str(uri).lower()
        for dt in cls:
            if dt.value.lower() in uri:
                return dt
        return None




def _uri_label(uri: str) -> str:
    """Extract a human-readable label from a URI."""
    # Get the last part of the URI after the last / or #
    label = str(uri).split('/')[-1].split('#')[-1]
    # Convert camelCase or snake_case to space-separated words
    # You might want to customize this based on your URI patterns
    return label.replace('_', ' ').replace('-', ' ')

class KnowledgeObject(BaseModel, N3Serializable, ABC):
    """
    Base class for all knowledge objects.
    Each object has an ID, which is a unique identifier, at least a label and optionally some comment.
    """
    id: ID = Field(
        ...,
        description="The unique identifier of the object, which supports n3 serialization."
    )
    labels: List[str] = Field(
        default_factory=list,
        description="The human-readable labels of the object. If missing or void, a default label is generated from the ID."
    )
    comments: Optional[List[str]] = Field(
        default_factory=list,
        description="The human-readable comments of the object."
    )

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, cls):
            return v
        if isinstance(v, dict):
            return cls(**v)
        if isinstance(v, str):
            # Assuming you want to create an object from a string ID
            return cls(id=v)
        raise ValueError(f'Cannot create {cls.__name__} from {type(v)}')

    def __init__(self, **data):
        # Convert id to N3String if it's another type
        if 'id' in data and not isinstance(data['id'], N3String):
            data['id'] = N3String(str(data['id']))

        # Initialize labels list if not present
        if 'labels' not in data or not data['labels']:
            data['labels'] = [_uri_label(data['id'])]
        elif isinstance(data['labels'], str):
            # Handle case where single string is provided
            data['labels'] = [data['labels']]

        # Initialize comments as empty list if not present
        if 'comments' not in data:
            data['comments'] = []
        elif isinstance(data['comments'], str):
            # Handle case where single string is provided
            data['comments'] = [data['comments']]

        super().__init__(**data)

    def add_label(self, label: str) -> None:
        """Add a label to the object."""
        if not self.labels:
            self.labels = []
        if label not in self.labels:
            self.labels.append(label)

    def add_comment(self, comment: str) -> None:
        """Add a comment to the object."""
        if not self.comments:
            self.comments = []
        if comment not in self.comments:
            self.comments.append(comment)

    def get_primary_label(self) -> str:
        """Get the primary (first) label of the object."""
        return self.labels[0] if self.labels else _uri_label(self.id)


class Predicate(KnowledgeObject):
    """
    Represents any predicate.
    """
    parents: Optional[Set[ID]] = Field(default_factory=set, description="The parent concepts of this concept.")
    disjoint: Optional[Set[ID]] = Field(default_factory=set, description="The disjoint concepts of this concept.")

    def add_parent(self, uri: str | ID):
        if isinstance(uri, str):
            uri = ID(uri)
        self.parents.add(uri)

    def add_disjoint(self, uri: str| ID):
        if isinstance(uri, str):
            uri = ID(uri)
        self.disjoint.add(uri)

    def n3(self) -> str:
        result = super().n3() + "\n"
        for parent in self.parents:
            result += f"{self.id.n3()} rdfs:subPropertyOf {parent.n3()} .\n"
        for disjoint in self.disjoint:
            result += f"{self.id.n3()} owl:disjointWith {disjoint.n3()} .\n"
        return result.strip()




class Concept(Predicate):
    """
    Represents a unary predicate in the knowledge base.
    """


    def n3(self) -> str:
        result = f"{self.id.n3()} a owl:Class .\n"
        result += super().n3() + "\n"
        return result.strip()


class Property(Predicate):
    """
    Represents a binary predicate (type) in the knowledge base.
    """

    domain: Optional[ID] = Field(None, description="The domain of the property, represented as an ID. Specifies the type of concepts this property can be applied to.")

    def set_domain(self, ref: ID):
        self.domain = ref

    def n3(self) -> str:
        result = f"{self.id.n3()} a rdf:Property .\n"
        if self.domain:
            result += f"{self.id.n3()} rdfs:domain {self.domain.n3()} .\n"
        for parent in self.parents:
            result += f"{self.id.n3()} rdfs:subPropertyOf {parent.n3()} .\n"
        result += super().n3() + "\n"
        return result.strip()




class Attribute(Property):
    """
    Represents a property that has a range on data types.
    """
    range: DataType = Field(
        None,
        description="The data type of the attribute's value. Specifies what kind of data this attribute can hold."
    )

    def set_range(self, data_type: DataType):
        self.range = data_type

    def n3(self) -> str:
        result = super().n3() + "\n"
        if self.range:
            result += f"{self.id.n3()} rdfs:range {self.range.n3()} .\n"
        result += super().n3() + "\n"
        return result.strip()

class Relation(Property):
    """
    Represents a property that has a range on knowledge objects.
    """

    range: Optional[ID] = Field(
        None,
        description="The range of the relation, represented as ID. Specifies the type of concepts this relation can point to."
    )
    inverse: Optional[ID] = Field(
        None,
        description="The ID of the inverse relation, if it exists. For example, if this relation is 'parent', the inverse might be 'child'."
    )

    def set_range(self, ref: ID):
        self.range = ref

    def set_inverse(self, ref: ID):
        self.inverse = ref

    def n3(self) -> str:
        result = super().n3() + "\n"
        if self.range:
            result += f"{self.id.n3()} rdfs:range {self.range.n3()} .\n"
        if self.inverse:
            result += f"{self.id.n3()} owl:inverseOf {self.inverse.n3()} .\n"
        return result.strip()


class Assertion(BaseModel, N3Serializable, ABC):
    """
    Represents a statement in the knowledge base.
    """
    property: ID = Field(
        ...,  # The field is required
        description="The predicate of the assertion, represented as an ID."
    )
    subject: Optional[ID] = Field(None,
                                  description="The subject of the assertion, represented as an ID. If missing, should be inferred from the context.")



class AttributeAssertion(Assertion):
    """
    Represents an attribute assertion in the knowledge base.
    """
    values: List[N3String] = Field(
        [],
        description="The values of the attribute, represented as n3 serializable string."
    )

    class Config:
        title = "AttributeAssertion"
        description = "Represents an attribute assertion in the knowledge base."

    def n3(self) -> str:
        if self.subject is None or not self.values:
             raise ValueError("Both subject and object must be present for N3 serialization")
        subject_n3 = self.subject.n3()
        predicate_n3 = self.property.n3()
        result = ""
        for value in self.values:
           result += f"{subject_n3} {predicate_n3} {value.n3()} .\n"
        return result

class RelationAssertion(Assertion):
    """
    Represents a relation assertion in the knowledge base.
    """
    objects: List[KnowledgeObject] = Field(
        [],
        description="The object (individual) of the relation, represented as an ID."
    )

    class Config:
        title = "RelationAssertion"
        description = "Represents a relation assertion in the knowledge base."

    def n3(self) -> str:
        if self.subject is None or not self.objects:
             raise ValueError("Both subject and object must be present for N3 serialization")
        subject_n3 = self.subject.n3()
        predicate_n3 = self.property.n3()
        result = ""
        for obj in self.objects:
           result += f"{subject_n3} {predicate_n3} {obj.id.n3()} .\n"
        return result

SCORE_ANNOTATION = ID("https://isagog.com/ontology#score")

class Individual(KnowledgeObject):
    """
    Represents an individual in the knowledge base.
    """
    kind: List[ID] = Field(default_factory=list,
                           description="The kind of the individual, represented as a list of IDs. Specifies the ("
                                       "possibly composed) type of the individual.")
    attributes: Optional[List[AttributeAssertion]] = Field(None,
                                                           description="The attributes of the individual, represented "
                                                                       "as a list of AttributeAssertion objects.")
    relations: Optional[List[RelationAssertion]] = Field(None,
                                                         description="The relations of the individual, represented as "
                                                                     "a list of RelationAssertion objects.")
    score: Optional[float] = Field(None,
                                   description="The score of the individual, if it has been constructed within "
                                               "scoring funcions (e.g. search or queries.")

    class Config:
        title = "Individual"
        description = "Represents an individual in the knowledge base."

    def add_kind(self, concept: ID):
        if isinstance(self.kind, list):
            if concept not in self.kind:
                self.kind.append(concept)
        else:
            self.kind = [self.kind, concept]

    def add_relation(self, relation: ID, obj: ID | KnowledgeObject):
        if self.relations is None:
            self.relations = []
        relation_assertion = self.get_relation(relation)
        if not relation_assertion:
            relation_assertion = RelationAssertion(property=relation)
            self.relations.append(relation_assertion)
        if isinstance(obj, ID):
            obj = KnowledgeObject(id=obj)
            relation_assertion.objects.append(obj)
        elif isinstance(obj, KnowledgeObject):
            relation_assertion.objects.append(obj)
        else:
            raise ValueError("Invalid object type")

    def add_attribute(self, attribute: ID, value: str | int | float | bool):
        if self.attributes is None:
            self.attributes = []
        attribute_assertion = self.get_attribute(attribute)
        if not attribute_assertion:
            attribute_assertion = AttributeAssertion(property=attribute)
            self.attributes.append(attribute_assertion)
        attribute_assertion.values.append(N3String(value))

    def get_labels(self) -> List[str]:
        return [a.value for a in self.attributes if a.property == RDFS.label]

    def get_comments(self) -> List[str]:
        return [a.value for a in self.attributes if a.property == RDFS.comment]

    def set_score(self, score: float):
        self.score = score

    def has_score(self) -> bool:
        return self.score is not None

    def get_score(self) -> Optional[float]:
        return self.score

    def get_attribute(self, property_id: ID) -> Optional[AttributeAssertion]:
        return next((attr for attr in self.attributes if attr.property == property_id), None)

    def get_relation(self, property_id: ID) -> Optional[RelationAssertion]:
        return next((rel for rel in self.relations if rel.property == property_id), None)

    def n3(self, **kwargs) -> str:

        result = super().n3() + "\n"
        result += f"{self.id.n3()} a owl:NamedIndividual"
        for k in self.kind:
            result += f", {k.n3()}"
        result += " .\n"

        for attr in self.attributes or []:
            attr.subject = self.id
            result += attr.n3()

        for rel in self.relations or []:
            rel.subject = self.id
            result += rel.n3()

        for comment in self.comments or []:
            result += f"{self.id.n3()} rdfs:comment {N3String(comment).n3()} .\n"

        if self.score is not None:
            result += f"{self.id.n3()}  {SCORE_ANNOTATION.n3()} {self.score} .\n"

        return result.strip()


def get_ancestors(predicate_id: ID, predicate_map: Dict[ID, Predicate], visited: Set[ID] = None) -> Set[ID]:
    """
    Helper function to get all ancestors (parents and their parents) of a predicate.
    Uses recursion with cycle detection.
    """
    if visited is None:
        visited = set()

    if predicate_id in visited:
        return set()

    visited.add(predicate_id)
    current_predicate = predicate_map.get(predicate_id)

    if not current_predicate or not current_predicate.parents:
        return set()

    ancestors = set(current_predicate.parents)
    for parent_id in current_predicate.parents:
        parent_ancestors = get_ancestors(parent_id, predicate_map, visited)
        ancestors.update(parent_ancestors)

    return ancestors


def validate_predicate_hierarchy(predicate: Predicate, predicate_map: Dict[ID, Predicate]) -> bool:
    """
    Validates that a predicate's hierarchy is consistent by checking:
    1. No cycles in the parent hierarchy
    2. No disjoint predicates in the ancestor chain

    Args:
        predicate: The predicate to validate
        predicate_map: A mapping of ID to Predicate objects to look up related predicates

    Returns:
        bool: True if the hierarchy is valid, False otherwise
    """
    # First check: Detect cycles in the hierarchy
    visited = set()
    to_visit = {predicate.id}

    while to_visit:
        current_id = to_visit.pop()
        if current_id in visited:
            # Cycle detected
            return False

        visited.add(current_id)
        current_predicate = predicate_map.get(current_id)

        if current_predicate and current_predicate.parents:
            to_visit.update(current_predicate.parents)

    # Second check: Verify no disjoint predicates in ancestor chain
    # Get all ancestors including parents of parents
    all_ancestors = get_ancestors(predicate.id, predicate_map)

    # Check if any of the disjoint predicates appear in the ancestor chain
    if predicate.disjoint:
        if any(disj_id in all_ancestors for disj_id in predicate.disjoint):
            return False

    # Check if any ancestor's disjoint predicates conflict with other ancestors
    for ancestor_id in all_ancestors:
        ancestor = predicate_map.get(ancestor_id)
        if ancestor and ancestor.disjoint:
            if any(disj_id in all_ancestors for disj_id in ancestor.disjoint):
                return False

    return True




# Constants and definitions
Thing = Concept(id=OWL.Thing)

Predicate = Relation | Attribute | ID

Value = Literal | str | int | float

Argument = Value | KnowledgeObject

Assertions = Dict[Predicate, List[Argument]]

Binding = Dict[str, ID | Value]
