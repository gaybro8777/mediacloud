"""Functions for manipulating Solr queries."""

import abc
import inspect
import io
import shlex
import re

from tokenize import generate_tokens
from typing import List, Callable, Union

from mediawords.util.log import create_logger
from mediawords.util.perl import decode_string_from_bytes_if_needed

l = create_logger(__name__)

# Token types
T_OPEN = 'open paren'
T_CLOSE = 'close paren'
T_PHRASE = 'phrase'
T_AND = 'and'
T_OR = 'or'
T_NOT = 'not'
T_FIELD = 'field'
T_TERM = 'term'
T_PLUS = 'plus'
T_MINUS = 'minus'
T_NOOP = 'noop'

# this text will be considered a noop token
NOOP_PLACEHOLDER = '__NOOP__'

# replace ':' with this before tokenization so that it gets included with the field name
FIELD_PLACEHOLDER = '__FIELD__'

# replace '*' with this before tokenization so that it gets included with the term
WILD_PLACEHOLDER = '__WILD__'


class Token(object):
    """Object that holds the token value and type. type should one of T_* above """

    token_type = None
    token_value = None

    def __init__(self, token_value, token_type):
        self.token_value = token_value
        self.token_type = token_type

    def __repr__(self):
        return "[ %s: %s ]" % (self.token_type, self.token_value)

    def __str__(self):
        return self.__repr__()


class AbstractParseNode(object):
    __metaclass__ = abc.ABCMeta

    field = None
    operand = None
    parent = None
    filtered_by_function = None
    operands = []

    @abc.abstractmethod
    def get_re(self, operands: list = None) -> str:
        raise NotImplementedError("Abstract method")

    @abc.abstractmethod
    def get_tsquery(self) -> str:
        raise NotImplementedError("Abstract method")

    @abc.abstractmethod
    def filter_tree(self, filter_function):
        raise NotImplementedError("Abstract method")


class ParseNode(AbstractParseNode):
    """Parent class for universal methods for *Node classes."""

    @abc.abstractmethod
    def _filter_node_children(self, filter_function):
        raise NotImplementedError("Abstract method")

    @abc.abstractmethod  # further clarify parameter type of get_re()
    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        raise NotImplementedError("Abstract method")

    @staticmethod
    def __node_is_field_or_noop(node: AbstractParseNode) -> bool:
        """Return true if the field is a non-sentence field or is a noop."""

        if (type(node) is FieldNode) and (node.field != 'sentence'):
            return True
        elif type(node) is NoopNode:
            return True

        return False

    @staticmethod
    def __node_is_field_or_noop_or_not(node: AbstractParseNode) -> bool:
        """Return true if the field is a non-sentence field or is a noop."""

        if (type(node) is FieldNode) and (node.field != 'sentence'):
            return True
        elif type(node) in (NoopNode, NotNode):
            return True

        return False

    def __str__(self):
        return self.__repr__()

    def _filter_boolean_node_children(self, filter_function: Callable[[AbstractParseNode], bool]) \
            -> Union[AbstractParseNode, None]:

        boolean_type = type(self)
        filtered_operands = []
        for operand in self.operands:
            filtered_operand = operand.filter_tree(filter_function)
            if filtered_operand:
                filtered_operands.append(filtered_operand)

        if len(filtered_operands) > 0:
            return boolean_type(filtered_operands)
        else:
            return None

    def filter_tree(self, filter_function: Callable[[AbstractParseNode], bool]) -> Union[AbstractParseNode, None]:
        """ filter all nodes from the tree for which filter_function returns tree.
        so if the filter is lamda x: type( x ) is NotNode then '( foo and !bar ) or baz' will be filtered to
        '( foo ) or baz'
        """

        try:
            if self.filtered_by_function == filter_function:
                return self
        except AttributeError:
            pass

        if filter_function(self):
            return None
        else:
            filtered_tree = self._filter_node_children(filter_function)
            if filtered_tree:
                filtered_tree.filtered_by_function = filter_function
            return filtered_tree

    def tsquery(self) -> str:
        """ return a postgres tsquery that represents the parse tree """

        filtered_tree = self.filter_tree(self.__node_is_field_or_noop)

        if filtered_tree is None:
            raise ParseSyntaxError("query is empty without fields or ranges")

        return filtered_tree.get_tsquery()

    def re(self) -> str:
        """ return a posix regex that represents the parse tree """

        filtered_tree = self.filter_tree(self.__node_is_field_or_noop_or_not)

        if filtered_tree is None:
            raise ParseSyntaxError("query is empty without fields or ranges")

        return filtered_tree.get_re()


class TermNode(ParseNode):
    """ parse node type for a simple keyword """

    def __init__(self, term, wildcard=False, phrase=False):
        self.term = term
        self.wildcard = wildcard
        self.phrase = phrase

    def __repr__(self):
        return self.term if (not self.wildcard) else self.term + "*"

    def get_tsquery(self) -> str:
        if self.phrase:
            dequoted_phrase = shlex.split(self.term)[0]
            operands = []
            for term in re.split('\W+', dequoted_phrase):
                if term:
                    operands.append(TermNode(term))

            if len(operands) == 0:
                raise ParseSyntaxError("empty phrase not allowed")

            return AndNode(operands).get_tsquery()
        else:
            return self.term if (not self.wildcard) else self.term + ":*"

    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        term = self.term
        if self.phrase:
            term = shlex.split(term)[0]

            # should already be lower case, but make sure
            term = term.lower()

            # replace spaces with placeholder text so that we can replace it with [[:space:]] after re.escape
            term = re.sub(r'\s+', 'SPACE', term)

            term = re.escape(term)
            term = re.sub('SPACE', '[[:space:]]+', term)

            return '[[:<:]]' + term
        else:
            return '[[:<:]]' + re.escape(term)

    def _filter_node_children(self, filter_function: Callable[[AbstractParseNode], bool]) \
            -> Union[AbstractParseNode, None]:
        return TermNode(self.term, wildcard=self.wildcard, phrase=self.phrase)


class BooleanNode(ParseNode):
    """Super class for ANDs and ORs."""

    def __init__(self, operands):
        self.operands = operands
        for operand in operands:
            operand.parent = self

    def _plain_connector(self):
        raise AssertionError("sub class must define _plain_connector")

    def _tsquery_connector(self):
        raise AssertionError("sub class must define _tsquery_connector")

    def __repr__(self):
        connector = ' ' + self._plain_connector() + ' '
        return '( ' + connector.join(map(lambda x: str(x), self.operands)) + ' )'

    def get_tsquery(self) -> str:
        connector = ' ' + self._tsquery_connector() + ' '
        return '( ' + connector.join(map(lambda x: x.get_tsquery(), self.operands)) + ' )'

    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        raise NotImplementedError("FIXME not implemented!")

    def _filter_node_children(self, filter_function: Callable[[AbstractParseNode], bool]) \
            -> Union[AbstractParseNode, None]:
        return self._filter_boolean_node_children(filter_function)


class AndNode(BooleanNode):
    """Parse node for an AND clause."""

    def _plain_connector(self):
        return 'and'

    def _tsquery_connector(self):
        return '&'

    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        if operands is None:
            operands = self.operands

        if len(operands) == 1:
            return operands[0].get_re()
        else:
            a = operands[0].get_re()
            b = self.get_re(operands[1:])
            return '(?: (?: %s .* %s ) | (?: %s .* %s ) )' % (a, b, b, a)


class OrNode(BooleanNode):
    """Parse node for an OR clause."""

    def _plain_connector(self):
        return 'or'

    def _tsquery_connector(self):
        return '|'

    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        return '(?: ' + ' | '.join(map(lambda x: x.get_re(), self.operands)) + ' )'


class NotNode(ParseNode):
    """Parse node for a NOT clause."""

    def __init__(self, operand: AbstractParseNode):
        self.operand = operand
        operand.parent = self

    def __repr__(self):
        return '!' + str(self.operand)

    def get_tsquery(self) -> str:
        return '!' + self.operand.get_tsquery()

    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        raise ParseSyntaxError("not operations not supported for re()")

    def _filter_node_children(self, filter_function: Callable[[AbstractParseNode], bool]) \
            -> Union[AbstractParseNode, None]:
        filtered_operand = self.operand.filter_tree(filter_function)
        return NotNode(filtered_operand) if filtered_operand else None


class FieldNode(ParseNode):
    """Parse node for a field clause."""

    def __init__(self, field: str, operand: AbstractParseNode):
        self.field = field
        self.operand = operand
        operand.parent = self

    def __repr__(self):
        return self.field + ':' + str(self.operand)

    def get_tsquery(self) -> str:
        if self.field == 'sentence':
            return self.operand.get_tsquery()
        else:
            raise ValueError("non-sentence field nodes should have been filtered")

    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        if self.field == 'sentence':
            return self.operand.get_re()
        else:
            raise ValueError("non-sentence field nodes should have been filtered")

    def _filter_node_children(self, filter_function: Callable[[AbstractParseNode], bool]) \
            -> Union[AbstractParseNode, None]:
        filtered_operand = self.operand.filter_tree(filter_function)
        return FieldNode(self.field, filtered_operand) if filtered_operand else None


class NoopNode(ParseNode):
    """Parse node for a node that should have no impact on the result of the query."""

    def __init__(self):
        pass

    def __repr__(self):
        return NOOP_PLACEHOLDER

    def get_tsquery(self) -> str:
        raise ValueError("noop nodes should have been filtered")

    def get_re(self, operands: List[AbstractParseNode] = None) -> str:
        raise ValueError("noop nodes should have been filtered")

    def _filter_node_children(self, filter_function: Callable[[AbstractParseNode], bool]) \
            -> Union[AbstractParseNode, None]:
        return NoopNode()


class ParseSyntaxError(Exception):
    """Error class for syntax errors encountered when parsing."""
    pass


def __parse_tokens(tokens: List[Token], want_type: List[str] = None) -> ParseNode:
    """Given a flat list of tokens, generate a boolean logic tree."""

    def __check_type(checked_token: Token, checked_want_type: List[str]) -> None:
        """Throw a ParseSyntaxError if the given type is not in the want_type list."""
        if checked_token.token_type not in checked_want_type:
            raise ParseSyntaxError(
                "Token '%s' is not one of the following expected types: %s" % (
                    str(checked_token), str(checked_want_type))
            )

    l.debug("parse tree: " + str(tokens))

    if want_type is None:
        want_type = [T_OPEN, T_PHRASE, T_NOT, T_TERM]

    clause = None
    boolean_clause = None
    hanging_boolean = False

    while len(tokens) > 0:

        frame_depth = len(inspect.getouterframes(inspect.currentframe()))
        l.debug("clause: %s [%s] [frame_depth: %s]" % (clause, type(clause), frame_depth))

        token = tokens.pop(0)
        l.debug("parse token: " + str(token))

        if (token.token_type == T_PLUS) and (not clause or (type(clause) in (AndNode, OrNode))):
            continue

        if hanging_boolean:
            boolean_clause = clause
            hanging_boolean = False
        elif clause and (token.token_type in [T_OPEN, T_PHRASE, T_TERM, T_NOOP, T_FIELD]):
            l.debug("INSERT OR")
            tokens.insert(0, token)
            token = Token(T_OR, 'or')
        elif clause and (token.token_type in [T_NOT]):
            l.debug("INSERT AND")
            tokens.insert(0, token)
            token = Token(T_AND, 'and')

        __check_type(token, want_type)

        if token.token_type == T_OPEN:
            clause = __parse_tokens(tokens, [T_OPEN, T_PHRASE, T_NOT, T_FIELD, T_TERM, T_NOOP, T_CLOSE])
            want_type = [T_OPEN, T_PHRASE, T_NOT, T_FIELD, T_TERM, T_NOOP, T_CLOSE, T_AND, T_OR, T_PLUS]

        elif token.token_type == T_CLOSE:
            break

        elif token.token_type == T_NOOP:
            want_type = [T_CLOSE, T_AND, T_OR, T_PLUS]
            clause = NoopNode()

        elif token.token_type == T_TERM:
            want_type = [T_CLOSE, T_AND, T_OR, T_PLUS]
            wildcard = False
            if token.token_value.endswith(WILD_PLACEHOLDER):
                token.token_value = token.token_value.replace(WILD_PLACEHOLDER, '')
                wildcard = True

            clause = TermNode(token.token_value, wildcard=wildcard)

        elif token.token_type == T_PHRASE:
            want_type = [T_CLOSE, T_AND, T_OR, T_PLUS]
            clause = TermNode(token.token_value, phrase=True)
            # operands = []

        elif token.token_type in (T_AND, T_PLUS, T_OR):
            want_type = [T_OPEN, T_PHRASE, T_NOT, T_FIELD, T_TERM, T_NOOP, T_CLOSE, T_PLUS]

            node_type = OrNode if (token.token_type == T_OR) else AndNode

            if type(clause) is node_type:
                clause = node_type(clause.operands)
            else:
                clause = node_type([clause])

            hanging_boolean = True

        elif token.token_type == T_FIELD:
            want_type = [T_CLOSE, T_AND, T_OR, T_PLUS]
            field_name = re.sub(FIELD_PLACEHOLDER, '', token.token_value)
            next_token = tokens.pop(0)
            if next_token.token_type == T_OPEN:
                field_clause = __parse_tokens(tokens, [T_PHRASE, T_NOT, T_TERM, T_NOOP, T_CLOSE, T_PLUS])
            else:
                field_clause = __parse_tokens([next_token], [T_PHRASE, T_TERM, T_NOOP])

            l.debug("field operand for %s: %s" % (field_name, field_clause))

            clause = FieldNode(field_name, field_clause)

        elif token.token_type == T_NOT:
            want_type = [T_CLOSE, T_AND, T_OR, T_PLUS]
            # operand = None
            next_token = tokens.pop(0)
            if next_token.token_type == T_OPEN:
                operand = __parse_tokens(tokens, [T_FIELD, T_PHRASE, T_NOT, T_TERM, T_NOOP, T_CLOSE, T_PLUS])
            elif next_token.token_type == T_FIELD:
                tokens.insert(0, next_token)
                operand = __parse_tokens(tokens, [T_FIELD])
            else:
                operand = __parse_tokens([next_token], [T_PHRASE, T_TERM, T_NOOP, T_FIELD])
            clause = NotNode(operand)

        else:
            raise ParseSyntaxError("unknown type for token '%s'" % token)

        want_type += [T_CLOSE]

        if boolean_clause:
            l.debug("boolean append: %s <- %s" % (boolean_clause, clause))
            if type(boolean_clause) is type(clause):
                boolean_clause.operands += clause.operands
            else:
                boolean_clause.operands.append(clause)
            clause = boolean_clause
            boolean_clause = None

    # noinspection PyBroadException
    try:
        l.debug("parse result: " + str(clause))
    except:
        l.debug("parse_result: [" + str(type(clause)) + "]")

    return clause


def __get_tokens(query: str) -> List[Token]:
    """Get a list of Token objects from the query."""

    def __get_token_type(token: str) -> str:
        """Given some token text, return one of T_* as the type for that token."""

        if token == '(':
            return T_OPEN
        elif token == ')':
            return T_CLOSE
        elif token[0] in "'\"":
            return T_PHRASE
        elif token.lower() == 'and':
            return T_AND
        elif token.lower() == 'or':
            return T_OR
        elif token.lower() in ('not', '!', '-'):
            return T_NOT
        elif token == '+':
            return T_PLUS
        elif token == '~':
            raise ParseSyntaxError("proximity searches not supported")
        elif token == '/':
            raise ParseSyntaxError("regular expression searches not supported")
        elif (WILD_PLACEHOLDER in token) and not re.match(r'^\w+' + WILD_PLACEHOLDER + '$', token):
            raise ParseSyntaxError("* can only appear the end of a term: " + token)
        elif token == NOOP_PLACEHOLDER:
            return T_NOOP
        elif token.endswith(FIELD_PLACEHOLDER):
            return T_FIELD
        elif re.match('^\w+$', token):
            return T_TERM
        else:
            raise ParseSyntaxError("unrecognized token '%s'" % str(token))

    tokens = []

    # normalize everything to lower case and make sure nothing conflicts with placeholders below
    query = query.lower()

    # the tokenizer interprets as ! as a special character, which results in the ! and subsequent text disappearing.
    # we just replace it with the equivalent - to avoid this.
    query = query.replace('!', '-')

    # also the tokenizer treats newlines as tokens, so we replace them
    query = query.replace("\n", " ")
    query = query.replace("\r", " ")

    # we can't support solr range searches, and they break the tokenizer, so just regexp them away
    query = re.sub('\w+:\[[^\]]*\]', NOOP_PLACEHOLDER, query)

    # we want to include ':' at the end of field names, but tokenizer wants to make it a separate token
    query = re.sub(':', FIELD_PLACEHOLDER + ' ', query)

    # we want to include '*' at the end of field names, but tokenizer wants to make it a separate token
    query = re.sub(r'\*', WILD_PLACEHOLDER, query)

    l.debug("filtered query: " + query)

    raw_tokens = generate_tokens(io.StringIO(query).readline)

    for raw_token in raw_tokens:
        token_value = raw_token[1]
        l.debug("raw token '%s'" % token_value)
        if len(token_value) > 0:
            token_type = __get_token_type(token_value)
            tokens.append(Token(token_value, token_type))

    return tokens


def parse(solr_query: str) -> ParseNode:
    """ Parse a solr query and return a set of *Node objects that encapsulate the query in structured form."""

    solr_query = "( " + decode_string_from_bytes_if_needed(solr_query) + " )"

    tokens = __get_tokens(solr_query)

    l.debug(tokens)

    return __parse_tokens(tokens)
