from datetime import datetime, timedelta, timezone

import httpx
from dateutil import parser
from pydantic import BaseModel, Field

from mcp.server.fastmcp import TMCP
from mcp.types import TextContent

# Create an MCP server
mcp = TMCP("GitHubDemo", port=8001)


@mcp.tool()
async def get_recent_commits_somehow():
    """Get the commit messages from the past week on the main branch of a GitHub repository for which we do not yet
    know the name"""

    class Repository(BaseModel):
        owner: str = Field(description="Repository owner")
        repository: str = Field(description="GitHub repository name")

    response = await mcp.get_context().elicit(
        message="What repository do you want to use?",
        schema=Repository,
    )

    if response.action != "accept":
        return TextContent(type="text", text="The user declined to specify which repository to use.")

    return get_recent_commits(response.data.owner, response.data.repository)


@mcp.tool()
def get_recent_commits(owner: str, repository: str):
    """Get the commit messages from the past week on the main branch of a GitHub repository of a certain name by a
    certain owner, starting with the most recent commit"""

    response = httpx.get(f"https://api.github.com/repos/{owner}/{repository}/commits")
    if response.is_error:
        return f"Could not get recent commits (reason: {response.reason_phrase})"

    data = response.json()

    now = datetime.now(timezone.utc)

    return [
        {
            "message": c["commit"]["message"],
            "author": c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
        }
        for c in data
        if now - parser.parse(c["commit"]["author"]["date"]) <= timedelta(weeks=1)
    ]


if __name__ == "__main__":
    import sys

    # Initialize and run the server
    transport = sys.argv[1] if len(sys.argv) >= 2 else "sse"
    mcp.run(transport=transport)  # type: ignore
