#!/usr/bin/env python3
"""Create a Codeup Merge Request (Change Request) via the OpenAPI.

Usage:
    python3 create_mr.py <repo_web_url> <source_branch> <target_branch> <title> [description]

Environment variables required:
    CODEUP_TOKEN          Personal Access Token (x-yunxiao-token)
    CODEUP_DOMAIN         API domain, e.g. devops.aliyun.com
    CODEUP_ORGANIZATION_ID  (optional) Organization ID for central-edition Codeup

Example:
    python3 create_mr.py https://codeup.aliyun.com/myorg/myrepo \\
        feature/REQ-123 main "feat(REQ-123): my changes" "Auto-generated MR."
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: create_mr.py <repo_web_url> <source_branch> <target_branch> <title> [description]",
            file=sys.stderr,
        )
        sys.exit(1)

    repo_url = sys.argv[1]
    source_branch = sys.argv[2]
    target_branch = sys.argv[3]
    title = sys.argv[4]
    description = sys.argv[5] if len(sys.argv) > 5 else ""

    token = os.environ.get("CODEUP_TOKEN", "")
    domain = os.environ.get("CODEUP_DOMAIN", "")
    org_id = os.environ.get("CODEUP_ORGANIZATION_ID", "")

    if not token or not domain:
        print(
            "ERROR: CODEUP_TOKEN and CODEUP_DOMAIN environment variables must be set.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Extract path_with_namespace from repo URL (strip leading slash and .git suffix)
    parsed = urllib.parse.urlparse(repo_url)
    repo_path = parsed.path.strip("/").removesuffix(".git")
    repo_path_encoded = urllib.parse.quote(repo_path, safe="")

    if org_id:
        api_url = f"https://{domain}/oapi/v1/codeup/organizations/{org_id}/repositories/{repo_path_encoded}/changeRequests"
    else:
        api_url = f"https://{domain}/oapi/v1/codeup/repositories/{repo_path_encoded}/changeRequests"

    body = {
        "sourceBranch": source_branch,
        "targetBranch": target_branch,
        "title": title[:256],
        "description": description[:10000],
        "createFrom": "COMMAND_LINE",
    }

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(api_url, data=data, method="POST")
    req.add_header("x-yunxiao-token", token)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            web_url = result.get("webUrl") or result.get("web_url") or result.get("url", "")
            print(f"✅ MR created successfully: {web_url}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(
            f"ERROR: Codeup API returned HTTP {e.code}: {body_text}",
            file=sys.stderr,
        )
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Network error calling Codeup API: {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
