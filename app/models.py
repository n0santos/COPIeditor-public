from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship, DeclarativeBase
import datetime


class Base(DeclarativeBase):
    pass


class Term(Base):
    __tablename__ = "terms"

    id = Column(Integer, primary_key=True)
    preferred_label = Column(String(500), nullable=False)
    definition = Column(Text)
    source = Column(String(50), nullable=False)   # iso15926 | posc_caesar | cfihos | dexpi
    source_id = Column(String(500))               # original ID in the standard
    source_uri = Column(String(1000))             # URI when available
    term_type = Column(String(200))               # class / concept / equipment / instrument …
    created_at = Column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
    )

    properties = relationship("Property", back_populates="term", cascade="all, delete-orphan")
    synonyms = relationship("Synonym", back_populates="term", cascade="all, delete-orphan")
    parent_relations = relationship(
        "Hierarchy", foreign_keys="Hierarchy.child_term_id",
        back_populates="child", cascade="all, delete-orphan"
    )
    child_relations = relationship(
        "Hierarchy", foreign_keys="Hierarchy.parent_term_id",
        back_populates="parent", cascade="all, delete-orphan"
    )
    mappings_as_a = relationship(
        "Mapping", foreign_keys="Mapping.term_id_a",
        back_populates="term_a", cascade="all, delete-orphan"
    )
    mappings_as_b = relationship(
        "Mapping", foreign_keys="Mapping.term_id_b",
        back_populates="term_b", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_terms_source", "source"),
        Index("ix_terms_label", "preferred_label"),
        Index("ix_terms_source_label", "source", "preferred_label"),
        UniqueConstraint("source", "source_id", name="uq_term_source_id"),
    )


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("terms.id"), nullable=False)
    name = Column(String(500), nullable=False)
    definition = Column(Text)
    datatype = Column(String(100))
    unit = Column(String(200))
    is_required = Column(Boolean, default=False)

    term = relationship("Term", back_populates="properties")

    __table_args__ = (Index("ix_properties_term_id", "term_id"),)


class Synonym(Base):
    __tablename__ = "synonyms"

    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("terms.id"), nullable=False)
    label = Column(String(500), nullable=False)
    language = Column(String(10), default="en")

    term = relationship("Term", back_populates="synonyms")

    __table_args__ = (Index("ix_synonyms_term_id", "term_id"),)


class Hierarchy(Base):
    __tablename__ = "hierarchy"

    id = Column(Integer, primary_key=True)
    parent_term_id = Column(Integer, ForeignKey("terms.id"), nullable=False)
    child_term_id = Column(Integer, ForeignKey("terms.id"), nullable=False)
    relation_type = Column(String(100), default="subClassOf")  # subClassOf | partOf | …

    parent = relationship("Term", foreign_keys=[parent_term_id], back_populates="child_relations")
    child = relationship("Term", foreign_keys=[child_term_id], back_populates="parent_relations")

    __table_args__ = (
        Index("ix_hierarchy_parent", "parent_term_id"),
        Index("ix_hierarchy_child", "child_term_id"),
        UniqueConstraint("parent_term_id", "child_term_id", "relation_type", name="uq_hierarchy"),
    )


class Mapping(Base):
    __tablename__ = "mappings"

    id = Column(Integer, primary_key=True)
    term_id_a = Column(Integer, ForeignKey("terms.id"), nullable=False)
    term_id_b = Column(Integer, ForeignKey("terms.id"), nullable=False)
    mapping_type = Column(String(50))   # exact | close | broader | narrower | related
    confidence = Column(Float, default=1.0)
    notes = Column(Text)

    term_a = relationship("Term", foreign_keys=[term_id_a], back_populates="mappings_as_a")
    term_b = relationship("Term", foreign_keys=[term_id_b], back_populates="mappings_as_b")

    __table_args__ = (
        Index("ix_mappings_a", "term_id_a"),
        Index("ix_mappings_b", "term_id_b"),
    )
