# HR Recruiting AI Agent — Solution

## Как я моделирую процесс

Рекрутинг — это долгоживущий процесс с несколькими участниками, параллельными ветками и внешними ожиданиями. Ключевой вызов: граф должен уметь **ждать дни и недели** между шагами, сохраняя полный контекст.

### Этапы и где они ждут

```
Candidate applies (paste CV)
    │
    ▼
[INTAKE] ── AI: parse CV → extract contacts
    │         автоматически, секунды
    ▼
[SCORE_CV] ── AI: score 0-100 + summary
    │          автоматически, секунды
    │
    ▼  ← ЖДЁМ: Recruiter review (может быть несколько дней)
    │
    ├─ Reject → AI: gen rejection email → END
    │
    ▼  Fan-out → 3 параллельных аппрува
┌───┴───┬───────┐
│       │       │
HM    CFO    Legal   ← ЖДЁМ: каждый независимо, в любом порядке
│       │       │
└───┬───┴───────┘
    │  aggregate: ALL approve → proceed, ANY reject → veto
    │
    ▼  ← ЖДЁМ: Candidate accepts/declines interview
    │
    ▼  ← ЖДЁМ: Interviewer submits scorecard
    │
    ├─ Reject → AI: gen rejection email → END
    │
    ▼
[OFFER] ── AI: generate offer draft
    │        автоматически
    │
    ▼  ← ЖДЁМ: Recruiter approves offer
    │
    ▼  ← ЖДЁМ: Candidate accepts/rejects offer
    │
  HIRED ✓
```

**Параллельные действия:** HM, CFO, Legal — fan-out через LangGraph `Send()`. Каждый аппрув независим, порядок не важен, граф ждёт всех трёх (fan-in в `aggregate_approvals`).

**Где система ждёт:** 7 точек прерывания — recruiter review, 3 аппрува, interview schedule, scorecard, offer decision. В каждой точке граф сохраняет полный стейт и ждёт HTTP-запроса от человека — часы, дни, недели.

---

## Что автоматизируется, где нужен человек

### AI делает автоматически:
1. **CV Parsing** — извлечение имени, email, телефона, telegram, linkedin из произвольного текста. Если email не найден → флаг `no_contact`, все email-коммуникации с кандидатом отключаются.
2. **CV Scoring** — оценка 0-100 с reasoning, strengths, red_flags относительно требований конкретной вакансии.
3. **Recruiter Summary** — краткое описание кандидата для быстрого решения.
4. **Offer Draft** — генерация текста оффера по имени кандидата и позиции.
5. **Rejection Email** — персонализированный отказ (не шаблонный), с учётом причины отклонения.

### Человек принимает решения:
- **Recruiter**: approve/reject после скрининга; approve offer draft
- **HM, CFO, Legal**: параллельные аппрувы (правило: все должны одобрить; любой вето → rejection)
- **Interviewer**: scorecard после интервью
- **Candidate**: accept/decline интервью; accept/reject оффер

### Как агент понимает что делать дальше:
Граф использует **conditional edges** — функции-роутеры которые смотрят на поле `stage` в стейте и возвращают имя следующей ноды. После каждого человеческого решения `resume_workflow` передаёт `Command(resume={interrupt_id: decision})` в LangGraph, граф продолжается с того места где остановился.

---

## Как обрабатываются задержки и отсутствие ответа

Реализован **virtual clock** вместо реальных таймеров:
- Поле `clock_day` в стейте — виртуальный день процесса
- Кнопка "Skip Day" двигает часы вперёд
- При каждом advance часов система проверяет всех активных кандидатов
- Если `clock_day - last_action_day >= 3` → отправляет nudge в Slack соответствующему участнику
- **Граф не принимает автоматических решений** — только напоминает. Это принципиально: HR-процесс требует человеческого суждения на каждом шаге.

В production: virtual clock заменяется на реальные cron-задачи или scheduled функции.

---

## Почему LangGraph, а не просто код

Без LangGraph нужно самостоятельно реализовать:
- Персистенцию стейта между HTTP-запросами (граф ждёт дни)
- Механизм паузы/возобновления (`interrupt()` + `Command(resume=...)`)
- Fan-out с параллельными ожиданиями (`Send()` API)
- Восстановление после рестарта сервера (checkpointer)
- Инспекцию текущего состояния любого workflow (`get_state(thread_id)`)

LangGraph даёт всё это из коробки. Объём кода без него — несколько сотен строк кастомного state machine.

**Про checkpointer:** используется `SqliteSaver` — персистентность переживает рестарты сервера. Для multi-worker production замена на `AsyncPostgresSaver` (row-level locking вместо SQLite writer lock).

---

## Стек

| Компонент | Инструмент | Обоснование |
|-----------|-----------|-------------|
| Оркестрация | **LangGraph** | `interrupt()` для HITL, `Send()` для fan-out/fan-in, `SqliteSaver` для персистенции стейта между HTTP-запросами |
| LLM | **OpenAI gpt-4o-mini** | Баланс цена/качество для extraction и scoring. Structured output через `with_structured_output(Pydantic)` |
| LLM интеграция | **langchain-openai** | `ChatOpenAI` вместо прямого openai SDK — LangSmith автоматически видит токены и стоимость каждого вызова |
| Web | **FastAPI + Jinja2 + HTMX** | SSR без SPA-complexity. Process widget обновляется polling каждые 5 секунд без перезагрузки страницы |
| БД | **SQLite + SQLModel** | Zero-config, embedded. Две базы: `hr.db` (бизнес-данные) и `checkpoints.db` (LangGraph стейт) |
| Визуализация | **Mermaid** | Pipeline диаграмма в реальном времени — overview mode (количество кандидатов на каждом этапе) и focus mode (подсветка текущей ноды конкретного кандидата) |
| Observability | **LangSmith** | Трейсинг LLM вызовов, токены и стоимость по каждому run. Каждый workflow = отдельный именованный trace |
| Dev tools | **LangGraph Studio** | Визуальный граф, пошаговое выполнение, инспекция стейта в каждой ноде |

---

## Структура кода

```
src/
  workflow.py   — LangGraph StateGraph, routing, checkpointer, start/resume
  nodes.py      — функции нод (intake, score_cv, recruiter_review, approvals, ...)
  llm.py        — ChatOpenAI client, все LLM-вызовы
  comms.py      — send_email, send_slack, audit_log
  clock.py      — virtual clock (advance/now)
  models.py     — SQLModel: Candidate, Job, Message, AuditEvent, Clock
  schemas.py    — Pydantic: CandidateContact, CVScore
  app.py        — FastAPI routes, HTMX endpoints
  templates/    — Jinja2 + Bootstrap 5
data/
  hr.db              — бизнес-данные
  checkpoints.db     — LangGraph стейт всех workflow
  sample_cvs/        — тестовые резюме разного уровня
logs/
  audit.jsonl        — полный аудит лог всех событий
  emails/            — все отправленные emails (markdown файлы)
  slack/             — все slack сообщения (markdown файлы)
```

---

## Ключевые фрагменты кода

### Граф с fan-out и interrupt

```python
class RecruitingState(TypedDict, total=False):
    candidate_id: int
    stage: str
    score: dict
    approvals: dict[str, str]
    approval_results: Annotated[list[dict], operator.add]  # fan-in accumulator
    offer_text: str
    clock_day: int
    last_action_day: int

def route_after_recruiter(state) -> list[Send] | str:
    if state.get("stage") == "rejected":
        return END
    # fan-out: три параллельных аппрува
    return [
        Send("approval_hm", {...}),
        Send("approval_cfo", {...}),
        Send("approval_legal", {...}),
    ]

def recruiter_review(state: dict) -> dict:
    # граф останавливается здесь и ждёт HTTP-запроса
    decision = interrupt({
        "type": "recruiter_review",
        "score": state.get("score"),
        "message": "Review CV score and approve or reject.",
    })
    if decision["decision"] == "reject":
        # генерируем rejection email через LLM
        return {"stage": "rejected"}
    return {"stage": "approvals", "approvals": {"hm": "pending", "cfo": "pending", "legal": "pending"}}
```

### Персистентный resume через HTTP

```python
# FastAPI endpoint — кнопка Approve/Reject в UI
@app.post("/action/{candidate_id}")
def human_action(candidate_id: int, decision: str = Form(...), interrupt_id: str = Form("")):
    candidate = session.get(Candidate, candidate_id)
    resume_map = {interrupt_id: {"decision": decision, "comment": comment}}
    workflow.resume_workflow(candidate.thread_id, decision, comment, resume_map=resume_map)
    return RedirectResponse(url=f"/candidate/{candidate_id}")

# LangGraph resume — продолжает с места прерывания
def resume_workflow(thread_id: str, decision: str, resume_map: dict) -> dict:
    graph = get_graph()  # SqliteSaver — переживает рестарты
    config = {"configurable": {"thread_id": thread_id}, "run_name": f"..."}
    return graph.invoke(Command(resume=resume_map), config=config)
```

### Nudge при задержке

```python
def _check_nudges(session, current_day: int):
    for candidate in active_candidates:
        ws = workflow.get_workflow_state(candidate.thread_id)
        last_action = ws["values"].get("last_action_day", 0)
        if current_day - last_action >= 3:
            for node in ws["next"]:
                role = _node_to_role(node)
                comms.send_slack(session, candidate.id, "nudge", role,
                    f"Reminder: {candidate.name} waiting for {node} for {current_day - last_action} days.")
```

---

## Запуск и проверка

```bash
cp .env.example .env      # OPENAI_API_KEY + LANGSMITH_API_KEY
uv sync
uv run python -m src.db   # seed DB
uv run uvicorn src.app:app --reload --port 8000
# → http://localhost:8000

# LangGraph Studio (визуальный граф):
uv run langgraph dev
# → http://localhost:2024
```

**Demo сценарий (полный пайплайн):**
1. Роль **Candidate** → Apply → вставить CV из `data/sample_cvs/`
2. AI парсит и скорит CV автоматически
3. Роль **Recruiter** → Approve
4. Роли **HM**, **CFO**, **Legal** → Approve (в любом порядке)
5. Роль **Candidate** → Accept interview
6. Роль **Interviewer** → Approve scorecard
7. Роль **Recruiter** → Approve offer draft
8. Роль **Candidate** → Accept offer → **HIRED**

Параллельный тест: Skip 4 дня → nudge в Slack. CFO Reject → veto → rejection email кандидату.

---

## Production-ready улучшения

- **SQLite → PostgreSQL**: `AsyncPostgresSaver` для multi-worker (row-level locking вместо SQLite writer lock)
- **Graph migration**: при изменении флоу — версионирование графа (`graph_v1`, `graph_v2`), старые кандидаты продолжают в v1, новые идут в v2
- **Email/Slack**: заменить file-based logging на реальные интеграции (SendGrid, Slack API)
- **Auth**: сейчас роль выбирается cookie — в production JWT + RBAC
- **Observability**: LangSmith трейсинг уже подключён — каждый LLM вызов виден с токенами и стоимостью
