from datetime import datetime
import pytest
from database.database import Database
from services.calendar_service import CalendarService
from services.notification_service import NotificationService
from services.reminder_service import ReminderService

NOW = datetime(2026, 10, 6, 9, 0)  # Tuesday


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def db():
    return Database(":memory:")


@pytest.fixture
def cal(db):
    return CalendarService(db)


@pytest.fixture
def rem(db):
    return ReminderService(db, NotificationService(db))
