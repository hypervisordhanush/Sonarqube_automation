from dotenv import load_dotenv
load_dotenv()
from fastmcp.server import FastMCP
import os
import subprocess
import requests
from requests.auth import HTTPBasicAuth
from github import Github

# ─── Configuration ───
SONARQUBE_URL = os.getenv("SONARQUBE_URL", "http://localhost:9000")
SONARQUBE_TOKEN = os.getenv("SONARQUBE_TOKEN", "")
PROJECT_KEY = os.getenv("PROJECT_KEY", "")
AUTH = HTTPBasicAuth(SONARQUBE_TOKEN, "")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # Format: user/repo
GITHUB_USER = os.getenv("GITHUB_USER", "")
CLONE_DIR = "cloned_repo"
NEW_BRANCH = "auto-fix-sonar-issues"

# ─── MCP Server ───
mcp = FastMCP("Sonar + Git Auto-Fix MCP")

@mcp.tool()
def watch_github_commit(branch: str = "main") -> dict:
    """
    Detect new commit, check GitHub Actions build status, then trigger SonarQube scan and fix pipeline.
    """
    try:
        sha_file = "last_commit.txt"
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        latest_commit = repo.get_branch(branch).commit.sha

        # Load previous SHA
        previous_sha = None
        if os.path.exists(sha_file):
            with open(sha_file, "r") as f:
                previous_sha = f.read().strip()

        if latest_commit == previous_sha:
            return {"status": " No new commits", "latest_commit": latest_commit}

        # Check GitHub Actions build status
        workflows = repo.get_workflow_runs(branch=branch)
        latest_run = workflows[0] if workflows.totalCount > 0 else None

        if not latest_run:
            return {"status": " No recent workflow run found"}

        if latest_run.conclusion != "success":
            return {
                "status": " Build failed or still running",
                "build_status": latest_run.conclusion
            }

        # Save latest SHA and run the pipeline
        with open(sha_file, "w") as f:
            f.write(latest_commit)

        # Proceed to Sonar and PR
        result = full_auto_fix_pipeline()

        return {
            "status": "Build succeeded and commit processed",
            "commit": latest_commit,
            "pipeline_result": result
        }

    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def get_sonar_issues() -> dict:
    """Fetch unresolved SonarQube issues, or say there are none."""
    try:
        url = f"{SONARQUBE_URL}/api/issues/search"
        params = {"componentKeys": PROJECT_KEY, "resolved": "false", "ps": "100"}
        response = requests.get(url, params=params, auth=AUTH)
        response.raise_for_status()
        issues = response.json().get("issues", [])

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
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def apply_code_fixes() -> str:
    """🛠️ Apply formatting fixes using black and isort."""
    try:
        subprocess.run(["black", "."], cwd=CLONE_DIR, check=True)
        subprocess.run(["isort", "."], cwd=CLONE_DIR, check=True)
        return " Code formatted using black and isort."
    except Exception as e:
        return f" Failed to apply code fixes: {str(e)}"

@mcp.tool()
def commit_and_push() -> str:
    """📤 Commit and push changes to a new GitHub branch."""
    try:
        subprocess.run(["git", "checkout", "-b", NEW_BRANCH], cwd=CLONE_DIR, check=True)
        subprocess.run(["git", "add", "."], cwd=CLONE_DIR, check=True)
        subprocess.run(["git", "commit", "-m", "fix: auto-fix based on SonarQube issues"], cwd=CLONE_DIR, check=True)
        subprocess.run(["git", "push", "--set-upstream", "origin", NEW_BRANCH], cwd=CLONE_DIR, check=True)
        return f" Changes pushed to branch `{NEW_BRANCH}`."
    except Exception as e:
        return f" Git commit/push failed: {str(e)}"

@mcp.tool()
def raise_pr() -> dict:
    """ Create a GitHub Pull Request for the auto-fix branch."""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        pr = repo.create_pull(
            title="Auto-fix: SonarQube violations",
            body="This PR auto-fixes code formatting issues based on SonarQube results.",
            head=NEW_BRANCH,
            base="main"
        )
        return {"url": pr.html_url, "status": " PR created successfully"}
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def full_auto_fix_pipeline() -> dict:
    """🏁 End-to-end: get issues → fix → commit → PR (assuming repo already cloned)."""
    steps = {}
    steps["get_sonar_issues"] = get_sonar_issues()
    steps["apply_fixes"] = apply_code_fixes()
    steps["commit_push"] = commit_and_push()
    steps["create_pr"] = raise_pr()
    return steps

# # ─── Start MCP Server ───
# if __name__ == "__main__":
#     print("Checking available methods in FastMCP...")
#     print(dir(mcp))  
#     mcp.start()
import asyncio

if __name__ == "__main__":
    print("Starting MCP server on stdio...")
    asyncio.run(mcp.run_stdio_async())

