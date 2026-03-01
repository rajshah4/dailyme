import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Newsletter(Base):
    __tablename__ = "newsletters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sender_email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sender_domain: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    email_count: Mapped[int] = mapped_column(Integer, default=0)

    raw_emails: Mapped[list["RawEmail"]] = relationship(back_populates="newsletter")
    stories: Mapped[list["Story"]] = relationship(back_populates="newsletter")


class RawEmail(Base):
    __tablename__ = "raw_emails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gmail_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    newsletter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("newsletters.id")
    )
    subject: Mapped[str | None] = mapped_column(Text)
    from_address: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_html: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    parsed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)

    newsletter: Mapped[Newsletter | None] = relationship(back_populates="raw_emails")
    stories: Mapped[list["Story"]] = relationship(back_populates="raw_email")


class TopicCluster(Base):
    __tablename__ = "topic_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str | None] = mapped_column(String)
    centroid = mapped_column(Vector(384))
    story_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)

    stories: Mapped[list["Story"]] = relationship(back_populates="cluster")


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_emails.id")
    )
    newsletter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("newsletters.id")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    url_canonical: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
    embedding = mapped_column(Vector(384), nullable=True)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic_clusters.id")
    )
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id")
    )
    position_in_email: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)

    raw_email: Mapped[RawEmail | None] = relationship(back_populates="stories")
    newsletter: Mapped[Newsletter | None] = relationship(back_populates="stories")
    cluster: Mapped[TopicCluster | None] = relationship(back_populates="stories")
    group_memberships: Mapped[list["StoryGroupMember"]] = relationship(back_populates="story")

    __table_args__ = (
        Index("idx_stories_url_canonical", "url_canonical"),
        Index("idx_stories_extracted_at", extracted_at.desc()),
    )


class StoryGroup(Base):
    __tablename__ = "story_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_story_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url_canonical: Mapped[str | None] = mapped_column(Text)
    story_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)

    canonical_story: Mapped[Story | None] = relationship(foreign_keys=[canonical_story_id])
    members: Mapped[list["StoryGroupMember"]] = relationship(back_populates="story_group")

    __table_args__ = (Index("idx_story_groups_first_seen", first_seen_at.desc()),)


class StoryGroupMember(Base):
    __tablename__ = "story_group_members"

    story_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_groups.id"), primary_key=True
    )
    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id"), primary_key=True
    )

    story_group: Mapped[StoryGroup] = relationship(back_populates="members")
    story: Mapped[Story] = relationship(back_populates="group_memberships")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_groups.id")
    )
    action: Mapped[str] = mapped_column(String, nullable=False)  # thumbs_up, thumbs_down, hide_topic
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("topic_clusters.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)


class InterestWeight(Base):
    __tablename__ = "interest_weights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_keyword: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String, default="default")  # default, feedback, manual
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    story_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, sent, failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now)
