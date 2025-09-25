from dotenv import load_dotenv
from fastmcp.server import FastMCP
import os
import subprocess
import requests
from requests.auth import HTTPBasicAuth
from github import Github
import stat
import json
import google.generativeai as genai
from google.generativeai import GenerativeModel
import datetime
#import re


load_dotenv()
# ─── Configuration ───
SONARQUBE_URL = os.getenv("SONARQUBE_URL", "http://localhost:9000")
SONARQUBE_TOKEN = os.getenv("SONARQUBE_TOKEN", "")
PROJECT_KEY = os.getenv("PROJECT_KEY", "")
AUTH = HTTPBasicAuth(SONARQUBE_TOKEN, "")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  
GITHUB_USER = os.getenv("GITHUB_USER", "")
CLONE_DIR = "cloned_repo"
NEW_BRANCH = "auto-fix-sonar-issues"
NEW_BRANCH_FIX = "auto-fix-sonar-issues-fix"

timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
branch_with_ts = f"{NEW_BRANCH}-{timestamp}"

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
        #result = full_auto_fix_pipeline()

        return {
            "status": "Build succeeded and commit processed",
            "commit": latest_commit,
            #"pipeline_result": result
        }

    except Exception as e:
        return {"error": str(e)}


def get_sonar_issues() -> dict:
    """Fetch unresolved SonarQube issues using SonarQube API."""
    try:
        url = f"{SONARQUBE_URL}/api/issues/search"
        params = {"componentKeys": PROJECT_KEY, "resolved": "false", "ps": "100"}
        response = requests.get(url, params=params, auth=AUTH)
        response.raise_for_status()
        issues = response.json().get("issues", [])
        return issues
    except Exception as e:
        return {"error": str(e)}

def on_rm_error(func, path, exc_info):
    # Change the file to writable and reattempt removal
    os.chmod(path, stat.S_IWRITE)
    func(path)


def apply_code_fixes() -> str:
    """Clone the repo, install JS dependencies, and auto-fix code using eslint/prettier for a React project."""
    try:
        # Remove existing CLONE_DIR if it exists
        if os.path.isdir(CLONE_DIR):
            import shutil
            shutil.rmtree(CLONE_DIR, onerror=on_rm_error)

        # Clone the repo
        repo_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        subprocess.run(["git", "clone", repo_url, CLONE_DIR], check=True)

        assert os.path.isdir(CLONE_DIR), f"Directory {CLONE_DIR} does not exist"
        assert shutil.which("npx"), "npx is not installed or not in PATH"

        # Fetch all and checkout or create the feature branch
        subprocess.run(["git", "fetch", "origin"], cwd=CLONE_DIR, check=True)
        # Try to checkout the feature branch if it exists, else create from main
        result = subprocess.run(["git", "branch", "--list", NEW_BRANCH], cwd=CLONE_DIR, capture_output=True, text=True)
        if result.stdout.strip() == "":
            subprocess.run(["git", "checkout", "-b", NEW_BRANCH, "origin/main"], cwd=CLONE_DIR, check=True)
        else:
            subprocess.run(["git", "checkout", NEW_BRANCH], cwd=CLONE_DIR, check=True)

        # Install dependencies (npm or yarn)
        if os.path.exists(os.path.join(CLONE_DIR, "yarn.lock")):
            subprocess.run(["yarn", "install"], cwd=CLONE_DIR, check=True, shell=True)
        else:
            subprocess.run(["npm", "install"], cwd=CLONE_DIR, check=True, shell=True)


        # Generate ESLint JSON report for commented code
        eslint_report_path = os.path.join(CLONE_DIR, "eslint_report.json")
        report_proc = subprocess.run(
            ["npx", "eslint", ".", "--ext", ".js,.jsx,.ts,.tsx", "-f", "json", "-o", "eslint_report.json"],
            cwd=CLONE_DIR, check=False, shell=True,
            capture_output=True, text=True
)
        if report_proc.returncode not in (0, 1):
            # 0: success, 1: lint errors found (still generates report), other: real error
            raise Exception(f"ESLint failed: {report_proc.stderr}")

        # Remove commented code using the report
        remove_commented_code_from_eslint_report_full(eslint_report_path, CLONE_DIR)

        # Run Prettier for formatting (optional)
        #prettier_result = subprocess.run(
        #    ["npx", "prettier", "--write", "."],
        #    cwd=CLONE_DIR, capture_output=True, text=True, shell=True
        #)

        # Run prettier --write (optional, if configured)
        #prettier_result = subprocess.run(["npx", "prettier", "--write", "."], cwd=CLONE_DIR, capture_output=True, text=True, shell=True)

        return (
            f"Cloned repo, checked out feature branch, installed dependencies.\n"
          #  f"ESLint auto-fix output:\n{eslint_fix.stdout}\n"
           # f"Prettier output:\n{prettier_result.stdout}\n"
            f"Commented code removed based on ESLint report."
        )
    except Exception as e:
        return f"Failed to apply code fixes: {str(e)}"
    
    

def fix_file_with_gemini(file_path, violation_message, gemini_api_key):
    """
    Sends the file content and violation message to Gemini and overwrites the file with the fixed code.
    """
    # Read the original code
    with open(file_path, "r", encoding="utf-8") as f:
        original_code = f.read()

    # Prepare the prompt
    prompt = (
        f"The following JavaScript/TypeScript code has this issue: {violation_message}.\n"
        "Please fix the code according to best practices and return only the revised code and shouldn't append anything like ```javascript or ```typescript. Just the pure code is required in output :\n\n"
        f"{original_code}"
    )

    # Configure Gemini
    genai.configure(api_key=gemini_api_key)
    model = GenerativeModel('gemini-2.5-pro')

    # Get the revised code from Gemini
    response = model.generate_content(prompt)
    revised_code = response.text.strip()

    # Overwrite the file with the revised code
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(revised_code)

    return True
    


def remove_commented_code_from_eslint_report_full(eslint_report_path, project_dir):
    """
    Removes lines flagged as commented-out code by ESLint (sonarjs/no-commented-code),
    unused variable declarations, and removes the entire unused function block if flagged.
    """
    with open(eslint_report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    for file_result in report:
        file_path = file_result.get("filePath")
        #for msg in file_result["messages"]:
            # For each violation, call Gemini to fix
        fix_file_with_gemini(file_path, 'test', gemini_api_key)


def commit_and_push() -> str:
    """Commit and push changes to a new GitHub branch."""
    try:
        assert os.path.isdir(CLONE_DIR), f"Directory {CLONE_DIR} does not exist"
        # Add timestamp to branch name

        # Check if branch already exists
        result = subprocess.run(["git", "branch", "--list", branch_with_ts], cwd=CLONE_DIR, capture_output=True, text=True)
        if result.stdout.strip() == "":
            # Create new branch from main
            subprocess.run(["git", "checkout", "-b", branch_with_ts, "origin/main"], cwd=CLONE_DIR, check=True)
        else:
            # Switch to the branch if it exists
            subprocess.run(["git", "checkout", branch_with_ts], cwd=CLONE_DIR, check=True)

        # Unstage eslint_report.json if it was added
        subprocess.run(["git", "reset", "eslint_report.json"], cwd=CLONE_DIR, check=False)

        # Remove eslint_report.json from working directory if you don't want it in the repo at all
        eslint_report_path = os.path.join(CLONE_DIR, "eslint_report.json")
        if os.path.exists(eslint_report_path):
            os.remove(eslint_report_path)

        subprocess.run(["git", "add", "."], cwd=CLONE_DIR, check=True)
        # Only commit if there are staged changes
        diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=CLONE_DIR)
        if diff_result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "fix: auto-fix based on SonarQube issues"], cwd=CLONE_DIR, check=True)
        else:
            return f"No changes to commit on branch `{branch_with_ts}`."

        subprocess.run(["git", "push", "--set-upstream", "origin", branch_with_ts], cwd=CLONE_DIR, check=True)
        return f"Changes pushed to branch `{branch_with_ts}`."
    except Exception as e:
        return f"Git commit/push failed: {str(e)}"


def raise_pr() -> dict:
    """Create a GitHub Pull Request for the auto-fix branch."""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        pr = repo.create_pull(
            title="Auto-fix: SonarQube violations",
            body="This PR auto-fixes code formatting issues based on SonarQube results.",
            head=branch_with_ts,
            base="main"
        )
        return {"url": pr.html_url, "status": "PR created successfully"}
    except Exception as e:
        return {"error": str(e)}


#@mcp.tool()
def sonar_check_and_fix_pipeline() -> dict:
    """
    Sequentially: check SonarQube issues, apply code fixes, commit & push, and raise a PR.
    Returns a dict with the result of each step.
    """
    result = {}
    # 1. SonarQube check
    issues = get_sonar_issues()
    result["sonarqube_issues"] = issues if isinstance(issues, list) else [issues]
    if isinstance(issues, dict) and "error" in issues:
        result["status"] = "Failed at SonarQube check"
        return result
    if not issues:
        result["status"] = "No issues found. No further action taken."
        return result

    # 2. Apply code fixes
    result["code_fixes"] = apply_code_fixes()

    # 3. Commit and push
    result["commit_push"] = commit_and_push()

    # 4. Raise PR
    result["pr"] = raise_pr()

    result["status"] = "Completed all steps."
    return result

import asyncio

if __name__ == "__main__":
    print("Starting MCP server on stdio...")
    # Start the MCP server for agent requests
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run_pipeline":
        # Allow direct CLI test: python sonar_git_mcp.py run_pipeline
        print("Running sonar_check_and_fix_pipeline directly...")
        print(sonar_check_and_fix_pipeline())
    else:
        asyncio.run(mcp.run_stdio_async())

