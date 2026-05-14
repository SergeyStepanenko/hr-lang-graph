import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from src.models import Clock, Job

DB_PATH = Path(__file__).parent.parent / "data" / "hr.db"
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False)


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def seed():
    init_db()
    with Session(engine) as session:
        existing = session.exec(select(Job)).first()
        if existing:
            print("DB already seeded.")
            return

        job = Job(
            title="AI Engineer",
            description="We are looking for an AI Engineer to join our team and build intelligent systems.",
            requirements=(
                "- 3+ years Python experience\n"
                "- Experience with LLMs (OpenAI, Anthropic, etc.)\n"
                "- Understanding of ML/DL fundamentals\n"
                "- Experience with LangChain/LangGraph or similar frameworks\n"
                "- Strong problem-solving skills\n"
                "- Good communication skills"
            ),
        )
        session.add(job)

        clock = Clock(current_day=0)
        session.add(clock)
        session.commit()
        print("Seeded: 1 job, clock initialized.")

    _create_sample_cvs()


def _create_sample_cvs():
    cv_dir = Path(__file__).parent.parent / "data" / "sample_cvs"
    cv_dir.mkdir(parents=True, exist_ok=True)

    cv1 = cv_dir / "alice_johnson.txt"
    if not cv1.exists():
        cv1.write_text(
            "Alice Johnson\n"
            "Email: alice.johnson@example.com\n"
            "Phone: +1-555-0101\n"
            "LinkedIn: linkedin.com/in/alicejohnson\n"
            "Telegram: @alice_j\n\n"
            "SUMMARY\n"
            "AI Engineer with 5 years of experience building production ML systems.\n\n"
            "EXPERIENCE\n"
            "Senior ML Engineer @ TechCorp (2021-2024)\n"
            "- Built LLM-powered customer support agent (GPT-4, LangChain)\n"
            "- Designed RAG pipeline processing 10M documents\n"
            "- Led team of 3 engineers\n\n"
            "ML Engineer @ DataInc (2019-2021)\n"
            "- Developed recommendation system serving 5M users\n"
            "- Implemented NLP pipeline for sentiment analysis\n\n"
            "EDUCATION\n"
            "MS Computer Science, Stanford University, 2019\n"
            "BS Mathematics, MIT, 2017\n\n"
            "SKILLS\n"
            "Python, PyTorch, TensorFlow, LangChain, LangGraph, OpenAI API, AWS, Docker, Kubernetes\n"
        )

    cv2 = cv_dir / "bob_smith.txt"
    if not cv2.exists():
        cv2.write_text(
            "Bob Smith\n"
            "Email: bob.smith@email.org\n"
            "Phone: +44-20-7946-0958\n\n"
            "SUMMARY\n"
            "Junior developer transitioning into AI. 1 year of Python experience.\n\n"
            "EXPERIENCE\n"
            "Junior Web Developer @ WebShop (2023-2024)\n"
            "- Built React frontends\n"
            "- Some Python scripting for data processing\n\n"
            "EDUCATION\n"
            "BS Information Technology, State University, 2023\n\n"
            "SKILLS\n"
            "JavaScript, React, Python (basic), SQL\n"
        )

    cv3 = cv_dir / "carol_no_email.txt"
    if not cv3.exists():
        cv3.write_text(
            "Carol Martinez\n"
            "Telegram: @carol_m\n\n"
            "SUMMARY\n"
            "ML researcher with 4 years of experience in NLP and computer vision.\n\n"
            "EXPERIENCE\n"
            "Research Scientist @ AILab (2020-2024)\n"
            "- Published 5 papers on transformer architectures\n"
            "- Built production NLP pipeline for entity extraction\n"
            "- Experience with OpenAI, Anthropic APIs\n\n"
            "EDUCATION\n"
            "PhD Computer Science, UC Berkeley, 2020\n\n"
            "SKILLS\n"
            "Python, PyTorch, Transformers, LangGraph, CUDA, distributed training\n"
        )

    print(f"Sample CVs in {cv_dir}")


if __name__ == "__main__":
    seed()
