"""
LISA Sprint Dashboard — API
Deploy on Railway. Env vars needed:
  JIRA_BASE_URL   = https://lisainsurtech.atlassian.net
  JIRA_EMAIL      = tu-email@lisainsurtech.com
  JIRA_API_TOKEN  = el token de Jira
  ALLOWED_ORIGIN  = https://dferrocchio-collab.github.io
  DASHBOARD_API_KEY = tu-api-key
"""

import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone, date, timedelta

app = Flask(__name__)

ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
CORS(app, origins=ALLOWED_ORIGIN)

JIRA_BASE  = os.environ.get("JIRA_BASE_URL", "https://lisainsurtech.atlassian.net")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
API_KEY    = os.environ.get("DASHBOARD_API_KEY", "")

FIELDS = ",".join([
    "summary", "status", "issuetype", "assignee",
    "priority", "parent", "customfield_10020", "resolutiondate", "created"
])

JQL = (
    'project = EJ '
    'AND sprint in openSprints() '
    'AND issuetype NOT IN (Epic, Subtarea) '
    'ORDER BY created ASC'
)

EXCL_ASSIGNEES = {"francisco", "Rodrigo Randado"}

TEAMS_CONFIG = {
    "BPEs":    ["Camilo Arcos", "Nicolas Nash", "Marie Merle d Aubigne"],
    "CS":      ["Juan Ignacio Guila", "Antonella Lamberti", "Andrea Cardona",
                 "Yamil Jaluf", "Milton Alejo Caro", "Debora Wagner"],
    "Gestion": ["Diego Ferrocchio", "irina"],
    "QA":      ["bexi"],
}
EXCL_ASSIGNEES_LIST = ["francisco", "Rodrigo Randado"]

TEAM_MEMBERS = [
    "Camilo Arcos", "Nicolas Nash", "Marie Merle d Aubigne",
    "Juan Ignacio Guila", "Antonella Lamberti", "Andrea Cardona",
    "Yamil Jaluf", "Milton Alejo Caro", "Debora Wagner",
    "Diego Ferrocchio", "irina", "bexi",
    "Alejandro Aparicio Guerra", "Kenny Ortega", "Tonatiu Serrano",
    "Julio Fuentes Gallardo", "Gabriel", "Armando Felipe Fuentes Denis",
    "Miguel Angel Chavez Alfonso", "Benjamin Aseretto", "Jonathan Valdes",
    "Adriel Alejandro Aliaga Benavides", "Luis Carlos Alvarez Fernandez",
    "Antonella Lamberti Mattei",
]


def fetch_available_sprints():
    """Return active sprint + 2 future sprints using Jira Agile board API."""
    auth        = (JIRA_EMAIL, JIRA_TOKEN)
    headers_get = {"Accept": "application/json"}
    r = requests.get(
        f"{JIRA_BASE}/rest/agile/1.0/board",
        auth=auth, headers=headers_get,
        params={"projectKeyOrId": "EJ"}, timeout=15
    )
    r.raise_for_status()
    boards = r.json().get("values", [])
    if not boards:
        return []
    board_id = boards[0]["id"]

    sprint_url = f"{JIRA_BASE}/rest/agile/1.0/board/{board_id}/sprint"
    sprints = []
    for state in ("active", "future"):
        r = requests.get(sprint_url, auth=auth, headers=headers_get,
                         params={"state": state}, timeout=15)
        if r.status_code != 200:
            continue
        for s in r.json().get("values", []):
            sprints.append({
                "id":         str(s.get("id", "")),
                "name":       s.get("name", ""),
                "state":      state,
                "start_date": (s.get("startDate") or "")[:10],
                "end_date":   (s.get("endDate") or "")[:10],
            })

    active  = [s for s in sprints if s["state"] == "active"]
    futures = sorted(
        [s for s in sprints if s["state"] == "future" and s["start_date"]],
        key=lambda x: x["start_date"]
    )
    return active + futures[:2]


def fetch_all_issues():
    auth        = (JIRA_EMAIL, JIRA_TOKEN)
    url         = f"{JIRA_BASE}/rest/api/3/search/jql"
    req_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    issues, next_token = [], None
    while True:
        payload = {"jql": JQL, "fields": FIELDS.split(","), "maxResults": 100}
        if next_token:
            payload["nextPageToken"] = next_token
        r = requests.post(url, auth=auth, headers=req_headers, json=payload, timeout=30)
        r.raise_for_status()
        data  = r.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        next_token = data.get("nextPageToken")
        if not next_token or not batch:
            break
    return issues


def fetch_issues_for_sprint(sprint_name):
    auth        = (JIRA_EMAIL, JIRA_TOKEN)
    url         = f"{JIRA_BASE}/rest/api/3/search/jql"
    req_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    jql = (
        f'project = EJ AND sprint = "{sprint_name}" '
        f'AND issuetype NOT IN (Epic, Subtarea) ORDER BY created ASC'
    )
    issues, next_token = [], None
    while True:
        payload = {"jql": jql, "fields": FIELDS.split(","), "maxResults": 100}
        if next_token:
            payload["nextPageToken"] = next_token
        r = requests.post(url, auth=auth, headers=req_headers, json=payload, timeout=30)
        r.raise_for_status()
        data  = r.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        next_token = data.get("nextPageToken")
        if not next_token or not batch:
            break
    return issues


def get_sprint_start(issues):
    for issue in issues:
        sprints = issue["fields"].get("customfield_10020") or []
        for s in sprints:
            if s.get("state") == "active":
                sd = s.get("startDate", "")
                if sd:
                    return sd[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_principal_for_hours(issue):
    fields  = issue.get("fields", {})
    parent  = fields.get("parent") or {}
    pfields = parent.get("fields") or {}
    psum    = pfields.get("summary", "")
    ptype   = (pfields.get("issuetype") or {}).get("name", "")
    if ptype == "Epic" and psum:
        if psum.startswith("OPSADMON"):
            return "LISA"
        return psum
    return None


def transform(issue, sprint_start):
    fields        = issue["fields"]
    status        = fields["status"]["name"]
    status_cat    = fields["status"]["statusCategory"]["name"]
    itype         = fields["issuetype"]["name"]
    assignee      = (fields.get("assignee") or {}).get("displayName", "Sin asignar")
    summary       = fields.get("summary", "")
    priority      = (fields.get("priority") or {}).get("name", "—")
    parent        = fields.get("parent") or {}
    pfields       = parent.get("fields") or {}
    psum          = pfields.get("summary", "")
    ptype         = (pfields.get("issuetype") or {}).get("name", "")
    principal     = psum if psum else (parent.get("key") or "Sin principal")
    parent_type   = ptype
    sprints       = fields.get("customfield_10020") or []
    active        = next((s for s in sprints if s.get("state") == "active"), None)
    in_sprint     = active is not None
    resdate       = fields.get("resolutiondate") or ""
    resolved_date = resdate[:10] if resdate else None
    created_raw   = fields.get("created") or ""
    created       = created_raw[:10] if created_raw else None

    return {
        "key":           issue["key"],
        "summary":       summary,
        "status":        status,
        "status_cat":    status_cat,
        "type":          itype,
        "assignee":      assignee,
        "priority":      priority,
        "principal":     principal,
        "parent_type":   parent_type,
        "in_sprint":     in_sprint,
        "resolved_date": resolved_date,
        "created":       created,
    }, parent_type, principal, assignee


def filter_issues(raw_issues, sprint_start):
    result = []
    for issue in raw_issues:
        item, parent_type, principal, assignee = transform(issue, sprint_start)
        if parent_type and parent_type != "Epic":
            continue
        if principal.startswith("OPSADMON"):
            continue
        if assignee in EXCL_ASSIGNEES:
            continue
        if item["status"] in ("FINALIZADO", "ABANDONADO"):
            rd = item.get("resolved_date") or ""
            if rd < sprint_start:
                continue
        del item["parent_type"]
        result.append(item)
    return result


@app.route("/api/sprints")
def sprints_list():
    if API_KEY and request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        available = fetch_available_sprints()
        return jsonify({"sprints": available})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sprint")
def sprint():
    if API_KEY and request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        sprint_name = request.args.get("sprint")

        if sprint_name:
            available    = fetch_available_sprints()
            sprint_meta  = next((s for s in available if s["name"] == sprint_name), None)
            is_future    = sprint_meta["state"] == "future" if sprint_meta else False
            sprint_start = sprint_meta["start_date"] if sprint_meta else ""
            sprint_end   = sprint_meta["end_date"] if sprint_meta else ""
            raw          = fetch_issues_for_sprint(sprint_name)

            if is_future:
                issues = []
                for issue in raw:
                    item, parent_type, principal, assignee = transform(issue, sprint_start)
                    if parent_type and parent_type != "Epic": continue
                    if principal.startswith("OPSADMON"): continue
                    if assignee in EXCL_ASSIGNEES: continue
                    if item["status"] in ("FINALIZADO", "ABANDONADO"): continue
                    del item["parent_type"]
                    issues.append(item)
            else:
                sstart       = sprint_start or get_sprint_start(raw)
                issues       = filter_issues(raw, sstart)
                sprint_start = sstart
        else:
            raw          = fetch_all_issues()
            sprint_start = get_sprint_start(raw)
            issues       = filter_issues(raw, sprint_start)
            avail        = fetch_available_sprints()
            active_meta  = next((s for s in avail if s["state"] == "active"), None)
            sprint_name  = active_meta["name"] if active_meta else "Sprint activo"
            sprint_end   = active_meta["end_date"] if active_meta else ""

        return jsonify({
            "sprint_start":   sprint_start,
            "sprint_end":     sprint_end,
            "sprint_name":    sprint_name,
            "issues":         issues,
            "total":          len(issues),
            "teams":          TEAMS_CONFIG,
            "excl_assignees": EXCL_ASSIGNEES_LIST,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"ok": True})


def get_date_range(period):
    today = date.today()
    if period == "1m":
        return today.replace(day=1).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == "1mp":
        first_this = today.replace(day=1)
        last_prev  = first_this - timedelta(days=1)
        return last_prev.replace(day=1).strftime("%Y-%m-%d"), last_prev.strftime("%Y-%m-%d")
    elif period == "3m":
        return (today - timedelta(days=90)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    elif period == "6m":
        return (today - timedelta(days=180)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
    else:
        return (today - timedelta(days=365)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def fetch_worklogs_bulk(date_from, date_to):
    auth        = (JIRA_EMAIL, JIRA_TOKEN)
    headers_get = {"Accept": "application/json"}
    dt_from     = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since_ms    = int(dt_from.timestamp() * 1000)

    worklog_ids, since = [], since_ms
    while True:
        r = requests.get(
            f"{JIRA_BASE}/rest/api/3/worklog/updated",
            auth=auth, headers=headers_get,
            params={"since": since}, timeout=30
        )
        r.raise_for_status()
        data   = r.json()
        worklog_ids.extend([v["worklogId"] for v in data.get("values", [])])
        if data.get("lastPage", True):
            break
        since = data.get("until", since + 1)

    if not worklog_ids:
        return []

    worklogs = []
    for i in range(0, len(worklog_ids), 1000):
        r = requests.post(
            f"{JIRA_BASE}/rest/api/3/worklog/list",
            auth=auth,
            headers={**headers_get, "Content-Type": "application/json"},
            json={"ids": worklog_ids[i:i+1000]}, timeout=30
        )
        r.raise_for_status()
        worklogs.extend(r.json())

    filtered, issue_keys = [], set()
    for wl in worklogs:
        started = (wl.get("started") or "")[:10]
        if started < date_from or started > date_to:
            continue
        author = (wl.get("author") or {}).get("displayName", "")
        if author not in TEAM_MEMBERS:
            continue
        issue_id = str(wl.get("issueId", ""))
        filtered.append({"author": author, "seconds": wl.get("timeSpentSeconds", 0),
                          "issue_id": issue_id, "date": started})
        issue_keys.add(issue_id)

    if not filtered:
        return []

    url         = f"{JIRA_BASE}/rest/api/3/search/jql"
    req_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    jql         = f'project = EJ AND issue in ({",".join(issue_keys)})'
    issue_map, next_token = {}, None
    while True:
        payload = {"jql": jql, "fields": ["parent", "issuetype"], "maxResults": 100}
        if next_token:
            payload["nextPageToken"] = next_token
        r = requests.post(url, auth=(JIRA_EMAIL, JIRA_TOKEN), headers=req_headers,
                          json=payload, timeout=30)
        if r.status_code != 200:
            break
        data = r.json()
        for issue in data.get("issues", []):
            issue_map[issue["id"]] = issue
        next_token = data.get("nextPageToken")
        if not next_token or not data.get("issues"):
            break

    result = []
    for wl in filtered:
        issue = issue_map.get(wl["issue_id"])
        if not issue:
            continue
        principal = get_principal_for_hours(issue)
        if principal is None:
            continue
        result.append({"author": wl["author"], "seconds": wl["seconds"],
                        "principal": principal, "month": wl["date"][:7]})
    return result


@app.route("/api/worklogs")
def worklogs():
    if API_KEY and request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        period             = request.args.get("period", "1m")
        date_from, date_to = get_date_range(period)
        entries            = fetch_worklogs_bulk(date_from, date_to)

        by_person = {}; by_project = {}; detail = {}
        by_month_project = {}; by_month_person = {}; by_month_person_project = {}

        for wl in entries:
            author = wl["author"]; hrs = round(wl["seconds"] / 3600, 2)
            label  = wl["principal"]; month = wl.get("month", "")
            by_person[author]   = round(by_person.get(author, 0) + hrs, 2)
            by_project[label]   = round(by_project.get(label, 0) + hrs, 2)
            if author not in detail: detail[author] = {}
            detail[author][label] = round(detail[author].get(label, 0) + hrs, 2)
            if month:
                if label not in by_month_project: by_month_project[label] = {}
                by_month_project[label][month] = round(by_month_project[label].get(month,0)+hrs,2)
                if author not in by_month_person: by_month_person[author] = {}
                by_month_person[author][month] = round(by_month_person[author].get(month,0)+hrs,2)
                if author not in by_month_person_project: by_month_person_project[author] = {}
                if label not in by_month_person_project[author]: by_month_person_project[author][label] = {}
                by_month_person_project[author][label][month] = round(
                    by_month_person_project[author][label].get(month,0)+hrs,2)

        return jsonify({
            "period": period, "date_from": date_from, "date_to": date_to,
            "by_person":               dict(sorted(by_person.items(),  key=lambda x: -x[1])),
            "by_project":              dict(sorted(by_project.items(), key=lambda x: -x[1])),
            "detail": detail, "total_hours": round(sum(by_person.values()), 2),
            "by_month_project":        by_month_project,
            "by_month_person":         by_month_person,
            "by_month_person_project": by_month_person_project,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
