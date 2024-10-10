import requests
import psycopg2
import logging
from datetime import datetime, timedelta
import json
import os

JIRA_URL = os.getenv("JIRA_URL")
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
db_host = os.getenv("DB_HOST")
db_name = os.getenv("DB_NAME")
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_port = os.getenv("DB_PORT")


yesterday_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')



JQL_QUERY = f"project = 'CSI' AND (created >= '{yesterday_date}' OR updated >= '{yesterday_date}')"

def get_issues_by_jql(jql_query):
    url = f"{JIRA_URL}/rest/api/2/search"
    auth = (JIRA_USERNAME, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}
    start_at = 0
    max_results = 100
    all_issues = []

    while True:
        params = {"jql": jql_query, "startAt": start_at, "maxResults": max_results}

        response = requests.get(url, headers=headers, auth=auth, params=params)
        response.raise_for_status()

        data = response.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)

        total_issues = data.get("total", 0)
        print(f"Fetched {len(all_issues)} out of {total_issues} issues")

        if start_at + max_results >= total_issues:
            break

        start_at += max_results

    return all_issues


def parse_description(description_content):
    parsed_data = {
        "display_name": None,
        "monitor_groups": None,
        "monitor_type": None,
        "monitor_status": None,
        "down_since": None,
        "failed_locations": None,
        "reason": None
    }


    if isinstance(description_content, list):  # Structured JSON case
        description_text = ""
        for block in description_content:
            for content in block.get("content", []):
                if content.get("type") == "text":
                    description_text += content.get("text", "") + "\n"
        lines = description_text.splitlines()
    else:
        lines = description_content.splitlines()


    for line in lines:
        if "Display Name" in line:
            parsed_data["display_name"] = line.split(":")[1].strip()
        elif "Monitor Groups" in line:
            parsed_data["monitor_groups"] = line.split(":")[1].strip()
        elif "Monitor Type" in line:
            parsed_data["monitor_type"] = line.split(":")[1].strip()
        elif "Monitor status" in line:
            parsed_data["monitor_status"] = line.split(":")[1].strip()
        elif "Down since" in line:
            down_since_str = line.split(":", 1)[1].strip()  # Split only on the first colon
            print(f"Extracted 'down_since' string: {down_since_str}")  # Debugging step

            try:

                down_since_cleaned = " ".join(down_since_str.split()[:-1])
                print(f"Cleaned 'down_since' string: {down_since_cleaned}")  # Debugging step


                parsed_data["down_since"] = datetime.strptime(down_since_cleaned, "%B %d, %Y, %I:%M %p")
                print("Successfully parsed down_since!")
            except ValueError as ve:

                print(f"Error parsing 'down_since': {ve}")
                parsed_data["down_since"] = None
        elif "Failed locations" in line:
            parsed_data["failed_locations"] = line.split(":")[1].strip()
        elif "Reason" in line:
            parsed_data["reason"] = line.split(":")[1].strip()



    return parsed_data


def save_to_postgresql(issue):
    try:
        connection = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password,
            port=db_port
        )
        cursor = connection.cursor()


        issue_key = issue.get("key", "")
        fields = issue.get("fields", {})

        summary = fields.get("summary", "")
        status = fields.get("status", {}).get("name", "")
        created_date = fields.get("created", None)
        updated_date = fields.get("updated", None)
        reporter = fields.get("reporter", {}).get("displayName", None)
        priority = fields.get("priority", {}).get("name", None)

        permfix = fields.get("customfield_12351", {}).get("value", None) if fields.get("customfield_12351") else None
        team = fields.get("customfield_10900", {}).get("value", None) if fields.get("customfield_10900") else None
        rca = fields.get("customfield_12350", {}).get("value", None) if fields.get("customfield_12350") else None
        components_list = fields.get("components", [])
        components = ', '.join([component.get("name", "") for component in components_list])
        product = fields.get("customfield_12024", {}).get("value", None) if fields.get("customfield_12024") else None
        team_resp = fields.get("customfield_12357", {}).get("value", None) if fields.get("customfield_12357") else None

        permfix_str = json.dumps(permfix) if isinstance(permfix, dict) else str(permfix)
        team_str = json.dumps(team) if isinstance(team, dict) else str(team)
        rca_str = json.dumps(rca) if isinstance(rca, dict) else str(rca)
        product_str = json.dumps(product) if isinstance(product, dict) else str(product)
        components_str = json.dumps(components) if isinstance(components, dict) else str(components)
        team_resp_str = json.dumps(team_resp) if isinstance(team_resp, dict) else str(team_resp)

        description = fields.get("description", {})
        if description:
            if isinstance(description, dict) and "content" in description:
                description_content = description.get("content", [])
            elif isinstance(description, str):  # It's a plain string
                description_content = description
            else:
                description_content = None
        else:
            description_content = None


        if description_content:
            description_data = parse_description(description_content)
        else:
            description_data = {}




        query = """
        INSERT INTO camproj (key, summary, status, created_date, updated_date, reporter, priority, display_name, monitor_groups, monitor_type, monitor_status, down_since, failed_locations, reason, permfix, team, rca, components, product, team_resp)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (key)
        DO UPDATE SET 
            summary = EXCLUDED.summary,
            status = EXCLUDED.status,
            updated_date = EXCLUDED.updated_date,
            reporter = EXCLUDED.reporter,
            priority = EXCLUDED.priority,
            display_name = EXCLUDED.display_name,
            monitor_groups = EXCLUDED.monitor_groups,
            monitor_type = EXCLUDED.monitor_type,
            monitor_status = EXCLUDED.monitor_status,
            down_since = EXCLUDED.down_since,
            failed_locations = EXCLUDED.failed_locations,
            reason = EXCLUDED.reason,
            permfix = EXCLUDED.permfix,
            team = EXCLUDED.team,
            rca = EXCLUDED.rca,
            components = EXCLUDED.components,
            product = EXCLUDED.product,
            team_resp = EXCLUDED.team_resp
        """

        cursor.execute(query, (
            issue_key, summary, status, created_date, updated_date, reporter, priority,
            description_data.get("display_name"),
            description_data.get("monitor_groups"),
            description_data.get("monitor_type"),
            description_data.get("monitor_status"),
            description_data.get("down_since"),
            description_data.get("failed_locations"),
            description_data.get("reason"),
            permfix_str, team_str, rca_str, components_str, product_str, team_resp_str
        ))
        connection.commit()

    except Exception as e:
        logging.error(f"Error saving data to PostgreSQL: {e}")
    finally:
        if connection:
            cursor.close()
            connection.close()

def main():
    issues = get_issues_by_jql(JQL_QUERY)

    print(f"Total issues fetched: {len(issues)}")


    for issue in issues:
        save_to_postgresql(issue)

if __name__ == "__main__":
    main()

