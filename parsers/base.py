from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedTerm:
    preferred_label: str
    source: str
    source_id: str
    source_uri: Optional[str] = None
    definition: Optional[str] = None
    term_type: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)
    properties: list["ParsedProperty"] = field(default_factory=list)
    parent_source_ids: list[str] = field(default_factory=list)


@dataclass
class ParsedProperty:
    name: str
    definition: Optional[str] = None
    datatype: Optional[str] = None
    unit: Optional[str] = None
    is_required: bool = False


class BaseParser:
    """Base class for all standard parsers."""

    source_name: str = ""

    def parse(self) -> list[ParsedTerm]:
        raise NotImplementedError
