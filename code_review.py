#!/usr/bin/env python3

import json
import os
import requests
import subprocess
import sys
from urllib.parse import urlparse
import urllib3

urllib3.disable_warnings()


def get_pull_request_details(api_url, owner, repo, pr_number, token):
    """
    Fetches details of a specific pull request from the GitHub API.
    """
    result = ""

    # --- 1. Set up headers for authentication ---
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # --- 2. Get the main PR data (title and body) ---
    pr_api_url = f"{api_url}/repos/{owner}/{repo}/pulls/{pr_number}"
    try:
        response = requests.get(pr_api_url, headers=headers, verify=False)
        response.raise_for_status()  # Raise an exception for bad status codes
        pr_data = response.json()

        result += "--- Pull Request Details ---\n"
        result += f"Title: {pr_data.get('title')}\n"
        result += f"Body:\n{pr_data.get('body')}\n\n"

    except requests.exceptions.RequestException as e:
        print(f"Error fetching files data: {e}")
        if e.response is not None:
            print(f"API Response: {e.response.text}")
            exit(1)

    # --- 4. Get the list of changed files and their patches ---
    files_api_url = f"{pr_api_url}/files"
    try:
        response = requests.get(files_api_url, headers=headers, verify=False)
        response.raise_for_status()
        files_data = response.json()

        result += "--- Changed Files ---\n"
        for file_info in files_data:
            result += f"File Name: {file_info.get('filename')}\n"
            patch = file_info.get("patch", "No patch data available.")
            result += "Patch:\n"
            result += "--------------------------------\n"
            result += f"{patch}\n"
            result += "--------------------------------"

    except requests.exceptions.RequestException as e:
        print(f"Error fetching files data: {e}")
        if e.response is not None:
            print(f"API Response: {e.response.text}")
            exit(1)

    return result


def execute_cody_cli(repo, prompt):
    command_list = ["cody", "chat", "--context-repo", repo, "-m", prompt]
    try:
        # Execute the command
        # `shell=False` is the default, secure setting.
        result = subprocess.run(
            command_list,
            capture_output=True,
            text=True,
            check=False,  # We will check the return code manually
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(result.stderr.strip())
            print("\n--- Command failed! ---", file=sys.stderr)
            exit(result.returncode)

    except FileNotFoundError:
        print(f"Error: The command 'cody' was not found.", file=sys.stderr)
        print(
            "Please ensure 'cody' is installed and in your system's PATH.",
            file=sys.stderr,
        )
        exit(1)

    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        exit(1)


def add_pr_comment(api_url, owner, repo, pr_number, token, comment_body):
    # GitHub API endpoint for creating a general PR comment (Issues API)
    url = f"{api_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"

    # Headers with authentication
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Comment payload
    payload = {"body": comment_body}

    try:
        # Make the POST request
        response = requests.post(
            url, headers=headers, data=json.dumps(payload), verify=False
        )

        # Check if the request was successful
        if response.status_code == 201:
            print("Comment added successfully!")
            return response.json()
        else:
            print(f"Failed to add comment. Status code: {response.status_code}")
            print(response.json())
            return None

    except requests.RequestException as e:
        print(f"An error occurred: {e}")
        return None


if __name__ == "__main__":
    # need to make sure we are in the pull request github action
    # by checking GITHUB_EVENT_NAME=pull_request in env
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        # check a few env variables
        if not (token := os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")):
            print(
                "GitHub authentication token is missing. Please set GITHUB_TOKEN or GH_TOKEN."
            )
            exit(1)

        # Check required Cody environment variables
        if not (cody_endpoint := os.environ.get("SRC_ENDPOINT")) or not (
            cody_access_token := os.environ.get("SRC_ACCESS_TOKEN")
        ):
            print(
                "Missing required Cody environment variables: SRC_ENDPOINT and/or SRC_ACCESS_TOKEN"
            )
            exit(1)

        api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")

        # repo_host is api_url domain
        repo_host = urlparse(api_url).hostname

        # parse the org and repo name from env variable: GITHUB_REPOSITORY=Test-Org/Test
        repo_owner, repo_name = os.environ.get("GITHUB_REPOSITORY").split("/")

        # parse the pull request number from env variable: GITHUB_REF=refs/pull/2/merge
        pr_number = os.environ.get("GITHUB_REF").split("/")[2]

        pr_details = get_pull_request_details(
            api_url, repo_owner, repo_name, pr_number, token
        )

        cody_prompt = f"""You are an expert code reviewer tasked with analyzing the changes in a GitHub pull request (PR).
Your review must focus **exclusively** on the modified, added, or removed lines in the PR diffs, as provided below.
Only reference the broader repository codebase when necessary to understand the context of the changes (e.g., to verify referenced variables, functions, or dependencies).
Provide clear, actionable feedback on correctness, best practices, security, and maintainability, specific to the changed lines.

{pr_details}

**Instructions**:
1. **Analyze Only the PR Changes**:
   - Review the diffs in each changed file, focusing solely on the added, removed, or modified lines.
   - Check the syntax and semantics of the changes for correctness, ensuring they align with the programming language or configuration format used.
   - Infer the purpose of the changes based on the PR title, body (if provided), and diffs. If the intent is unclear, note it and suggest seeking clarification from the PR author.

2. **Contextual References (Only When Necessary)**:
   - If the changed lines reference variables, functions, or resources (e.g., a variable in a configuration file), check the repository to confirm their definition or existence, but do not review unrelated code.
   - Limit repository access to files directly relevant to the changes.

3. **Evaluate Best Practices**:
   - Ensure the changed lines follow best practices for the relevant language or framework (e.g., idiomatic code, clear naming, proper error handling).
   - Check for adherence to common standards, such as documentation or formatting, but only for the modified code.
   - Identify any anti-patterns or suboptimal changes in the diffs.

4. **Security Review**:
   - Identify potential security risks in the changed lines, such as hard-coded credentials, insecure configurations, or language-specific vulnerabilities.
   - Suggest mitigations for any security issues in the modified code.

5. **Maintainability and Clarity**:
   - Assess whether the changed lines are clear and maintainable. Suggest improvements like adding comments or refactoring only for the modified code.
   - Check for redundant or obsolete changes (e.g., commented-out code in the diffs) and recommend removal or documentation.

6. **Potential Issues**:
   - Highlight risks in the changed lines, such as potential bugs, breaking changes, or compatibility issues.
   - Note any assumptions in the modified code that may not hold (e.g., unverified resources or edge cases).

7. **Actionable Feedback**:
   - Provide specific recommendations for fixes or improvements, referencing file names and line numbers from the diffs.
   - If the changes are correct and beneficial, acknowledge their value (e.g., improved functionality or clarity).
   - Prioritize critical issues (e.g., bugs, security risks) over stylistic improvements.

8. **Formatting**:
   - Structure your response with clear sections: **Summary**, **Issues Found**, **Recommendations**, **Benefits**, and **Questions/Clarifications**.
   - Reference specific files and line numbers from the diffs when discussing issues or suggestions.
   - Use bullet points for clarity and conciseness.

**Additional Notes**:
- If the PR body is empty or vague, infer the intent from the title and diffs, but note any assumptions and suggest clarifying with the PR author.
- If the changes reference undefined variables, functions, or resources, include a request for their definitions in the **Questions/Clarifications** section.
- The changes may involve any programming language or configuration format (e.g., Terraform, Python, JavaScript, YAML). Tailor the review to the specific language/format based on the file extensions and diff content.

**Output Format**:
- **Summary**: Brief overview of the PR changes and their inferred purpose.
- **Issues Found**: List any problems (syntax, security, best practices) in the changed lines, with file and line references.
- **Recommendations**: Actionable suggestions to address issues or improve the changed code.
- **Benefits**: Positive aspects of the changes (if any).
- **Questions/Clarifications**: Any information needed from the PR author or repository to understand the changes (e.g., definitions of referenced variables).
"""

        comment = execute_cody_cli(f"{repo_host}/{repo_owner}/{repo_name}", cody_prompt)
        add_pr_comment(api_url, repo_owner, repo_name, pr_number, token, comment)
    else:
        print("Script intended to run only in GitHub Pull Request context")
        exit(1)
