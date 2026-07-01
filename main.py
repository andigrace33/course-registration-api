# AI Interaction Log: Since phase 1, I have learned a little bit of python so I asked ChatGPT to walk me through
# step by step how to turn the phase 2 code into the phase 3 requirements. I learned about python
# dictionaries, how to make comments with #, remove spaces and hyphens and make uppercase,
# I learned about python lists. I relied on ChatGPT to cover the edge cases involving prerequisites,
# courses taken multiple times etc. ChatGPT also showed me how to execute commands in the Terminal,
# and also how to use uvicorn, and how to complete the github actions checks portion as I have not done this before

from fastapi import FastAPI, UploadFile, File, HTTPException, status
from pydantic import BaseModel
from bs4 import BeautifulSoup
import re

app = FastAPI()

courses = {}
students = {}

# term and year dictionary
season_order = {"W": 1, "SP": 2, "S": 3, "F": 4}


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


# function to separate year and season
def yearSeasonSeparator(yearSeason):
    year = yearSeason[0:2]
    season = yearSeason[2:4]

    if not (year.isdigit()):
        print("invalid year")

    if not (season.isalpha()):
        print("invalid season")

    return (year, season)


# function to determine the earlier term of 2 terms
def isTermEarlier(yearSeason1, yearSeason2):

    year1, season1 = yearSeasonSeparator(yearSeason1)
    year2, season2 = yearSeasonSeparator(yearSeason2)

    if season1 in season_order:
        season1Code = season_order.get(season1)
    if season2 in season_order:
        season2Code = season_order.get(season2)

    term1 = (int(year1), season1Code)
    term2 = (int(year2), season2Code)

    if term1 > term2:
        return False
    if term1 < term2:
        return True
    else:
        return False


# remove spaces and hyphens, make uppercase
def normalize(code: str) -> str:
    return code.replace("-", "").upper().strip().replace(" ", "")


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
        cleaned.append(
            {
                "course_code": record["course_code"],
                "term": record["term"],
                "credits_earned": record["credits_earned"],
                "status": record["status"],
            }
        )

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

        if (
            "status" not in headers
            or "course" not in headers
            or "term" not in headers
            or "credits" not in headers
        ):
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
            grade_text = (
                cells[grade_i].get_text(strip=True)
                if grade_i is not None and grade_i < len(cells)
                else ""
            )

            if status_text not in valid_statuses:
                continue

            if not term_text:
                continue

            records.append(
                {
                    "course_code": course_text,
                    "term": term_text,
                    "credits_earned": credit_int(credits_text),
                    "status": status_text,
                    "_grade": grade_text,
                }
            )

    return records


def parse_ellucian_bubbles(soup):
    records = []

    for bubble in soup.find_all(
        "div", class_=lambda c: c and "dp-coursebubble-complete" in c
    ):
        link = bubble.find("a", class_=lambda c: c and "dp-planneditemlink" in c)
        grade_span = bubble.find(
            "span", id=lambda x: x and x.startswith("display-grade-")
        )
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

        records.append(
            {
                "course_code": course_code,
                "term": term,
                "credits_earned": credit_int(credits_text),
                "status": "Completed",
                "_grade": grade_text,
            }
        )

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


def term_value(term: str):
    term = term.upper().strip()
    year = int(term[0:2])
    season = term[2:]
    return (year, season_order[season])


def term_before(term1: str, term2: str):
    return term_value(term1) < term_value(term2)


def split_course_list(text: str):
    if not text:
        return []

    result = []

    for item in text.split(","):
        item = item.strip()

        if item:
            result.append(item)

    return result


# check prerequisites
def check_prerequisites(student_id: str):
    history = students[student_id]["history"]
    plan = students[student_id]["plan"]

    term_errors = {}

    for planned_course in plan:
        planned_code = planned_course["course_code"]
        planned_term = planned_course["term"]

        catalog_key = normalize(planned_code)

        if catalog_key not in courses:
            continue

        catalog_course = courses[catalog_key]
        prerequisites = split_course_list(catalog_course["prerequisites"])

        for prerequisite in prerequisites:
            found = False

            for history_course in history:
                same_course = normalize(history_course["course_code"]) == normalize(
                    prerequisite
                )
                completed = history_course["status"] == "Completed"
                earlier = term_before(history_course["term"], planned_term)

                if same_course and completed and earlier:
                    found = True
                    break

            if not found:
                if planned_term not in term_errors:
                    term_errors[planned_term] = []

                term_errors[planned_term].append(
                    {
                        "course_code": planned_code,
                        "type": "MISSING_PREREQUISITE",
                        "message": "Missing prerequisite: " + prerequisite,
                    }
                )

    timeline_validation = []

    for term in sorted(term_errors.keys(), key=term_value):
        timeline_validation.append({"term": term, "errors": term_errors[term]})

    return timeline_validation


# cross list checker
def check_cross_lists(student_id: str):
    history = students[student_id]["history"]
    plan = students[student_id]["plan"]

    completed_codes = []

    for history_course in history:
        if history_course["status"] == "Completed":
            completed_codes.append(normalize(history_course["course_code"]))

    violations = []

    for planned_course in plan:
        planned_code = planned_course["course_code"]
        catalog_key = normalize(planned_code)

        if catalog_key not in courses:
            continue

        catalog_course = courses[catalog_key]
        cross_listed_courses = split_course_list(catalog_course["cross_listed"])

        for cross_listed in cross_listed_courses:
            if normalize(cross_listed) in completed_codes:
                violations.append(
                    {
                        "course_code": planned_code,
                        "type": "CROSS_LIST_CONFLICT",
                        "message": "Cross-listed with completed course " + cross_listed,
                    }
                )

    return violations


# credit summary


def get_credit_summary(student_id: str):
    history = students[student_id]["history"]
    plan = students[student_id]["plan"]

    completed_courses = {}
    total_planned = 0

    for history_course in history:
        key = normalize(history_course["course_code"])

        if history_course["status"] == "Completed":
            completed_courses[key] = history_course["credits_earned"]

    total_earned = sum(completed_courses.values())

    for planned_course in plan:
        key = normalize(planned_course["course_code"])

        if key in courses:
            total_planned += courses[key]["credits"]

    total_remaining = max(0, 120 - total_earned - total_planned)

    return {
        "total_earned": total_earned,
        "total_planned": total_planned,
        "total_remaining_for_graduation": total_remaining,
    }


# phase 1 API


@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):

    content = await file.read()
    soup = BeautifulSoup(content, "html.parser")

    table = soup.find("table")
    if not table:
        return {"message": "No table found"}

    rows = table.find("tbody").find_all("tr")

    count = 0

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        course_code = cols[0].get_text(strip=True)
        title = cols[1].get_text(strip=True)
        credits_text = cols[2].get_text(strip=True)
        prerequisites = cols[3].get_text(strip=True)
        cross_listed = cols[4].get_text(strip=True)

        credits = int(credits_text) if credits_text.isdigit() else 0

        key = normalize(course_code)

        courses[key] = {
            "course_code": course_code,
            "title": title,
            "credits": credits,
            "prerequisites": prerequisites,
            "cross_listed": cross_listed,
        }

        count += 1

    return {"message": "Catalog imported", "courses_loaded": count}


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):

    key = normalize(course_code)

    if key not in courses:
        raise HTTPException(status_code=404, detail="Course not found")

    return courses[key]


# phase 2 API


@app.post(
    "/api/v1/students/{student_id}/history/import", status_code=status.HTTP_201_CREATED
)
async def import_history(student_id: str, file: UploadFile = File(...)):
    content = await file.read()
    history = parse_history_html(content)

    students[student_id] = {"history": history, "plan": []}

    return {"status": "success", "past_courses_imported": len(history)}


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, body: HistoryBody):
    require_student(student_id)

    students[student_id]["history"] = [item.model_dump() for item in body.history]

    return {"status": "success", "message": "Academic history updated successfully"}


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    require_student(student_id)

    students[student_id]["history"] = []

    return {"status": "success", "message": "Academic history cleared successfully"}


@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, body: PlanBody):
    require_student(student_id)

    students[student_id]["plan"] = [item.model_dump() for item in body.planned_courses]

    return {"status": "success", "planned_courses_saved": len(body.planned_courses)}


@app.put("/api/v1/students/{student_id}/plan")
def update_plan(student_id: str, body: PlanBody):
    require_student(student_id)

    students[student_id]["plan"] = [item.model_dump() for item in body.planned_courses]

    return {"status": "success", "planned_courses_saved": len(body.planned_courses)}


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    require_student(student_id)

    students[student_id]["plan"] = []

    return {"status": "success", "message": "Plan cleared successfully"}


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    require_student(student_id)

    return {
        "student_id": student_id,
        "history": students[student_id]["history"],
        "plan": students[student_id]["plan"],
    }


@app.get("/api/v1/students/{student_id}/audit-report")
def audit_report(student_id: str, strict: bool = False):
    require_student(student_id)

    timeline_validation = check_prerequisites(student_id)
    cross_list_violations = check_cross_lists(student_id)
    credit_summary = get_credit_summary(student_id)

    has_issues = bool(timeline_validation) or bool(cross_list_violations)

    if has_issues and strict:
        report_status = "failed"
    elif has_issues:
        report_status = "warning"
    else:
        report_status = "ok"

    return {
        "student_id": student_id,
        "status": report_status,
        "timeline_validation": timeline_validation,
        "cross_list_violations": cross_list_violations,
        "credit_summary": credit_summary,
    }
