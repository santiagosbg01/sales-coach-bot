"""Group model — teams of reps managed by a manager."""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

COUNTRIES = ["mexico", "chile", "colombia", "peru"]


class Group(Base):
    """
    Group of reps. Can be:
    - Country-level (parent_id=null): e.g. Mexico — holds sub-groups, country manager sees all
    - Sub-group (parent_id=country): e.g. Farmers Mexico, Hunters Mexico — users assigned here
    """
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    country = Column(String(50), nullable=True)  # mexico, chile, colombia, peru
    parent_group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id", use_alter=True, name="fk_group_manager"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("Group", remote_side=[id], backref="children")
    manager = relationship("User", backref="managed_groups", foreign_keys=[manager_id], post_update=True)
    users = relationship("User", back_populates="group", foreign_keys="User.group_id")

    @property
    def is_country_group(self) -> bool:
        """True if this is a country-level group (has no parent)."""
        return self.parent_group_id is None

    def descendant_ids(self, db) -> list:
        """Return [self.id] plus all descendant group IDs (for country groups: self + children)."""
        ids = [self.id]
        for child in db.query(Group).filter(Group.parent_group_id == self.id).all():
            ids.append(child.id)
        return ids
