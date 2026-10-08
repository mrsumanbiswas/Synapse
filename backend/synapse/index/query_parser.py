"""Boolean query language parsed with stacks (Dijkstra's shunting-yard algorithm).

    machine learning AND (python OR "deep learning") NOT java author:hinton year:2015..2020

1. The lexer turns the string into tokens and inserts the implicit ANDs.
2. Shunting-yard uses an *operator stack* to reorder infix tokens into
   Reverse Polish Notation: ``machine learning AND python "deep learning" OR AND java NOT AND``.
3. RPN is evaluated with an *operand stack* of document-id sets, so AND, OR and
   NOT become set intersection, union and difference.

Precedence: NOT > AND > OR. Operators must be upper case so ordinary words like
"and" in "salt and pepper" stay plain search terms.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

FIELDS = ("author", "title", "year", "topic", "venue", "source", "doi")

TOKEN_RE = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<lparen>\()
  | (?P<rparen>\))
  | (?P<and>&&|&|AND\b)
  | (?P<or>\|\||\||OR\b)
  | (?P<not>!|NOT\b)
  | (?P<field>(?i:(?P<fname>author|title|year|topic|venue|source|doi)):(?P<fvalue>"[^"]*"?|[^\s()]+))
  | (?P<phrase>"(?P<ptext>[^"]*)"?)
  | (?P<neg>-)(?=[^\s)])
  | (?P<word>[^\s()"]+)
    """,
    re.VERBOSE,
)

PRECEDENCE = {"OR": 1, "AND": 2, "NOT": 3}
OPERAND_TYPES = {"TERM", "PHRASE", "FIELD"}


class QuerySyntaxError(ValueError):
    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.position = position


@dataclass(frozen=True)
class Token:
    type: str  # TERM | PHRASE | FIELD | AND | OR | NOT | LPAREN | RPAREN
    value: str = ""
    field: str | None = None
    position: int = 0
    implicit: bool = False

    def __str__(self) -> str:
        if self.type == "TERM":
            return self.value
        if self.type == "PHRASE":
            return f'"{self.value}"'
        if self.type == "FIELD":
            return f"{self.field}:{self.value}"
        return {"LPAREN": "(", "RPAREN": ")"}.get(self.type, self.type)


# --------------------------------------------------------------------------- AST


@dataclass(frozen=True)
class Node:
    def to_dict(self) -> dict:
        raise NotImplementedError


@dataclass(frozen=True)
class Term(Node):
    text: str

    def to_dict(self) -> dict:
        return {"type": "term", "value": self.text}

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class Phrase(Node):
    text: str

    def to_dict(self) -> dict:
        return {"type": "phrase", "value": self.text}

    def __str__(self) -> str:
        return f'"{self.text}"'


@dataclass(frozen=True)
class Field(Node):
    name: str
    value: str

    def to_dict(self) -> dict:
        return {"type": "field", "field": self.name, "value": self.value}

    def __str__(self) -> str:
        value = f'"{self.value}"' if " " in self.value else self.value
        return f"{self.name}:{value}"


@dataclass(frozen=True)
class Not(Node):
    child: Node

    def to_dict(self) -> dict:
        return {"type": "not", "children": [self.child.to_dict()]}

    def __str__(self) -> str:
        return f"NOT {self.child}"


@dataclass(frozen=True)
class And(Node):
    left: Node
    right: Node

    def operands(self) -> list[Node]:
        out = []
        for side in (self.left, self.right):
            out.extend(side.operands() if isinstance(side, And) else [side])
        return out

    def to_dict(self) -> dict:
        return {"type": "and", "children": [c.to_dict() for c in self.operands()]}

    def __str__(self) -> str:
        return "(" + " AND ".join(map(str, self.operands())) + ")"


@dataclass(frozen=True)
class Or(Node):
    left: Node
    right: Node

    def operands(self) -> list[Node]:
        out = []
        for side in (self.left, self.right):
            out.extend(side.operands() if isinstance(side, Or) else [side])
        return out

    def to_dict(self) -> dict:
        return {"type": "or", "children": [c.to_dict() for c in self.operands()]}

    def __str__(self) -> str:
        return "(" + " OR ".join(map(str, self.operands())) + ")"


@dataclass(frozen=True)
class All(Node):
    """Matches every document (used for "*" and for constraint rewriting)."""

    def to_dict(self) -> dict:
        return {"type": "all"}

    def __str__(self) -> str:
        return "*"


@dataclass(frozen=True)
class Empty(Node):
    def to_dict(self) -> dict:
        return {"type": "none"}

    def __str__(self) -> str:
        return "∅"


ALL = All()
EMPTY = Empty()


# --------------------------------------------------------------------------- parsing


def tokenize(query: str) -> list[Token]:
    """Lex the query and insert the implicit AND between adjacent operands."""
    raw: list[Token] = []
    pos = 0
    while pos < len(query):
        match = TOKEN_RE.match(query, pos)
        if match is None:  # pragma: no cover - the word branch matches anything else
            raise QuerySyntaxError(f"Unexpected character {query[pos]!r}", pos)
        kind = match.lastgroup
        pos = match.end()
        if kind == "space":
            continue
        start = match.start()
        if kind == "field":
            value = match.group("fvalue").strip('"').strip()
            if value:
                raw.append(Token("FIELD", value, match.group("fname").lower(), start))
        elif kind == "phrase":
            text = " ".join(match.group("ptext").split())
            if text:
                raw.append(Token("PHRASE", text, position=start))
        elif kind == "word":
            word = match.group().lstrip("+")
            if word in ("*",):
                raw.append(Token("TERM", "*", position=start))
            elif word:
                raw.append(Token("TERM", word, position=start))
        elif kind == "neg":
            raw.append(Token("NOT", position=start))
        else:
            raw.append(Token(kind.upper(), position=start))

    tokens: list[Token] = []
    for token in raw:
        if tokens:
            prev = tokens[-1]
            ends_operand = prev.type in OPERAND_TYPES or prev.type == "RPAREN"
            starts_operand = token.type in OPERAND_TYPES or token.type in ("LPAREN", "NOT")
            if ends_operand and starts_operand:
                tokens.append(Token("AND", position=token.position, implicit=True))
        tokens.append(token)
    return tokens


def to_rpn(tokens: list[Token]) -> list[Token]:
    """Shunting-yard: infix tokens -> Reverse Polish Notation using an operator stack."""
    output: list[Token] = []
    operators: list[Token] = []
    for token in tokens:
        if token.type in OPERAND_TYPES:
            output.append(token)
        elif token.type == "NOT":
            operators.append(token)  # unary prefix operator: wait for its operand
        elif token.type in ("AND", "OR"):
            while operators and operators[-1].type != "LPAREN" and \
                    PRECEDENCE[operators[-1].type] >= PRECEDENCE[token.type]:
                output.append(operators.pop())
            operators.append(token)
        elif token.type == "LPAREN":
            operators.append(token)
        elif token.type == "RPAREN":
            while operators and operators[-1].type != "LPAREN":
                output.append(operators.pop())
            if not operators:
                raise QuerySyntaxError("Unmatched ')'", token.position)
            operators.pop()
    while operators:
        op = operators.pop()
        if op.type == "LPAREN":
            raise QuerySyntaxError("Unmatched '('", op.position)
        output.append(op)
    return output


def _leaf(token: Token) -> Node:
    if token.type == "TERM":
        return ALL if token.value == "*" else Term(token.value)
    if token.type == "PHRASE":
        return Phrase(token.value)
    return Field(token.field or "", token.value)


def rpn_to_ast(rpn: list[Token]) -> Node:
    """Rebuild the expression tree from RPN, again with a stack."""
    stack: list[Node] = []
    for token in rpn:
        if token.type in OPERAND_TYPES:
            stack.append(_leaf(token))
        elif token.type == "NOT":
            if not stack:
                raise QuerySyntaxError("NOT needs something to negate", token.position)
            stack.append(Not(stack.pop()))
        else:
            if len(stack) < 2:
                raise QuerySyntaxError(f"{token.type} needs a term on both sides", token.position)
            right, left = stack.pop(), stack.pop()
            stack.append(And(left, right) if token.type == "AND" else Or(left, right))
    if not stack:
        return ALL
    if len(stack) != 1:  # pragma: no cover - implicit ANDs make this unreachable
        raise QuerySyntaxError("Malformed query")
    return stack[0]


@dataclass
class ParsedQuery:
    text: str
    tokens: list[Token]
    rpn: list[Token]
    ast: Node
    fallback: bool = False  # True when the query was not valid syntax and was read as plain words
    error: str | None = None

    @property
    def has_operators(self) -> bool:
        return any(t.type in ("AND", "OR", "NOT", "FIELD") and not t.implicit for t in self.tokens) or \
            any(t.type in ("PHRASE", "LPAREN") for t in self.tokens)

    def positive_terms(self) -> list[Node]:
        return positive_leaves(self.ast)

    def constraint(self) -> Node:
        return simplify(constraint_of(self.ast))

    def to_dict(self) -> dict:
        return {
            "query": self.text,
            "tokens": [{"type": t.type, "text": str(t), "implicit": t.implicit} for t in self.tokens],
            "rpn": [str(t) for t in self.rpn],
            "ast": self.ast.to_dict(),
            "normalized": str(self.ast),
            "fallback": self.fallback,
            "error": self.error,
        }


def parse_query(query: str, strict: bool = False) -> ParsedQuery:
    """Parse ``query``. Unless ``strict``, invalid syntax degrades to plain words."""
    query = (query or "").strip()
    if not query:
        return ParsedQuery(query, [], [], ALL)
    try:
        tokens = tokenize(query)
        rpn = to_rpn(tokens)
        return ParsedQuery(query, tokens, rpn, rpn_to_ast(rpn))
    except QuerySyntaxError as exc:
        if strict:
            raise
        words = re.findall(r"[^\s()\"&|!]+", query)
        words = [w for w in words if w not in ("AND", "OR", "NOT") and w.strip("-+")]
        tokens = tokenize(" ".join(w.strip("-+") for w in words)) if words else []
        rpn = to_rpn(tokens)
        return ParsedQuery(query, tokens, rpn, rpn_to_ast(rpn), fallback=True, error=str(exc))


# --------------------------------------------------------------------------- rewriting


def positive_leaves(node: Node, negated: bool = False) -> list[Node]:
    """Terms and phrases the user wants to *find* (not those under NOT)."""
    if isinstance(node, (Term, Phrase)):
        return [] if negated else [node]
    if isinstance(node, Not):
        return positive_leaves(node.child, not negated)
    if isinstance(node, (And, Or)):
        return positive_leaves(node.left, negated) + positive_leaves(node.right, negated)
    return []


def constraint_of(node: Node, negated: bool = False) -> Node:
    """Keep only the hard filters: field filters and excluded terms.

    Ranked modes score documents by the positive terms, so those leaves become
    ``ALL`` here. ``python NOT java author:hinton`` -> ``NOT java AND author:hinton``.
    """
    if isinstance(node, (Term, Phrase)):
        return node if negated else ALL
    if isinstance(node, Not):
        return Not(constraint_of(node.child, not negated))
    if isinstance(node, And):
        return And(constraint_of(node.left, negated), constraint_of(node.right, negated))
    if isinstance(node, Or):
        return Or(constraint_of(node.left, negated), constraint_of(node.right, negated))
    return node


def simplify(node: Node) -> Node:
    if isinstance(node, Not):
        child = simplify(node.child)
        if child is ALL:
            return EMPTY
        if child is EMPTY:
            return ALL
        return Not(child)
    if isinstance(node, And):
        left, right = simplify(node.left), simplify(node.right)
        if left is EMPTY or right is EMPTY:
            return EMPTY
        if left is ALL:
            return right
        if right is ALL:
            return left
        return And(left, right)
    if isinstance(node, Or):
        left, right = simplify(node.left), simplify(node.right)
        if left is ALL or right is ALL:
            return ALL
        if left is EMPTY:
            return right
        if right is EMPTY:
            return left
        return Or(left, right)
    return node


# --------------------------------------------------------------------------- evaluation


@dataclass
class Resolver:
    """How leaves map to document sets; supplied by the shard that evaluates the query."""

    term: Callable[[str], set[str]]
    phrase: Callable[[str], set[str]]
    field: Callable[[str, str], set[str]]
    universe: Callable[[], set[str]]


@dataclass
class EvaluationStep:
    action: str  # "push" or an operator
    label: str
    size: int
    depth: int


@dataclass
class Evaluation:
    docs: set[str]
    steps: list[EvaluationStep] = field(default_factory=list)


def ast_to_rpn(node: Node) -> list[Node | str]:
    if isinstance(node, Not):
        return ast_to_rpn(node.child) + ["NOT"]
    if isinstance(node, And):
        return ast_to_rpn(node.left) + ast_to_rpn(node.right) + ["AND"]
    if isinstance(node, Or):
        return ast_to_rpn(node.left) + ast_to_rpn(node.right) + ["OR"]
    return [node]


def evaluate(node: Node, resolver: Resolver, trace: bool = False) -> Evaluation:
    """Evaluate an expression in RPN order with a stack of document sets."""
    stack: list[set[str]] = []
    steps: list[EvaluationStep] = []
    universe: set[str] | None = None

    def everything() -> set[str]:
        nonlocal universe
        if universe is None:
            universe = resolver.universe()
        return universe

    for item in ast_to_rpn(node):
        if isinstance(item, str):
            if item == "NOT":
                stack.append(everything() - stack.pop())
            else:
                right, left = stack.pop(), stack.pop()
                stack.append(left & right if item == "AND" else left | right)
            label = item
        else:
            if isinstance(item, Term):
                docs = resolver.term(item.text)
            elif isinstance(item, Phrase):
                docs = resolver.phrase(item.text)
            elif isinstance(item, Field):
                docs = resolver.field(item.name, item.value)
            elif item is ALL:
                docs = set(everything())
            else:
                docs = set()
            stack.append(docs)
            label = str(item)
        if trace:
            steps.append(EvaluationStep("push" if not isinstance(item, str) else item.lower(),
                                        label, len(stack[-1]), len(stack)))
    return Evaluation(stack[-1] if stack else set(), steps)


# --------------------------------------------------------------------------- field helpers


YEAR_RANGE_RE = re.compile(r"^(\d{4})?\s*(?:\.\.|-|–|to)\s*(\d{4})?$")
YEAR_CMP_RE = re.compile(r"^(>=|<=|>|<)\s*(\d{4})$")


def year_bounds(value: str) -> tuple[int | None, int | None]:
    """``2015`` / ``2010..2020`` / ``>2015`` / ``<=1999`` -> inclusive (low, high)."""
    value = value.strip()
    if value.isdigit():
        return int(value), int(value)
    match = YEAR_CMP_RE.match(value)
    if match:
        op, year = match.group(1), int(match.group(2))
        return {">": (year + 1, None), ">=": (year, None), "<": (None, year - 1), "<=": (None, year)}[op]
    match = YEAR_RANGE_RE.match(value)
    if match and (match.group(1) or match.group(2)):
        low = int(match.group(1)) if match.group(1) else None
        high = int(match.group(2)) if match.group(2) else None
        return low, high
    raise QuerySyntaxError(f"Cannot read year filter {value!r}; try year:2015 or year:2010..2020")
