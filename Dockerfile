# Use official Python image as base
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install dependencies if requirements.txt exists
COPY requirements.txt ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Copy the rest of the code
COPY . .

# Expose port if your MCP server listens on a specific port (optional)
# EXPOSE 8000

# Set environment variables from command line (do not bake .env into image)
# Entrypoint expects env vars to be passed at runtime

# Default command (update as needed for your MCP server)
CMD ["python", "sonar_git_mcp.py"]
