from dotenv import load_dotenv
load_dotenv()
from fastmcp.server import FastMCP
import os
import subprocess
import requests
from requests.auth import HTTPBasicAuth
from github import Github
import stat
import json

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

        # Run eslint --fix (assumes eslint is set up in the project)
        eslint_result = subprocess.run(["npx", "eslint", ".", "--ext", ".js,.jsx,.ts,.tsx", "--fix"], cwd=CLONE_DIR, capture_output=True, text=True, shell=True)

        # Run prettier --write (optional, if configured)
        #prettier_result = subprocess.run(["npx", "prettier", "--write", "."], cwd=CLONE_DIR, capture_output=True, text=True, shell=True)

        return f"Cloned repo, checked out feature branch, installed dependencies, ran eslint and prettier.\nESLint output:\n{eslint_result.stdout}"
    except Exception as e:
        return f"Failed to apply code fixes: {str(e)}"

def remove_commented_code_from_eslint_report(eslint_report_path, project_dir):
    """
    Removes lines flagged as commented-out code by ESLint (sonarjs/no-commented-code).
    eslint_report_path: Path to the ESLint JSON report.
    project_dir: Root directory of your JS/TS project.
    """
    with open(eslint_report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    for file_result in report:
        file_path = file_result.get("filePath")
        if not file_path or not file_result.get("messages"):
            continue

        # Collect line numbers to remove
        lines_to_remove = set()
        for msg in file_result["messages"]:
            if msg.get("ruleId") == "sonarjs/no-commented-code":
                lines_to_remove.add(msg["line"])

        if not lines_to_remove:
            continue

        # Remove lines from the file
        rel_path = os.path.relpath(file_path, project_dir)
        abs_path = os.path.join(project_dir, rel_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(abs_path, "w", encoding="utf-8") as f:
            for idx, line in enumerate(lines, 1):
                if idx not in lines_to_remove:
                    f.write(line)

def commit_and_push() -> str:
    """Commit and push changes to a new GitHub branch."""
    try:
        assert os.path.isdir(CLONE_DIR), f"Directory {CLONE_DIR} does not exist"
        # Check if branch already exists
        result = subprocess.run(["git", "branch", "--list", NEW_BRANCH], cwd=CLONE_DIR, capture_output=True, text=True)
        if result.stdout.strip() == "":
            # Create new branch from main
            subprocess.run(["git", "checkout", "-b", NEW_BRANCH, "origin/main"], cwd=CLONE_DIR, check=True)
        else:
            # Switch to the branch if it exists
            subprocess.run(["git", "checkout", NEW_BRANCH], cwd=CLONE_DIR, check=True)

        remove_commented_code_from_eslint_report(os.path.join(CLONE_DIR, "eslint_report.json"), CLONE_DIR)

        subprocess.run(["git", "add", "."], cwd=CLONE_DIR, check=True)
        # Only commit if there are staged changes
        diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=CLONE_DIR)
        if diff_result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "fix: auto-fix based on SonarQube issues"], cwd=CLONE_DIR, check=True)
        else:
            return f"No changes to commit on branch `{NEW_BRANCH}`."

        subprocess.run(["git", "push", "--set-upstream", "origin", NEW_BRANCH], cwd=CLONE_DIR, check=True)
        return f"Changes pushed to branch `{NEW_BRANCH}`."
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
            head=NEW_BRANCH,
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

