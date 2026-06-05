from fastapi import FastAPI, UploadFile, File, HTTPException
from bs4 import BeautifulSoup

app = FastAPI()

courses = {}

def normalize(code: str) -> str:
    return code.replace(" ", "").strip()

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
            "cross_listed": cross_listed
        }

        count += 1

    return {
        "message": "Catalog imported",
        "courses_loaded": count
    }


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    key = normalize(course_code)

    if key not in courses:
        raise HTTPException(status_code=404, detail="Course not found")

    return courses[key]
