import asyncio

from mcp import ClientSession , StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
  command="python",
  args=["src/patchguard/mcp_server.py"]
)

async def main():
  async with stdio_client(server_params) as (read,write):
    async with ClientSession(read,write) as session:
      await session.initialize() # Initialize the MCP connection

      tools = await session.list_tools()

      print("Available tools: ")
      for tool in tools.tools:
        print(f"- {tool.name}")

      
      file_result = await session.call_tool(
        "read_file",
        {"path":"sample.txt"}
      )
      print("\nread_file result:")
      print(file_result.structured_content["result"])

      # Test search_code.
      search_result = await session.call_tool(
        "search_code",
        {"query": "this-thing-does-not-exist"},
      )
      print("\nsearch_code result:")
      print(search_result.structured_content["result"]) #The above one didnt work properly

if __name__=="__main__":
  asyncio.run(main())