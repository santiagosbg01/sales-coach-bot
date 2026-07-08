"""Alert system for monitoring user engagement and performance."""
from datetime import datetime, timedelta
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import and_
from models import (
    User, Alert, AlertType, AlertSeverity, SessionStatus, UserRole, UserStatus,
    Session as SessionModel, Attempt, Grade, PassState
)
from config import Config


class AlertSystem:
    """Manages alerts for low engagement and performance issues."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def check_all_alerts(self) -> List[Alert]:
        """Run all alert checks and create alerts as needed. Only checks reps (not managers/admins)."""
        alerts = []
        
        users = self.db.query(User).filter(
            User.status == UserStatus.ACTIVE,
            User.role == UserRole.REP,
        ).all()
        
        for user in users:
            # Check low engagement
            engagement_alert = self._check_low_engagement(user)
            if engagement_alert:
                alerts.append(engagement_alert)
            
            # Check low accuracy
            accuracy_alert = self._check_low_accuracy(user)
            if accuracy_alert:
                alerts.append(accuracy_alert)
            
            # Check missed days
            missed_days_alert = self._check_missed_days(user)
            if missed_days_alert:
                alerts.append(missed_days_alert)
            
            # Check knowledge gaps
            gap_alert = self._check_persistent_gaps(user)
            if gap_alert:
                alerts.append(gap_alert)
        
        return alerts
    
    def _check_low_engagement(self, user: User) -> Alert:
        """Check for low engagement (response rate < 50% in last 7 days)."""
        week_ago = datetime.utcnow() - timedelta(days=7)
        
        # Expected: 5 weekdays (Mon–Fri) in a typical week
        expected = 5
        
        # Count completed sessions in last 7 days
        completed = self.db.query(SessionModel).filter(
            and_(
                SessionModel.user_id == user.id,
                SessionModel.date >= week_ago,
                SessionModel.status == SessionStatus.COMPLETED
            )
        ).count()
        
        response_rate = (completed / expected) * 100
        
        if response_rate < 50:
            # Check if alert already exists
            existing = self.db.query(Alert).filter(
                and_(
                    Alert.user_id == user.id,
                    Alert.type == AlertType.LOW_ENGAGEMENT,
                    Alert.is_resolved == False
                )
            ).first()
            
            if existing:
                return None
            
            alert = Alert(
                user_id=user.id,
                type=AlertType.LOW_ENGAGEMENT,
                severity=AlertSeverity.WARNING if response_rate > 25 else AlertSeverity.CRITICAL,
                title=f"Low Engagement: {user.name}",
                message=f"Only {completed}/{expected} sessions completed this week ({response_rate:.0f}%)",
                context={"response_rate": response_rate, "completed": completed, "expected": expected}
            )
            
            self.db.add(alert)
            self.db.commit()
            
            return alert
        
        return None
    
    def _check_low_accuracy(self, user: User) -> Alert:
        """Check for low accuracy (avg score below threshold in last 14 days)."""
        two_weeks_ago = datetime.utcnow() - timedelta(days=14)
        threshold = getattr(Config, "MANAGER_ALERT_ACCURACY_THRESHOLD", 2.5)
        
        scores = self.db.query(Grade.score_0_5).join(Attempt).filter(
            and_(
                Attempt.user_id == user.id,
                Attempt.asked_at >= two_weeks_ago,
                Attempt.is_skipped == False,
                Grade.score_0_5.isnot(None)
            )
        ).all()
        
        if not scores or len(scores) < 5:  # Need at least 5 attempts
            return None
        
        avg_score = sum(s[0] for s in scores) / len(scores)
        
        if avg_score < threshold:
            existing = self.db.query(Alert).filter(
                and_(
                    Alert.user_id == user.id,
                    Alert.type == AlertType.LOW_ACCURACY,
                    Alert.is_resolved == False
                )
            ).first()
            
            if existing:
                return None
            
            alert = Alert(
                user_id=user.id,
                type=AlertType.LOW_ACCURACY,
                severity=AlertSeverity.WARNING if avg_score > (threshold - 0.5) else AlertSeverity.CRITICAL,
                title=f"Low Accuracy: {user.name}",
                message=f"Average score {avg_score:.1f}/5 over last 14 days (threshold: {threshold})",
                context={"avg_score": avg_score, "attempts": len(scores)}
            )
            
            self.db.add(alert)
            self.db.commit()
            
            return alert
        
        return None
    
    def _check_missed_days(self, user: User) -> Alert:
        """Check for consecutive missed days (3+ days without activity)."""
        if not user.last_active_at:
            return None
        
        days_inactive = (datetime.utcnow() - user.last_active_at).days
        
        if days_inactive >= 3:
            existing = self.db.query(Alert).filter(
                and_(
                    Alert.user_id == user.id,
                    Alert.type == AlertType.MISSED_DAYS,
                    Alert.is_resolved == False
                )
            ).first()
            
            if existing:
                return None
            
            alert = Alert(
                user_id=user.id,
                type=AlertType.MISSED_DAYS,
                severity=AlertSeverity.INFO if days_inactive < 7 else AlertSeverity.WARNING,
                title=f"Missed Days: {user.name}",
                message=f"No activity for {days_inactive} days",
                context={"days_inactive": days_inactive, "last_active": user.last_active_at.isoformat()}
            )
            
            self.db.add(alert)
            self.db.commit()
            
            return alert
        
        return None
    
    def _check_persistent_gaps(self, user: User) -> Alert:
        """Check for persistent knowledge gaps (same concept failed 3+ times)."""
        month_ago = datetime.utcnow() - timedelta(days=30)
        
        attempts = self.db.query(Attempt).join(Grade).filter(
            and_(
                Attempt.user_id == user.id,
                Attempt.asked_at >= month_ago,
                Grade.pass_state == PassState.FAIL
            )
        ).all()
        
        gap_counts = {}
        for attempt in attempts:
            if attempt.grade and attempt.grade.missed_concepts:
                for concept in attempt.grade.missed_concepts:
                    gap_counts[concept] = gap_counts.get(concept, 0) + 1
        
        persistent_gaps = {k: v for k, v in gap_counts.items() if v >= 3}
        
        if persistent_gaps:
            existing = self.db.query(Alert).filter(
                and_(
                    Alert.user_id == user.id,
                    Alert.type == AlertType.KNOWLEDGE_GAP,
                    Alert.is_resolved == False
                )
            ).first()
            
            if existing:
                return None
            
            top_gaps = sorted(persistent_gaps.items(), key=lambda x: x[1], reverse=True)[:3]
            gaps_text = ", ".join([f"{concept} ({count}x)" for concept, count in top_gaps])
            
            alert = Alert(
                user_id=user.id,
                type=AlertType.KNOWLEDGE_GAP,
                severity=AlertSeverity.WARNING,
                title=f"Knowledge Gaps: {user.name}",
                message=f"Persistent gaps in: {gaps_text}",
                context={"gaps": persistent_gaps}
            )
            
            self.db.add(alert)
            self.db.commit()
            
            return alert
        
        return None
    
    def resolve_alert(self, alert_id: int, resolved_by: int) -> bool:
        """Resolve an alert."""
        alert = self.db.query(Alert).get(alert_id)
        if not alert:
            return False
        
        alert.is_resolved = True
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by = resolved_by
        
        self.db.commit()
        
        return True
    
    def get_open_alerts(self, user_id: int = None, severity: AlertSeverity = None) -> List[Alert]:
        """Get open alerts with optional filters."""
        query = self.db.query(Alert).filter(Alert.is_resolved == False)
        
        if user_id:
            query = query.filter(Alert.user_id == user_id)
        
        if severity:
            query = query.filter(Alert.severity == severity)
        
        return query.order_by(Alert.triggered_at.desc()).all()
