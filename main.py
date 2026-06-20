# AI Interaction Log: I used ChatGPT to write the code in Python. I do not know Python yet but I know a little bit of java and c++. 
# I wanted to use python for the project so that I can become more familiar with it. I told ChatGPT what the requirements were for
# ...phase 2. I am not familiar with FastAPI so I asked ChatGPT to create the endpoints that are required for history (post,put,delete)
#..., plan (post,put,delete) and profile endpoint (get). I went to the example at "student-example.html". I inspected the website in
#... Microsoft Edge to get the original html. I put the html in a vscode .html file. I gave the html file to ChatGPT so that it could
#... use it for testing. I used ChatGPT to learn more about what BeautifulSoup is and I now understand it is library that converts html
#...to a cleaner format in a tree-like structure for python to parse. ChatGPT walked me through the steps of how to actually submit the
#... code by opening the project folder using command prompt, using "python -m uvicorn main:app --reload" to get uvicorn to start a
#... web server, open a second command prompt window to test my API using a test "student 111"
#ChatGPT gave me this link to test the import endpoint: curl -F "file=@student-example.html" http://127.0.0.1:8000/api/v1/students/111/history/import
#ChatGPT gave me this to test if I could receive student 111's info including history, plan, course info including attempted and 
# ...zero credit: curl http://127.0.0.1:8000/api/v1/students/111/profile
#ChatGPT gave me this to test the plan endpoint: curl -X POST http://127.0.0.1:8000/api/v1/students/111/plan -H "Content-Type: application/json" -d "{\"planned_courses\":[{\"course_code\":\"COSC-3506\",\"term\":\"26F\"}]}"


from fastapi import FastAPI, UploadFile, File, HTTPException, status
from pydantic import BaseModel
from bs4 import BeautifulSoup
import re

app = FastAPI()

students = {}


class HistoryItem(BaseModel):
    course_code: str
    term: str
    credits_earned: int
    status: str


class HistoryBody(BaseModel):
    history: list[HistoryItem]


class PlannedCourse(BaseModel):
    course_code: str
    term: str


class PlanBody(BaseModel):
    planned_courses: list[PlannedCourse]


def credit_int(text: str) -> int:
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else 0


def course_code_only(text: str) -> str:
    text = (text or "").strip()
    before_colon = text.split(":")[0].strip()
    parts = before_colon.split("-")
    if len(parts) >= 2:
        return parts[0] + "-" + parts[1]
    return before_colon


def grade_score(grade: str) -> int:
    grade = (grade or "").strip()
    if grade.isdigit():
        return 3
    if grade and grade.upper() != "P":
        return 2
    if grade.upper() == "P":
        return 1
    return 0


def deduplicate(records):
    best = {}

    for record in records:
        key = (record["course_code"], record["term"])
        current = best.get(key)

        if current is None:
            best[key] = record
            continue

        new_grade = record.get("_grade", "")
        old_grade = current.get("_grade", "")

        if grade_score(new_grade) > grade_score(old_grade):
            best[key] = record
        elif grade_score(new_grade) == grade_score(old_grade):
            if record["credits_earned"] > current["credits_earned"]:
                best[key] = record

    cleaned = []
    for record in best.values():
        cleaned.append({
            "course_code": record["course_code"],
            "term": record["term"],
            "credits_earned": record["credits_earned"],
            "status": record["status"]
        })

    return cleaned


def parse_table_transcript(soup):
    records = []
    valid_statuses = {"Completed", "In-Progress", "Attempted"}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        headers = [cell.get_text(strip=True).lower() for cell in header_cells]

        if "status" not in headers or "course" not in headers or "term" not in headers or "credits" not in headers:
            continue

        status_i = headers.index("status")
        course_i = headers.index("course")
        grade_i = headers.index("grade") if "grade" in headers else None
        term_i = headers.index("term")
        credits_i = headers.index("credits")

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(status_i, course_i, term_i, credits_i):
                continue

            status_text = cells[status_i].get_text(strip=True)
            course_text = cells[course_i].get_text(strip=True)
            term_text = cells[term_i].get_text(strip=True)
            credits_text = cells[credits_i].get_text(strip=True)
            grade_text = cells[grade_i].get_text(strip=True) if grade_i is not None and grade_i < len(cells) else ""

            if status_text not in valid_statuses:
                continue

            if not term_text:
                continue

            records.append({
                "course_code": course_text,
                "term": term_text,
                "credits_earned": credit_int(credits_text),
                "status": status_text,
                "_grade": grade_text
            })

    return records


def parse_ellucian_bubbles(soup):
    records = []

    for bubble in soup.find_all("div", class_=lambda c: c and "dp-coursebubble-complete" in c):
        link = bubble.find("a", class_=lambda c: c and "dp-planneditemlink" in c)
        grade_span = bubble.find("span", id=lambda x: x and x.startswith("display-grade-"))
        credits_span = bubble.find("span", class_=lambda c: c and "dp-creditstext" in c)

        if not link or not grade_span:
            continue

        course_text = link.get_text(strip=True)
        course_code = course_code_only(course_text)

        grade_id = grade_span.get("id", "")
        match = re.search(r"display-grade-([A-Za-z0-9]+)-", grade_id)
        term = match.group(1) if match else ""

        if not term:
            continue

        grade_text = grade_span.get_text(strip=True)
        credits_text = credits_span.get_text(strip=True) if credits_span else ""

        records.append({
            "course_code": course_code,
            "term": term,
            "credits_earned": credit_int(credits_text),
            "status": "Completed",
            "_grade": grade_text
        })

    return records


def parse_history_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")

    records = parse_table_transcript(soup)

    if not records:
        records = parse_ellucian_bubbles(soup)

    return deduplicate(records)


def require_student(student_id: str):
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")


@app.post("/api/v1/students/{student_id}/history/import", status_code=status.HTTP_201_CREATED)
async def import_history(student_id: str, file: UploadFile = File(...)):
    content = await file.read()
    history = parse_history_html(content)

    students[student_id] = {
        "history": history,
        "plan": []
    }

    return {
        "status": "success",
        "past_courses_imported": len(history)
    }


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, body: HistoryBody):
    require_student(student_id)

    students[student_id]["history"] = [item.model_dump() for item in body.history]

    return {
        "status": "success",
        "message": "Academic history updated successfully"
    }


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    require_student(student_id)

    students[student_id]["history"] = []

    return {
        "status": "success",
        "message": "Academic history cleared successfully"
    }


@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, body: PlanBody):
    require_student(student_id)

    students[student_id]["plan"] = [item.model_dump() for item in body.planned_courses]

    return {
        "status": "success",
        "planned_courses_saved": len(body.planned_courses)
    }


@app.put("/api/v1/students/{student_id}/plan")
def update_plan(student_id: str, body: PlanBody):
    require_student(student_id)

    students[student_id]["plan"] = [item.model_dump() for item in body.planned_courses]

    return {
        "status": "success",
        "planned_courses_saved": len(body.planned_courses)
    }


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    require_student(student_id)

    students[student_id]["plan"] = []

    return {
        "status": "success",
        "message": "Plan cleared successfully"
    }


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    require_student(student_id)

    return {
        "student_id": student_id,
        "history": students[student_id]["history"],
        "plan": students[student_id]["plan"]
    }
