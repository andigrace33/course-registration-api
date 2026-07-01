from fastapi.testclient import TestClient

from main import app, courses, students, normalize

client = TestClient(app)


def reset_data():
    courses.clear()
    students.clear()


def add_course(code, credits=3, prerequisites="", cross_listed=""):
    courses[normalize(code)] = {
        "course_code": code,
        "title": code + " Title",
        "credits": credits,
        "prerequisites": prerequisites,
        "cross_listed": cross_listed,
    }


def add_student(history, plan):
    students["770001"] = {
        "history": history,
        "plan": plan,
    }


def get_report(strict=False):
    url = "/api/v1/students/770001/audit-report"
    if strict:
        url += "?strict=true"
    response = client.get(url)
    assert response.status_code == 200
    return response.json()


def test_clean_audit_status_ok():
    reset_data()
    add_course("COSC-2006", prerequisites="COSC-1047")
    add_course("COSC-1047")
    add_student(
        history=[
            {
                "course_code": "COSC-1047",
                "term": "23F",
                "credits_earned": 3,
                "status": "Completed",
            }
        ],
        plan=[{"course_code": "COSC-2006", "term": "24W"}],
    )

    report = get_report()

    assert report["status"] == "ok"
    assert report["timeline_validation"] == []
    assert report["cross_list_violations"] == []
    assert report["credit_summary"]["total_earned"] == 3
    assert report["credit_summary"]["total_planned"] == 3
    assert report["credit_summary"]["total_remaining_for_graduation"] == 114


def test_missing_prerequisite_warning_and_strict_failed():
    reset_data()
    add_course("COSC-2006", prerequisites="COSC-1047")
    add_course("COSC-1047")
    add_student(
        history=[],
        plan=[{"course_code": "COSC-2006", "term": "24W"}],
    )

    report = get_report()
    strict_report = get_report(strict=True)

    assert report["status"] == "warning"
    assert strict_report["status"] == "failed"
    assert report["timeline_validation"][0]["term"] == "24W"
    assert (
        report["timeline_validation"][0]["errors"][0]["type"] == "MISSING_PREREQUISITE"
    )
    assert report["timeline_validation"][0]["errors"][0]["course_code"] == "COSC-2006"


def test_same_term_prerequisite_does_not_count():
    reset_data()
    add_course("COSC-2006", prerequisites="COSC-1047")
    add_course("COSC-1047")
    add_student(
        history=[
            {
                "course_code": "COSC-1047",
                "term": "24W",
                "credits_earned": 3,
                "status": "Completed",
            }
        ],
        plan=[{"course_code": "COSC-2006", "term": "24W"}],
    )

    report = get_report()

    assert report["status"] == "warning"
    assert (
        report["timeline_validation"][0]["errors"][0]["type"] == "MISSING_PREREQUISITE"
    )


def test_later_term_prerequisite_does_not_count():
    reset_data()
    add_course("COSC-2006", prerequisites="COSC-1047")
    add_course("COSC-1047")
    add_student(
        history=[
            {
                "course_code": "COSC-1047",
                "term": "24F",
                "credits_earned": 3,
                "status": "Completed",
            }
        ],
        plan=[{"course_code": "COSC-2006", "term": "24W"}],
    )

    report = get_report()

    assert report["status"] == "warning"
    assert (
        report["timeline_validation"][0]["errors"][0]["type"] == "MISSING_PREREQUISITE"
    )


def test_course_code_matching_ignores_case_spaces_and_hyphens():
    reset_data()
    add_course("COSC-2006", prerequisites="COSC-1047")
    add_course("COSC-1047")
    add_student(
        history=[
            {
                "course_code": "cosc 1047",
                "term": "23F",
                "credits_earned": 3,
                "status": "Completed",
            }
        ],
        plan=[{"course_code": "COSC2006", "term": "24W"}],
    )

    report = get_report()

    assert report["status"] == "ok"
    assert report["timeline_validation"] == []


def test_multiple_prerequisites_one_missing():
    reset_data()
    add_course("COSC-3506", prerequisites="COSC-2006, COSC-3127")
    add_course("COSC-2006")
    add_course("COSC-3127")
    add_student(
        history=[
            {
                "course_code": "COSC-2006",
                "term": "23F",
                "credits_earned": 3,
                "status": "Completed",
            }
        ],
        plan=[{"course_code": "COSC-3506", "term": "24F"}],
    )

    report = get_report()

    assert report["status"] == "warning"
    assert len(report["timeline_validation"][0]["errors"]) == 1
    assert "COSC-3127" in report["timeline_validation"][0]["errors"][0]["message"]


def test_timeline_validation_sorted_chronologically():
    reset_data()
    add_course("COSC-2006", prerequisites="COSC-1047")
    add_course("COSC-3006", prerequisites="COSC-2006")
    add_student(
        history=[],
        plan=[
            {"course_code": "COSC-3006", "term": "24F"},
            {"course_code": "COSC-2006", "term": "24W"},
        ],
    )

    report = get_report()

    terms = [item["term"] for item in report["timeline_validation"]]
    assert terms == ["24W", "24F"]


def test_cross_list_conflict_with_completed_course():
    reset_data()
    add_course("ITEC-3506", prerequisites="", cross_listed="COSC-3506")
    add_course("COSC-3506")
    add_student(
        history=[
            {
                "course_code": "COSC-3506",
                "term": "24W",
                "credits_earned": 3,
                "status": "Completed",
            }
        ],
        plan=[{"course_code": "ITEC-3506", "term": "24F"}],
    )

    report = get_report()

    assert report["status"] == "warning"
    assert len(report["cross_list_violations"]) == 1
    assert report["cross_list_violations"][0]["type"] == "CROSS_LIST_CONFLICT"
    assert "COSC-3506" in report["cross_list_violations"][0]["message"]


def test_cross_list_does_not_trigger_for_attempted_course():
    reset_data()
    add_course("ITEC-3506", prerequisites="", cross_listed="COSC-3506")
    add_course("COSC-3506")
    add_student(
        history=[
            {
                "course_code": "COSC-3506",
                "term": "24W",
                "credits_earned": 0,
                "status": "Attempted",
            }
        ],
        plan=[{"course_code": "ITEC-3506", "term": "24F"}],
    )

    report = get_report()

    assert report["status"] == "ok"
    assert report["cross_list_violations"] == []


def test_retake_completed_course_counts_once_later_pass_overrides_failure():
    reset_data()
    add_course("COSC-2006")
    add_student(
        history=[
            {
                "course_code": "COSC-2006",
                "term": "23F",
                "credits_earned": 0,
                "status": "Attempted",
            },
            {
                "course_code": "COSC-2006",
                "term": "24W",
                "credits_earned": 3,
                "status": "Completed",
            },
        ],
        plan=[],
    )

    report = get_report()

    assert report["credit_summary"]["total_earned"] == 3


def test_duplicate_completed_course_counts_once():
    reset_data()
    add_course("COSC-2006")
    add_student(
        history=[
            {
                "course_code": "COSC-2006",
                "term": "23F",
                "credits_earned": 3,
                "status": "Completed",
            },
            {
                "course_code": "COSC 2006",
                "term": "24W",
                "credits_earned": 3,
                "status": "Completed",
            },
        ],
        plan=[],
    )

    report = get_report()

    assert report["credit_summary"]["total_earned"] == 3


def test_non_completed_courses_do_not_count_for_credits():
    reset_data()
    add_course("COSC-2006")
    add_student(
        history=[
            {
                "course_code": "COSC-2006",
                "term": "23F",
                "credits_earned": 3,
                "status": "In-Progress",
            },
            {
                "course_code": "MATH-1006",
                "term": "23F",
                "credits_earned": 3,
                "status": "Attempted",
            },
        ],
        plan=[],
    )

    report = get_report()

    assert report["credit_summary"]["total_earned"] == 0


def test_remaining_credit_never_negative():
    reset_data()
    add_course("COSC-4000", credits=6)
    history = []

    for i in range(40):
        history.append(
            {
                "course_code": f"DONE-{i}",
                "term": "23F",
                "credits_earned": 3,
                "status": "Completed",
            }
        )

    add_student(
        history=history,
        plan=[{"course_code": "COSC-4000", "term": "24F"}],
    )

    report = get_report()

    assert report["credit_summary"]["total_earned"] == 120
    assert report["credit_summary"]["total_planned"] == 6
    assert report["credit_summary"]["total_remaining_for_graduation"] == 0
