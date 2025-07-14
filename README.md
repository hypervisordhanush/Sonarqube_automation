"sonarqubemcp": {
  "command": "docker",
  "args": [
    "run",
    "-i",
    "--rm",
    "--init",
    "-e", "SONARQUBE_URL",
    "-e", "SONARQUBE_TOKEN",
    "-e", "PROJECT_KEY",
    "-e", "GITHUB_TOKEN",
    "-e", "GITHUB_REPO",
    "-e", "GITHUB_USER",
    "sonarqube-mcp"
  ],
  "env": {
    "SONARQUBE_URL": "http://52.184.147.19:9000",
    "SONARQUBE_TOKEN": "squ_111508df0789913de879c34f492f6402b5c2bff5",
    "PROJECT_KEY": "AITest",
    "GITHUB_TOKEN": "your_github_token",
    "GITHUB_REPO": "your_github_repo",
    "GITHUB_USER": "your_github_user"
  }
}