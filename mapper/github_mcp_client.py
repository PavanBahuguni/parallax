"""GitHub MCP Client - Wrapper for fetching additional PR context.

This module provides MCP-style tools for fetching GitHub PR context beyond just diffs.
Used by the agentic context processor to fetch full files, PR descriptions, etc.
"""
import os
import re
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Try importing PyGithub, fallback to httpx if not available
try:
    from github import Github
    HAS_PYGITHUB = True
except ImportError:
    HAS_PYGITHUB = False

import httpx


class GitHubMCPClient:
    """MCP-style client for GitHub API operations.
    
    Provides tools for fetching additional PR context:
    - PR description and comments
    - Full file contents (not just diffs)
    - Related files (via imports/dependencies)
    - Commit messages
    """
    
    def __init__(self, github_token: Optional[str] = None, github_domain: str = "github.com"):
        """Initialize GitHub MCP client.
        
        Args:
            github_token: GitHub API token (or from GITHUB_TOKEN env var)
            github_domain: GitHub domain (default: github.com, or e.g., github.enterprise.com)
        """
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.github_domain = github_domain
        
        # Determine API base URL
        if github_domain == "github.com":
            self.api_base_url = "https://api.github.com"
        else:
            # GitHub Enterprise: https://github.enterprise.com -> https://github.enterprise.com/api/v3
            self.api_base_url = f"https://{github_domain}/api/v3"
        
        # Initialize GitHub client if available
        self.github_client = None
        if HAS_PYGITHUB and self.github_token:
            if github_domain == "github.com":
                self.github_client = Github(self.github_token)
            else:
                self.github_client = Github(base_url=self.api_base_url, login_or_token=self.github_token)
    
    def parse_pr_url(self, pr_link: str) -> Optional[Dict[str, str]]:
        """Parse PR URL to extract owner, repo, and PR number.
        
        Args:
            pr_link: GitHub PR URL
            
        Returns:
            Dict with 'owner', 'repo', 'pr_number', 'github_domain' or None if invalid
        """
        # Pattern: https://[domain]/owner/repo/pull/123
        pr_match = re.search(r'https?://([^/]+)/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
        if not pr_match:
            # Fallback to old pattern for github.com
            pr_match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_link)
            if not pr_match:
                return None
            github_domain = "github.com"
            owner, repo, pr_number = pr_match.groups()
        else:
            github_domain = pr_match.group(1)
            owner = pr_match.group(2)
            repo = pr_match.group(3)
            pr_number = pr_match.group(4)
        
        return {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "github_domain": github_domain
        }
    
    def fetch_pr_description(self, pr_link: str) -> Dict[str, Any]:
        """Fetch PR description, title, and comments.
        
        Args:
            pr_link: GitHub PR URL
            
        Returns:
            Dict with 'title', 'body', 'comments', 'labels'
        """
        parsed = self.parse_pr_url(pr_link)
        if not parsed:
            return {"error": "Invalid PR URL"}
        
        owner = parsed["owner"]
        repo = parsed["repo"]
        pr_number = parsed["pr_number"]
        
        try:
            if self.github_client:
                # Use PyGithub
                repo_obj = self.github_client.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(int(pr_number))
                
                # Fetch comments
                comments = []
                for comment in pr.get_issue_comments():
                    comments.append({
                        "body": comment.body,
                        "author": comment.user.login,
                        "created_at": comment.created_at.isoformat() if comment.created_at else None
                    })
                
                return {
                    "title": pr.title,
                    "body": pr.body,
                    "comments": comments,
                    "labels": [label.name for label in pr.labels],
                    "state": pr.state,
                    "merged": pr.merged
                }
            else:
                # Fallback to httpx
                headers = {}
                if self.github_token:
                    if self.github_domain == "github.com":
                        headers["Authorization"] = f"token {self.github_token}"
                    else:
                        headers["Authorization"] = f"Bearer {self.github_token}"
                
                verify_ssl = os.getenv("GITHUB_VERIFY_SSL", "true").lower() == "true"
                
                with httpx.Client(verify=verify_ssl, timeout=30.0, headers=headers) as client:
                    # Fetch PR details
                    pr_url = f"{self.api_base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
                    pr_response = client.get(pr_url)
                    pr_response.raise_for_status()
                    pr_data = pr_response.json()
                    
                    # Fetch comments
                    comments_url = f"{self.api_base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
                    comments_response = client.get(comments_url)
                    comments_data = comments_response.json() if comments_response.status_code == 200 else []
                    
                    return {
                        "title": pr_data.get("title", ""),
                        "body": pr_data.get("body", ""),
                        "comments": [
                            {
                                "body": c.get("body", ""),
                                "author": c.get("user", {}).get("login", ""),
                                "created_at": c.get("created_at")
                            }
                            for c in comments_data
                        ],
                        "labels": [label.get("name") for label in pr_data.get("labels", [])],
                        "state": pr_data.get("state", ""),
                        "merged": pr_data.get("merged", False)
                    }
        except Exception as e:
            return {"error": str(e)}
    
    def fetch_file_contents(self, pr_link: str, filename: str, ref: Optional[str] = None) -> Dict[str, Any]:
        """Fetch full file contents from PR branch or main branch.
        
        Args:
            pr_link: GitHub PR URL
            filename: File path relative to repo root
            ref: Git ref (branch/commit). If None, uses PR head branch
            
        Returns:
            Dict with 'content', 'size', 'encoding'
        """
        parsed = self.parse_pr_url(pr_link)
        if not parsed:
            return {"error": "Invalid PR URL"}
        
        owner = parsed["owner"]
        repo = parsed["repo"]
        pr_number = parsed["pr_number"]
        
        try:
            if self.github_client:
                # Use PyGithub
                repo_obj = self.github_client.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(int(pr_number))
                
                # Use PR head branch if ref not specified
                if not ref:
                    ref = pr.head.ref
                
                # Fetch file contents
                try:
                    file_content = repo_obj.get_contents(filename, ref=ref)
                    return {
                        "content": file_content.decoded_content.decode('utf-8'),
                        "size": file_content.size,
                        "encoding": "utf-8",
                        "sha": file_content.sha
                    }
                except Exception as e:
                    return {"error": f"File not found: {e}"}
            else:
                # Fallback to httpx
                headers = {}
                if self.github_token:
                    if self.github_domain == "github.com":
                        headers["Authorization"] = f"token {self.github_token}"
                    else:
                        headers["Authorization"] = f"Bearer {self.github_token}"
                
                verify_ssl = os.getenv("GITHUB_VERIFY_SSL", "true").lower() == "true"
                
                with httpx.Client(verify=verify_ssl, timeout=30.0, headers=headers) as client:
                    # First, get PR to find head branch
                    if not ref:
                        pr_url = f"{self.api_base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
                        pr_response = client.get(pr_url)
                        pr_response.raise_for_status()
                        pr_data = pr_response.json()
                        ref = pr_data.get("head", {}).get("ref", "main")
                    
                    # Fetch file contents
                    file_url = f"{self.api_base_url}/repos/{owner}/{repo}/contents/{filename}"
                    file_response = client.get(file_url, params={"ref": ref})
                    
                    if file_response.status_code == 404:
                        return {"error": "File not found"}
                    
                    file_response.raise_for_status()
                    file_data = file_response.json()
                    
                    # Decode base64 content
                    import base64
                    content = base64.b64decode(file_data.get("content", "")).decode('utf-8')
                    
                    return {
                        "content": content,
                        "size": file_data.get("size", 0),
                        "encoding": "utf-8",
                        "sha": file_data.get("sha", "")
                    }
        except Exception as e:
            return {"error": str(e)}
    
    def fetch_commit_messages(self, pr_link: str) -> Dict[str, Any]:
        """Fetch commit messages from PR.
        
        Args:
            pr_link: GitHub PR URL
            
        Returns:
            Dict with 'commits' list containing commit messages
        """
        parsed = self.parse_pr_url(pr_link)
        if not parsed:
            return {"error": "Invalid PR URL"}
        
        owner = parsed["owner"]
        repo = parsed["repo"]
        pr_number = parsed["pr_number"]
        
        try:
            if self.github_client:
                # Use PyGithub
                repo_obj = self.github_client.get_repo(f"{owner}/{repo}")
                pr = repo_obj.get_pull(int(pr_number))
                
                commits = []
                for commit in pr.get_commits():
                    commits.append({
                        "sha": commit.sha,
                        "message": commit.commit.message,
                        "author": commit.commit.author.name if commit.commit.author else None,
                        "date": commit.commit.author.date.isoformat() if commit.commit.author and commit.commit.author.date else None
                    })
                
                return {"commits": commits}
            else:
                # Fallback to httpx
                headers = {}
                if self.github_token:
                    if self.github_domain == "github.com":
                        headers["Authorization"] = f"token {self.github_token}"
                    else:
                        headers["Authorization"] = f"Bearer {self.github_token}"
                
                verify_ssl = os.getenv("GITHUB_VERIFY_SSL", "true").lower() == "true"
                
                with httpx.Client(verify=verify_ssl, timeout=30.0, headers=headers) as client:
                    commits_url = f"{self.api_base_url}/repos/{owner}/{repo}/pulls/{pr_number}/commits"
                    commits_response = client.get(commits_url)
                    commits_response.raise_for_status()
                    commits_data = commits_response.json()
                    
                    commits = []
                    for commit_data in commits_data:
                        commit_info = commit_data.get("commit", {})
                        commits.append({
                            "sha": commit_data.get("sha", ""),
                            "message": commit_info.get("message", ""),
                            "author": commit_info.get("author", {}).get("name", ""),
                            "date": commit_info.get("author", {}).get("date", "")
                        })
                    
                    return {"commits": commits}
        except Exception as e:
            return {"error": str(e)}
