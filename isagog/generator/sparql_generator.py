"""
SPARQL query generator
(c) Isagog S.r.l. 2024, MIT License
"""
import logging
from io import StringIO
from typing import Tuple

from isagog.model.query_model import Generator, Clause, Value
from isagog.model.query_model import UnaryQuery, AtomicClause, Comparison, Variable, \
    ConjunctiveClause, DisjunctiveClause, SCORE_VARIABLE, Select, META_PROPERTIES


def _comparison_op(comparison: Comparison) -> str:
    match comparison:
        case Comparison.GREATER:
            return ">"
        case Comparison.LESSER:
            return "<"
        case Comparison.GREATER_EQUAL:
            return ">="
        case Comparison.LESSER_EQUAL:
            return "<="
        case Comparison.EQUAL:
            return "="
        case _:
            raise ValueError(f"Unsupported comparison {comparison}")




class SPARQLGenerator(Generator):
    """
    SPARQL query generator
    """


    def __init__(self):
        super().__init__(language="SPARQL")
        self.var_count = 0


    def fresh_variable(self) -> Variable:
        self.var_count += 1
        return Variable(symbol=f"?_v{self.var_count}")

    def _atomic_clause(self, clause: AtomicClause, strio: StringIO) -> None:
        """
        Generates the sparql triple clause
        """

        if not clause.is_defined():
            raise ValueError(f"Clause not defined {clause.subject} {clause.property} {clause.argument}")

        # todo add support for meta properties
        if str(clause.property) == META_PROPERTIES.IN.value:
            return f"FILTER ({clause.subject} IN ({clause.argument})) .\n"

        if clause.optional:
            strio.write("OPTIONAL {")
        comparison = Comparison(clause.operator)
        match comparison:
            case Comparison.EXACT | Comparison.ANY:
                strio.write(clause.n3())  # f"{self.subject} {self.property} {self.argument}"
            case Comparison.REGEX:
                strio.write(self._regex_clause(clause, strio=strio))
            case Comparison.KEYWORD:
                strio.write( f'({clause.subject} ?{SCORE_VARIABLE}) text:query "{clause.argument}"')

            case Comparison.NOT_EXISTS:
                var = self.fresh_variable()
                strio.write( f'FILTER NOT EXISTS {{ {clause.subject} {clause.property.n3()} {var} }}')
            case Comparison.SIMILARITY:
                pass
            case _:
                self._comparative_clause(clause, comparison, strio)



        if clause.optional:
                strio.write(" }\n")
        else:
            strio.write( " .\n")



    def _conjunctive_clause(self, clause: ConjunctiveClause, strio: StringIO):
        """
        Generates the sparql triple clause
        """

        if len(clause.clauses) > 1:
            if clause.optional:
                strio.write("OPTIONAL")
            strio.write("\t{\n")
            for sub_clause in clause.clauses:  # [1:]:
                strio.write("\t\t\t" + self.generate_clause(sub_clause))  # sub_clause.to_sparql())
            strio.write("\t\t}\n")
            # strio.write("\t}\n")
        else:
            strio.write("\t\t\t" + self.generate_clause(clause.clauses[0]))  # clause.clauses[0].to_sparql())



    def _disjunctive_clause(self, clause: DisjunctiveClause, strio: StringIO):

        if len(clause.clauses) > 1:
            strio.write("\t{\n")

            strio.write("\t\t{\n")
            self.generate_clause(clause.clauses[0], strio=strio)
            strio.write("\t\t}\n")

            strio.write("\tUNION {\n")
            for constraint in clause.clauses[1:]:
                strio.write("\t\t\t")
                self.generate_clause(constraint, strio=strio)
            strio.write("\t\t}\n")
            strio.write("\t}\n")
        else:
            strio.write("\tUNION {\n")
            strio.write("\t\t\t")
            self.generate_clause(clause.clauses[0], strio=strio)  # clause.clauses[0].to_sparql())
            strio.write("\t}\n")


    def _regex_clause(self, clause: AtomicClause, strio: StringIO):

        tmp_var = self.fresh_variable()  # self._temp_var()
        strio.write(f"{clause.subject} {clause.property.n3()} {tmp_var} .\n")
        if isinstance(clause.argument.constraint, Value):
            strio.write(f'\n\t\tFILTER  regex({tmp_var}, "{clause.argument.constraint}", "i")')
        elif isinstance(clause.argument.constraint, Tuple):
            tmp_subvar = self.fresh_variable()
            strio.write(f"\t\t\t{tmp_var} {clause.argument.constraint[0].n3()} {tmp_subvar}\n")
            strio.write(f'\n\t\t\tFILTER  regex({tmp_subvar}, "{clause.argument.constraint[1]}", "i")')
        else:
            raise ValueError(f"Unsupported regex constraint {clause.argument.constraint}")

    def _comparative_clause(self, clause: AtomicClause, comparison: Comparison, strio: StringIO):

        match clause.get_argument_class():
            case 'Value':
                var = self.fresh_variable()
                strio.write(f"{clause.subject} {clause.property.n3()} {var}\n")
                strio.write(f'\t\tFILTER ({var} {_comparison_op(comparison)} "{clause.argument}")')
            case 'Variable':
                if not clause.argument.constraint:
                    raise ValueError(f"Variable constraint not defined {clause.argument}")
                strio.write(f"{clause.subject} {clause.property.n3()} {clause.argument}\n")
                strio.write(f'\t\tFILTER ({clause.argument} {_comparison_op(comparison)} "{clause.argument.constraint}")')
            case _:
                raise ValueError(f"Bad argument type {clause.argument_type()}")


    def generate_clause(self, clause: Clause, **kwargs) -> str:
      strio = kwargs.get('strio', StringIO())
      try:
        if isinstance(clause, AtomicClause):
            self._atomic_clause(clause, strio)
        elif isinstance(clause, ConjunctiveClause):
            self._conjunctive_clause(clause, strio)
        elif isinstance(clause, DisjunctiveClause):
            self._disjunctive_clause(clause, strio)
        else:
            raise ValueError("Unsupported clause type")
      except Exception as e:
          logging.error(f"Error in generate_clause: {e}", exc_info=True)
      return ""


    def generate_query(self, query: UnaryQuery, **kwargs) -> str:
       """
        Generates a SPARQL query from a SelectQuery
        :param query:
        :param kwargs:
        :return:
       """
       self.var_count = 0
       try:
            if kwargs.get('optimize', True):
                query.sort_clauses()

            if not isinstance(query, UnaryQuery):
                raise TypeError("Can only generate_query from Query")

            # generate the prefixes
            strio = StringIO()
            for (name, uri) in query.prefixes.items():
                if uri.endswith("#") or uri.endswith("/"):
                    strio.write(f"PREFIX {name}: <{uri}>\n")
                else:
                    strio.write(f"PREFIX {name}: <{uri}#>\n")

            # generate the select header
            strio.write("SELECT distinct ")
            for rv in query.project_vars():
                strio.write(f" {rv} ")
            if query.is_scored():
                strio.write(f" {SCORE_VARIABLE} ")
            strio.write(" WHERE {\n")

            # generate the clauses
            for clause in query.clauses:
                self.generate_clause(clause, strio=strio)
            strio.write("\n}\n")
            # generate the score filter
            if query.is_scored():
                strio.write(f'\tFILTER (?{SCORE_VARIABLE} >= {query.min_score})\n')
                strio.write(f"ORDER BY DESC(?{SCORE_VARIABLE})\n")

            # generate the limit
            if query.limit > 0:
                strio.write(f"LIMIT {query.limit}\n")

            rt = strio.getvalue()
            strio.close()
            return rt

       except Exception as e:
                logging.error(f"Error in generate_query: {e}", exc_info=True)



_SPARQLGEN = SPARQLGenerator()
