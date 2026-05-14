# HR Recruiting AI Agent — MVP Plan

**Цель:** работающий MVP рекрутинг-системы с web UI, где один человек симулирует **всех** актёров процесса (кандидата, рекрутера, HM, CFO, Legal, Interviewer) через переключатель ролей.

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│            Web UI (FastAPI + Jinja2 + HTMX)                 │
│                                                             │
│  Role Switcher │ Dashboard │ Candidate │ Inbox │ Logs       │
│  Skip-Time button (virtual clock)                           │
│  Global Process Widget (mermaid, all pages, HTMX polling)   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              Orchestration (LangGraph)                       │
│                                                             │
│  StateGraph → interrupt_before (human-in-the-loop)          │
│  Send API → параллельные апрувы (HM ∥ CFO ∥ Legal)          │
│  SqliteSaver → персист state между HTTP-запросами           │
└────────────┬─────────────────────────────┬──────────────────┘
             │                             │
┌────────────▼────────────┐   ┌────────────▼──────────────────┐
│    AI (LangGraph nodes) │   │    Communications              │
│    instructor + openai  │   │    (File Logs + Inbox)         │
│                         │   │                                │
│  • cv_parser → Contact  │   │  logs/emails/*.md              │
│  • cv_scorer → CVScore  │   │  logs/slack/*.md               │
│  • summary (str)        │   │  inbox: filter by to_role      │
│  • offer_draft (str)    │   │  logs/audit.jsonl              │
│  • rejection (str)      │   │                                │
└────────────┬────────────┘   └────────────────────────────────┘
             │
       OpenAI API (gpt-4o-mini)
```

## Стек

| Компонент | Инструмент |
|-----------|-----------|
| Язык | Python 3.12+, uv, ruff |
| Web | FastAPI + Jinja2 + HTMX |
| Оркестрация | LangGraph (StateGraph, interrupt_before, Send, SqliteSaver) |
| LLM | OpenAI gpt-4o-mini через `instructor` (structured output: CandidateContact, CVScore) |
| БД | SQLite (SQLModel) |
| Коммуникации | Файловые логи (markdown) + Inbox в UI |

## Ключевые решения

1. **LangGraph `interrupt_before`** — граф останавливается перед human-step. UI читает pending action из БД, кнопка POST резюмит граф через `thread_id`.
2. **Один пользователь = все роли** — верхний переключатель "Я сейчас: Candidate / Recruiter / HM / CFO / Legal / Interviewer". Dashboard и Inbox фильтруются по выбранной роли.
3. **Параллельные апрувы через `Send`** — fan-out на 3 ноды (HM, CFO, Legal), независимые interrupts, fan-in aggregator. **Правило:** all-approve чтобы пройти, любой reject = veto → кандидат отклонён.
4. **Виртуальные часы** — кнопка "Skip 1 day" в UI вместо реального scheduler. Двигает `clock`, триггерит nudge/auto-reject правила.
5. **Кандидат — тоже актёр** — Apply (paste CV + выбор вакансии), accept/decline interview, accept/reject offer. Кнопка "Stay silent" = ничего не делать (для теста таймаутов).
6. **Коммуникации = файлы + Inbox** — каждое "письмо" пишется в `logs/emails/*.md` И добавляется в `messages` (поле `to_role`). UI показывает Inbox под текущей ролью.
7. **Две Pydantic-схемы для LLM:**
   - `CandidateContact` (name, email?, phone?, telegram?, linkedin?) — все каналы опциональны (LLM возвращает None если не нашёл); email используется как primary канал, без него коммуникации с кандидатом отключаются (флаг "no contact")
   - `CVScore` (score, reasoning, red_flags, strengths) — влияет на ветвление графа
   - Summary / offer / rejection = `str`.
8. **Глобальный Process Widget** — mermaid-диаграмма pipeline в `base.html`, виден на каждой странице. Два режима:
   - **Overview (default)** — на каждой ноде badge с количеством кандидатов в этом стейдже, клик → список
   - **Focus** — диаграмма одного кандидата с подсветкой текущей ноды (зелёное = пройдено, жёлтое pulsing = pending human, серое = впереди); параллельные апрувы рендерятся как три дорожки с индивидуальными статусами
   - Переключение через кнопку "Focus on case ▾" / "Back to overview"; выбранный кандидат хранится в cookie `focus_candidate_id`
   - Auto-focus при заходе на `/candidate/{id}`
   - HTMX `hx-get="/widget" hx-trigger="every 2s"` → обновление без F5

## Структура проекта

```
hr-test-assignment/
├── plan.md
├── AI engineer Test Task.pdf
├── pyproject.toml             # fastapi, langgraph, langgraph-checkpoint-sqlite,
│                              # instructor, openai, sqlmodel, jinja2, python-multipart
├── .env.example               # OPENAI_API_KEY
├── Makefile                   # make run, make seed
├── src/
│   ├── __init__.py
│   ├── app.py                 # FastAPI app + routes
│   ├── models.py              # SQLModel: Candidate, Job, Message, AuditEvent, Clock
│   ├── schemas.py             # Pydantic: CandidateContact, CVScore
│   ├── workflow.py            # LangGraph StateGraph + Send
│   ├── nodes.py               # node-функции (parse/score/approve/...)
│   ├── llm.py                 # instructor client + промпты
│   ├── comms.py               # send_email / send_slack / inbox / audit
│   ├── clock.py               # VirtualClock: now(), advance(days)
│   ├── db.py                  # SQLite + seed
│   └── templates/
│       ├── base.html          # role switcher + skip-time + process widget slot
│       ├── _process_widget.html  # partial: mermaid диаграмма (overview/focus)
│       ├── dashboard.html     # список кандидатов + my pending actions
│       ├── candidate.html     # timeline + текущий stage + действия
│       ├── approval.html      # approve/reject форма
│       ├── inbox.html         # сообщения для текущей роли
│       └── logs.html          # viewer файлов
├── logs/
│   ├── emails/
│   ├── slack/
│   └── audit.jsonl
├── data/
│   └── sample_cvs/            # *.txt (paste-friendly, без PDF)
└── tests/
    └── test_workflow.py
```

## Pipeline: 5 стадий

| Stage | Название | AI | Human / Внешнее | Лог |
|-------|----------|-----|------------------|-----|
| 1 | INTAKE | `cv_parser` → CandidateContact (name, email?, phone?, telegram?, linkedin?) | Candidate: paste CV + apply | audit + welcome email |
| 2 | SCREENING | `cv_scorer` → CVScore; summary | Recruiter: Approve/Reject | email кандидату на extracted email |
| 3 | APPROVALS (∥) | — | HM + CFO + Legal параллельно (all-approve, veto-rule) | slack нотификации |
| 4 | INTERVIEW | — | Candidate: accept/decline slot; Interviewer: scorecard | email invite |
| 5 | OFFER | `offer_draft` (str) | Recruiter approve → Candidate accept/reject | email offer |

**Таймауты (через virtual clock):**
- Молчание роли > 3 дней → nudge в slack (без авто-решений; кейс остаётся pending)
- Время идёт дальше, граф ждёт ручного действия неограниченно

## Этапы реализации

### Step 1: Скелет + модели
- `pyproject.toml`, `.env.example`, `Makefile`
- `SQLModel`: `Candidate` (id, name, email?, phone?, telegram?, linkedin?, cv_text, stage: Literal["intake","screening","approvals","interview","offer","hired","rejected"], status: Literal["active","rejected","hired"], created_at), `Job`, `Message` (id, to_role, to_email?, subject, body, created_at_virtual), `AuditEvent`, `Clock` (single row)
- `Candidate.stage` — материализованное зеркало LangGraph state; ноды графа пишут туда при каждом переходе. Source of truth — checkpoint в SqliteSaver; `Candidate.stage` нужен только для быстрых SQL-аггрегатов (Overview-виджет, dashboard)
- Pydantic: `CandidateContact`, `CVScore`
- Seed: 1 вакансия "AI Engineer", 2-3 CV-текста в `data/sample_cvs/` (с контактами внутри)

### Step 2: LangGraph workflow
- `RecruitingState` TypedDict: `candidate_id`, `stage`, `cv_text`, `score`, `approvals: dict[str, Literal["pending","approved","rejected"]]`, `interview`, `offer`, `clock_day`
- Ноды: `intake` (parse_contact → создать Candidate с заполненными полями), `score_cv`, `recruiter_review`, `fanout_approvals` (через `Send`), `aggregate_approvals`, `interview_schedule`, `interview_scorecard`, `offer_generate`, `offer_decision`
- `interrupt_before` на всех human-нодах
- `SqliteSaver` checkpointer, `thread_id = candidate_id`

### Step 3: LLM ноды (instructor + OpenAI)
- `llm.py`: `client = instructor.from_openai(OpenAI())`
- `cv_parser(cv_text) -> CandidateContact` (все поля опциональны: name, email, phone, telegram, linkedin; `max_retries=2`)
- `cv_scorer(cv_text, job) -> CVScore` (structured, `max_retries=2`)
- `gen_summary(cv_score) -> str` (свободный текст для рекрутера)
- `gen_offer(candidate, job) -> str`
- `gen_rejection(reason) -> str`
- Если email не извлёкся (None) — записать audit warning, поставить флаг "no contact"; коммуникации с кандидатом отключаются, флоу не падает

### Step 4: Communications + Inbox
- `send_email(to_role, to_email, subject, body)` → файл `logs/emails/*.md` + запись в `Message`. Для кандидата `to_email` = `candidate.email` (из CandidateContact), `to_role="candidate"`. Для внутренних — `to_email=None`, `to_role` ∈ {recruiter, hm, cfo, legal, interviewer}.
- `send_slack(channel, to_role, message)` → файл + запись в `Message`
- `audit_log(event, actor, reasoning)` → append `logs/audit.jsonl`
- Все коммуникации помечают `created_at_virtual = clock.now()`
- Inbox-фильтр единый: показываем `Message` где `to_role = current_role` (включая Candidate)

### Step 5: Web UI
- `base.html`: role switcher (cookie-based session role), Skip-1-day кнопка, **слот Process Widget** (HTMX polling every 2s)
- `_process_widget.html` partial: mermaid-диаграмма; режим overview (counts на нодах) или focus (подсветка текущей ноды конкретного кандидата + 3 дорожки на Stage 3)
- Endpoint `GET /widget` → читает cookie `focus_candidate_id`, отдаёт нужный режим
- Кнопки "Focus on case ▾" (dropdown с активными кандидатами) / "Back to overview" — переключают cookie
- Авто-focus при заходе на `/candidate/{id}` (set-cookie на сервере)
- Mermaid-источник: `graph.get_graph().draw_mermaid()` + пост-обработка для подсветки нод по `state.stage` и параллельным `approvals`
- `dashboard.html`: таблица кандидатов + "Мои pending" (фильтр по роли)
- `candidate.html`: timeline всех audit events + действия для активной роли (widget уже сверху из base)
- `approval.html`: AI summary + Approve/Reject + поле комментария
- `inbox.html`: сообщения где `to_role = current_role`
- `logs.html`: список файлов + render markdown
- Resume графа: POST на approve/reject → `graph.invoke(None, config={"thread_id": ...})` с записью решения в state

### Step 6: Glue + Skip-Time логика
- `clock.advance(1)` → проверить все активные threads → если `now - last_action > 3` дней: записать nudge в slack. Авто-решений нет; граф остаётся в pending до ручного действия
- Idempotency: повторный approve игнорируется если stage уже продвинулся

### Step 7: Demo run
- `make seed` + `make run` → :8000
- Сценарий: apply как Candidate → switch на Recruiter approve → switch HM/CFO/Legal approve в любом порядке → Skip 5 days → switch Candidate accept interview → switch Interviewer scorecard → switch Recruiter approve offer → switch Candidate accept
- Параллельный сценарий: создать второго кандидата, прогнать с reject от CFO → проверить veto-flow
- Сценарий молчания: Skip 4 days → увидеть nudge в slack-логе; кейс остаётся pending

### Step 8: Финальный solution.md
- Схема процесса
- Логика агента (как принимает решения, где interrupt, как обрабатывает таймауты/veto)
- Стек + обоснование
- Ссылки на код из работающего MVP

---

_Создано: 2026-05-13_
