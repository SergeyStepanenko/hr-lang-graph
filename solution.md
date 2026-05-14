# HR Recruiting AI Agent — Solution

## Схема процесса

```
Candidate applies (paste CV)
    │
    ▼
[INTAKE] ── AI: parse CV → extract contacts (CandidateContact)
    │
    ▼
[SCREENING] ── AI: score CV (CVScore) + generate summary
    │
    ▼  ← interrupt_before: Recruiter reviews score → Approve/Reject
    │
    ├─ Reject → email candidate → END
    │
    ▼  Fan-out via LangGraph Send()
┌───┴───┬───────┐
│       │       │
HM    CFO    Legal    ← 3 parallel interrupt_before
│       │       │
└───┬───┴───────┘
    │  Fan-in: aggregate_approvals
    │  Rule: ALL approve → proceed, ANY reject → veto → END
    │
    ▼
[INTERVIEW] ← interrupt_before: Candidate accepts/declines slot
    │
    ▼  ← interrupt_before: Interviewer submits scorecard
    │
    ├─ Reject → email candidate → END
    │
    ▼
[OFFER] ── AI: generate offer draft
    │
    ▼  ← interrupt_before: Recruiter approves offer
    │
    ▼  ← interrupt_before: Candidate accepts/rejects
    │
    ├─ Reject → END
    ▼
  HIRED ✓
```

## Логика агента

### Решения AI принимает:
1. **CV Parsing** — извлечение контактов (name, email, phone, telegram, linkedin). Все поля кроме name опциональны. Если email нет → флаг `no_contact`, коммуникации с кандидатом отключены.
2. **CV Scoring** — оценка 0-100 с reasoning, strengths, red_flags. Через `instructor` structured output.
3. **Summary** — краткое описание для рекрутера.
4. **Offer Draft** — генерация текста оффера.
5. **Rejection Email** — генерация вежливого отказа.

### Решения принимают люди (interrupt_before):
- **Recruiter**: approve/reject после скрининга; approve offer draft
- **HM, CFO, Legal**: параллельные апрувы (all-approve rule, any-veto rule)
- **Interviewer**: scorecard после интервью
- **Candidate**: accept/decline интервью; accept/reject оффер

### Таймауты:
- Virtual clock вместо реального таймера
- Skip 1 Day кнопка двигает `clock_day`
- Молчание > 3 дней → nudge в slack (без авто-решений)
- Граф остаётся в pending бесконечно до ручного действия

### Параллельные апрувы:
- `Send()` API LangGraph для fan-out на 3 ноды
- Каждая нода имеет `interrupt_before` — независимый human action
- `aggregate_approvals` — fan-in, проверяет all-approve / any-veto
- Порядок апрувов не важен — каждый может быть выполнен независимо

## Стек

| Компонент | Инструмент | Обоснование |
|-----------|-----------|-------------|
| Оркестрация | **LangGraph** | Встроенная поддержка interrupt_before (human-in-the-loop), Send (fan-out/fan-in), SqliteSaver (персистенция state между HTTP-запросами) — идеально для multi-step approval pipeline |
| LLM | **OpenAI gpt-4o-mini + instructor** | instructor обеспечивает structured output с Pydantic валидацией и retry. gpt-4o-mini — баланс цены/качества для extraction и scoring |
| Web | **FastAPI + Jinja2 + HTMX** | FastAPI для API + SSR, Jinja2 для шаблонов, HTMX для real-time обновлений без SPA complexity. Process widget обновляется polling каждые 3 секунды |
| БД | **SQLite + SQLModel** | Zero-config, embedded. SQLModel для type-safe ORM. Отдельная SQLite для LangGraph checkpoints |
| Визуализация | **Mermaid** | Pipeline диаграмма в реальном времени — overview mode (badge counts) и focus mode (подсветка текущей ноды кандидата) |

## Структура кода

- `src/workflow.py` — LangGraph StateGraph, routing, checkpointer
- `src/nodes.py` — функции нод графа (intake, score, approve, interview, offer)
- `src/llm.py` — instructor client, все LLM-вызовы
- `src/comms.py` — send_email, send_slack, audit_log (файлы + БД)
- `src/clock.py` — virtual clock (advance/now)
- `src/models.py` — SQLModel: Candidate, Job, Message, AuditEvent, Clock
- `src/schemas.py` — Pydantic: CandidateContact, CVScore
- `src/app.py` — FastAPI routes + HTMX endpoints
- `src/templates/` — Jinja2 шаблоны с Bootstrap 5

## Запуск

```bash
cp .env.example .env  # вставить OPENAI_API_KEY
make install           # uv sync
make seed              # создать БД + seed данные
make run               # запустить на :8000
```

## Demo сценарий

1. Роль: **Candidate** → Apply (paste CV из `data/sample_cvs/`)
2. AI: parse contacts + score CV → interrupt
3. Роль: **Recruiter** → Approve скрининг
4. Fan-out → interrupt на 3 апрувах
5. Роли: **HM**, **CFO**, **Legal** → Approve (в любом порядке)
6. Роль: **Candidate** → Accept interview
7. Роль: **Interviewer** → Submit scorecard (approve)
8. AI: draft offer → Роль: **Recruiter** → Approve offer
9. Роль: **Candidate** → Accept offer → **HIRED**

Параллельно: Skip 4 days → nudge в slack. CFO reject → veto → rejection email.
