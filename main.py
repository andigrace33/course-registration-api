# AI Interaction Log: I have been watching a tutorial on YouTube that covers
# FastAPI and Python:
# https://youtu.be/iukOehU5aF4?si=JvjnOCMSNZ1oy5x8
#
# During Phase 4 I learned more about bcrypt, jwt, and pydantic.
# I used ChatGPT to walk me through what code to put in order to implement
# the APIs.
# I looked at what ChatGPT sent and then I would go into the documentation
# here to learn about what is actually happening.
#
# JWT:
# https://pyjwt.readthedocs.io/en/stable/
#
# BCRYPT:
# https://github.com/pyca/bcrypt/blob/main/README.rst?plain=1
#
# PYDANTIC:
# https://pydantic.dev/docs/validation/latest/get-started/
#
# I used ChatGPT to format the code with the proper spacing and indents and
# I used it to write functions.
# I also used ChatGPT to make sure all of the edge cases were handled in the
# code.

import os
import re
import jwt
import bcrypt
import time
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    status,
    Header,
    Depends,
    Request,
)
from pydantic import BaseModel
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

app = FastAPI()

courses = {}
students = {}
users = {}
rate_limits = {}

# bcrypt
users["admin"] = {
    "password_hash": bcrypt.hashpw("admin".encode("utf-8"), bcrypt.gensalt()),
    "role": "admin",
}

# for password
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "phase-4-development-secret-key",
)
ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60


# dict for semester order
season_order = {"W": 1, "SP": 2, "S": 3, "F": 4}

# pydantic BaseModel inherited classes


class AuthRequest(BaseModel):
    username: str
    password: str


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


# function to return bool for the earlier term of 2 terms
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


def create_access_token(username: str, role: str) -> str:
    expiration = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    payload = {"sub": username, "role": role, "exp": expiration}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not payload.get("sub") or not payload.get("role"):
        raise HTTPException(status_code=401, detail="Invalid token")

    return payload


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization token required")

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    return decode_access_token(token.strip())


def require_owner(student_id: str, current_user: dict) -> None:
    if current_user["sub"] != student_id:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_owner_or_admin(student_id: str, current_user: dict) -> None:
    is_owner = current_user["sub"] == student_id
    is_admin = current_user.get("role") == "admin"
    if not is_owner and not is_admin:
        raise HTTPException(status_code=401, detail="Unauthorized")


def rate_limit_identifier(request: Request, authorization: str | None) -> str:
    if authorization:
        scheme, separator, token = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and token.strip():
            payload = decode_access_token(token.strip())
            return "user:" + payload["sub"]

    client_ip = request.client.host if request.client else "unknown"
    return "ip:" + client_ip


def enforce_audit_rate_limit(identifier: str) -> None:
    now = time.time()
    recent_requests = [
        timestamp
        for timestamp in rate_limits.get(identifier, [])
        if now - timestamp < 60
    ]

    if len(recent_requests) >= 10:
        rate_limits[identifier] = recent_requests
        raise HTTPException(status_code=429, detail="Too many requests")

    recent_requests.append(now)
    rate_limits[identifier] = recent_requests


def next_recommendation_term(term: str) -> str:
    year = int(term[:2])
    season = term[2:].upper()

    if season == "F":
        return f"{year + 1:02d}W"
    return f"{year:02d}F"


def build_recommended_pathway(student_id: str) -> list[dict]:
    history = students[student_id]["history"]
    completed = {
        normalize(item["course_code"])
        for item in history
        if item["status"] == "Completed"
    }

    remaining = {key for key in courses if key not in completed}
    adjacency = {key: [] for key in remaining}
    indegree = {key: 0 for key in remaining}

    for course_key in remaining:
        prerequisites = split_course_list(courses[course_key]["prerequisites"])

        for prerequisite in prerequisites:
            prerequisite_key = normalize(prerequisite)

            if prerequisite_key in completed:
                continue

            if prerequisite_key in remaining:
                adjacency[prerequisite_key].append(course_key)
                indegree[course_key] += 1

    available = sorted(key for key, degree in indegree.items() if degree == 0)
    pathway = []
    scheduled_count = 0
    term = "26F"

    while available:
        current_level = available
        current_courses = [courses[key]["course_code"] for key in current_level]
        pathway.append({"term": term, "courses": current_courses})
        scheduled_count += len(current_level)

        next_available = []
        for course_key in current_level:
            for dependent in adjacency[course_key]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    next_available.append(dependent)

        available = sorted(next_available)
        term = next_recommendation_term(term)

    if scheduled_count != len(remaining):
        raise HTTPException(
            status_code=400,
            detail="Catalog prerequisites contain a cycle or unresolved dependency",
        )

    return pathway


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

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]
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


# phase 2 and phase 4 protected student APIs


@app.post(
    "/api/v1/students/{student_id}/history/import",
    status_code=status.HTTP_201_CREATED,
)
async def import_history(
    student_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    require_owner(student_id, current_user)
    content = await file.read()
    history = parse_history_html(content)

    existing_plan = students.get(student_id, {}).get("plan", [])
    students[student_id] = {"history": history, "plan": existing_plan}

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
def get_profile(
    student_id: str,
    current_user: dict = Depends(get_current_user),
):
    require_owner_or_admin(student_id, current_user)
    require_student(student_id)
    return {
        "student_id": student_id,
        "history": students[student_id]["history"],
        "plan": students[student_id]["plan"],
    }


@app.get("/api/v1/students/{student_id}/plan")
def get_plan(
    student_id: str,
    current_user: dict = Depends(get_current_user),
):
    require_owner_or_admin(student_id, current_user)
    require_student(student_id)
    return {
        "student_id": student_id,
        "planned_courses": students[student_id]["plan"],
    }


@app.get("/api/v1/students/{student_id}/audit-report")
def audit_report(
    student_id: str,
    request: Request,
    strict: bool = False,
    authorization: str | None = Header(default=None),
):
    identifier = rate_limit_identifier(request, authorization)
    enforce_audit_rate_limit(identifier)
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


# phase 4 authentication


@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register_user(auth: AuthRequest):
    username = auth.username.strip()

    if not username or not auth.password:
        raise HTTPException(
            status_code=400, detail="Username and password are required"
        )

    if username in users:
        raise HTTPException(status_code=409, detail="Username already exists")

    password_hash = bcrypt.hashpw(
        auth.password.encode("utf-8"),
        bcrypt.gensalt(),
    )
    users[username] = {"password_hash": password_hash, "role": "student"}
    return {"status": "registered"}


@app.post("/api/v1/auth/login")
def login_user(auth: AuthRequest):
    username = auth.username.strip()
    user = users.get(username)

    if user is None or not bcrypt.checkpw(
        auth.password.encode("utf-8"),
        user["password_hash"],
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token(username, user["role"])
    return {"access_token": access_token, "token_type": "bearer"}


# phase 4 recommendations


@app.get("/api/v1/students/{student_id}/recommendations")
def get_recommendations(
    student_id: str,
    current_user: dict = Depends(get_current_user),
):
    require_owner_or_admin(student_id, current_user)
    require_student(student_id)

    return {
        "student_id": student_id,
        "recommended_pathway": build_recommended_pathway(student_id),
    }
