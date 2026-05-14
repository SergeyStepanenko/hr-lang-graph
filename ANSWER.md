# HR Recruiting AI Agent — Ответ на тестовое задание

> **Репозиторий с реализацией:** [github.com/SergeyStepanenko/hr-lang-graph](https://github.com/SergeyStepanenko/hr-lang-graph)

---

## Контекст задания

Recruiting flow — **долгоживущий и многоучастниковый процесс**. Между шагами проходят не секунды, а дни и недели. Система должна уметь ждать, сохраняя полный контекст, переживать рестарты, поддерживать параллельные ветки и возобновляться с точного места прерывания. Из этих требований и вытекают все технические решения ниже.

---

## Оптимальный процесс глазами бизнеса

> *«Опишите, как вы видите оптимальный процесс…»*

До того как обсуждать AI-агента — как должен выглядеть процесс в идеале:

1. **Кандидат подаёт CV** — единая точка входа (форма / email / ATS-интеграция). Никаких «отправь резюме на почту X, а потом продублируй Y».
2. **Быстрая первичная оценка без человека** — AI парсит CV, извлекает контакты, скорит относительно требований конкретной вакансии. Это снимает с recruiter рутину чтения сотен CV.
3. **Recruiter принимает решение по короткой сводке** — не читает всё CV целиком, а видит score, strengths, red_flags и 3–5 предложений summary. Решение — **за человеком**, AI только готовит контекст.
4. **Параллельные апрувы, а не последовательные** — HM (профильное соответствие), CFO (бюджет), Legal (возможность работы в локации) запрашиваются **одновременно**. Любой может заблокировать → процесс останавливается с понятной причиной. Все одобрили → дальше.
5. **Кандидат и интервьюер согласуют интервью** — система отправляет приглашение, ждёт подтверждения, фиксирует scorecard.
6. **Оффер генерируется AI, проверяется recruiter, отправляется кандидату** — никаких «оффер по шаблону руками в Word». Recruiter ревьюит черновик перед отправкой.
7. **Прозрачность на каждом шаге** — кто, когда, по какой причине принял решение. Полный audit trail для HR-аудита и compliance.
8. **Терпимость к задержкам** — если участник не отвечает 3+ дня, система **напоминает**, но **не принимает решение за него**. HR-решения требуют человеческого суждения, автоматический reject из-за тишины недопустим.
9. **Edge cases — не блокеры, а ветки** — CV без email не должен ронять процесс; рестарт сервера не должен терять стейт; параллельные кандидаты на одну вакансию — независимы.

Ниже — как этот процесс ложится на AI-agent flow.

---

## 1. Как я моделирую процессы

> *«Какие этапы выделяете; где есть параллельные действия; где система должна ждать внешний ответ или фидбэк.»*

### Граф процесса

Ниже — реальный граф из **LangGraph Studio** (`langgraph dev`), построенный на основе кода этого проекта. Нагляднее любой ASCII-схемы: видны параллельные ветки апрувов, все точки прерывания и альтернативные пути завершения через `__end__`.

![LangGraph Studio — граф recruiting pipeline](assets/langgraph-studio-graph.png)

### Этапы процесса

Линейно процесс выглядит так: **кандидат подаёт CV → AI парсит контакты и скорит относительно вакансии → recruiter ревьюит сводку → если ок, параллельно стартуют апрувы HM/CFO/Legal → если все одобрили, согласуется интервью → интервьюер заполняет scorecard → AI генерирует offer draft → recruiter ревьюит → оффер уходит кандидату → кандидат принимает решение**. На любом шаге процесс может уйти в rejection — с автоматической отправкой эмпатичного отказа.

Каждый этап — нода в LangGraph. Автоматические шаги работают без участия человека, шаги с `⏸` — точки `interrupt()`, где граф сериализует стейт и ждёт HTTP-запроса с решением.

| # | Нода | Тип | Участник |
|---|---|---|---|
| 1 | `intake` | Автомат (AI) | — |
| 2 | `score_cv` | Автомат (AI) | — |
| 3 | `recruiter_review` | ⏸ Ожидание | Recruiter |
| 4a | `approval_hm` | ⏸ Параллельно | Hiring Manager |
| 4b | `approval_cfo` | ⏸ Параллельно | CFO |
| 4c | `approval_legal` | ⏸ Параллельно | Legal |
| 5 | `aggregate_approvals` | Автомат | — |
| 6 | `interview_schedule` | ⏸ Ожидание | Candidate |
| 7 | `interview_scorecard` | ⏸ Ожидание | Interviewer |
| 8 | `offer_generate` | Автомат (AI) | — |
| 9 | `offer_recruiter_review` | ⏸ Ожидание | Recruiter |
| 10 | `offer_candidate_decision` | ⏸ Ожидание | Candidate |

### Где есть параллельные действия

Этапы 4a/4b/4c — апрувы HM, CFO и Legal — **запускаются одновременно** через LangGraph `Send()` (fan-out). Каждый ждёт своего `interrupt()` независимо, в любом порядке. Fan-in происходит в `aggregate_approvals`: граф туда попадает только когда все три ветки завершились.

Правило агрегации: **все должны одобрить** → `stage = "interview"`; **любой вето** → rejection email кандидату + `END`.

**Код fan-out** [src/workflow.py:48](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/workflow.py#L48):

```python
def route_after_recruiter(state: RecruitingState) -> list[Send] | str:
    if state.get("stage") == "rejected":
        return END
    # fan-out: три параллельных аппрува
    return [
        Send("approval_hm",    {"candidate_id": ..., "clock_day": ...}),
        Send("approval_cfo",   {"candidate_id": ..., "clock_day": ...}),
        Send("approval_legal", {"candidate_id": ..., "clock_day": ...}),
    ]
```

**Код fan-in** (reducer-аккумулятор) [src/workflow.py:40](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/workflow.py#L40):

```python
class RecruitingState(TypedDict, total=False):
    approval_results: Annotated[list[dict], operator.add]  # каждый апрув добавляет в список
```

### Где система должна ждать внешний ответ

7 точек прерывания — `interrupt()` внутри ноды останавливает граф, сериализует стейт в SQLite, освобождает поток. Граф не «спит» — ждёт HTTP-запроса, который может прийти через часы или недели.

**Как это выглядит в коде** [src/nodes.py:90](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/nodes.py#L90):

```python
def recruiter_review(state: dict) -> dict:
    # граф останавливается здесь. стейт сериализован в SqliteSaver.
    # процесс не держит память/поток — ждёт ровно до момента,
    # когда придёт HTTP /action/{candidate_id} с решением.
    decision = interrupt({
        "type": "recruiter_review",
        "score": state.get("score"),
        "message": "Review CV score and approve or reject.",
    })
    # сюда возвращаемся уже на следующем HTTP-запросе через дни/недели
    return {"stage": "approvals" if decision["decision"] == "approve" else "rejected"}
```

Полный список точек ожидания:

| Нода | Кто отвечает | Что система отправила до этого |
|---|---|---|
| `recruiter_review` | Recruiter | Slack: AI score + summary кандидата |
| `approval_hm` | Hiring Manager | Slack: запрос на апрув |
| `approval_cfo` | CFO | Slack: запрос на апрув |
| `approval_legal` | Legal | Slack: запрос на апрув |
| `interview_schedule` | Candidate | Email: приглашение на интервью |
| `interview_scorecard` | Interviewer | Email: подтверждение расписания |
| `offer_recruiter_review` | Recruiter | Slack: "offer draft ready" |
| `offer_candidate_decision` | Candidate | Email: текст оффера |

---

## 2. Как работает агент/flow

> *«Какие шаги автоматизируются полностью; где нужен человек; как агент понимает, что делать дальше; как обрабатываются исключения, задержки и отсутствие ответа.»*

### Что автоматизируется полностью

| Шаг | Что делает AI | Код |
|---|---|---|
| **CV Parsing** | Извлекает name, email, phone, telegram, linkedin из произвольного текста. Structured output → Pydantic `CandidateContact`. Если email не найден → флаг `no_contact`, email-коммуникации с кандидатом отключаются. | [src/llm.py:19](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/llm.py#L19) |
| **CV Scoring** | Оценка 0–100 с reasoning, strengths, red_flags относительно требований конкретной вакансии. Structured output → `CVScore`. | [src/llm.py:34](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/llm.py#L34) |
| **Recruiter Summary** | 3–5 предложений о кандидате для быстрого принятия решения. | [src/llm.py:48](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/llm.py#L48) |
| **Offer Draft** | Персонализированный текст job offer letter — имя кандидата + позиция. | [src/llm.py:62](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/llm.py#L62) |
| **Rejection Email** | Профессиональный эмпатичный отказ с учётом причины. Внутренние формулировки ("too junior") не попадают в текст письма кандидату. | [src/llm.py:70](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/llm.py#L70) |
| **Approval aggregation** | Детерминированная логика без LLM: ALL approved → interview, ANY rejected → veto + rejection. | [src/nodes.py:174](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/nodes.py#L174) |

### Где нужен человек

Каждое бизнес-решение остаётся за человеком. AI только готовит информацию и контекст:

- **Recruiter** — approve/reject кандидата после скрининга; approve offer draft перед отправкой
- **HM / CFO / Legal** — параллельные апрувы (любой может заблокировать)
- **Interviewer** — scorecard с оценкой после интервью
- **Candidate** — подтверждение интервью; accept/reject оффера

Нажатие кнопки Approve/Reject в UI → POST `/action/{candidate_id}` → `resume_workflow()` → `Command(resume={interrupt_id: decision})` → LangGraph продолжает с точного места прерывания.

### Как агент понимает, что делать дальше

**Принципиально: LLM не принимает решений о маршрутизации.** Агент не «думает», что делать следующим — следующий шаг определяется детерминированной функцией от `state["stage"]`. LLM работает только внутри нод и только над контентом (парсинг CV, скоринг, генерация текста оффера/отказа). Это делает поведение графа воспроизводимым, тестируемым и понятным аудиту.

Граф использует **conditional edges** — функции-роутеры, которые читают `state["stage"]` и возвращают имя следующей ноды (или `END`). Единственный источник правды — поле `stage`. Каждая нода возвращает `{"stage": "..."}`, роутер переходит дальше.

**Код роутеров** [src/workflow.py:73](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/workflow.py#L73):

```python
def route_after_aggregate(state: RecruitingState) -> str:
    if state.get("stage") == "rejected":
        return END
    if state.get("stage") == "interview":
        return "interview_schedule"
    return END

def route_after_scorecard(state: RecruitingState) -> str:
    if state.get("stage") == "rejected":
        return END
    return "offer_generate"
```

Нет `if event == "cfo_approved_do_X"`. Нет распределённого state machine по всему коду. Один граф, одна функция перехода на каждое ребро.

### Как обрабатываются исключения, задержки и отсутствие ответа

#### Задержки и отсутствие ответа — virtual clock + nudge

Вместо реальных таймеров — **virtual clock**: целое число `clock_day` в БД. Кнопка "Skip Time" двигает его вперёд. При каждом `advance()` система проверяет всех активных кандидатов: если `clock_day - last_action_day >= 3` → Slack-напоминание ответственному участнику.

**Принципиально важно**: граф **не принимает автоматических решений при таймауте** — только напоминает. HR-решения требуют человеческого суждения, автоматический reject из-за задержки недопустим.

**Код nudge** [src/app.py:63](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/app.py#L63):

```python
def _check_nudges(session, current_day: int):
    for candidate in active_candidates:
        ws = workflow.get_workflow_state(candidate.thread_id)
        last_action = ws["values"].get("last_action_day", 0)
        if current_day - last_action >= 3:
            for node in ws["next"]:
                role = _node_to_role(node)
                comms.send_slack(session, candidate.id, "nudge", role,
                    f"Reminder: {candidate.name} waiting for {node} "
                    f"for {current_day - last_action} days.")
```

В production: virtual clock → реальный cron (APScheduler / Cloud Scheduler).

#### Кандидат без email — флаг `no_contact`

Если `parse_cv_contact` не нашёл email → `no_contact = True`. Все `send_email()` для кандидата пропускаются условно. Workflow продолжается полностью — только без email-коммуникаций с кандидатом.

**Код** [src/nodes.py:38](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/nodes.py#L38):

```python
no_contact = contact.email is None
if no_contact:
    audit_log(session, candidate_id, "no_contact_warning", "system", "No email found")
else:
    comms.send_email(session, candidate_id, "candidate", "Application Received", ...)
```

#### Ошибки запуска workflow

`try/except` в `/apply`: если `start_workflow` падает (сеть, API), ошибка пишется в `audit_log`, кандидат сохраняется в БД. **Код** [src/app.py:161](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/app.py#L161).

#### Персистентность после рестарта сервера

`SqliteSaver` как checkpointer: стейт каждого workflow сериализован в `data/checkpoints.db`. Сервер перезапускается — граф продолжает с последней контрольной точки без потери данных. **Код** [src/workflow.py:144](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/workflow.py#L144).

---

## 3. Как я реализовал решение

> *«Можно текстом, схемой, псевдокодом или небольшим кодовым примером; не нужен большой production-ready проект; важнее логика, структура решения и ход мыслей.»*

### Почему LangGraph, а не просто код

Без LangGraph нужно реализовать вручную: персистенцию стейта между HTTP-запросами, механизм паузы/возобновления, fan-out с параллельными ожиданиями, восстановление после рестарта, инспекцию текущего состояния любого workflow. LangGraph даёт всё это из коробки через `interrupt()`, `Send()` и checkpointer.

### Стек

| Компонент | Инструмент | Обоснование |
|---|---|---|
| Оркестрация | **LangGraph** | `interrupt()` для HITL, `Send()` для fan-out/fan-in, `SqliteSaver` для персистенции |
| LLM | **OpenAI gpt-4o-mini** | Structured output через Pydantic, баланс цена/качество для extraction и scoring |
| LLM интеграция | **langchain-openai** | `ChatOpenAI` — LangSmith автоматически видит токены и стоимость каждого вызова |
| Web | **FastAPI + Jinja2 + HTMX** | SSR без SPA-complexity. Process widget polling каждые 5 секунд без перезагрузки |
| БД | **SQLite + SQLModel** | Zero-config, embedded. Две базы: `hr.db` (бизнес-данные) и `checkpoints.db` (LangGraph стейт) |
| Observability | **LangSmith** | Трейсинг всех LLM вызовов, каждый workflow = именованный trace с метаданными |
| Dev tools | **LangGraph Studio** | Визуальный граф (скриншот выше), пошаговое выполнение, инспекция стейта |

### Структура кода

```
src/
  workflow.py   — StateGraph, routing functions, checkpointer, start/resume
  nodes.py      — node functions: intake, score_cv, recruiter_review, approvals, ...
  llm.py        — ChatOpenAI client, все LLM-вызовы с run_name для LangSmith
  comms.py      — send_email, send_slack, audit_log
  clock.py      — virtual clock (advance/now)
  models.py     — SQLModel: Candidate, Job, Message, AuditEvent, Clock
  schemas.py    — Pydantic: CandidateContact, CVScore
  app.py        — FastAPI routes, HTMX endpoints, nudge logic
tests/
  test_workflow_routing.py  — unit: routing functions (без БД, без LLM)
  test_nodes.py             — integration: ноды с мок-LLM, in-memory DB
  test_evals.py             — LLM evals: heuristic + LLM-as-judge (реальные API вызовы)
```

### Ключевые фрагменты

#### Стейт и resume через HTTP

[src/workflow.py:29](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/workflow.py#L29):

```python
class RecruitingState(TypedDict, total=False):
    candidate_id: int
    stage: str
    score: dict
    approvals: dict[str, str]
    approval_results: Annotated[list[dict], operator.add]  # fan-in reducer
    offer_text: str
    clock_day: int
    last_action_day: int
```

[src/workflow.py:189](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/workflow.py#L189) — resume после человеческого решения:

```python
def resume_workflow(thread_id: str, decision: str, resume_map: dict | None = None, ...) -> dict:
    graph = get_graph()  # SqliteSaver — переживает рестарты
    config = {"configurable": {"thread_id": thread_id},
              "run_name": f"{label} — {node_name}: {decision}"}
    if resume_map:
        return graph.invoke(Command(resume=resume_map), config=config)
    return graph.invoke(Command(resume={"decision": decision, "comment": comment}), config=config)
```

#### interrupt в ноде → решение человека → продолжение

[src/nodes.py:90](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/nodes.py#L90):

```python
def recruiter_review(state: dict) -> dict:
    # граф останавливается здесь, стейт сохранён в SQLite
    decision = interrupt({
        "type": "recruiter_review",
        "score": state.get("score"),
        "message": "Review CV score and approve or reject.",
    })
    if decision["decision"] == "reject":
        rejection_text = llm.gen_rejection(candidate.name, decision.get("comment"))
        comms.send_email(...)
        return {"stage": "rejected"}
    return {"stage": "approvals", "approvals": {"hm": "pending", "cfo": "pending", "legal": "pending"}}
```

#### Параллельный approval с fan-in

[src/nodes.py:148](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/nodes.py#L148):

```python
def _do_approval(state: dict, role: str) -> dict:
    decision = interrupt({"type": f"approval_{role}", "role": role, ...})
    human_decision = decision.get("decision", "approved")
    comms.send_slack(..., f"{'✅' if human_decision == 'approved' else '❌'} {role.upper()} {human_decision}")
    # operator.add reducer накапливает результаты всех трёх апрувов
    return {"approval_results": [{"approver": role, "approval_decision": human_decision, ...}]}
```

[src/nodes.py:174](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/nodes.py#L174):

```python
def aggregate_approvals(state: dict) -> dict:
    for r in state.get("approval_results", []):
        approvals[r["approver"]] = r["approval_decision"]

    if any(v == "rejected" for v in approvals.values()):
        return {"stage": "rejected"}   # любой вето → rejection email + END
    if all(v == "approved" for v in approvals.values()):
        return {"stage": "interview"}  # все одобрили → интервью
    return {"stage": "approvals"}      # ещё не все ответили
```

#### LLM scoring со structured output

[src/llm.py:34](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/llm.py#L34):

```python
def score_cv(cv_text: str, job_title: str, job_requirements: str) -> CVScore:
    chain = _get_llm().with_structured_output(CVScore).with_config(
        run_name=f"Score CV for: {job_title}"  # виден в LangSmith с токенами и стоимостью
    )
    return chain.invoke([
        SystemMessage(content=f"Score CV for: {job_title}.\nRequirements:\n{job_requirements}"),
        HumanMessage(content=cv_text),
    ])

# Pydantic схема — src/schemas.py:13
class CVScore(BaseModel):
    score: int = Field(ge=0, le=100)
    reasoning: str
    red_flags: list[str]
    strengths: list[str]
```

#### LLM Evals — проверка качества AI-решений

Два слоя: **heuristic** (детерминированные assertions) + **LLM-as-judge** (второй LLM оценивает качество первого).

[tests/test_evals.py:59](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/tests/test_evals.py#L59):

```python
def llm_judge(judge, question: str, context: str) -> bool:
    response = judge.invoke([
        SystemMessage(content="You are a strict evaluator. Answer only YES or NO."),
        HumanMessage(content=f"Context:\n{context}\n\nQuestion: {question}"),
    ])
    return response.content.strip().upper().startswith("YES")

# пример: rejection email не должен раскрывать внутренние формулировки кандидату
def test_does_not_reveal_internal_reason_verbatim(self, judge):
    result = llm.gen_rejection("Bob Smith", "Candidate is too junior and lacks focus")
    assert llm_judge(judge,
        'Does this email avoid repeating harsh internal notes like "too junior" verbatim?',
        result,
    )
```

### Прозрачность — полный audit trail

> *«Весь флоу должен быть контролируемым и прозрачным, независимо от того, выполняется ли он автоматически, ожидает наступления события в будущем или требует действий со стороны пользователя.»*

Каждое действие — и автоматическое, и человеческое — пишется в `audit.jsonl` через [src/comms.py:78](https://github.com/SergeyStepanenko/hr-lang-graph/blob/9268ed0/src/comms.py#L78):

```json
{"event": "cv_scored",              "actor": "ai",        "reasoning": "Score: 87/100", "clock_day": 0}
{"event": "recruiter_approved",     "actor": "recruiter", "reasoning": "Good fit",      "clock_day": 0}
{"event": "approval_cfo_rejected",  "actor": "cfo",       "reasoning": "Budget freeze", "clock_day": 2}
{"event": "approvals_vetoed",       "actor": "system",    "reasoning": "...",           "clock_day": 2}
{"event": "offer_accepted",         "actor": "candidate", "reasoning": "",              "clock_day": 5}
```

Кто что решил, когда (виртуальный день), по какой причине — полный след для HR-аудита.

---

## Запуск

```bash
git clone https://github.com/SergeyStepanenko/hr-lang-graph
cd hr-lang-graph
cp .env.example .env      # OPENAI_API_KEY=sk-...
uv sync
uv run python -m src.db   # seed DB
uv run uvicorn src.app:app --reload --port 8000
# → http://localhost:8000

uv run langgraph dev       # LangGraph Studio
# → http://localhost:2024

uv run pytest              # unit + integration
uv run pytest -m eval      # LLM evals (требует OPENAI_API_KEY)
```

**Demo — полный happy path:**
1. Роль **candidate** → Apply → `data/sample_cvs/alice_johnson.txt`
2. AI парсит и скорит автоматически
3. Роль **recruiter** → Approve
4. Роли **hm / cfo / legal** → Approve в любом порядке
5. Роль **candidate** → Accept interview
6. Роль **interviewer** → Approve scorecard
7. Роль **recruiter** → Approve offer draft
8. Роль **candidate** → Accept offer → **HIRED**

**Demo — edge cases:**
- CFO → Reject → veto → rejection email кандидату
- Skip 4 дня → nudge в Slack всем ожидающим
- `carol_no_email.txt` → процесс без email-коммуникаций

---

## Production-ready улучшения

| Что сейчас | Что в production |
|---|---|
| `SqliteSaver` | `AsyncPostgresSaver` — row-level locking для multi-worker |
| Один граф | Версионирование: `graph_v1` / `graph_v2` — старые кандидаты в старом графе |
| File-based email/Slack | SendGrid + Slack API |
| Cookie-role | JWT + RBAC |
| Virtual clock + nudge | Реальный cron (APScheduler / Cloud Scheduler) |
| LangSmith уже подключён | Каждый LLM вызов виден с токенами, стоимостью и latency |
