from sqlmodel import Session, select

from src.models import Clock


def get_clock(session: Session) -> Clock:
    clock = session.exec(select(Clock)).first()
    if not clock:
        clock = Clock(current_day=0)
        session.add(clock)
        session.commit()
        session.refresh(clock)
    return clock


def now(session: Session) -> int:
    return get_clock(session).current_day


def advance(session: Session, days: int = 1) -> int:
    clock = get_clock(session)
    clock.current_day += days
    session.add(clock)
    session.commit()
    session.refresh(clock)
    return clock.current_day
