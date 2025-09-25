import os
import json
import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request, HTTPException, status, Header
from pydantic import BaseModel
from dotenv import load_dotenv
import subprocess

load_dotenv()

app = FastAPI()

# --- Configuration (Set these securely, e.g., environment variables) ---
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
if not GITHUB_WEBHOOK_SECRET:
    raise ValueError("GITHUB_WEBHOOK_SECRET environment variable not set.")
SONARQUBE_URL = os.getenv("SONARQUBE_URL")
if not SONARQUBE_URL:
    raise ValueError("SONARQUBE_URL environment variable not set.")
CI_JOB_TOKEN = os.getenv("CI_JOB_TOKEN")
if not CI_JOB_TOKEN:
    raise ValueError("CI_JOB_TOKEN environment variable not set.")
PROJECT_KEY = os.getenv("PROJECT_KEY")
if not PROJECT_KEY:
    raise ValueError("PROJECT_KEY environment variable not set.")

# Pydantic model for type hinting and validation of the incoming payload (optional but good practice)
class PullRequestPayload(BaseModel):
    action: str
    pull_request: dict
    repository: dict

async def fetch_sonarqube_issues():
    url = f"{SONARQUBE_URL}/api/issues/search"
    params = {"componentKeys": PROJECT_KEY, "resolved": "false"}
    async with httpx.AsyncClient(auth=(CI_JOB_TOKEN, "")) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        #return (await response.json()).get("issues", [])
        try:
            data = await response.json()
        except Exception:
            try:
                data = json.loads(response.text)
            except Exception:
                print("SonarQube response was not JSON:", response.text)
                return []
        return data.get("issues", [])

@app.post("/github-webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None)
):
    # 1. Verify the signature
    if not x_hub_signature_256:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-Hub-Signature-256 header missing!"
        )

    # Get the raw payload body
    payload_body = await request.body()

    # Calculate our own signature
    expected_signature = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).hexdigest()

    #if not hmac.compare_digest(expected_signature, x_hub_signature_256):
    #    raise HTTPException(
    #        status_code=status.HTTP_403_FORBIDDEN,
    #        detail="Signatures do not match!"
    #    )

    # 2. Parse the JSON payload
    try:
        payload = json.loads(payload_body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload."
        )

    # 3. Check for PR creation/update event
    if x_github_event == 'pull_request':
        action = payload.get('action')
        pr = payload.get('pull_request')

        if action in ['opened', 'reopened', 'synchronize'] and pr:
            pr_id = pr.get('id')
            pr_number = pr.get('number')
            pr_head_ref = pr.get('head', {}).get('ref')
            pr_head_sha = pr.get('head', {}).get('sha')
            repo_clone_url = pr.get('head', {}).get('repo', {}).get('clone_url')
            repo_full_name = pr.get('head', {}).get('repo', {}).get('full_name')

            print(f"Detected Pull Request event: '{action}' for PR #{pr_number} in {repo_full_name}")
            print(f"  Branch: {pr_head_ref}, SHA: {pr_head_sha}")

        if action == 'closed' and pr and pr.get('merged') == True: # 
            base_branch = pr.get('base', {}).get('ref') # 
            if base_branch == 'main': 
                print(f"DEBUG: Code merged to main branch for PR #{pr.get('number')}") # 
                # Invoke your automated flow (e.g., SonarQube scan for the merged branch) 
            else:
                print(f"DEBUG: PR merged to non-main branch: {base_branch}")

            pr_id = pr.get('id')
            pr_number = pr.get('number')
            pr_head_ref = pr.get('head', {}).get('ref')
            pr_head_sha = pr.get('head', {}).get('sha')
            repo_clone_url = pr.get('head', {}).get('repo', {}).get('clone_url')
            repo_full_name = pr.get('head', {}).get('repo', {}).get('full_name')

            # 4. Invoke SonarQube scan (via CI/CD)
        #   try:
        #       ci_payload = {
        #           'token': CI_JOB_TOKEN,
        #           'PR_NUMBER': pr_number,
        #           'PR_HEAD_REF': pr_head_ref,
        #           'PR_HEAD_SHA': pr_head_sha,
        #           'REPO_CLONE_URL': repo_clone_url,
        #           'REPO_FULL_NAME': repo_full_name
        #       }
                # Using httpx for async requests, which is common with FastAPI
                # Or you can stick with `requests` if you prefer, but it will block the event loop
                # for the duration of the HTTP call. For quick webhooks, async is better.
        #        async with httpx.AsyncClient() as client:
                    #response = await client.post(SONARQUBE_URL, params=ci_payload)
                    #response.raise_for_status()
                    #issues = await fetch_sonarqube_issues()
        #       print(f"Successfully triggered SonarQube scan for PR #{pr_number} via CI/CD.")
        #        if not issues:
        #            return {
        #                "status": "No issues found",
        #                "total": 0,
        #                "issues": []
        #            }

        #        return {
        #            "status": "Issues found",
        #            "total": len(issues),
        #            "issues": [
        #                {
        #                    "message": i.get("message"),
        #                    "severity": i.get("severity"),
        #                    "type": i.get("type"),
        #                    "component": i.get("component"),
        #                    "line": i.get("line")
        #                } for i in issues[:10]
        #            ]
        #        }

        #    except httpx.RequestError as e:
        #        print(f"Error triggering SonarQube scan: {e}")
        #        raise HTTPException(
        #            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        #            detail=f"Error triggering SonarQube scan: {e}"
        #        )

            #return {'status': 'success', 'message': 'SonarQube scan triggered.', 'response': {response.status_code: response.text}}
            return {'status': 'success', 'message': 'PR is merged and closed'}

        else:
            print(f"Ignoring PR action: {action}")
            return {'status': 'ignored', 'message': f'Ignoring PR action: {action}'}
    
    elif x_github_event == 'workflow_run':
        action = payload.get('action')
        workflow_run = payload.get('workflow_run', {})
        workflow_name = workflow_run.get('name')
        conclusion = workflow_run.get('conclusion')
        head_branch = workflow_run.get('head_branch')
        head_sha = workflow_run.get('head_sha')
        repo = payload.get('repository', {})
        repo_full_name = repo.get('full_name')

        print(f"Workflow event: {workflow_name}, action: {action}, conclusion: {conclusion}, branch: {head_branch}")

        # Only act on completed and successful workflows
        if action == 'completed' and conclusion == 'success':
            # Trigger SonarQube scan or any other logic here
            """ try:
                issues = await fetch_sonarqube_issues() 
                print(f"Successfully triggered SonarQube scan for PR via CI/CD.")
                if not issues:
                    return {
                        "status": "No issues found",
                        "total": 0,
                        "issues": []
                    }

                return {
                    "status": "Issues found",
                    "total": len(issues),
                    "issues": [
                        {
                            "message": i.get("message"),
                            "severity": i.get("severity"),
                            "type": i.get("type"),
                            "component": i.get("component"),
                            "line": i.get("line")
                        } for i in issues[:10]
                    ]
                }
            except httpx.RequestError as e:
                print(f"Error triggering SonarQube scan: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error triggering SonarQube scan: {e}"
                )
            except Exception as e:
                print(f"Error fetching SonarQube issues: {e}")
                issues = [] """
            result = subprocess.run(
            ["python", "mcp_agent_runner.py"],
            capture_output=True,
            text=True
        )
        print("MCP Agent Runner output:", result.stdout)
        return {"status": "Triggered mcp_agent_runner", "output": result.stdout}

    else:
        print(f"Ignoring GitHub event type: {x_github_event}")
        return {'status': 'ignored', 'message': f'Ignoring GitHub event type: {x_github_event}'}