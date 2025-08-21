import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from pydantic import BaseModel, Field

from tmcp import TmcpManager

# Create an MCP server
mcp = FastMCP("GitHubDemo", port=8003, transport_manager=TmcpManager(transport="http://localhost:8003/mcp"))


@mcp.tool()
async def get_recent_commits(repository: str | None, owner: str | None):
    """
    Get the commit messages of the 10 most recent commits on the main branch of a GitHub repository of a certain name
    by a certain owner, starting with the most recent commit.
    You can call this tool without an explicit owner if they are not specified by the user. In that case we will ask
    the user who is the owner so you don't have to. So no need to bother asking the user to specify the owner,
    just call this tool with None for the owner if the owner is not clearly indicated by the user.
    Also, please don't try to guess the owner, because then you will likely end up on the wrong repository or a
    repository that doesn't exist.
    The same applies to the repository, which may also be None if the user didn't specify which repository to use.

    Parameters:

    :param str | None repository: the GitHub repository to get the commits from (use None if unknown)
    :param str | None owner: the owner of the GitHub repository to get the commits from (use None if unknown)
    """

    if repository is None:

        class Repository(BaseModel):
            repository: str = Field(description="GitHub repository")

        response = await mcp.get_context().elicit(
            message="Which repository do you want to get the commits of?",
            schema=Repository,
        )

        if response.action != "accept":
            return TextContent(type="text", text="The user declined to specify which repository to use.")

        repository = response.data.repository

    if owner is None:

        class Owner(BaseModel):
            owner: str = Field(description="Repository owner")

        response = await mcp.get_context().elicit(
            message=f"Who is the owner of the {repository} repository?",
            schema=Owner,
        )

        if response.action != "accept":
            return TextContent(type="text", text="The user declined to specify who is the owner of the repository.")

        owner = response.data.owner

    response = httpx.get(f"https://api.github.com/repos/{owner}/{repository}/commits")
    if response.is_error:
        return (
            f"Could not get recent commits from the {repository} repository owned by {owner} "
            f"(reason: {response.reason_phrase})"
        )

    data = response.json()

    return {
        "repository": repository,
        "owner": owner,
        "commits": [
            {
                "message": c["commit"]["message"],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"],
            }
            for c in data
        ][:10],
    }


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="streamable-http")
