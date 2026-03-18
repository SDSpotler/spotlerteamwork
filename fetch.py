import os
import requests
import json
import base64
import time
from pathlib import Path

API_KEY = os.getenv("TEAMWORK_API_KEY")

if not API_KEY:
    raise Exception("Geen API key gevonden. Check je GitHub Secret TEAMWORK_API_KEY.")

DOMAIN = "spotler.eu.teamwork.com"
BASE_PROJECTS_URL = (
    f"https://{DOMAIN}/projects/api/v3/projects.json"
    f"?fields[projects]=id,name,projectOwnerId,companyId,createdAt"
    f"&pageSize=500"
)

OWNER_MAP = {
    449082: "Danny Leeuwestein",
    453708: "Dineke Kuiper",
    449072: "Iris Pieterse",
    454071: "Marcel Vergonet",
    447157: "Martijn de Kock",
    453304: "Michael Don",
    450082: "Sjoerd Dijkshoorn",
    444398: "Fedor Troe",
    449083: "Lois Laffertu"
}

COMPANY_MAP = {
    122255: "Spotler Activate",
    122323: "Spotler Activate Search",
    122638: "Spotler B2B Solution",
    122280: "Spotler Engage",
    122370: "Spotler Insights",
    122281: "Spotler AIgent",
    119110: "Spotler Mail+",
    117681: "Spotler MailPro",
    124480: "Spotler Message",
    117357: "Spotler SendPro",
    123452: "Spotler DACH",
    123281: "Spotler Connect",
    124845: "Spotler Momice / Events"
}

TARGET_CUSTOM_FIELDS = {
    37806: "accountmanager",
    41213: "status project"
}

auth = base64.b64encode(f"{API_KEY}:xxx".encode()).decode()

HEADERS = {
    "Authorization": f"Basic {auth}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

session = requests.Session()
session.headers.update(HEADERS)

DETAILS_DIR = Path("details")
DETAILS_DIR.mkdir(exist_ok=True)

def split_name(full_name):
    if not full_name:
        return {"firstName": "", "lastName": ""}
    parts = str(full_name).strip().split(" ", 1)
    return {
        "firstName": parts[0],
        "lastName": parts[1] if len(parts) > 1 else ""
    }

def normalize_value(value):
    if value is None:
        return ""

    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(
                    str(
                        item.get("value")
                        or item.get("name")
                        or item.get("label")
                        or json.dumps(item, ensure_ascii=False)
                    )
                )
            else:
                parts.append(str(item))
        return ", ".join([p.strip() for p in parts if str(p).strip()])

    if isinstance(value, dict):
        return str(
            value.get("value")
            or value.get("name")
            or value.get("label")
            or json.dumps(value, ensure_ascii=False)
        ).strip()

    return str(value).strip()

def format_custom_field_value(item):
    possible_values = [
        item.get("value"),
        item.get("textValue"),
        item.get("numberValue"),
        item.get("dateValue"),
        item.get("datetimeValue"),
        item.get("optionValue"),
        item.get("optionValues"),
        item.get("customfieldProjectOptions"),
        item.get("customfieldprojectoptions"),
        item.get("values"),
    ]

    raw = next((v for v in possible_values if v is not None and v != ""), None)
    return normalize_value(raw)

def extract_custom_field_rows(json_data):
    included_customfields = (
        json_data.get("included", {}).get("customfields", [])
        if isinstance(json_data.get("included"), dict)
        else []
    )

    defs_by_id = {
        int(cf["id"]): cf
        for cf in included_customfields
        if isinstance(cf, dict) and str(cf.get("id", "")).isdigit()
    }

    value_candidates = []
    for key in [
        "customfieldProjects",
        "customfieldprojects",
        "projectCustomFields",
        "projectcustomfields",
        "customFieldProjects",
    ]:
        arr = json_data.get(key)
        if isinstance(arr, list):
            value_candidates.extend(arr)

    value_map = {}

    for item in value_candidates:
        cf_id = (
            item.get("customFieldId")
            or item.get("customfieldId")
            or item.get("customfieldid")
            or item.get("id")
        )
        if not cf_id:
            continue

        cf_id = int(cf_id)
        if cf_id not in TARGET_CUSTOM_FIELDS:
            continue

        defn = defs_by_id.get(cf_id, {})
        value_map[cf_id] = {
            "id": cf_id,
            "name": TARGET_CUSTOM_FIELDS[cf_id],
            "type": defn.get("type") or item.get("type") or "",
            "value": format_custom_field_value(item),
            "required": bool(defn.get("required"))
        }

    rows = []
    for cf_id, label in TARGET_CUSTOM_FIELDS.items():
        defn = defs_by_id.get(cf_id, {})
        rows.append(
            value_map.get(cf_id, {
                "id": cf_id,
                "name": label,
                "type": defn.get("type") or "",
                "value": "",
                "required": bool(defn.get("required"))
            })
        )
    return rows

def fetch_all_projects():
    all_projects = []
    page = 1

    while True:
        url = f"{BASE_PROJECTS_URL}&page={page}"
        print(f"Projectpagina {page} ophalen...")
        response = session.get(url, timeout=60)
        response.raise_for_status()

        data = response.json()
        projects = data.get("projects", [])

        if not projects:
            break

        all_projects.extend(projects)
        print(f"  {len(projects)} projecten gevonden")
        page += 1

    print(f"Totaal projecten: {len(all_projects)}")
    return all_projects

def fetch_project_customfields(project_id):
    url = (
        f"https://{DOMAIN}/projects/api/v3/projects/{project_id}/customfields.json"
        f"?include=customfields,projects"
        f"&fields[projects]=id,name"
        f"&fields[customfields]=id,name,type,description,required"
    )

    response = session.get(url, timeout=60)

    if response.status_code == 429:
        print(f"429 op project {project_id}, even rustig aan...")
        time.sleep(2)
        response = session.get(url, timeout=60)

    response.raise_for_status()
    return extract_custom_field_rows(response.json())

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Oude detailbestanden opruimen
for old_file in DETAILS_DIR.glob("*.json"):
    old_file.unlink()

projects = fetch_all_projects()
list_output = {"projects": []}

for idx, p in enumerate(projects, start=1):
    project_id = p.get("id")
    owner_name = OWNER_MAP.get(p.get("projectOwnerId"), "")
    owner_obj = split_name(owner_name)
    company_name = COMPANY_MAP.get(p.get("companyId"), "")

    list_output["projects"].append({
        "id": project_id,
        "name": p.get("name") or "",
        "createdAt": p.get("createdAt") or "",
        "projectOwner": owner_obj,
        "companyName": company_name
    })

    print(f"[{idx}/{len(projects)}] Custom fields ophalen voor project {project_id}...")

    try:
        rows = fetch_project_customfields(project_id)
    except Exception as e:
        print(f"  Fout bij project {project_id}: {e}")
        rows = [
            {"id": 37806, "name": "accountmanager", "type": "", "value": "", "required": False},
            {"id": 41213, "name": "status project", "type": "", "value": "", "required": False}
        ]

    detail_output = {
        "projectId": project_id,
        "projectName": p.get("name") or "",
        "customfields": rows
    }

    write_json(DETAILS_DIR / f"{project_id}.json", detail_output)
    time.sleep(0.15)

write_json("data.json", list_output)

print(f"Klaar! data.json bevat {len(list_output['projects'])} projecten")
print(f"Klaar! {len(list_output['projects'])} detailbestanden aangemaakt in /details")