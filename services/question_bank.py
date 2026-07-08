"""Question bank management."""
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from models import Question, Rubric, QuestionCategory, DifficultyLevel, QuestionType


class QuestionBank:
    """Manages question CRUD operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_question(
        self,
        prompt: str,
        category: QuestionCategory,
        difficulty: DifficultyLevel,
        must_have_concepts: List[Dict],
        tags: Optional[List[str]] = None,
        question_type: QuestionType = QuestionType.OPEN_ENDED,
        choices: Optional[List[Dict]] = None,
        correct_answer: Optional[str] = None,
        product: Optional[str] = None,
        country: Optional[str] = None,
        good_to_have_concepts: Optional[List[Dict]] = None,
        ideal_answer: Optional[str] = None,
        reference_url: Optional[str] = None,
        reference_snippet: Optional[str] = None,
        followup_templates: Optional[List[str]] = None,
        created_by: Optional[int] = None
    ) -> Question:
        """Create a new question with rubric."""
        question = Question(
            prompt=prompt,
            category=category,
            difficulty=difficulty,
            tags=tags or [],
            question_type=question_type,
            choices=choices,
            correct_answer=correct_answer,
            product=product,
            country=country,
            active=True,
            version=1,
            created_by=created_by
        )
        
        self.db.add(question)
        self.db.flush()
        
        # Create rubric
        rubric = Rubric(
            question_id=question.id,
            must_have_concepts=must_have_concepts,
            good_to_have_concepts=good_to_have_concepts or [],
            ideal_answer=ideal_answer,
            reference_url=reference_url,
            reference_snippet=reference_snippet,
            followup_templates=followup_templates or []
        )
        
        self.db.add(rubric)
        self.db.commit()
        self.db.refresh(question)
        
        return question
    
    def update_question(
        self,
        question_id: int,
        **updates
    ) -> Optional[Question]:
        """Update a question. Creates new version for significant changes."""
        question = self.db.query(Question).get(question_id)
        if not question:
            return None
        
        # Update question fields
        for key, value in updates.items():
            if hasattr(question, key):
                setattr(question, key, value)
        
        self.db.commit()
        self.db.refresh(question)
        
        return question
    
    def update_rubric(
        self,
        question_id: int,
        **updates
    ) -> Optional[Rubric]:
        """Update a question's rubric."""
        rubric = self.db.query(Rubric).filter(
            Rubric.question_id == question_id
        ).first()
        
        if not rubric:
            return None
        
        for key, value in updates.items():
            if hasattr(rubric, key):
                setattr(rubric, key, value)
        
        self.db.commit()
        self.db.refresh(rubric)
        
        return rubric
    
    def deactivate_question(self, question_id: int) -> bool:
        """Soft delete a question."""
        question = self.db.query(Question).get(question_id)
        if not question:
            return False
        
        question.active = False
        self.db.commit()
        
        return True
    
    def get_question(self, question_id: int) -> Optional[Question]:
        """Get a question by ID."""
        return self.db.query(Question).get(question_id)
    
    def list_questions(
        self,
        category: Optional[QuestionCategory] = None,
        difficulty: Optional[DifficultyLevel] = None,
        tags: Optional[List[str]] = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0
    ) -> List[Question]:
        """List questions with filters."""
        query = self.db.query(Question)
        
        if active_only:
            query = query.filter(Question.active == True)
        
        if category:
            query = query.filter(Question.category == category)
        
        if difficulty:
            query = query.filter(Question.difficulty == difficulty)
        
        if tags:
            # Questions that have any of the specified tags
            tag_filters = [Question.tags.contains(tag) for tag in tags]
            query = query.filter(or_(*tag_filters))
        
        return query.offset(offset).limit(limit).all()
    
    def search_questions(self, search_term: str, limit: int = 50) -> List[Question]:
        """Search questions by prompt text."""
        return self.db.query(Question).filter(
            and_(
                Question.active == True,
                Question.prompt.ilike(f"%{search_term}%")
            )
        ).limit(limit).all()
    
    def get_question_stats(self) -> Dict:
        """Get question bank statistics."""
        total = self.db.query(Question).filter(Question.active == True).count()
        
        by_category = {}
        for cat in QuestionCategory:
            count = self.db.query(Question).filter(
                and_(
                    Question.active == True,
                    Question.category == cat
                )
            ).count()
            by_category[cat.value] = count
        
        by_difficulty = {}
        for diff in DifficultyLevel:
            count = self.db.query(Question).filter(
                and_(
                    Question.active == True,
                    Question.difficulty == diff
                )
            ).count()
            by_difficulty[diff.value] = count
        
        return {
            "total": total,
            "by_category": by_category,
            "by_difficulty": by_difficulty
        }
